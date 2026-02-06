import pytest

from ultron.nlp.intent import parse_intent


@pytest.mark.parametrize(
    "text,expected",
    [
        ("open chrome", "open_app"),
        ("launch spotify", "open_app"),
        ("open google.com", "open_site"),
        ("search for best restaurants in boston", "site.search"),
        ("search on wikipedia for Python", "site.search"),
        ("what's the weather in London", "weather.get"),
        ("tell me the weather", "weather.get"),
        ("take a screenshot", "screenshot"),
        ("minimize this window", "window_minimize"),
        ("please maximize the window", "window_maximize"),
        ("close the window", "window_close"),
        ("put the pc to sleep", "power_sleep"),
        ("shut down the computer", "power_shutdown"),
        ("restart the computer", "power_restart"),
        ("lock the PC", "power_lock"),
        ("what is the battery level", "battery_query"),
        ("wifi status", "wifi_status"),
        ("turn on wifi", "wifi_on"),
        ("disconnect wifi", "wifi_disconnect"),
        ("connect to wifi 'MyNetwork'", "wifi_connect"),
        ("set volume to 30", "volume_set"),
        ("volume up by 10", "volume_up"),
        ("volume down", "volume_down"),
        ("mute volume", "volume_mute"),
        ("unmute volume", "volume_unmute"),
        ("set brightness to 70", "brightness_set"),
        ("increase brightness", "brightness_up"),
        ("decrease brightness", "brightness_down"),
        ("list audio outputs", "audio_list_outputs"),
        ("set output to 'headphones'", "audio_switch_output"),
        ("create a meeting tomorrow at 3pm", "calendar.create"),
        ("unknown gibberish sentence that means nothing", "unknown"),
    ],
)
def test_parse_intent_expected(text, expected):
    ir = parse_intent(text)
    assert ir is not None
    assert hasattr(ir, "intent")
    assert ir.intent == expected, f"For '{text}' expected intent '{expected}', got '{ir.intent}'"
