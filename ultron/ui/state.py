from enum import Enum
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, Signal


class UltronMode(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    EXECUTING = "executing"
    SPEAKING = "speaking"
    ERROR = "error"
    FOCUS = "focus"


@dataclass
class UIState:
    mode: UltronMode = UltronMode.IDLE
    mic_active: bool = False
    tts_active: bool = False
    last_action: str = ""


class UIStateManager(QObject):
    """State manager for the UI.

    Emits Qt signals on important changes so UI widgets can connect directly.
    This object must not import any UI widget classes.
    """

    mode_changed = Signal(object)  # UltronMode
    last_action_changed = Signal(str)
    mic_active_changed = Signal(bool)
    tts_active_changed = Signal(bool)

    def __init__(self, initial: Optional[UIState] = None):
        super().__init__()
        self._state = initial or UIState()

    @property
    def state(self) -> UIState:
        return self._state

    def set_mode(self, mode: UltronMode):
        if self._state.mode != mode:
            self._state.mode = mode
            try:
                self.mode_changed.emit(mode)
            except Exception as e:
                print("UIStateManager.mode_changed emit error:", e)

    def set_mic_active(self, active: bool):
        if self._state.mic_active != active:
            self._state.mic_active = active
            try:
                self.mic_active_changed.emit(bool(active))
            except Exception as e:
                print("UIStateManager.mic_active_changed emit error:", e)

    def set_tts_active(self, active: bool):
        if self._state.tts_active != active:
            self._state.tts_active = active
            try:
                self.tts_active_changed.emit(bool(active))
            except Exception as e:
                print("UIStateManager.tts_active_changed emit error:", e)

    def set_last_action(self, action: str):
        if self._state.last_action != action:
            self._state.last_action = action
            try:
                self.last_action_changed.emit(action or "")
            except Exception as e:
                print("UIStateManager.last_action_changed emit error:", e)
