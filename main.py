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
from ultron.skills.apps import open_app
from ultron.skills.gemini import ask_gemini
from ultron.ack import wake_ack


tts = TTS()
listener = Listener(
    energy_threshold=300,
    dynamic_energy=True,
    calibrate_on_start=True,
    calibration_duration=0.25,  # fast boot calibration
    pause_threshold=0.8,         # wait a bit longer before deciding you stopped
    non_speaking_duration=0.30,  # tolerate tiny gaps
    phrase_time_limit=15         # more time to speak
)


def log_event(event: dict):
    event["ts"] = datetime.utcnow().isoformat() + "Z"
    os.makedirs(os.path.dirname(LOGS_PATH), exist_ok=True)
    with open(LOGS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _ensure_url(site: str) -> str:
    """
    Build a valid URL from a spoken site name:
    - trims and lowercases
    - removes spaces (e.g., "hugging face" -> "huggingface")
    - adds .com if no dot is present
    - prefixes https:// if no scheme
    """
    s = (site or "").strip().lower()
    if not s:
        return s
    s = s.replace(" ", "")
    if not s.startswith(("http://", "https://")):
        if "." not in s:
            s += ".com"
        s = "https://" + s
    return s


def _speak_chunks(text: str, chunk_size: int = 350):
    """
    Safely speak long text by chunking to avoid TTS buffer issues.
    Splits on sentence boundaries where possible.
    """
    if not text:
        return
    text = text.strip()
    if len(text) <= chunk_size:
        tts.speak(text)
        return

    buf = []
    for token in text.replace("\n", " ").split(" "):
        if sum(len(x) for x in buf) + len(buf) + len(token) > chunk_size:
            tts.speak(" ".join(buf))
            buf = [token]
        else:
            buf.append(token)
    if buf:
        tts.speak(" ".join(buf))


def handle_command(text: str):
    intent = parse_intent(text)
    log_event({"type": "asr_result", "text": text, "intent": intent.intent, "entity": intent.entity})

    # --- OPEN WEBSITE ---
    if intent.intent == "open_site" and isinstance(intent.entity, str):
        url = _ensure_url(intent.entity)
        say = f"Opening {url.replace('https://','').replace('http://','')}"
        print(f"[Ultron] {say}")
        tts.speak_blocking(say, timeout=2.5)
        ok = open_url(url, browser_pref=BROWSER)
        log_event({"type": "action", "name": "open_site", "target": url, "status": "success" if ok else "failed"})
        return

    # --- OPEN DESKTOP APP / BROWSER APP ---
    if intent.intent == "open_app" and isinstance(intent.entity, str):
        app = intent.entity
        say = f"Opening {app}"
        print(f"[Ultron] {say}")
        tts.speak_blocking(say, timeout=2.5)
        ok = open_app(app)
        log_event({"type": "action", "name": "open_app", "target": app, "status": "success" if ok else "failed"})
        if not ok:
            tts.speak(f"I couldn't find {app} on this PC.")
        return

    # --- FALLBACK: GENERAL QUESTION → GEMINI ---
    print(f"[Ultron] Asking Gemini: {text}")
    tts.speak("Let me check that for you.")
    answer = ask_gemini(text)

    # Log and speak the result (chunked for stability)
    print(f"[Ultron] Gemini says: {answer}")
    log_event({"type": "action", "name": "ask_gemini", "query": text, "answer": answer})

    if answer.startswith("Error contacting Gemini:"):
        tts.speak("I couldn't reach Gemini right now.")
        return

    _speak_chunks(answer)


def on_wake():
    print("[Ultron] Wake word detected. Listening...")

    # Non-blocking wake acknowledgment so the mic opens immediately
    try:
        # If your wake_ack supports a non-blocking/beep mode, you can use it instead:
        # wake_ack(tts, blocking=False)
        tts.speak("Ultron is listening.")
    except Exception:
        pass

    print("[Ultron] Capturing command...")
    try:
        # More time to START (timeout) and more time to SPEAK (phrase_time_limit)
        cmd = listener.listen_once(timeout=10, phrase_time_limit=15)
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

    # Startup line (blocking so you hear it once)
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
        # Shutdown line (blocking)
        tts.speak_blocking("Ultron shutting down.", timeout=3.0)
        try:
            tts.shutdown(timeout=3.0)
        except Exception:
            pass
        log_event({"type": "shutdown"})


if __name__ == "__main__":
    main()
