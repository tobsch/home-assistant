"""
Support for Snips on-device ASR and NLU.

For more details about this component, please refer to the documentation at
https://home-assistant.io/components/snips/
"""
import asyncio
import json
import logging
from datetime import timedelta
import voluptuous as vol
from homeassistant.helpers import intent, config_validation as cv
import homeassistant.components.mqtt as mqtt

DOMAIN = 'snips'
DEPENDENCIES = ['mqtt']
CONF_INTENTS = 'intents'
CONF_ACTION = 'action'

INTENT_TOPIC = 'hermes/intent/#'

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: {}
}, extra=vol.ALLOW_EXTRA)

INTENT_SCHEMA = vol.Schema({
    vol.Required('input'): str,
    vol.Required('intent'): {
        vol.Required('intentName'): str
    },
    vol.Optional('slots'): [{
        vol.Required('slotName'): str,
        vol.Required('value'): {
            vol.Required('kind'): str,
            vol.Optional('value'): cv.match_all,
            vol.Optional('rawValue'): cv.match_all
        }
    }]
}, extra=vol.ALLOW_EXTRA)


@asyncio.coroutine
def async_setup(hass, config):
    """Activate Snips component."""
    @asyncio.coroutine
    def message_received(topic, payload, qos):
        """Handle new messages on MQTT."""
        _LOGGER.debug("New intent: %s", payload)

        try:
            request = json.loads(payload)
        except TypeError:
            _LOGGER.error('Received invalid JSON: %s', payload)
            return

        try:
            request = INTENT_SCHEMA(request)
        except vol.Invalid as err:
            _LOGGER.error('Intent has invalid schema: %s. %s', err, request)
            return

        if request['intent']['intentName'].startswith('user_'):
            intent_type = request['intent']['intentName'].split('__')[-1]
        else:
            intent_type = request['intent']['intentName'].split(':')[-1]
        snips_response = None
        slots = {}
        for slot in request.get('slots', []):
            slots[slot['slotName']] = {'value': resolve_slot_values(slot)}

        try:
            intent_response = yield from intent.async_handle(
                hass, DOMAIN, intent_type, slots, request['input'])
            if 'plain' in intent_response.speech:
                snips_response = intent_response.speech['plain']['speech']
        except intent.UnknownIntent as err:
            _LOGGER.warning("Received unknown intent %s",
                            request['intent']['intentName'])
            snips_response = "Unknown Intent"
        except intent.IntentError:
            _LOGGER.exception("Error while handling intent: %s.", intent_type)
            snips_response = "Error while handling intent"

        notification = {'sessionId': request.get('sessionId', 'default'),
                        'text': snips_response}

        _LOGGER.debug("send_response %s", json.dumps(notification))
        mqtt.async_publish(hass, 'hermes/dialogueManager/endSession',
                           json.dumps(notification))

    yield from hass.components.mqtt.async_subscribe(
        INTENT_TOPIC, message_received)

    return True


def resolve_slot_values(slot):
    """Convert snips builtin types to useable values."""
    if 'value' in slot['value']:
        value = slot['value']['value']
    else:
        value = slot['rawValue']

    if slot.get('entity') == "snips/duration":
        delta = timedelta(weeks=slot['value']['weeks'],
                          days=slot['value']['days'],
                          hours=slot['value']['hours'],
                          minutes=slot['value']['minutes'],
                          seconds=slot['value']['seconds'])
        value = delta.seconds

    return value
