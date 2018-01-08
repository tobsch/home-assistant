"""Component to integrate the Home Assistant cloud."""
import asyncio
from datetime import datetime
import json
import logging
import os

import aiohttp
import async_timeout
import voluptuous as vol

from homeassistant.const import (
    EVENT_HOMEASSISTANT_START, CONF_REGION, CONF_MODE)
from homeassistant.helpers import entityfilter
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
from homeassistant.components.alexa import smart_home as alexa_sh
from homeassistant.components.google_assistant import smart_home as ga_sh

from . import http_api, iot
from .const import CONFIG_DIR, DOMAIN, SERVERS

REQUIREMENTS = ['warrant==0.6.1']

_LOGGER = logging.getLogger(__name__)

CONF_ALEXA = 'alexa'
CONF_GOOGLE_ACTIONS = 'google_actions'
CONF_FILTER = 'filter'
CONF_COGNITO_CLIENT_ID = 'cognito_client_id'
CONF_RELAYER = 'relayer'
CONF_USER_POOL_ID = 'user_pool_id'

MODE_DEV = 'development'
DEFAULT_MODE = 'production'
DEPENDENCIES = ['http']

CONF_ENTITY_CONFIG = 'entity_config'

ALEXA_ENTITY_SCHEMA = vol.Schema({
    vol.Optional(alexa_sh.CONF_DESCRIPTION): cv.string,
    vol.Optional(alexa_sh.CONF_DISPLAY_CATEGORIES): cv.string,
    vol.Optional(alexa_sh.CONF_NAME): cv.string,
})

ASSISTANT_SCHEMA = vol.Schema({
    vol.Optional(
        CONF_FILTER,
        default=lambda: entityfilter.generate_filter([], [], [], [])
    ): entityfilter.FILTER_SCHEMA,
})

ALEXA_SCHEMA = ASSISTANT_SCHEMA.extend({
    vol.Optional(CONF_ENTITY_CONFIG): {cv.entity_id: ALEXA_ENTITY_SCHEMA}
})

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Optional(CONF_MODE, default=DEFAULT_MODE):
            vol.In([MODE_DEV] + list(SERVERS)),
        # Change to optional when we include real servers
        vol.Optional(CONF_COGNITO_CLIENT_ID): str,
        vol.Optional(CONF_USER_POOL_ID): str,
        vol.Optional(CONF_REGION): str,
        vol.Optional(CONF_RELAYER): str,
        vol.Optional(CONF_ALEXA): ALEXA_SCHEMA,
        vol.Optional(CONF_GOOGLE_ACTIONS): ASSISTANT_SCHEMA,
    }),
}, extra=vol.ALLOW_EXTRA)


@asyncio.coroutine
def async_setup(hass, config):
    """Initialize the Home Assistant cloud."""
    if DOMAIN in config:
        kwargs = dict(config[DOMAIN])
    else:
        kwargs = {CONF_MODE: DEFAULT_MODE}

    alexa_conf = kwargs.pop(CONF_ALEXA, None) or ALEXA_SCHEMA({})
    gactions_conf = (kwargs.pop(CONF_GOOGLE_ACTIONS, None) or
                     ASSISTANT_SCHEMA({}))

    kwargs[CONF_ALEXA] = alexa_sh.Config(
        should_expose=alexa_conf[CONF_FILTER],
        entity_config=alexa_conf.get(CONF_ENTITY_CONFIG),
    )
    kwargs['gactions_should_expose'] = gactions_conf[CONF_FILTER]
    cloud = hass.data[DOMAIN] = Cloud(hass, **kwargs)

    success = yield from cloud.initialize()

    if not success:
        return False

    yield from http_api.async_setup(hass)
    return True


class Cloud:
    """Store the configuration of the cloud connection."""

    def __init__(self, hass, mode, alexa, gactions_should_expose,
                 cognito_client_id=None, user_pool_id=None, region=None,
                 relayer=None):
        """Create an instance of Cloud."""
        self.hass = hass
        self.mode = mode
        self.alexa_config = alexa
        self._gactions_should_expose = gactions_should_expose
        self._gactions_config = None
        self.jwt_keyset = None
        self.id_token = None
        self.access_token = None
        self.refresh_token = None
        self.iot = iot.CloudIoT(self)

        if mode == MODE_DEV:
            self.cognito_client_id = cognito_client_id
            self.user_pool_id = user_pool_id
            self.region = region
            self.relayer = relayer

        else:
            info = SERVERS[mode]

            self.cognito_client_id = info['cognito_client_id']
            self.user_pool_id = info['user_pool_id']
            self.region = info['region']
            self.relayer = info['relayer']

    @property
    def is_logged_in(self):
        """Get if cloud is logged in."""
        return self.id_token is not None

    @property
    def subscription_expired(self):
        """Return a boolen if the subscription has expired."""
        return dt_util.utcnow() > self.expiration_date

    @property
    def expiration_date(self):
        """Return the subscription expiration as a UTC datetime object."""
        return datetime.combine(
            dt_util.parse_date(self.claims['custom:sub-exp']),
            datetime.min.time()).replace(tzinfo=dt_util.UTC)

    @property
    def claims(self):
        """Return the claims from the id token."""
        return self._decode_claims(self.id_token)

    @property
    def user_info_path(self):
        """Get path to the stored auth."""
        return self.path('{}_auth.json'.format(self.mode))

    @property
    def gactions_config(self):
        """Return the Google Assistant config."""
        if self._gactions_config is None:
            def should_expose(entity):
                """If an entity should be exposed."""
                return self._gactions_should_expose(entity.entity_id)

            self._gactions_config = ga_sh.Config(
                should_expose=should_expose,
                agent_user_id=self.claims['cognito:username']
            )

        return self._gactions_config

    @asyncio.coroutine
    def initialize(self):
        """Initialize and load cloud info."""
        jwt_success = yield from self._fetch_jwt_keyset()

        if not jwt_success:
            return False

        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START,
                                        self._start_cloud)

        return True

    def path(self, *parts):
        """Get config path inside cloud dir.

        Async friendly.
        """
        return self.hass.config.path(CONFIG_DIR, *parts)

    @asyncio.coroutine
    def logout(self):
        """Close connection and remove all credentials."""
        yield from self.iot.disconnect()

        self.id_token = None
        self.access_token = None
        self.refresh_token = None
        self._gactions_config = None

        yield from self.hass.async_add_job(
            lambda: os.remove(self.user_info_path))

    def write_user_info(self):
        """Write user info to a file."""
        with open(self.user_info_path, 'wt') as file:
            file.write(json.dumps({
                'id_token': self.id_token,
                'access_token': self.access_token,
                'refresh_token': self.refresh_token,
            }, indent=4))

    def _start_cloud(self, event):
        """Start the cloud component."""
        # Ensure config dir exists
        path = self.hass.config.path(CONFIG_DIR)
        if not os.path.isdir(path):
            os.mkdir(path)

        user_info = self.user_info_path
        if not os.path.isfile(user_info):
            return

        with open(user_info, 'rt') as file:
            info = json.loads(file.read())

        # Validate tokens
        try:
            for token in 'id_token', 'access_token':
                self._decode_claims(info[token])
        except ValueError as err:  # Raised when token is invalid
            _LOGGER.warning('Found invalid token %s: %s', token, err)
            return

        self.id_token = info['id_token']
        self.access_token = info['access_token']
        self.refresh_token = info['refresh_token']

        self.hass.add_job(self.iot.connect())

    @asyncio.coroutine
    def _fetch_jwt_keyset(self):
        """Fetch the JWT keyset for the Cognito instance."""
        session = async_get_clientsession(self.hass)
        url = ("https://cognito-idp.us-east-1.amazonaws.com/"
               "{}/.well-known/jwks.json".format(self.user_pool_id))

        try:
            with async_timeout.timeout(10, loop=self.hass.loop):
                req = yield from session.get(url)
                self.jwt_keyset = yield from req.json()

            return True

        except (asyncio.TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.error("Error fetching Cognito keyset: %s", err)
            return False

    def _decode_claims(self, token):
        """Decode the claims in a token."""
        from jose import jwt, exceptions as jose_exceptions
        try:
            header = jwt.get_unverified_header(token)
        except jose_exceptions.JWTError as err:
            raise ValueError(str(err)) from None
        kid = header.get("kid")

        if kid is None:
            raise ValueError('No kid in header')

        # Locate the key for this kid
        key = None
        for key_dict in self.jwt_keyset["keys"]:
            if key_dict["kid"] == kid:
                key = key_dict
                break
        if not key:
            raise ValueError(
                "Unable to locate kid ({}) in keyset".format(kid))

        try:
            return jwt.decode(
                token, key, audience=self.cognito_client_id, options={
                    'verify_exp': False,
                })
        except jose_exceptions.JWTError as err:
            raise ValueError(str(err)) from None
