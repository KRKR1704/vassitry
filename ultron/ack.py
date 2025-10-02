import platform
from ultron.config import WAKE_ACK, WAKE_ACK_TEXT, BEEP_FREQ, BEEP_MS

def wake_ack(tts, blocking: bool = True):
    """
    Confirmation that Ultron is listening.
    If blocking=True, waits for the voice line to finish before returning.
    """
    mode = (WAKE_ACK or "voice").lower()
    print(f"[Ultron][ACK] mode={mode} text='{WAKE_ACK_TEXT}'")

    did_voice = False
    if mode in ("voice", "both"):
        if blocking:
            print("[Ultron][ACK] speaking (blocking) wake text…")
            tts.speak_blocking(WAKE_ACK_TEXT or "Ultron is listening.", timeout=2.5)
        else:
            print("[Ultron][ACK] speaking (non-blocking) wake text…")
            tts.speak(WAKE_ACK_TEXT or "Ultron is listening.")
        did_voice = True

    if mode in ("beep", "both"):
        try:
            if platform.system() == "Windows":
                import winsound
                winsound.Beep(int(BEEP_FREQ), int(BEEP_MS))
                print("[Ultron][ACK] beeped.")
        except Exception as e:
            print(f"[Ultron][ACK] Beep failed: {e}")

    if not did_voice and mode in ("off", "beep"):
        print("[Ultron][ACK] voice disabled by config (off/beep).")
