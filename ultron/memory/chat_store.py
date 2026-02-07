import json
from pathlib import Path

# History stored under repository-local data/ directory
HISTORY_FILE = Path("data/chat_history.json")
MAX_MESSAGES = 100


class ChatStore:
    def __init__(self):
        self.messages = []
        self.load()

    def load(self):
        if HISTORY_FILE.exists():
            try:
                self.messages = json.loads(HISTORY_FILE.read_text())
            except Exception:
                self.messages = []

    def save(self):
        HISTORY_FILE.parent.mkdir(exist_ok=True)
        HISTORY_FILE.write_text(json.dumps(self.messages[-MAX_MESSAGES:], indent=2))

    def add(self, role: str, text: str):
        self.messages.append({"role": role, "text": text})
        self.messages = self.messages[-MAX_MESSAGES:]
        try:
            self.save()
        except Exception:
            pass
