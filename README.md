UltronAssistant/
│
├── main.py                  # Entry point
├── requirements.txt         # Project dependencies
├── .env                     # Your API keys & config (excluded in gitignore)
├── .gitignore               # Ignore venv, logs, etc.
│
├── ultron/                  # Core assistant logic
│   ├── __init__.py
│   ├── config.py            # Loads env vars (API keys, prefs)
│   ├── wakeword.py          # Porcupine wake word engine
│   ├── listener.py          # Speech recognition / microphone handling
│   ├── tts.py               # Text-to-speech (pyttsx3)
│   ├── ack.py               # Wake acknowledgements (voice/beep)
│   │
│   ├── nlp/                 # Intent detection
│   │   ├── __init__.py
│   │   └── intent.py        # Keyword / regex intent parser
│   │
│   ├── skills/              # Actions Ultron can do
│   │   ├── __init__.py
│   │   ├── browser.py       # Open websites / browsers
│   │   └── system.py        # (Future: shutdown PC, launch apps, etc.)
│   │
│   └── utils/               # Helpers (optional future expansion)
│       └── __init__.py
│
└── logs/
    └── ultron.log           # Runtime logs (ignored in git)
