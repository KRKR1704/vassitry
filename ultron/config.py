# ultron/config.py
import os

# `python-dotenv` is optional for users who run the project without
# an environment file. Import it if available, otherwise provide a
# no-op `load_dotenv` so the rest of the config can import successfully.
try:
	from dotenv import load_dotenv  # type: ignore
except ModuleNotFoundError:
	# Minimal .env loader fallback so the project can read .env files even
	# when `python-dotenv` isn't installed. This is intentionally small and
	# only supports simple KEY=VALUE lines and comments beginning with '#'.
	def load_dotenv(dotenv_path: str | None = None, override: bool = False):  # pragma: no cover - runtime fallback
		path = dotenv_path or os.path.join(os.getcwd(), '.env')
		try:
			if not os.path.exists(path):
				return False
			with open(path, 'r', encoding='utf-8') as f:
				for raw in f:
					line = raw.strip()
					if not line or line.startswith('#'):
						continue
					if '=' not in line:
						continue
					key, val = line.split('=', 1)
					key = key.strip()
					val = val.strip()
					# Remove optional surrounding quotes
					if len(val) >= 2 and ((val[0] == val[-1]) and val.startswith(('"', "'"))):
						val = val[1:-1]
					# Respect existing environment unless override=True
					if override or os.getenv(key) is None:
						os.environ[key] = val
			return True
		except Exception:
			return False

load_dotenv()

# Ensure .env values explicitly override existing environment when present.
def _override_from_envfile(keys: list[str], dotenv_path: str | None = None):
	path = dotenv_path or os.path.join(os.getcwd(), '.env')
	try:
		if not os.path.exists(path):
			return
		with open(path, 'r', encoding='utf-8') as f:
			for raw in f:
				line = raw.strip()
				if not line or line.startswith('#') or '=' not in line:
					continue
				key, val = line.split('=', 1)
				key = key.strip()
				if key not in keys:
					continue
				val = val.split('#', 1)[0].strip()
				if val is None:
					continue
				os.environ[key] = val
	except Exception:
		# Best-effort only; don't crash if parsing fails
		pass

# Keys we want to respect from .env even if an environment variable exists
_override_from_envfile(["WAKE_ENGINE", "PORCUPINE_ACCESS_KEY", "WAKEWORD", "BROWSER"])

# Core config
def _env_strip(key: str, default: str = "") -> str:
	"""Read an env var and remove inline comments/trailing whitespace."""
	val = os.getenv(key, default)
	if val is None:
		return default
	# Remove inline comments after a '#' and strip whitespace
	return val.split('#', 1)[0].strip()

PORCUPINE_ACCESS_KEY = _env_strip("PORCUPINE_ACCESS_KEY", "")
WAKE_ENGINE = _env_strip("WAKE_ENGINE", "hotkey").lower()   # "hotkey" | "openwakeword" | "porcupine" | "both"
WAKEWORD = _env_strip("WAKEWORD", "ultron")
BROWSER = _env_strip("BROWSER", "default").lower()

# Global hotkey (used when WAKE_ENGINE == "hotkey")
# Examples: "ctrl+alt+u", "win+shift+space", "ctrl+shift+enter"
HOTKEY = os.getenv("ULTRON_HOTKEY", "alt+u")

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

#weather
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Newark, NJ")
UNITS = os.getenv("UNITS", "auto")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")

# Logging
LOGS_PATH = os.path.join("logs", "events.jsonl")
os.makedirs("logs", exist_ok=True)
