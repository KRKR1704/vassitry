import platform
import subprocess
import threading
import queue
import time
import os
from typing import Optional

# comtypes is required on Windows for COM initialization in threads
try:
    import comtypes
    from comtypes import CoInitialize, CoUninitialize
except Exception:
    comtypes = None
    CoInitialize = None
    CoUninitialize = None
try:
    import pyttsx3
except Exception:
    pyttsx3 = None
import os
from typing import Optional

from ultron.config import (
    TTS_BACKEND, TTS_VOICE_NAME, TTS_RATE, TTS_VOLUME, TTS_STARTUP_TEST
)

class _Utterance:
    def __init__(self, text: str):
        self.text = text
        self.done = threading.Event()
        # instrumentation fields
        try:
            self.id = int(time.time() * 1000)
        except Exception:
            self.id = 0
        self.enqueued_ts = None
        self.started_ts = None

# ---------- PowerShell backend ----------
class _PowerShellTTS:
    """
    Windows .NET System.Speech fallback. Uses a worker thread and a PowerShell
    process per utterance, which we can terminate from stop().
    """
    def __init__(self):
        if platform.system() != "Windows":
            raise RuntimeError("PowerShell TTS is only available on Windows.")

        self._q: queue.Queue[_Utterance] = queue.Queue()
        self._stop = threading.Event()
        self._cancel = threading.Event()
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.RLock()

        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

        print("[Ultron][TTS] Backend: PowerShell/.NET Speech")
        if TTS_STARTUP_TEST:
            self.speak("Text to speech is ready.")

    def _escape_ps_single_quotes(self, s: str) -> str:
        return s.replace("'", "''")

    def _build_ps_command(self, text: str) -> str:
        rate = max(-10, min(10, int(round(TTS_RATE / 3))))
        volume = max(0, min(100, int(round(TTS_VOLUME * 100))))
        voice_select = ""
        if TTS_VOICE_NAME:
            v = self._escape_ps_single_quotes(TTS_VOICE_NAME)
            voice_select = f"$s.SelectVoice('{v}'); "
        phrase = self._escape_ps_single_quotes(text)
        cmd = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"{voice_select}$s.Rate = {rate}; $s.Volume = {volume}; "
            f"$s.Speak('{phrase}');"
        )
        return cmd

    def _clear_queue(self):
        try:
            while True:
                self._q.get_nowait()
                self._q.task_done()
        except queue.Empty:
            pass

    def _run(self):
        while not self._stop.is_set():
            try:
                utt = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                cmd = self._build_ps_command(utt.text)
                # Notify any on-start listener just before starting subprocess
                try:
                    if hasattr(self, '_on_start') and callable(self._on_start):
                        try:
                            self._on_start()
                        except Exception:
                            pass
                except Exception:
                    pass
                with self._lock:
                    self._cancel.clear()
                    self._proc = subprocess.Popen(
                        ["powershell", "-NoProfile", "-Command", cmd],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                # Poll so stop() can interrupt promptly
                while self._proc and self._proc.poll() is None:
                    if self._cancel.is_set() or self._stop.is_set():
                        try:
                            self._proc.terminate()
                        except Exception:
                            try:
                                self._proc.kill()
                            except Exception:
                                pass
                        break
                    time.sleep(0.05)
            except Exception as e:
                print(f"[Ultron][TTS][PS] Error speaking: {e}")
            finally:
                with self._lock:
                    self._proc = None
                utt.done.set()
                self._q.task_done()

    def speak(self, text: str):
        if text:
            utt = _Utterance(text)
            try:
                utt.enqueued_ts = time.time()
                print(f"[TTS-INSTR][PS] enqueue id={utt.id} ts={utt.enqueued_ts:.3f} text='{text[:30]}'")
            except Exception:
                pass
            self._q.put(utt)

    def set_on_start(self, cb):
        """Optional: set a callback invoked when speech actually begins."""
        self._on_start = cb

    def speak_blocking(self, text: str, timeout: float | None = None):
        if not text:
            return
        utt = _Utterance(text)
        self._q.put(utt)
        utt.done.wait(timeout=timeout)

    def stop(self):
        """Immediately stop current speech and clear pending items."""
        with self._lock:
            self._cancel.set()
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.terminate()
                except Exception:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                finally:
                    self._proc = None
        self._clear_queue()

    def flush(self, timeout: float | None = None):
        start = time.time()
        while not self._q.empty():
            if timeout is not None and (time.time() - start) > timeout:
                break
            time.sleep(0.05)

    def shutdown(self, timeout: float = 2.0):
        self.stop()
        self._stop.set()
        if self._worker.is_alive():
            self._worker.join(timeout=timeout)

# ---------- pyttsx3 backend ----------
class _Pyttsx3TTS:
    def __init__(self):
        self._q: queue.Queue[_Utterance] = queue.Queue()
        self._stop = threading.Event()

        # Control messages handled on the worker thread
        self._cancel_req = threading.Event()
        self._engine = None
        self._on_start = None

        # how long to wait to collect more sentences into one runAndWait batch
        self._batch_window_sec = 0.06

        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

        print("[Ultron][TTS] Backend: pyttsx3 (COM + engine pinned to worker thread)")
        if TTS_STARTUP_TEST:
            self.speak("Text to speech is ready.")

    def set_on_start(self, cb):
        self._on_start = cb

    def speak(self, text: str):
        if not text:
            return
        utt = _Utterance(text)
        try:
            utt.enqueued_ts = time.time()
            print(f"[TTS-INSTR][PY] enqueue id={utt.id} ts={utt.enqueued_ts:.3f} text='{text[:30]}'")
        except Exception:
            pass
        self._q.put(utt)

    def speak_blocking(self, text: str, timeout: float | None = None):
        if not text:
            return
        utt = _Utterance(text)
        self._q.put(utt)
        utt.done.wait(timeout=timeout)

    def stop(self):
        """
        Request stop ASAP. Do not touch engine here (wrong thread).
        Worker will observe this and call engine.stop() safely.
        """
        self._cancel_req.set()
        # Clear pending queue items so nothing "ghost speaks"
        try:
            while True:
                u = self._q.get_nowait()
                u.done.set()
                self._q.task_done()
        except queue.Empty:
            pass

    def flush(self, timeout: float | None = None):
        start = time.time()
        while not self._q.empty():
            if timeout is not None and (time.time() - start) > timeout:
                break
            time.sleep(0.02)

    def shutdown(self, timeout: float = 2.0):
        # Request stop and exit
        self.stop()
        self._stop.set()
        if self._worker.is_alive():
            self._worker.join(timeout=timeout)

    def _init_engine_on_worker(self):
        # COM must be initialized on this worker thread
        co_init = False
        if platform.system() == "Windows" and CoInitialize:
            try:
                CoInitialize()
                co_init = True
            except Exception:
                co_init = False

        if pyttsx3 is None:
            raise RuntimeError("pyttsx3 not available")

        driver = "sapi5" if platform.system() == "Windows" else None
        try:
            eng = pyttsx3.init(driverName=driver)
        except Exception:
            eng = pyttsx3.init()

        # Configure voice/rate/volume on worker thread
        try:
            voices = eng.getProperty("voices") or []
            if TTS_VOICE_NAME:
                chosen = None
                want = TTS_VOICE_NAME.lower()
                for v in voices:
                    nm = (getattr(v, "name", "") or "").lower()
                    vid = (getattr(v, "id", "") or "").lower()
                    if want in nm or want in vid:
                        chosen = v
                        break
                if chosen:
                    try:
                        eng.setProperty("voice", chosen.id)
                    except Exception:
                        pass
            try:
                base_rate = int(eng.getProperty("rate"))
                eng.setProperty("rate", max(80, base_rate + int(TTS_RATE)))
            except Exception:
                pass
            try:
                eng.setProperty("volume", max(0.0, min(1.0, float(TTS_VOLUME))))
            except Exception:
                pass
        except Exception:
            pass

        return eng, co_init

    def _run(self):
        # Initialize engine once, here, on the worker thread
        co_init = False
        try:
            self._engine, co_init = self._init_engine_on_worker()
        except Exception as e:
            print(f"[Ultron][TTS] pyttsx3 init failed: {e}")
            self._engine = None

        try:
            while not self._stop.is_set():
                # Wait for first utterance
                try:
                    first = self._q.get(timeout=0.1)
                except queue.Empty:
                    # Still honor cancel requests even if idle
                    if self._cancel_req.is_set() and self._engine:
                        try:
                            self._engine.stop()
                        except Exception:
                            pass
                        self._cancel_req.clear()
                    continue

                if not self._engine:
                    # No engine: just mark done and continue
                    first.done.set()
                    self._q.task_done()
                    continue

                # If cancel was requested, stop engine and skip this batch
                if self._cancel_req.is_set():
                    try:
                        self._engine.stop()
                    except Exception:
                        pass
                    self._cancel_req.clear()
                    first.done.set()
                    self._q.task_done()
                    continue

                # Batch: collect more utterances for a short window
                batch = [first]
                t0 = time.time()
                while (time.time() - t0) < self._batch_window_sec:
                    try:
                        nxt = self._q.get_nowait()
                        batch.append(nxt)
                    except queue.Empty:
                        time.sleep(0.005)

                # Notify "audio is about to start" once per batch
                try:
                    if callable(self._on_start):
                        self._on_start()
                except Exception:
                    pass

                # Queue all text, then run once (reduces gaps)
                try:
                    for utt in batch:
                        try:
                            utt.started_ts = time.time()
                            print(f"[TTS-INSTR][PY] start id={utt.id} ts={utt.started_ts:.3f} text='{(utt.text or '')[:30]}'")
                        except Exception:
                            pass
                        self._engine.say(utt.text)
                    self._engine.runAndWait()
                except Exception as e:
                    print(f"[Ultron][TTS] speak batch error: {e}")
                    try:
                        self._engine.stop()
                    except Exception:
                        pass
                finally:
                    for utt in batch:
                        utt.done.set()
                        self._q.task_done()

                # If cancel was requested mid-speech, stop now
                if self._cancel_req.is_set():
                    try:
                        self._engine.stop()
                    except Exception:
                        pass
                    self._cancel_req.clear()

        finally:
            # Cleanup must happen on this worker thread
            try:
                if self._engine:
                    try:
                        self._engine.stop()
                    except Exception:
                        pass
                    try:
                        self._engine = None
                    except Exception:
                        pass
            finally:
                if platform.system() == "Windows" and CoUninitialize and co_init:
                    try:
                        CoUninitialize()
                    except Exception:
                        pass

# ---------- Unified facade ----------
class TTS:
    """
    Unified TTS facade with two backends:
    - pyttsx3 (sapi5)
    - powershell (.NET System.Speech)
    Select via TTS_BACKEND in .env: auto | pyttsx3 | powershell
    """
    def __init__(self):
        backend = TTS_BACKEND
        if backend not in ("auto", "pyttsx3", "powershell"):
            backend = "auto"

        self._impl = None
        if backend == "powershell":
            self._impl = _PowerShellTTS()
        elif backend == "pyttsx3":
            self._impl = _Pyttsx3TTS()
        else:
            # auto: try pyttsx3 first, fallback to PowerShell
            try:
                self._impl = _Pyttsx3TTS()
            except Exception as e:
                print(f"[Ultron][TTS] pyttsx3 backend failed in auto: {e}")
                self._impl = _PowerShellTTS()

    # public API delegates
    def speak(self, text: str):
        self._impl.speak(text)

    def set_on_start(self, cb):
        """Set a callback invoked when the underlying TTS actually begins speaking."""
        try:
            if hasattr(self._impl, 'set_on_start'):
                self._impl.set_on_start(cb)
        except Exception:
            pass

    def speak_blocking(self, text: str, timeout: float | None = None):
        self._impl.speak_blocking(text, timeout=timeout)

    def stop(self):
        """Immediate cancel of current speech and clears queue."""
        if hasattr(self._impl, "stop"):
            self._impl.stop()

    def flush(self, timeout: float | None = None):
        self._impl.flush(timeout=timeout)

    def shutdown(self, timeout: float = 2.0):
        self._impl.shutdown(timeout=timeout)
