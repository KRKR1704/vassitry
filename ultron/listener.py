import speech_recognition as sr

def _auto_pick_device_index() -> int | None:
    """
    Try system default first; if that fails to open, scan all devices and pick the first input that works.
    """
    # Try default device
    try:
        with sr.Microphone() as _:
            print("[Ultron][Listener] Using system default microphone.")
            return None
    except Exception as e:
        print(f"[Ultron][Listener] Default mic failed to open: {e}")

    # Scan devices
    names = sr.Microphone.list_microphone_names() or []
    print("[Ultron][Listener] Scanning input devices...")
    for idx, name in enumerate(names):
        try:
            with sr.Microphone(device_index=idx) as _:
                print(f"[Ultron][Listener] Selected mic #{idx}: {name}")
                return idx
        except Exception:
            continue

    print("[Ultron][Listener] No working microphone found.")
    return None

class Listener:
    def __init__(self, energy_threshold: int = 300):
        self.r = sr.Recognizer()
        self.r.dynamic_energy_threshold = True
        self.r.energy_threshold = energy_threshold
        self.r.pause_threshold = 0.6
        self.r.phrase_threshold = 0.1
        self.r.non_speaking_duration = 0.2
        self._device_index = _auto_pick_device_index()

    def listen_once(self, timeout=8, phrase_time_limit=10) -> str | None:
        print(f"[Ultron][Listener] Opening mic (device={self._device_index})...")
        with sr.Microphone(device_index=self._device_index) as source:
            try:
                self.r.adjust_for_ambient_noise(source, duration=0.5)
                print(f"[Ultron][Listener] Calibrated energy threshold -> {self.r.energy_threshold}")
            except Exception as e:
                print(f"[Ultron][Listener] ambient noise adjust skipped: {e}")
            print("[Ultron][Listener] Listening for command...")
            try:
                audio = self.r.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            except sr.WaitTimeoutError:
                print("[Ultron][Listener] Timeout waiting for speech.")
                return None

        try:
            text = self.r.recognize_google(audio)
            print(f"[Ultron][Listener] STT text: {text}")
            return text.lower().strip()
        except sr.UnknownValueError:
            print("[Ultron][Listener] STT could not understand audio.")
            return None
        except sr.RequestError as e:
            print(f"[Ultron][Listener] STT request error: {e}")
            return None
        except Exception as e:
            print(f"[Ultron][Listener] STT unexpected error: {e}")
            return None
