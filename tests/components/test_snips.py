"""Test the Snips component."""
import asyncio
import json

from homeassistant.core import callback
from homeassistant.bootstrap import async_setup_component
from tests.common import async_fire_mqtt_message, async_mock_intent


@asyncio.coroutine
def test_snips_intent(hass, mqtt_mock):
    """Test intent via Snips."""
    result = yield from async_setup_component(hass, "snips", {
        "snips": {},
    })
    assert result
    payload = """
    {
        "input": "turn the lights green",
        "intent": {
            "intentName": "Lights",
            "probability": 1
        },
        "slots": [
            {
                "slotName": "light_color",
                "value": {
                    "kind": "Custom",
                    "value": "green"
                }
            }
        ]
    }
    """

    intents = async_mock_intent(hass, 'Lights')

    async_fire_mqtt_message(hass, 'hermes/intent/Lights',
                            payload)
    yield from hass.async_block_till_done()
    assert len(intents) == 1
    intent = intents[0]
    assert intent.platform == 'snips'
    assert intent.intent_type == 'Lights'
    assert intent.slots == {'light_color': {'value': 'green'}}
    assert intent.text_input == 'turn the lights green'


@asyncio.coroutine
def test_snips_intent_with_duration(hass, mqtt_mock):
    """Test intent with Snips duration."""
    result = yield from async_setup_component(hass, "snips", {
        "snips": {},
    })
    assert result
    payload = """
    {
      "input": "set a timer of five minutes",
      "intent": {
        "intentName": "SetTimer"
      },
      "slots": [
        {
          "rawValue": "five minutes",
          "value": {
            "kind": "Duration",
            "years": 0,
            "quarters": 0,
            "months": 0,
            "weeks": 0,
            "days": 0,
            "hours": 0,
            "minutes": 5,
            "seconds": 0,
            "precision": "Exact"
          },
          "range": {
            "start": 15,
            "end": 27
          },
          "entity": "snips/duration",
          "slotName": "timer_duration"
        }
      ]
    }
    """
    intents = async_mock_intent(hass, 'SetTimer')

    async_fire_mqtt_message(hass, 'hermes/intent/SetTimer',
                            payload)
    yield from hass.async_block_till_done()
    assert len(intents) == 1
    intent = intents[0]
    assert intent.platform == 'snips'
    assert intent.intent_type == 'SetTimer'
    assert intent.slots == {'timer_duration': {'value': 300}}


@asyncio.coroutine
def test_intent_speech_response(hass, mqtt_mock):
    """Test intent speech response via Snips."""
    event = 'call_service'
    events = []

    @callback
    def record_event(event):
        """Add recorded event to set."""
        events.append(event)

    result = yield from async_setup_component(hass, "snips", {
        "snips": {},
    })
    assert result
    result = yield from async_setup_component(hass, "intent_script", {
        "intent_script": {
            "spokenIntent": {
                "speech": {
                    "type": "plain",
                    "text": "I am speaking to you"
                }
            }
        }
    })
    assert result
    payload = """
    {
        "input": "speak to me",
        "sessionId": "abcdef0123456789",
        "intent": {
            "intentName": "spokenIntent"
        },
        "slots": []
    }
    """
    hass.bus.async_listen(event, record_event)
    async_fire_mqtt_message(hass, 'hermes/intent/spokenIntent',
                            payload)
    yield from hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data['domain'] == 'mqtt'
    assert events[0].data['service'] == 'publish'
    payload = json.loads(events[0].data['service_data']['payload'])
    topic = events[0].data['service_data']['topic']
    assert payload['sessionId'] == 'abcdef0123456789'
    assert payload['text'] == 'I am speaking to you'
    assert topic == 'hermes/dialogueManager/endSession'


@asyncio.coroutine
def test_snips_unknown_intent(hass, mqtt_mock):
    """Test calling unknown Intent via Snips."""
    event = 'call_service'
    events = []

    @callback
    def record_event(event):
        """Add recorded event to set."""
        events.append(event)
    result = yield from async_setup_component(hass, "snips", {
        "snips": {},
    })
    assert result
    payload = """
    {
        "input": "what to do",
        "intent": {
            "intentName": "unknownIntent"
        },
        "slots": []
    }
    """
    intents = async_mock_intent(hass, 'knownIntent')
    hass.bus.async_listen(event, record_event)
    async_fire_mqtt_message(hass, 'hermes/intent/unknownIntent',
                            payload)
    yield from hass.async_block_till_done()

    assert not intents
    assert len(events) == 1
    assert events[0].data['domain'] == 'mqtt'
    assert events[0].data['service'] == 'publish'
    payload = json.loads(events[0].data['service_data']['payload'])
    topic = events[0].data['service_data']['topic']
    assert payload['text'] == 'Unknown Intent'
    assert topic == 'hermes/dialogueManager/endSession'


@asyncio.coroutine
def test_snips_intent_user(hass, mqtt_mock):
    """Test intentName format user_XXX__intentName."""
    result = yield from async_setup_component(hass, "snips", {
        "snips": {},
    })
    assert result
    payload = """
    {
        "input": "what to do",
        "intent": {
            "intentName": "user_ABCDEF123__Lights"
        },
        "slots": []
    }
    """
    intents = async_mock_intent(hass, 'Lights')
    async_fire_mqtt_message(hass, 'hermes/intent/user_ABCDEF123__Lights',
                            payload)
    yield from hass.async_block_till_done()

    assert len(intents) == 1
    intent = intents[0]
    assert intent.platform == 'snips'
    assert intent.intent_type == 'Lights'


@asyncio.coroutine
def test_snips_intent_username(hass, mqtt_mock):
    """Test intentName format username:intentName."""
    result = yield from async_setup_component(hass, "snips", {
        "snips": {},
    })
    assert result
    payload = """
    {
        "input": "what to do",
        "intent": {
            "intentName": "username:Lights"
        },
        "slots": []
    }
    """
    intents = async_mock_intent(hass, 'Lights')
    async_fire_mqtt_message(hass, 'hermes/intent/username:Lights',
                            payload)
    yield from hass.async_block_till_done()

    assert len(intents) == 1
    intent = intents[0]
    assert intent.platform == 'snips'
    assert intent.intent_type == 'Lights'
