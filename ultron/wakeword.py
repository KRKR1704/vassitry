import os
import queue
import threading
import time
from typing import Callable

from ultron.config import WAKE_ENGINE, WAKEWORD, PORCUPINE_ACCESS_KEY

class WakeWordEngine:
    def __init__(self, on_wake: Callable[[], None]):
        self.on_wake = on_wake
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if WAKE_ENGINE == "porcupine":
            self._start_porcupine()
        else:
            self._start_openwakeword()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    # ---------- openWakeWord ----------
    def _start_openwakeword(self):
        import sounddevice as sd
        from openwakeword.model import Model
        import numpy as np

        def runner():
            model = Model(wakeword_models=[WAKEWORD])  # built-in name or path to model
            q = queue.Queue()

            def audio_cb(indata, frames, time_info, status):
                if status:
                    pass
                q.put(indata.copy())

            while not self._stop.is_set():
                with sd.InputStream(channels=1, samplerate=16000, dtype="float32", callback=audio_cb):
                    detected = False
                    while not self._stop.is_set():
                        try:
                            audio = q.get(timeout=0.1)
                        except queue.Empty:
                            continue
                        probs = model.predict(audio.squeeze())
                        if any(p > 0.8 for p in probs.values()):
                            detected = True
                            break

                if self._stop.is_set():
                    break

                if detected:
                    time.sleep(0.50)  # give OS time to fully release device
                    try:
                        self.on_wake()
                    except Exception:
                        pass
                    # loop continues to re-open stream and resume listening

        self._thread = threading.Thread(target=runner, daemon=True)
        self._thread.start()

    # ---------- Porcupine ----------
    def _start_porcupine(self):
        import pvporcupine
        import pyaudio
        import numpy as np

        if not PORCUPINE_ACCESS_KEY:
            raise RuntimeError("Porcupine selected but PORCUPINE_ACCESS_KEY is empty in .env")

        builtin_keywords = {
            "grapefruit", "computer", "blueberry", "hey google", "porcupine", "ok google",
            "terminator", "grasshopper", "picovoice", "pico clock", "hey barista", "americano",
            "hey siri", "bumblebee", "jarvis", "alexa"
        }

        kw = WAKEWORD.strip()
        is_custom_model = os.path.isfile(kw) and kw.lower().endswith(".ppn")

        if is_custom_model:
            porcupine = pvporcupine.create(access_key=PORCUPINE_ACCESS_KEY, keyword_paths=[kw])
        else:
            if kw not in builtin_keywords:
                raise ValueError(
                    f'"{kw}" is not a built-in Porcupine keyword and no .ppn file found.\n'
                    f'Choose one of: {", ".join(sorted(builtin_keywords))}\n'
                    f'Or set WAKEWORD to a .ppn file path for your custom keyword.'
                )
            porcupine = pvporcupine.create(access_key=PORCUPINE_ACCESS_KEY, keywords=[kw])

        pa = pyaudio.PyAudio()

        def open_stream():
            # None => system default input device
            return pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=porcupine.sample_rate,
                input=True,
                input_device_index=None,
                frames_per_buffer=porcupine.frame_length,
            )

        def runner():
            stream = open_stream()
            try:
                while not self._stop.is_set():
                    pcm_bytes = stream.read(porcupine.frame_length, exception_on_overflow=False)
                    pcm = np.frombuffer(pcm_bytes, dtype=np.int16)  # 512 samples
                    result = porcupine.process(pcm)
                    if result >= 0:
                        try:
                            stream.stop_stream()
                            stream.close()
                        except Exception:
                            pass

                        time.sleep(0.50)  # let Windows release the device

                        try:
                            self.on_wake()
                        except Exception:
                            pass

                        if self._stop.is_set():
                            break
                        stream = open_stream()
            finally:
                try:
                    if stream and stream.is_active():
                        stream.stop_stream()
                    if stream:
                        stream.close()
                except Exception:
                    pass
                try:
                    pa.terminate()
                except Exception:
                    pass
                try:
                    porcupine.delete()
                except Exception:
                    pass

        self._thread = threading.Thread(target=runner, daemon=True)
        self._thread.start()
