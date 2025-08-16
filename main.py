import json
import time
import os
from datetime import datetime

from ultron.config import LOGS_PATH, BROWSER, WAKE_ENGINE
from ultron.wakeword import WakeWordEngine
from ultron.listener import Listener
from ultron.tts import TTS
from ultron.nlp.intent import parse_intent
from ultron.skills.browser import open_url
from ultron.skills.apps import open_browser_app
from ultron.ack import wake_ack

tts = TTS()
listener = Listener(energy_threshold=300)

def log_event(event: dict):
    event["ts"] = datetime.utcnow().isoformat() + "Z"
    os.makedirs(os.path.dirname(LOGS_PATH), exist_ok=True)
    with open(LOGS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

def _ensure_url(site: str) -> str:
    s = (site or "").strip().lower()
    if not s:
        return s
    if s.startswith(("http://", "https://")):
        return s
    if "." not in s:
        s += ".com"
    return "https://" + s

def handle_command(text: str):
    intent = parse_intent(text)
    log_event({"type": "asr_result", "text": text, "intent": intent.intent, "entity": intent.entity})

    if intent.intent == "open_site" and intent.entity:
        url = _ensure_url(intent.entity)
        to_say = f"Opening {url.replace('https://','').replace('http://','')}"
        print(f"[Ultron] {to_say}")
        tts.speak_blocking(to_say, timeout=2.5)
        ok = open_url(url, browser_pref=BROWSER)
        log_event({"type": "action", "name": "open_site", "target": url, "status": "success" if ok else "failed"})

    elif intent.intent == "open_app" and intent.entity:
        app = intent.entity
        to_say = f"Opening {app} browser"
        print(f"[Ultron] {to_say}")
        tts.speak_blocking(to_say, timeout=2.5)
        ok = open_browser_app(app)
        log_event({"type": "action", "name": "open_app", "target": app, "status": "success" if ok else "failed"})

    else:
        tts.speak("Try saying: open YouTube.")
        log_event({"type": "action", "name": "unknown", "status": "no_intent"})

def on_wake():
    print("[Ultron] Wake word detected. Listening...")
    wake_ack(tts, blocking=True)
    time.sleep(0.10)

    print("[Ultron] Capturing command...")
    try:
        cmd = listener.listen_once(timeout=8, phrase_time_limit=10)
    except Exception as e:
        print(f"[Ultron] Listener error: {e}")
        log_event({"type": "listen_error", "error": str(e)})
        tts.speak("I had trouble hearing you.")
        return

    if not cmd:
        tts.speak("I didn't hear anything.")
        log_event({"type": "listen_timeout"})
        return

    print(f"[Ultron] Heard: {cmd}")
    handle_command(cmd)

def main():
    os.makedirs("logs", exist_ok=True)
    print(f"[Ultron] Starting with wake engine: {WAKE_ENGINE}")
    log_event({"type": "boot", "wake_engine": WAKE_ENGINE})

    tts.speak_blocking("Ultron is standing by.", timeout=2.5)

    ww = WakeWordEngine(on_wake=on_wake)
    ww.start()

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[Ultron] Shutting down...")
    finally:
        try:
            ww.stop()
        except Exception:
            pass
        tts.speak_blocking("Ultron shutting down.", timeout=3.0)
        try:
            tts.shutdown(timeout=3.0)
        except Exception:
            pass
        log_event({"type": "shutdown"})

if __name__ == "__main__":
    main()
