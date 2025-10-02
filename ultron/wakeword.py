import os
import queue
import threading
import time
from typing import Callable

from ultron.config import WAKE_ENGINE, WAKEWORD, PORCUPINE_ACCESS_KEY

# Try to import an optional MIC_INDEX if your config defines it
try:
    from ultron.config import MIC_INDEX  # -1 or None => system default
except Exception:
    MIC_INDEX = None


class WakeWordEngine:
    def __init__(self, on_wake: Callable[[], None]):
        self.on_wake = on_wake
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        """Pick backend based on WAKE_ENGINE and/or WAKEWORD extension."""
        mode = (WAKE_ENGINE or "").strip().lower()
        kw = (WAKEWORD or "").strip()
        ext = os.path.splitext(kw)[1].lower()

        # Explicit selection
        if mode == "porcupine":
            self._start_porcupine()
            return
        if mode == "openwakeword":
            # If user accidentally pointed to a .ppn, route to porcupine
            if ext == ".ppn":
                print("[Ultron][WakeWord] WAKE_ENGINE=openwakeword but WAKEWORD is .ppn → using Porcupine.")
                self._start_porcupine()
            else:
                self._start_openwakeword()
            return

        # Auto / both / anything else: choose by extension
        if ext == ".ppn":
            print("[Ultron][WakeWord] Auto-select → Porcupine (.ppn detected).")
            self._start_porcupine()
        else:
            print("[Ultron][WakeWord] Auto-select → OpenWakeWord.")
            self._start_openwakeword()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    # ---------- OpenWakeWord ----------
    def _start_openwakeword(self):
        import sounddevice as sd
        from openwakeword.model import Model
        import numpy as np

        def runner():
            kw = (WAKEWORD or "").strip()
            # If no model given, you can use a bundled/built-in OWW name (example: "hey_jarvis")
            wake_models = [kw] if kw and not kw.lower().endswith(".ppn") else ["hey_jarvis"]

            print(f"[Ultron][WakeWord] OpenWakeWord starting (model={wake_models[0]!r})")
            model = Model(wakeword_models=wake_models)
            q = queue.Queue()

            def audio_cb(indata, frames, time_info, status):
                if status:
                    # You could log status if you like
                    pass
                q.put(indata.copy())

            # Use system default if MIC_INDEX is None or negative
            device = MIC_INDEX if (isinstance(MIC_INDEX, int) and MIC_INDEX >= 0) else None

            while not self._stop.is_set():
                # Float32 stream is fine for OWW; 16k recommended
                with sd.InputStream(channels=1, samplerate=16000, dtype="float32",
                                    callback=audio_cb, device=device):
                    detected = False
                    while not self._stop.is_set():
                        try:
                            audio = q.get(timeout=0.1)
                        except queue.Empty:
                            continue
                        # audio is shape (N,1) float32 [-1..1]; squeeze for model
                        probs = model.predict(audio.squeeze())
                        # Trigger threshold (tweak if too sensitive)
                        if any(p >= 0.5 for p in probs.values()):
                            detected = True
                            break

                if self._stop.is_set():
                    break

                if detected:
                    time.sleep(0.50)  # give OS time to release device
                    try:
                        self.on_wake()
                    except Exception:
                        pass
                    # loop to reopen stream & continue listening

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

        kw = (WAKEWORD or "").strip()
        is_custom_model = os.path.isfile(kw) and kw.lower().endswith(".ppn")

        if is_custom_model:
            porcupine = pvporcupine.create(
                access_key=PORCUPINE_ACCESS_KEY,
                keyword_paths=[kw],
                sensitivities=[0.6],
            )
            shown = os.path.basename(kw)
        else:
            if kw.lower() not in builtin_keywords:
                raise ValueError(
                    f'"{kw}" is not a built-in Porcupine keyword and no .ppn file found.\n'
                    f'Choose one of: {", ".join(sorted(builtin_keywords))}\n'
                    f'Or set WAKEWORD to a .ppn file path for your custom keyword.'
                )
            porcupine = pvporcupine.create(
                access_key=PORCUPINE_ACCESS_KEY,
                keywords=[kw.lower()],
                sensitivities=[0.6],
            )
            shown = kw.lower()

        pa = pyaudio.PyAudio()

        def open_stream():
            # None => system default input device (use MIC_INDEX if valid)
            dev = MIC_INDEX if (isinstance(MIC_INDEX, int) and MIC_INDEX >= 0) else None
            return pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=porcupine.sample_rate,
                input=True,
                input_device_index=dev,
                frames_per_buffer=porcupine.frame_length,
            )

        def runner():
            print(f"[Ultron][WakeWord] Porcupine listening ({shown})")
            stream = open_stream()
            try:
                while not self._stop.is_set():
                    pcm_bytes = stream.read(porcupine.frame_length, exception_on_overflow=False)
                    pcm = np.frombuffer(pcm_bytes, dtype=np.int16)
                    result = porcupine.process(pcm)
                    if result >= 0:
                        # Detected
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
