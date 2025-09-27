# ultron/config.py
import os
from dotenv import load_dotenv

load_dotenv()

# Core config
PORCUPINE_ACCESS_KEY = os.getenv("PORCUPINE_ACCESS_KEY", "")
WAKE_ENGINE = os.getenv("WAKE_ENGINE", "openwakeword").lower()   # "hotkey" | "openwakeword" | "porcupine"
WAKEWORD = os.getenv("WAKEWORD", "ultron").strip()
BROWSER = os.getenv("BROWSER", "default").lower()

# Global hotkey (used when WAKE_ENGINE == "hotkey")
# Examples: "ctrl+alt+u", "win+shift+space", "ctrl+shift+enter"
HOTKEY = os.getenv("ULTRON_HOTKEY", "ctrl+alt+u")

# Microphone: None = system default
MIC_INDEX = None

# Wake acknowledgement
WAKE_ACK = os.getenv("WAKE_ACK", "voice").lower()           # voice | beep | both | off
WAKE_ACK_TEXT = os.getenv("WAKE_ACK_TEXT", "Yes?").strip()
BEEP_FREQ = int(os.getenv("BEEP_FREQ", "800"))
BEEP_MS = int(os.getenv("BEEP_MS", "150"))

# Narration
SPEAK_MODE = os.getenv("SPEAK_MODE", "actions").lower()     # minimal | actions | debug
STARTUP_TEXT = os.getenv("STARTUP_TEXT", "Ultron is standing by.").strip()
SHUTDOWN_TEXT = os.getenv("SHUTDOWN_TEXT", "Ultron shutting down.").strip()
HEARD_PREFIX = os.getenv("HEARD_PREFIX", "You said").strip()

# TTS settings
TTS_BACKEND = os.getenv("TTS_BACKEND", "auto").lower()      # auto | pyttsx3 | powershell
TTS_VOICE_NAME = os.getenv("TTS_VOICE_NAME", "").strip()
TTS_RATE = int(os.getenv("TTS_RATE", "0"))                  # pyttsx3: relative delta; powershell: -10..10 mapped
TTS_VOLUME = float(os.getenv("TTS_VOLUME", "1.0"))
TTS_STARTUP_TEST = os.getenv("TTS_STARTUP_TEST", "0").strip() in ("1", "true", "yes")

# Wait after wake-ack voice
ACK_BLOCKING_SECS = float(os.getenv("ACK_BLOCKING_SECS", "1.2"))

# Logging
LOGS_PATH = os.path.join("logs", "events.jsonl")
os.makedirs("logs", exist_ok=True)
