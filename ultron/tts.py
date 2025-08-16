import platform
import subprocess
import threading
import queue
import time
import pyttsx3

from ultron.config import (
    TTS_BACKEND, TTS_VOICE_NAME, TTS_RATE, TTS_VOLUME, TTS_STARTUP_TEST
)

class _Utterance:
    def __init__(self, text: str):
        self.text = text
        self.done = threading.Event()

# ---------- PowerShell backend ----------
class _PowerShellTTS:
    """
    Windows .NET System.Speech fallback. Very reliable for audible output.
    speak() and speak_blocking() are implemented via a single worker thread.
    """
    def __init__(self):
        if platform.system() != "Windows":
            raise RuntimeError("PowerShell TTS is only available on Windows.")

        self._q: queue.Queue[_Utterance] = queue.Queue()
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

        print("[Ultron][TTS] Backend: PowerShell/.NET Speech")
        if TTS_STARTUP_TEST:
            self.speak("Text to speech is ready.")

    def _escape_ps_single_quotes(self, s: str) -> str:
        # In PowerShell single-quoted strings, escape single quote by doubling it
        return s.replace("'", "''")

    def _build_ps_command(self, text: str) -> str:
        # Build a PowerShell command that uses .NET SpeechSynthesizer
        # Rate: -10..10 ; Volume: 0..100
        rate = max(-10, min(10, int(round(TTS_RATE / 3))))  # map roughly from our delta
        volume = max(0, min(100, int(round(TTS_VOLUME * 100))))
        voice_select = ""
        if TTS_VOICE_NAME:
            # Select voice by name if provided
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

    def _run(self):
        while not self._stop.is_set():
            try:
                utt = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                cmd = self._build_ps_command(utt.text)
                # Use -NoProfile for speed and to avoid user profile scripts
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", cmd],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
                )
            except Exception as e:
                print(f"[Ultron][TTS][PS] Error speaking: {e}")
            finally:
                utt.done.set()
                self._q.task_done()

    def speak(self, text: str):
        if text:
            self._q.put(_Utterance(text))

    def speak_blocking(self, text: str, timeout: float | None = None):
        if not text:
            return
        utt = _Utterance(text)
        self._q.put(utt)
        utt.done.wait(timeout=timeout)

    def flush(self, timeout: float | None = None):
        start = time.time()
        while not self._q.empty():
            if timeout is not None and (time.time() - start) > timeout:
                break
            time.sleep(0.05)

    def shutdown(self, timeout: float = 2.0):
        self.flush(timeout=timeout)
        self._stop.set()
        if self._worker.is_alive():
            self._worker.join(timeout=timeout)

# ---------- pyttsx3 backend ----------
class _Pyttsx3TTS:
    def __init__(self):
        driver = "sapi5" if platform.system() == "Windows" else None
        try:
            self._engine = pyttsx3.init(driverName=driver)
        except Exception as e:
            print(f"[Ultron][TTS] pyttsx3 init failed: {e}")
            self._engine = pyttsx3.init()

        # List voices (diagnostic)
        voices = self._engine.getProperty("voices") or []
        print("[Ultron][TTS] Available voices:")
        for v in voices:
            print(f"  - id='{getattr(v,'id','')}' name='{getattr(v,'name','')}'")

        # Voice selection
        if TTS_VOICE_NAME:
            chosen = None
            for v in voices:
                nm = (getattr(v, "name", "") or "").lower()
                vid = (getattr(v, "id", "") or "").lower()
                if TTS_VOICE_NAME.lower() in nm or TTS_VOICE_NAME.lower() in vid:
                    chosen = v; break
            if chosen:
                try:
                    self._engine.setProperty("voice", chosen.id)
                    print(f"[Ultron][TTS] Using voice: {chosen.name or chosen.id}")
                except Exception as e:
                    print(f"[Ultron][TTS] Failed to set voice '{TTS_VOICE_NAME}': {e}")

        # Rate & volume
        try:
            base_rate = int(self._engine.getProperty("rate"))
            self._engine.setProperty("rate", max(80, base_rate + int(TTS_RATE)))
        except Exception as e:
            print(f"[Ultron][TTS] Rate set failed: {e}")
        try:
            self._engine.setProperty("volume", max(0.0, min(1.0, float(TTS_VOLUME))))
        except Exception as e:
            print(f"[Ultron][TTS] Volume set failed: {e}")

        self._q: queue.Queue[_Utterance] = queue.Queue()
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

        print("[Ultron][TTS] Backend: pyttsx3")
        if TTS_STARTUP_TEST:
            self.speak("Text to speech is ready.")

    def _run(self):
        while not self._stop.is_set():
            try:
                utt = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._engine.say(utt.text)
                self._engine.runAndWait()
            except Exception as e:
                print(f"[Ultron][TTS] Error speaking: {e}")
            finally:
                utt.done.set()
                self._q.task_done()

    def speak(self, text: str):
        if text:
            self._q.put(_Utterance(text))

    def speak_blocking(self, text: str, timeout: float | None = None):
        if not text:
            return
        utt = _Utterance(text)
        self._q.put(utt)
        utt.done.wait(timeout=timeout)

    def flush(self, timeout: float | None = None):
        start = time.time()
        while not self._q.empty():
            if timeout is not None and (time.time() - start) > timeout:
                break
            time.sleep(0.05)

    def shutdown(self, timeout: float = 2.0):
        self.flush(timeout=timeout)
        self._stop.set()
        try:
            self._engine.stop()
        except Exception:
            pass
        if self._worker.is_alive():
            self._worker.join(timeout=timeout)

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
            # auto: try pyttsx3 first
            try:
                self._impl = _Pyttsx3TTS()
            except Exception as e:
                print(f"[Ultron][TTS] pyttsx3 backend failed in auto: {e}")
                self._impl = _PowerShellTTS()

    # public API delegates
    def speak(self, text: str):
        self._impl.speak(text)

    def speak_blocking(self, text: str, timeout: float | None = None):
        self._impl.speak_blocking(text, timeout=timeout)

    def flush(self, timeout: float | None = None):
        self._impl.flush(timeout=timeout)

    def shutdown(self, timeout: float = 2.0):
        self._impl.shutdown(timeout=timeout)
