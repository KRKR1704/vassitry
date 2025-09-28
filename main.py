# --- load .env *before anything else* so keys are available to all modules ---
try:
    from dotenv import load_dotenv  # pip install python-dotenv
    load_dotenv()
except Exception as _e:
    print(f"[Ultron][.env] Skipped loading .env: {_e}")

import json
import time
import os
import re
import platform
import ctypes
import threading
from datetime import datetime, UTC

from pynput import keyboard  # <-- NEW: for Esc-to-cancel

from ultron.config import LOGS_PATH, BROWSER, WAKE_ENGINE, HOTKEY
from ultron.wakeword import WakeWordEngine
from ultron.listener import Listener
from ultron.tts import TTS
from ultron.nlp.intent import parse_intent
from ultron.skills.browser import open_url
from ultron.skills import weather as weather_skill

# --- Optional skills (import defensively) ---
try:
    from ultron.skills.apps import open_app           # desktop app launcher
except Exception:
    open_app = None

try:
    from ultron.skills.apps import open_browser_app   # browser app launcher
except Exception:
    open_browser_app = None

try:
    from ultron.skills import system as sysctl        # system controls (volume, wifi, etc.)
except Exception:
    sysctl = None

# Gemini fallback (log status so you know if it's active)
try:
    from ultron.skills.gemini import ask_gemini
    print("[Ultron][Gemini] ask_gemini() loaded. Key present:",
          bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")))
except Exception as e:
    ask_gemini = None
    print(f"[Ultron][Gemini] disabled: {e}")

from ultron.ack import wake_ack
from ultron.hotkey import HotkeyEngine

IS_WINDOWS = platform.system() == "Windows"
_user32 = ctypes.windll.user32 if IS_WINDOWS else None

tts = TTS()

# ==== NEW: global cancel flag + helper ========================================
SPEECH_CANCEL = threading.Event()

def stop_speaking():
    """Signal any ongoing TTS to stop ASAP."""
    SPEECH_CANCEL.set()
    try:
        # If your TTS class exposes a stop() / cancel() method, call it.
        if hasattr(tts, "stop"):
            tts.stop()
    except Exception:
        pass
# ==============================================================================

listener = Listener(
    energy_threshold=300,
    dynamic_energy=True,
    calibrate_on_start=True,
    calibration_duration=0.25,  # fast boot calibration
    pause_threshold=0.8,        # wait a bit longer before deciding you stopped
    non_speaking_duration=0.30, # tolerate tiny gaps
    phrase_time_limit=15        # more time to speak
)

def log_event(event: dict):
    event["ts"] = datetime.now(UTC).isoformat()
    os.makedirs(os.path.dirname(LOGS_PATH), exist_ok=True)
    with open(LOGS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

def log_action(name: str, status: str, **fields):
    payload = {"type": "action", "name": name, "status": status}
    payload.update(fields)
    log_event(payload)

def _ensure_url(site: str) -> str:
    """
    Build a valid URL from a spoken site name.
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
    Escape hatch: press ESC to cancel speaking.
    """
    if not text:
        return

    if SPEECH_CANCEL.is_set():
        return

    text = text.strip()
    if len(text) <= chunk_size:
        # single shot
        try:
            tts.speak(text)
        except Exception:
            pass
        return

    buf = []
    for token in text.replace("\n", " ").split(" "):
        if SPEECH_CANCEL.is_set():
            break
        # flush chunk if it would overflow
        if sum(len(x) for x in buf) + len(buf) + len(token) > chunk_size:
            try:
                tts.speak(" ".join(buf))
            except Exception:
                pass
            buf = [token]
        else:
            buf.append(token)

    if not SPEECH_CANCEL.is_set() and buf:
        try:
            tts.speak(" ".join(buf))
        except Exception:
            pass

# -------- Audio device-name extraction helpers --------
_GENERIC_AUDIO_WORDS = {
    "audio","sound","output","device","the","my","default",
    "headphones","headset","headphone","speaker","speakers"
}

def _extract_device_name_from_text(utterance: str) -> str | None:
    """
    Pull a device-ish name from the user's phrase.
    """
    s = (utterance or "").strip()
    if not s:
        return None

    m = re.search(r"[\"“']\s*([^\"”']+?)\s*[\"”']", s)
    if m:
        name = m.group(1).strip()
        return name if len(name) >= 2 else None

    low = s.lower()
    m = re.search(
        r"(?:switch|set|change|route|move)\s+(?:the\s+)?(?:audio|sound)?\s*(?:output|device)?\s*(?:to|onto|over to)\s+(.+)$",
        low
    )
    tail = m.group(1).strip() if m else low

    tokens = [t for t in re.split(r"[\s,]+", tail) if t and t not in _GENERIC_AUDIO_WORDS]
    while tokens and tokens[-1] in {"please","now","thanks"}:
        tokens.pop()
    name = " ".join(tokens).strip()
    return name if len(name) >= 3 else None

# ===================== Strict Hotkey Guard =====================
VK = {
    "shift": [0xA0, 0xA1], "ctrl": [0xA2, 0xA3], "alt": [0xA4, 0xA5],
    "win": [0x5B, 0x5C], "cmd": [0x5B, 0x5C], "meta": [0x5B, 0x5C], "super": [0x5B, 0x5C],
    "space": [0x20], "tab": [0x09], "enter": [0x0D], "esc": [0x1B], "escape": [0x1B],
    "backspace": [0x08], "delete": [0x2E],
}

def _vk_for_char(ch: str) -> int | None:
    if len(ch) != 1:
        return None
    c = ch.upper()
    if "A" <= c <= "Z" or "0" <= c <= "9":
        return ord(c)
    return None

def _vk_for_token(tok: str) -> list[int]:
    t = tok.strip().lower()
    if t in VK:
        return VK[t][:]
    if t.startswith("f") and t[1:].isdigit():
        n = int(t[1:])
        if 1 <= n <= 24:
            return [0x70 + (n - 1)]
    v = _vk_for_char(t)
    return [v] if v is not None else []

def _parse_hotkey_to_requirements(combo: str) -> list[list[int]]:
    parts = [p for p in re.split(r"[+\-]", combo or "") if p.strip()]
    reqs: list[list[int]] = []
    for p in parts:
        vks = _vk_for_token(p)
        if vks:
            reqs.append(vks)
    return reqs

def _vk_down(vk: int) -> bool:
    if not (IS_WINDOWS and _user32):
        return True
    state = _user32.GetAsyncKeyState(ctypes.c_int(vk))
    return bool(state & 0x8000)

def _hotkey_confirm_pressed(reqs: list[list[int]], samples: int = 3, interval_ms: int = 50) -> bool:
    if not reqs:
        return True
    for _ in range(max(1, samples)):
        if not all(any(_vk_down(vk) for vk in group) for group in reqs):
            return False
        time.sleep(interval_ms / 1000.0)
    return True

_HOTKEY_REQS = _parse_hotkey_to_requirements(HOTKEY)
_LAST_HOTKEY_TS = 0.0
_HOTKEY_LOCK = threading.Lock()
_HOTKEY_COOLDOWN_SEC = 1.25
# ===================== End Hotkey Guard =====================

def _speak_ok_fail(ok: bool, ok_msg: str, fail_msg: str):
    tts.speak(ok_msg if ok else fail_msg)

def handle_command(text: str):
    intent = parse_intent(text)
    print(f"[Ultron] Intent={intent.intent} entity={intent.entity}")
    log_event({"type": "asr_result", "text": text, "intent": intent.intent, "entity": intent.entity})

    # ---------- Websites / Apps ----------
    if intent.intent == "open_site" and intent.entity:
        url = _ensure_url(intent.entity)
        say = f"Opening {url.replace('https://','').replace('http://','')}"
        print(f"[Ultron] {say}")
        tts.speak_blocking(say, timeout=2.5)
        ok = open_url(url, browser_pref=BROWSER)
        log_action("open_site", "success" if ok else "failed", target=url)
        return

    if intent.intent == "open_app" and isinstance(intent.entity, str):
        app = intent.entity.strip()
        said = f"Opening {app}"
        print(f"[Ultron] {said}")
        tts.speak_blocking(said, timeout=2.5)

        ok = False

        # Try desktop app first
        if open_app is not None:
            try:
                ok = open_app(app)
            except Exception:
                ok = False

        # Fallback → browser app
        if not ok and open_browser_app is not None:
            try:
                ok = open_browser_app(app)
            except Exception:
                ok = False

        log_action("open_app", "success" if ok else "failed", target=app)
        if not ok:
            tts.speak(f"I couldn't find or launch {app} on this PC.")
        return

    # ---------- Audio ----------
    if intent.intent == "volume_set" and intent.entity and sysctl:
        try:
            pct = int(intent.entity)
        except Exception:
            pct = 50
        ok = False
        try:
            ok = sysctl.set_volume(pct)
        finally:
            _speak_ok_fail(ok, f"Volume set to {pct} percent.", "Sorry, I couldn't change the volume.")
            log_action("volume_set", "success" if ok else "failed", target=pct)
        return

    if intent.intent == "volume_up" and sysctl:
        step = int(intent.entity) if intent.entity else 5
        ok = sysctl.volume_up(step)
        _speak_ok_fail(ok, "Volume up.", "Volume up failed.")
        log_action("volume_up", "success" if ok else "failed", target=step)
        return

    if intent.intent == "volume_down" and sysctl:
        step = int(intent.entity) if intent.entity else 5
        ok = sysctl.volume_down(step)
        _speak_ok_fail(ok, "Volume down.", "Volume down failed.")
        log_action("volume_down", "success" if ok else "failed", target=step)
        return

    if intent.intent == "volume_mute" and sysctl:
        ok = sysctl.mute()
        _speak_ok_fail(ok, "Muted.", "Mute failed.")
        log_action("mute", "success" if ok else "failed")
        return

    if intent.intent == "volume_unmute" and sysctl:
        ok = sysctl.unmute()
        _speak_ok_fail(ok, "Unmuted.", "Unmute failed.")
        log_action("unmute", "success" if ok else "failed")
        return

    # ---------- Audio devices ----------
    if intent.intent == "audio_list_outputs":
        if sysctl and hasattr(sysctl, "audio_list_outputs"):
            try:
                outs = sysctl.audio_list_outputs() or []
            except Exception as e:
                print(f"[Ultron][ERR] audio_list_outputs: {e}")
                outs = []
            if outs:
                names = [
                    f'{d.get("name","Unknown")}' + (' (default)' if d.get("default") != "none" else '')
                    for d in outs
                ]
                preview = ", ".join(names[:3]) + ("..." if len(names) > 3 else "")
                tts.speak(f"Available outputs: {preview}.")
                for i, d in enumerate(outs, 1):
                    print(f'[{i}] {d.get("name")} | state={d.get("state")} | default={d.get("default")} | id={d.get("id")}')
                log_action("audio_list_outputs", "success", outputs=outs)
            else:
                tts.speak("I couldn't list audio outputs.")
                log_action("audio_list_outputs", "failed")
        else:
            tts.speak("Listing audio outputs isn't available on this build.")
            log_action("audio_list_outputs", "not_supported")
        return

    if intent.intent == "audio_switch_output":
        requested = (intent.entity or "").strip()
        generic = requested.lower() in _GENERIC_AUDIO_WORDS or not requested
        if generic:
            alt = _extract_device_name_from_text(text)
            if alt:
                requested = alt

        if not requested or requested.lower() in _GENERIC_AUDIO_WORDS:
            tts.speak("Tell me the device name, like ‘switch audio to OnePlus Buds Z2’. You can also say ‘list audio outputs’.")
            log_action("audio_switch_output", "failed", requested=intent.entity, reason="no_device_name_extracted")
            return

        ok, info = False, "not_supported"
        if sysctl and hasattr(sysctl, "audio_switch_output"):
            try:
                ok, info = sysctl.audio_switch_output(requested)
            except Exception as e:
                print(f"[Ultron][ERR] audio_switch_output: {e}")
                ok, info = False, "error"

        if ok:
            tts.speak(f"Audio output set to {info}.")
            log_action("audio_switch_output", "success", requested=requested, chosen=info)
            return

        # Fallback: check paired Bluetooth devices and open settings if we find a match
        bt_list = []
        if sysctl and hasattr(sysctl, "bluetooth_list_paired"):
            try:
                bt_list = sysctl.bluetooth_list_paired() or []
            except Exception as e:
                print(f"[Ultron][ERR] bluetooth_list_paired: {e}")

        if bt_list:
            try:
                from difflib import get_close_matches
                names = [d["name"] for d in bt_list]
                match = get_close_matches(requested, names, n=1, cutoff=0.6)
                best = match[0] if match else next((n for n in names if requested.lower() in n.lower()), None)
            except Exception:
                best = None

            if best:
                tts.speak(f"I found a paired device named {best}. Please connect it from Bluetooth settings; I’ll open it now.")
                if sysctl and hasattr(sysctl, "open_bluetooth_settings"):
                    try:
                        sysctl.open_bluetooth_settings()
                    except Exception as e:
                        print(f"[Ultron][ERR] open_bluetooth_settings: {e}")
                log_action("audio_switch_output", "paired_not_connected", requested=requested, paired_match=best, reason=info)
                return

        if info in ("device_not_found", "no_devices"):
            tts.speak("I couldn't find that audio device. Make sure it’s connected, then say ‘list audio outputs’ and try again.")
        elif info == "not_supported":
            tts.speak("Switching audio outputs isn't available on this build.")
        else:
            tts.speak("I couldn't switch the audio output.")
        log_action("audio_switch_output", "failed", requested=requested, reason=info)
        return

    # ---------- Display (brightness) ----------
    if intent.intent == "brightness_set" and sysctl and intent.entity:
        try:
            pct = int(intent.entity)
        except Exception:
            pct = 50
        ok = sysctl.set_brightness(pct)
        _speak_ok_fail(ok, f"Brightness set to {pct} percent.", "Brightness control isn't available.")
        log_action("brightness_set", "success" if ok else "failed", target=pct)
        return

    if intent.intent == "brightness_up" and sysctl:
        step = int(intent.entity) if intent.entity else 10
        ok = sysctl.brightness_up(step)
        _speak_ok_fail(ok, "Brightness up.", "Brightness up failed.")
        log_action("brightness_up", "success" if ok else "failed", target=step)
        return

    if intent.intent == "brightness_down" and sysctl:
        step = int(intent.entity) if intent.entity else 10
        ok = sysctl.brightness_down(step)
        _speak_ok_fail(ok, "Brightness down.", "Brightness down failed.")
        log_action("brightness_down", "success" if ok else "failed", target=step)
        return

    # ---------- Night Light ----------
    if intent.intent == "night_light_toggle" and sysctl:
        ok = sysctl.night_light_toggle()
        _speak_ok_fail(ok, "Night light toggled.", "I couldn't toggle Night light.")
        log_action("night_light_toggle", "success" if ok else "failed")
        return

    if intent.intent == "night_light_on" and sysctl:
        ok = sysctl.night_light_on()
        _speak_ok_fail(ok, "Night light on.", "I couldn't turn Night light on.")
        log_action("night_light_on", "success" if ok else "failed")
        return

    if intent.intent == "night_light_off" and sysctl:
        ok = sysctl.night_light_off()
        _speak_ok_fail(ok, "Night light off.", "I couldn't turn Night light off.")
        log_action("night_light_off", "success" if ok else "failed")
        return

    # ---------- Display mode / Projection ----------
    if intent.intent == "display_mode" and sysctl and intent.entity:
        mode = intent.entity  # 'extend' | 'clone' | 'internal' | 'external'
        try:
            ok = sysctl.display_mode(mode)
        except Exception as e:
            print(f"[Ultron][ERR] display_mode: {e}")
            ok = False
        spoken = {
            "extend": "Extended display.",
            "clone": "Duplicated display.",
            "internal": "PC screen only.",
            "external": "Second screen only."
        }.get(mode, "Display mode changed.")
        _speak_ok_fail(ok, spoken, "I couldn't change the display mode.")
        log_action("display_mode", "success" if ok else "failed", mode=mode)
        return

    # ---------- Connectivity (Wi-Fi) ----------
    if intent.intent == "wifi_status":
        if sysctl and hasattr(sysctl, "wifi_status"):
            try:
                st = sysctl.wifi_status() or {}
            except Exception as e:
                print(f"[Ultron][ERR] wifi_status: {e}")
                st = {}
            enabled = st.get("enabled")
            state = (st.get("state") or "").lower()
            ssid = st.get("ssid")
            signal = st.get("signal")
            if enabled is False:
                tts.speak("Wi-Fi is off.")
            elif state == "connected" and ssid:
                if isinstance(signal, int):
                    tts.speak(f"Connected to {ssid}, signal {signal} percent.")
                else:
                    tts.speak(f"Connected to {ssid}.")
            elif state in ("disconnected", "disconnecting"):
                tts.speak("Wi-Fi is on but not connected.")
            elif enabled is True and state == "unknown":
                tts.speak("Wi-Fi is on, status unknown.")
            else:
                tts.speak("Wi-Fi status is unknown.")
            log_action("wifi_status", "success", **st)
        else:
            tts.speak("Wi-Fi status isn't available on this build.")
            log_action("wifi_status", "not_supported")
        return

    if intent.intent == "wifi_on":
        if sysctl and hasattr(sysctl, "wifi_on"):
            try:
                ok = sysctl.wifi_on()
            except Exception as e:
                print(f"[Ultron][ERR] wifi_on: {e}")
                ok = False
            _speak_ok_fail(ok, "Wi-Fi turned on.", "I couldn't turn Wi-Fi on.")
            log_action("wifi_on", "success" if ok else "failed")
        else:
            tts.speak("Turning Wi-Fi on isn't available on this build.")
            log_action("wifi_on", "not_supported")
        return

    if intent.intent == "wifi_off":
        if sysctl and hasattr(sysctl, "wifi_off"):
            try:
                ok = sysctl.wifi_off()
            except Exception as e:
                print(f"[Ultron][ERR] wifi_off: {e}")
                ok = False
            _speak_ok_fail(ok, "Wi-Fi turned off.", "I couldn't turn Wi-Fi off.")
            log_action("wifi_off", "success" if ok else "failed")
        else:
            tts.speak("Turning Wi-Fi off isn't available on this build.")
            log_action("wifi_off", "not_supported")
        return

    if intent.intent == "wifi_disconnect":
        if sysctl and hasattr(sysctl, "wifi_disconnect"):
            ok = False
            try:
                ok = sysctl.wifi_disconnect()
            except Exception as e:
                print(f"[Ultron][ERR] wifi_disconnect: {e}")
            _speak_ok_fail(ok, "Disconnected from Wi-Fi.", "I couldn't disconnect from Wi-Fi.")
            log_action("wifi_disconnect", "success" if ok else "failed")
        else:
            tts.speak("Disconnecting from Wi-Fi isn't available on this build.")
            log_action("wifi_disconnect", "not_supported")
        return

    if intent.intent == "wifi_connect" and intent.entity:
        ssid = intent.entity.strip().strip('"')
        if sysctl and hasattr(sysctl, "wifi_connect"):
            try:
                ok = sysctl.wifi_connect(ssid)
            except Exception as e:
                print(f"[Ultron][ERR] wifi_connect: {e}")
                ok = False
            _speak_ok_fail(ok, f"Connecting to {ssid}.", f"I couldn't connect to {ssid}.")
            log_action("wifi_connect", "success" if ok else "failed", ssid=ssid)
        else:
            tts.speak("Connecting to Wi-Fi networks isn't available on this build.")
            log_action("wifi_connect", "not_supported", ssid=ssid)
        return
    # ---------- Weather ----------
    if intent.intent == "weather.get":
        slots = intent.slots or {}
        city = slots.get("city")
        when = slots.get("when") or "today"
        print(f"[Ultron][Weather][DBG] slots={slots} city={city!r} when={when!r}")
        weather_skill.speak_weather_sync(tts, city, when)
        log_action("weather.get", "success", city=city, when=when)
        return
    # ---------- Power ----------
    if intent.intent == "power_sleep" and sysctl:
        tts.speak("Going to sleep.")
        log_action("sleep", "issued")
        try:
            sysctl.sleep()
        except Exception as e:
            print(f"[Ultron][ERR] sleep: {e}")
        return

    if intent.intent == "power_shutdown" and sysctl:
        tts.speak("Shutting down.")
        log_action("shutdown", "issued")
        try:
            sysctl.shutdown()
        except Exception as e:
            print(f"[Ultron][ERR] shutdown: {e}")
        return

    if intent.intent == "power_restart" and sysctl:
        tts.speak("Restarting.")
        log_action("restart", "issued")
        try:
            sysctl.restart()
        except Exception as e:
            print(f"[Ultron][ERR] restart: {e}")
        return

    if intent.intent == "power_lock" and sysctl:
        tts.speak("Locked.")
        log_action("lock", "issued")
        try:
            sysctl.lock()
        except Exception as e:
            print(f"[Ultron][ERR] lock: {e}")
        return

    if intent.intent == "battery_query" and sysctl:
        pct = None
        try:
            pct = sysctl.battery_percent()
        except Exception as e:
            print(f"[Ultron][ERR] battery: {e}")
        if pct is None:
            tts.speak("I couldn't read the battery level.")
            log_action("battery_query", "failed")
        else:
            tts.speak(f"Battery at {pct} percent.")
            log_action("battery_query", "success", target=pct)
        return

    # ---------- Window / App basics ----------
    if intent.intent == "window_minimize" and sysctl:
        ok = sysctl.minimize_active_window()
        _speak_ok_fail(ok, "Minimized.", "I couldn't minimize that.")
        log_action("window_minimize", "success" if ok else "failed")
        return

    if intent.intent == "window_maximize" and sysctl:
        ok = sysctl.maximize_active_window()
        _speak_ok_fail(ok, "Maximized.", "I couldn't maximize that.")
        log_action("window_maximize", "success" if ok else "failed")
        return

    if intent.intent == "window_close" and sysctl:
        ok = sysctl.close_active_window()
        _speak_ok_fail(ok, "Closed.", "I couldn't close that.")
        log_action("window_close", "success" if ok else "failed")
        return

    # ---------- Utility ----------
    if intent.intent == "screenshot" and sysctl:
        path = None
        try:
            path = sysctl.screenshot(None)
        except Exception as e:
            print(f"[Ultron][ERR] screenshot: {e}")
        if path:
            try:
                sysctl.reveal_in_explorer(path)
            except Exception:
                pass
        tts.speak("Screenshot saved in your Screenshots folder." if path else "I couldn't take a screenshot.")
        log_action("screenshot", "success" if path else "failed", target=path)
        return

    # ---------- Fallback: General question → Gemini ----------
    if ask_gemini is not None:
        print(f"[Ultron] Asking Gemini: {text}")
        tts.speak("Let me check that for you.")
        answer = ask_gemini(text)
        print(f"[Ultron] Gemini says: {answer}")
        log_event({"type": "action", "name": "ask_gemini", "query": text, "answer": answer})
        if isinstance(answer, str) and answer.startswith("Error contacting Gemini:"):
            tts.speak("I couldn't reach Gemini right now.")
            return

        # NEW: clear cancel flag before long read
        SPEECH_CANCEL.clear()
        _speak_chunks(answer if isinstance(answer, str) else str(answer))
        return

    # ---------- Final fallback ----------
    tts.speak("Try: ‘wifi status’, ‘extend my display’, ‘list audio outputs’, or ‘set volume to 50 percent’.")
    log_action("unknown", "no_intent")

# -------- trigger paths --------
def on_wake():
    print("[Ultron] Listening (triggered)…")
    # Audible wake ack (blocking so the user hears it once)
    try:
        wake_ack(tts, blocking=True)
    except Exception:
        try:
            tts.speak("Ultron is listening.")
        except Exception:
            pass
    time.sleep(0.10)

    print("[Ultron] Capturing command...")
    try:
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

    mode = (WAKE_ENGINE or "").strip().lower()
    print(f"[Ultron] Starting with trigger mode: {mode or 'hotkey'}")
    print("[Ultron] GOOGLE_API_KEY present:",
          bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")))
    log_event({"type": "boot", "trigger": mode or "hotkey"})

    # Startup line (blocking so you hear it once)
    tts.speak_blocking("Ultron is standing by.", timeout=2.5)

    # ==== NEW: start a global keyboard listener for ESC cancel ================
    def _kb_on_press(key):
        if key == keyboard.Key.esc:
            print("[Ultron][TTS] ESC pressed → cancel speech")
            stop_speaking()

    kb_listener = keyboard.Listener(on_press=_kb_on_press)
    kb_listener.daemon = True
    kb_listener.start()
    # ==========================================================================

    # Common hotkey callback used by hotkey-only and both-modes
    def _on_hotkey():
        # Strict hotkey guard: cooldown + physical key confirmation
        global _LAST_HOTKEY_TS
        with _HOTKEY_LOCK:
            now = time.time()
            if (now - _LAST_HOTKEY_TS) < _HOTKEY_COOLDOWN_SEC:
                log_event({"type": "hotkey_ignored", "reason": "cooldown"})
                return
            if not _hotkey_confirm_pressed(_HOTKEY_REQS, samples=3, interval_ms=50):
                log_event({"type": "hotkey_ignored", "reason": "not_confirmed"})
                return
            _LAST_HOTKEY_TS = now

        log_event({"type": "hotkey_trigger", "combo": HOTKEY})
        on_wake()

    trigger = None
    ww = None

    try:
        if mode == "hotkey":
            trigger = HotkeyEngine(HOTKEY, _on_hotkey)
            trigger.start()
            print(f"[Ultron] Registered hotkey {HOTKEY} (press to talk).")

            while True:
                time.sleep(0.5)

        elif mode == "both":
            trigger = HotkeyEngine(HOTKEY, _on_hotkey)
            try:
                trigger.start()
            except Exception:
                trigger = None

            ww = WakeWordEngine(on_wake=on_wake)
            try:
                ww.start()
            except Exception as e:
                print(f"[Ultron][WakeWord] Failed to start wakeword engine: {e}")
                ww = None

            print(f"[Ultron] Running both hotkey and wakeword triggers. Press {HOTKEY} or speak the wake word.")
            while True:
                time.sleep(0.5)

        else:
            # Default wakeword path (openwakeword or porcupine based on WAKE_ENGINE)
            ww = WakeWordEngine(on_wake=on_wake)
            ww.start()
            print("[Ultron] Wakeword listener started.")
            while True:
                time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n[Ultron] Shutting down...")
    finally:
        # Stop trigger if started
        try:
            if trigger:
                trigger.stop()
        except Exception:
            pass
        try:
            if ww:
                ww.stop()
        except Exception:
            pass

        # Stop keyboard listener cleanly
        try:
            kb_listener.stop()
        except Exception:
            pass

        # Common shutdown tasks
        tts.speak_blocking("Ultron shutting down.", timeout=3.0)
        try:
            tts.shutdown(timeout=3.0)
        except Exception:
            pass
        log_event({"type": "shutdown"})

if __name__ == "__main__":
    main()
