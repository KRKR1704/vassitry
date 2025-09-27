import json
import time
import os
import re
import platform
import ctypes
import threading
from datetime import datetime

from ultron.config import LOGS_PATH, BROWSER, WAKE_ENGINE, HOTKEY
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
        # Prefer browser app if available; fall back to desktop app.
        if open_browser_app is not None:
            try:
                ok = open_browser_app(app)
            except Exception:
                ok = False
        if not ok and open_app is not None:
            try:
                ok = open_app(app)
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
    log_event({"type": "boot", "trigger": mode or "hotkey"})

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
