# --- load .env *before anything else* so keys are available to all modules ---
import os
import sys

# Ensure we are running from the script's directory so relative paths (logs/, .env) work
if getattr(sys, 'frozen', False):
    # If bundled (e.g. PyInstaller), use the executable's dir
    _base_dir = os.path.dirname(sys.executable)
else:
    # Normal python script
    _base_dir = os.path.dirname(os.path.abspath(__file__))

os.chdir(_base_dir)
print(">>> main.py started")

# --- FIX FOR PYTHONW (Background Service) ---
# pythonw.exe does not have stdout/stderr, so print() can cause a crash.
# We redirect them to a log file or devnull.
if sys.executable.endswith("pythonw.exe"):
    # Redirect to a log file for debugging startup issues
    _log_file = os.path.join(_base_dir, "logs", "service_startup.log")
    os.makedirs(os.path.dirname(_log_file), exist_ok=True)
    sys.stdout = open(_log_file, "a", encoding="utf-8", buffering=1)
    sys.stderr = open(_log_file, "a", encoding="utf-8", buffering=1)
# --------------------------------------------

# --- Single-instance guard (Windows) ---
# Prevent multiple background launches from competing for the microphone.
try:
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        _mutex_name = "Global\\Ultron_vassitry_singleton"
        _mutex = kernel32.CreateMutexW(None, ctypes.c_bool(True), _mutex_name)
        _last_err = kernel32.GetLastError()
        # ERROR_ALREADY_EXISTS == 183
        if _last_err == 183:
            # Another instance is running. In normal use we exit silently to
            # avoid multiple background services competing for the mic. For
            # development, allow an override via ULTRON_DEV so you can launch
            # a second instance for UI testing.
            if not os.getenv("ULTRON_DEV"):
                sys.exit(0)
            else:
                print("[Ultron][DEV] Another instance detected — continuing because ULTRON_DEV=1")
except Exception:
    # If the guard fails for any reason, continue (don't prevent startup)
    pass


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
import traceback

from pynput import keyboard

from ultron.config import LOGS_PATH, BROWSER, WAKE_ENGINE, HOTKEY, HOTKEY_MINIMIZE
from ultron.wakeword import WakeWordEngine
from ultron.listener import Listener
from ultron.tts import TTS
from ultron.nlp.intent import parse_intent
from ultron.skills.browser import open_url
from ultron.skills import weather as weather_skill
from ultron.skills import site_search

# >>> NEW: Google Calendar integration <<<
# (safe import; if the file isn't present, calendar features will be skipped gracefully)
try:
    from ultron.skills.calendar_gcal import create_event_from_text as gcal_create_from_text
except Exception:
    gcal_create_from_text = None

# ---- minimal logging switch ----
DEBUG = True  # set True while debugging; False to silence startup logs

def log_debug(msg: str):
    if DEBUG:
        print(msg)

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
    log_debug(f"[Ultron][Gemini] ask_gemini() loaded. Key present: {bool(os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY'))}")
except Exception as e:
    ask_gemini = None
    log_debug(f"[Ultron][Gemini] disabled: {e}")

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

# Global UI handle (set when UI created) so wake callbacks can route to UI when present
MAIN_WINDOW = None

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
        try:
            tts.speak(text)
        except Exception:
            pass
        return

    buf = []
    for token in text.replace("\n", " ").split(" "):
        if SPEECH_CANCEL.is_set():
            break
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
# Global microphone lock to prevent concurrent listeners
MIC_LOCK = threading.Lock()
# ===================== End Hotkey Guard =====================

def _speak_ok_fail(ok: bool, ok_msg: str, fail_msg: str):
    tts.speak(ok_msg if ok else fail_msg)

def handle_command(text: str):
    intent = parse_intent(text)
    print(f"[Ultron] Intent={intent.intent} entity={intent.entity}")
    log_event({"type": "asr_result", "text": text, "intent": intent.intent, "entity": intent.entity})

    # ---------- Websites / Apps ----------
    if intent.intent == "open_site" and intent.entity:
        # Heuristic: if it doesn't have a dot (e.g. "notepad", "spotify"), try app first
        # unless it explicitly starts with http
        target = intent.entity.strip()
        is_url = "." in target or target.startswith(("http:", "https:"))
        
        if not is_url and open_app:
            # Try opening as app first
            print(f"[Ultron] '{target}' looks like an app, trying open_app first...")
            if open_app(target):
                tts.speak(f"Opening {target}.")
                log_action("open_app", "success", target=target, source="open_site_fallback")
                return

        # Otherwise, treat as site
        url = _ensure_url(target)
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

    # ---------- Site Search ----------
    if intent.intent == "site.search":
        slots = intent.slots or {}
        site  = slots.get("site")
        query = slots.get("query")

        # Tune behavior if you like:
        prefer_direct = True   # try direct on-site pattern (e.g., /search?q=)
        probe = False          # set True to verify which candidate actually works

        try:
            ok, url = site_search.open_site_search(
                open_url,
                site,
                query,
                browser_pref=BROWSER,
                prefer_direct=prefer_direct,
                probe=probe,
            )
            say_site = site or "the web"
            say_q = f" for {query}" if query else ""
            tts.speak_blocking(f"Searching {say_site}{say_q}.", timeout=2.0)
            log_action("site.search", "success" if ok else "failed",
                       site=site, query=query, target=url)
            if not ok:
                tts.speak("I couldn't open the browser.")
        except Exception as e:
            log_action("site.search", "error", site=site, query=query, error=str(e))
            tts.speak("I couldn't perform that search.")
        return

    # ---------- Calendar: Create event (Google Calendar) ----------
    if intent.intent == "calendar.create":
        if gcal_create_from_text is None:
            tts.speak("Calendar support isn't available in this build.")
            log_action("calendar.create", "not_supported")
            return
        try:
            # Prefer the raw utterance so NLP can see everything
            command_text = (intent.entity or text or "").strip()
            print(f"[Ultron][Calendar] Creating from text: {command_text}")
            tts.speak_blocking("Creating your event.", timeout=2.0)
            result = gcal_create_from_text(command_text)
            ok = bool(result and result.get("ok"))
            msg = (result or {}).get("message") or ("Created the event." if ok else "I couldn't create the event.")
            tts.speak(msg)
            log_action(
                "calendar.create",
                "success" if ok else "failed",
                **{k: v for k, v in (result or {}).items() if k in ("title", "start", "end", "link", "id", "message")}
            )
        except Exception as e:
            tts.speak("I couldn't create that event.")
            log_action("calendar.create", "error", error=str(e))
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
        _speak_ok_fail(ok, "Unmuted.", "Mute failed.")
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
    log_debug("[Ultron] Listening (triggered)…")
    # Audible wake ack (blocking so the user hears it once)
    try:
        # Use non-blocking voice ack to avoid delaying the mic capture
        wake_ack(tts, blocking=True)
    except Exception:
        try:
            tts.speak("Ultron is listening.")
        except Exception:
            pass
    # small pause to allow OS/device to settle after wake detection
    # Increase to 0.15s on Windows to avoid TTS blocking mic capture
    time.sleep(0.15)

    # Try to acquire mic lock so we don't have concurrent captures
    try:
        if not MIC_LOCK.acquire(blocking=False):
            log_debug("[Ultron] Mic busy, ignoring wake")
            return
    except Exception:
        # If lock acquisition fails unexpectedly, continue cautiously
        pass
    try:
        log_debug("[Ultron] Capturing command...")
        try:
            cmd = listener.listen_once(timeout=10, phrase_time_limit=15)
        except Exception as e:
            print(f"[Ultron] Listener error: {e}")
            log_event({"type": "listen_error", "error": str(e)})
            try:
                tts.speak("I had trouble hearing you.")
            except Exception:
                pass
            return

        if not cmd:
            try:
                tts.speak("I didn't hear anything.")
            except Exception:
                pass
            log_event({"type": "listen_timeout"})
            return

        log_debug(f"[Ultron] Heard: {cmd}")
    finally:
        try:
            MIC_LOCK.release()
        except Exception:
            pass
    # ALWAYS execute command centrally first so runtime actions occur
    try:
        handle_command(cmd)
    except Exception as _e:
        print("[Ultron][ERR] handle_command failed:", _e)
        traceback.print_exc()

    # THEN notify UI (optional, non-blocking cosmetic update)
    try:
        if MAIN_WINDOW is not None:
            try:
                print("[UI] voice received:", cmd)
                MAIN_WINDOW.on_voice_recognized(cmd)
            except Exception as _e:
                print("UI notify failed:", _e)
    except Exception:
        pass

def main():
    os.makedirs("logs", exist_ok=True)

    mode = (WAKE_ENGINE or "").strip().lower()
    log_debug(f"[Ultron] Starting with trigger mode: {mode or 'hotkey'}")
    log_debug(f"[Ultron] GOOGLE_API_KEY present: {bool(os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY'))}")
    log_event({"type": "boot", "trigger": mode or "hotkey"})

    # ==== Initialize app cache at startup ====
    try:
        from ultron.skills.app_scanner import initialize_app_cache
        initialize_app_cache()
    except Exception as e:
        log_debug(f"[Ultron] App cache initialization failed: {e}")

    # --- Start the Qt UI on the main thread BEFORE any blocking services ---
    try:
        from PySide6.QtWidgets import QApplication
        from ultron.ui.state import UIStateManager
        from ultron.ui.main_window import MainWindow

        app = QApplication(sys.argv)
        print("[Ultron][UI DEBUG] QApplication created")
        sm = UIStateManager()
        # Pass central command executor so UI input always reaches runtime
        win = MainWindow(state_manager=sm, command_executor=handle_command)
        print("[Ultron][UI DEBUG] MainWindow instance created")
        win.show()
        print("[Ultron][UI DEBUG] MainWindow.show() called")
        try:
            # Try to bring the window to the foreground in case it's off-screen or minimized
            from PySide6.QtCore import Qt
            try:
                win.raise_()
            except Exception:
                pass
            try:
                win.activateWindow()
            except Exception:
                pass
            try:
                win.setWindowState((win.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
            except Exception:
                pass
            print("[Ultron][UI DEBUG] Attempted to activate MainWindow (raise/activate)")
        except Exception:
            pass

        # expose global handle for on_wake routing
        global MAIN_WINDOW
        MAIN_WINDOW = win
    except Exception as e:
        print("Failed to start UI:", e)
        traceback.print_exc()
        # continue headless

    # Run background services (wakeword, hotkey, TTS startup) in a daemon thread
    def _run_triggers():
        # Startup line (blocking so you hear it once) — run in background
        try:
            tts.speak_blocking("Ultron is standing by.", timeout=2.5)
        except Exception:
            pass

        # If running under pythonw (VBS launcher), start a small log window so users see activity
        try:
            if sys.executable.lower().endswith("pythonw.exe"):
                try:
                    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "service_startup.log")
                    log_path = os.path.normpath(log_path)
                    from ultron.log_window import start_log_window_thread
                    start_log_window_thread(log_path)
                    log_debug("[Ultron][UI] Log window started for pythonw launcher.")
                except Exception as _e:
                    log_debug(f"[Ultron][UI] Failed to start log window: {_e}")
        except Exception:
            pass

        # ==== NEW: start a global keyboard listener for ESC cancel ================
        def _kb_on_press(key):
            if key == keyboard.Key.esc:
                log_debug("[Ultron][TTS] ESC pressed → cancel speech")
                stop_speaking()

        kb_listener = keyboard.Listener(on_press=_kb_on_press)
        kb_listener.daemon = True
        kb_listener.start()
        # ========================================================================

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
        cmd_trigger = None
        ww = None

        try:
            if mode == "hotkey":
                trigger = HotkeyEngine(HOTKEY, _on_hotkey)
                trigger.start()
                log_debug(f"[Ultron] Registered hotkey {HOTKEY} (press to talk).")

                # Register separate command hotkey if configured and different
                try:
                    if HOTKEY_MINIMIZE and HOTKEY_MINIMIZE != HOTKEY:
                        def _on_minimize_hotkey():
                            try:
                                if MAIN_WINDOW and hasattr(MAIN_WINDOW, 'input_router') and MAIN_WINDOW.input_router:
                                    MAIN_WINDOW.input_router.submit_text("minimize window", echo=True)
                                    return
                            except Exception:
                                pass
                            # Fallback for headless: directly handle command
                            try:
                                handle_command("minimize window")
                            except Exception:
                                pass

                        cmd_trigger = HotkeyEngine(HOTKEY_MINIMIZE, _on_minimize_hotkey)
                        cmd_trigger.start()
                        log_debug(f"[Ultron] Registered command hotkey {HOTKEY_MINIMIZE} (minimize).")
                except Exception as _e:
                    print("Failed to register command hotkey:", _e)

                while True:
                    time.sleep(0.5)

            elif mode == "both":
                trigger = HotkeyEngine(HOTKEY, _on_hotkey)
                try:
                    trigger.start()
                except Exception:
                    trigger = None

                # Register separate command hotkey if configured and different
                try:
                    if HOTKEY_MINIMIZE and HOTKEY_MINIMIZE != HOTKEY:
                        def _on_minimize_hotkey():
                            try:
                                if MAIN_WINDOW and hasattr(MAIN_WINDOW, 'input_router') and MAIN_WINDOW.input_router:
                                    MAIN_WINDOW.input_router.submit_text("minimize window", echo=True)
                                    return
                            except Exception:
                                pass
                            try:
                                handle_command("minimize window")
                            except Exception:
                                pass

                        cmd_trigger = HotkeyEngine(HOTKEY_MINIMIZE, _on_minimize_hotkey)
                        cmd_trigger.start()
                        log_debug(f"[Ultron] Registered command hotkey {HOTKEY_MINIMIZE} (minimize).")
                except Exception as _e:
                    print("Failed to register command hotkey:", _e)

                ww = WakeWordEngine(on_wake=on_wake)
                try:
                    ww.start()
                except Exception as e:
                    print(f"[Ultron][WakeWord] Failed to start wakeword engine: {e}")
                    ww = None

                log_debug(f"[Ultron] Running both hotkey and wakeword triggers. Press {HOTKEY} or speak the wake word.")
                while True:
                    time.sleep(0.5)

            else:
                # Default wakeword path (openwakeword or porcupine based on WAKE_ENGINE)
                # Register command hotkey even in default wakeword mode
                try:
                    if HOTKEY_MINIMIZE and HOTKEY_MINIMIZE != HOTKEY:
                        def _on_minimize_hotkey():
                            try:
                                if MAIN_WINDOW and hasattr(MAIN_WINDOW, 'input_router') and MAIN_WINDOW.input_router:
                                    MAIN_WINDOW.input_router.submit_text("minimize window", echo=True)
                                    return
                            except Exception:
                                pass
                            try:
                                handle_command("minimize window")
                            except Exception:
                                pass

                        cmd_trigger = HotkeyEngine(HOTKEY_MINIMIZE, _on_minimize_hotkey)
                        cmd_trigger.start()
                        log_debug(f"[Ultron] Registered command hotkey {HOTKEY_MINIMIZE} (minimize).")
                except Exception as _e:
                    print("Failed to register command hotkey:", _e)

                ww = WakeWordEngine(on_wake=on_wake)
                ww.start()
                log_debug("[Ultron] Wakeword listener started.")
                while True:
                    time.sleep(0.5)

        except KeyboardInterrupt:
            log_debug("\n[Ultron] Shutting down...")
        finally:
            # Stop trigger if started
            try:
                if trigger:
                    trigger.stop()
            except Exception:
                pass
                try:
                    if trigger:
                        trigger.stop()
                except Exception:
                    pass
                try:
                    if cmd_trigger:
                        cmd_trigger.stop()
                except Exception:
                    pass
                try:
                    if ww:
                        ww.stop()
                except Exception:
                    pass
            try:
                tts.shutdown(timeout=3.0)
            except Exception:
                pass
            log_event({"type": "shutdown"})

    print("[Ultron][UI DEBUG] Starting background services thread")
    # start background thread
    try:
        t = threading.Thread(target=_run_triggers, daemon=True)
        t.start()
    except Exception as e:
        print("Failed to start background triggers thread:", e)

    # Hand control to Qt event loop (if available)
    try:
        # If we created a QApplication above, enter its loop; otherwise run legacy blocking path
        if 'app' in locals():
            print("[Ultron][UI DEBUG] Entering Qt event loop (app.exec())")
            try:
                rc = app.exec()
                print("[Ultron][UI DEBUG] Qt event loop exited, rc=", rc)
                sys.exit(rc)
            except Exception as _e:
                print("[Ultron][UI DEBUG] app.exec() raised:", _e)
                traceback.print_exc()
    except Exception:
        traceback.print_exc()

    # Legacy fallback: if no UI, run the previous blocking loop behavior
    trigger = None
    ww = None
    try:
        if mode == "hotkey":
            trigger = HotkeyEngine(HOTKEY, lambda: on_wake())
            trigger.start()
            log_debug(f"[Ultron] Registered hotkey {HOTKEY} (press to talk).")

            while True:
                time.sleep(0.5)

        elif mode == "both":
            trigger = HotkeyEngine(HOTKEY, lambda: on_wake())
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

            log_debug(f"[Ultron] Running both hotkey and wakeword triggers. Press {HOTKEY} or speak the wake word.")
            while True:
                time.sleep(0.5)

        else:
            ww = WakeWordEngine(on_wake=on_wake)
            ww.start()
            log_debug("[Ultron] Wakeword listener started.")
            while True:
                time.sleep(0.5)

    except KeyboardInterrupt:
        log_debug("\n[Ultron] Shutting down...")
    finally:
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

        try:
            kb_listener.stop()
        except Exception:
            pass

        try:
            tts.speak_blocking("Ultron shutting down.", timeout=3.0)
        except Exception:
            pass
        try:
            tts.shutdown(timeout=3.0)
        except Exception:
            pass
        log_event({"type": "shutdown"})

if __name__ == "__main__":
    main()
