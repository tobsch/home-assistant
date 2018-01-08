"""
Stock market information from Alpha Vantage.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/sensor.alpha_vantage/
"""
from datetime import timedelta
import logging

import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    ATTR_ATTRIBUTION, CONF_API_KEY, CONF_CURRENCY, CONF_NAME)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity

REQUIREMENTS = ['alpha_vantage==1.8.0']

_LOGGER = logging.getLogger(__name__)

ATTR_CLOSE = 'close'
ATTR_HIGH = 'high'
ATTR_LOW = 'low'
ATTR_VOLUME = 'volume'

CONF_ATTRIBUTION = "Stock market information provided by Alpha Vantage"
CONF_FOREIGN_EXCHANGE = 'foreign_exchange'
CONF_FROM = 'from'
CONF_SYMBOL = 'symbol'
CONF_SYMBOLS = 'symbols'
CONF_TO = 'to'

DEFAULT_SYMBOL = {
    CONF_CURRENCY: 'USD',
    CONF_NAME: 'Google',
    CONF_SYMBOL: 'GOOGL',
}

DEFAULT_CURRENCY = {
    CONF_FROM: 'BTC',
    CONF_NAME: 'Bitcon',
    CONF_TO: 'USD',
}

ICONS = {
    'BTC': 'mdi:currency-btc',
    'EUR': 'mdi:currency-eur',
    'GBP': 'mdi:currency-gbp',
    'INR': 'mdi:currency-inr',
    'RUB': 'mdi:currency-rub',
    'TRY': 'mdi: currency-try',
    'USD': 'mdi:currency-usd',
}

SCAN_INTERVAL = timedelta(minutes=5)

SYMBOL_SCHEMA = vol.Schema({
    vol.Required(CONF_SYMBOL): cv.string,
    vol.Optional(CONF_CURRENCY): cv.string,
    vol.Optional(CONF_NAME): cv.string,
})

CURRENCY_SCHEMA = vol.Schema({
    vol.Required(CONF_FROM): cv.string,
    vol.Required(CONF_TO): cv.string,
    vol.Optional(CONF_NAME): cv.string,
})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_API_KEY): cv.string,
    vol.Optional(CONF_FOREIGN_EXCHANGE, default=[DEFAULT_CURRENCY]):
        vol.All(cv.ensure_list, [CURRENCY_SCHEMA]),
    vol.Optional(CONF_SYMBOLS, default=[DEFAULT_SYMBOL]):
        vol.All(cv.ensure_list, [SYMBOL_SCHEMA]),
})


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the Alpha Vantage sensor."""
    from alpha_vantage.timeseries import TimeSeries
    from alpha_vantage.foreignexchange import ForeignExchange

    api_key = config.get(CONF_API_KEY)
    symbols = config.get(CONF_SYMBOLS)

    timeseries = TimeSeries(key=api_key)

    dev = []
    for symbol in symbols:
        try:
            timeseries.get_intraday(symbol[CONF_SYMBOL])
        except ValueError:
            _LOGGER.error(
                "API Key is not valid or symbol '%s' not known", symbol)
        dev.append(AlphaVantageSensor(timeseries, symbol))

    forex = ForeignExchange(key=api_key)
    for conversion in config.get(CONF_FOREIGN_EXCHANGE):
        from_cur = conversion.get(CONF_FROM)
        to_cur = conversion.get(CONF_TO)
        try:
            forex.get_currency_exchange_rate(
                from_currency=from_cur, to_currency=to_cur)
        except ValueError as error:
            _LOGGER.error(
                "API Key is not valid or currencies '%s'/'%s' not known",
                from_cur, to_cur)
            _LOGGER.debug(str(error))
        dev.append(AlphaVantageForeignExchange(forex, conversion))

    add_devices(dev, True)


class AlphaVantageSensor(Entity):
    """Representation of a Alpha Vantage sensor."""

    def __init__(self, timeseries, symbol):
        """Initialize the sensor."""
        self._symbol = symbol[CONF_SYMBOL]
        self._name = symbol.get(CONF_NAME, self._symbol)
        self._timeseries = timeseries
        self.values = None
        self._unit_of_measurement = symbol.get(CONF_CURRENCY, self._symbol)
        self._icon = ICONS.get(symbol.get(CONF_CURRENCY, 'USD'))

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement of this entity, if any."""
        return self._unit_of_measurement

    @property
    def state(self):
        """Return the state of the sensor."""
        return self.values['1. open']

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        if self.values is not None:
            return {
                ATTR_ATTRIBUTION: CONF_ATTRIBUTION,
                ATTR_CLOSE: self.values['4. close'],
                ATTR_HIGH: self.values['2. high'],
                ATTR_LOW: self.values['3. low'],
                ATTR_VOLUME: self.values['5. volume'],
            }

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return self._icon

    def update(self):
        """Get the latest data and updates the states."""
        all_values, _ = self._timeseries.get_intraday(self._symbol)
        self.values = next(iter(all_values.values()))


class AlphaVantageForeignExchange(Entity):
    """Sensor for foreign exchange rates."""

    def __init__(self, foreign_exchange, config):
        """Initialize the sensor."""
        self._foreign_exchange = foreign_exchange
        self._from_currency = config.get(CONF_FROM)
        self._to_currency = config.get(CONF_TO)
        if CONF_NAME in config:
            self._name = config.get(CONF_NAME)
        else:
            self._name = '{}/{}'.format(self._to_currency, self._from_currency)
        self._unit_of_measurement = self._to_currency
        self._icon = ICONS.get(self._from_currency, 'USD')
        self.values = None

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement of this entity, if any."""
        return self._unit_of_measurement

    @property
    def state(self):
        """Return the state of the sensor."""
        return self.values['5. Exchange Rate']

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return self._icon

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        if self.values is not None:
            return {
                ATTR_ATTRIBUTION: CONF_ATTRIBUTION,
                CONF_FROM: self._from_currency,
                CONF_TO: self._to_currency,
            }

    def update(self):
        """Get the latest data and updates the states."""
        self.values, _ = self._foreign_exchange.get_currency_exchange_rate(
            from_currency=self._from_currency, to_currency=self._to_currency)
