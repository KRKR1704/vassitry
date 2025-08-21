# ultron/hotkey.py
from __future__ import annotations
from typing import Callable, Optional

try:
    from pynput import keyboard
except Exception:
    keyboard = None  # type: ignore

_TOKEN_ALIASES = {
    "control": "ctrl",
    "ctrl": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "win": "cmd",     # pynput uses 'cmd' for Windows key
    "cmd": "cmd",
}

def _to_pynput_combo(combo: str) -> str:
    """Convert 'ctrl+alt+u' -> '<ctrl>+<alt>+u' for pynput."""
    if not combo:
        return "<ctrl>+<alt>+u"
    parts = [p.strip().lower() for p in combo.replace(" ", "").split("+") if p.strip()]
    out: list[str] = []
    special = {
        "space": "<space>", "enter": "<enter>", "return": "<enter>", "tab": "<tab>",
        "esc": "<esc>", "escape": "<esc>", "backspace": "<backspace>", "delete": "<delete>",
        "insert": "<insert>", "home": "<home>", "end": "<end>",
        "pageup": "<page_up>", "pagedown": "<page_down>",
        "up": "<up>", "down": "<down>", "left": "<left>", "right": "<right>",
    }
    for p in parts:
        if p in _TOKEN_ALIASES:
            out.append(f"<{_TOKEN_ALIASES[p]}>")
        elif p in special:
            out.append(special[p])
        elif len(p) >= 2 and p[0] == "f" and p[1:].isdigit():  # f1..f24
            out.append(f"<{p}>")
        else:
            out.append(p)
    return "+".join(out)

class HotkeyEngine:
    """Global hotkey trigger using pynput."""
    def __init__(self, hotkey_combo: str, on_hotkey: Callable[[], None]) -> None:
        self.combo_raw = hotkey_combo or "ctrl+alt+u"
        self.combo_pynput = _to_pynput_combo(self.combo_raw)
        self._on_hotkey = on_hotkey
        self._listener: Optional["keyboard.GlobalHotKeys"] = None  # type: ignore[name-defined]

    def start(self) -> None:
        if keyboard is None:
            print("[Ultron][Hotkey] pynput not available; install 'pynput' to use hotkey mode.")
            return
        try:
            self._listener = keyboard.GlobalHotKeys({ self.combo_pynput: self._on_hotkey })
            self._listener.start()  # daemon thread
            print(f"[Ultron][Hotkey] Registered: {self.combo_raw}  (pynput: {self.combo_pynput})")
        except Exception as e:
            print(f"[Ultron][Hotkey][ERR] Could not register hotkey '{self.combo_raw}': {e}")

    def stop(self) -> None:
        try:
            if self._listener:
                self._listener.stop()
        except Exception:
            pass
