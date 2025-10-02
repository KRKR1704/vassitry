from ultron.config import SPEAK_MODE, STARTUP_TEXT, SHUTDOWN_TEXT, HEARD_PREFIX

# levels:
# minimal -> startup, wake ack (handled in ack.py), actions, shutdown
# actions -> minimal + heard + intent
# debug   -> actions + extra technical details (you can extend later)

def _s(tts, text: str, level: str):
    mode = SPEAK_MODE
    order = {"minimal": 0, "actions": 1, "debug": 2}
    if mode not in order:
        mode = "actions"
    if order[level] <= order[mode]:
        tts.speak(text)

def say_startup(tts):
    _s(tts, STARTUP_TEXT, "minimal")

def say_shutdown(tts):
    _s(tts, SHUTDOWN_TEXT, "minimal")

def say_heard(tts, text: str):
    _s(tts, f"{HEARD_PREFIX}: {text}", "actions")

def say_intent(tts, intent: str, entity: str | None):
    if entity:
        _s(tts, f"Intent {intent}. Target {entity}.", "actions")
    else:
        _s(tts, f"Intent {intent}.", "actions")

def say_action_open(tts, url: str):
    _s(tts, f"Opening {url.replace('https://','').replace('http://','')}", "minimal")

def say_unknown(tts):
    _s(tts, "Sorry, I didn't catch that. Try saying: open YouTube.", "minimal")

def say_listen_timeout(tts):
    _s(tts, "I didn't hear anything.", "minimal")

def say_error_listen(tts):
    _s(tts, "I had trouble hearing you.", "minimal")

def say_error_open(tts):
    _s(tts, "I couldn't open that site.", "minimal")
