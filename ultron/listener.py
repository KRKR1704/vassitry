# ultron/listener.py
import speech_recognition as sr

class Listener:
    def __init__(
        self,
        energy_threshold: int = 300,
        dynamic_energy: bool = True,
        calibrate_on_start: bool = True,
        calibration_duration: float = 0.25,
        pause_threshold: float = 0.8,         # wait a bit longer before cutting off
        non_speaking_duration: float = 0.30,  # ignore short gaps
        phrase_time_limit: int = 15           # allow longer utterances
    ):
        self.r = sr.Recognizer()
        self.r.energy_threshold = energy_threshold
        self.r.dynamic_energy_threshold = dynamic_energy
        self.r.pause_threshold = pause_threshold
        self.r.non_speaking_duration = non_speaking_duration
        self.phrase_time_limit = phrase_time_limit

        # Use system default mic (None); set an index if you prefer a specific device
        self.default_mic_index = None

        if calibrate_on_start:
            try:
                with sr.Microphone(device_index=self.default_mic_index) as source:
                    print(f"[Ultron][Listener] Using system default microphone.")
                    # brief ambient calibration (fast)
                    self.r.adjust_for_ambient_noise(source, duration=calibration_duration)
                    print(f"[Ultron][Listener] Calibrated energy threshold -> {self.r.energy_threshold}")
            except Exception as e:
                print(f"[Ultron][Listener] Calibration failed: {e}")

    def listen_once(self, timeout: float = 10, phrase_time_limit: int | None = None) -> str | None:
        """
        Listen once without recalibrating.
        - timeout: max seconds to wait for you to START speaking
        - phrase_time_limit: max seconds to capture AFTER you start speaking
        """
        pt = phrase_time_limit if phrase_time_limit is not None else self.phrase_time_limit
        try:
            with sr.Microphone(device_index=self.default_mic_index) as source:
                print("[Ultron][Listener] Listening for command...")
                audio = self.r.listen(source, timeout=timeout, phrase_time_limit=pt)
        except Exception as e:
            print(f"[Ultron][Listener] Listen error: {e}")
            return None

        try:
            text = self.r.recognize_google(audio, show_all=False)
            print(f"[Ultron][Listener] STT text: {text}")
            return text
        except Exception as e:
            print(f"[Ultron][Listener] STT error: {e}")
            return None
