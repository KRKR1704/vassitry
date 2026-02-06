from PySide6.QtCore import QObject, Signal
import time


class InputRouter(QObject):
    submitted = Signal(str)
    system = Signal(str)
    """
    Routes all user inputs (chat, hotkeys, voice) into the CommandController.
    Responsibilities:
    - Normalize text
    - Prevent double-submits when controller is busy
    - Basic deduplication of repeated immediate inputs
    - Emit `submitted` for UI echo and `system` for system messages
    """

    def __init__(self, controller, command_executor=None):
        super().__init__()
        self.controller = controller
        # command_executor should be a callable like handle_command(text)
        self.command_executor = command_executor
        self._last_text = None
        self._last_ts = 0.0

    def submit_text(self, text: str, echo: bool = False):
        if not text:
            return
        t = text.strip()
        if not t:
            return

        # UI logging for incoming text (helps debug routing)
        try:
            print("[UI] input received:", t)
        except Exception:
            pass

        try:
            # Busy guard: do not forward when controller is busy
            try:
                if self.controller and hasattr(self.controller, 'is_busy') and self.controller.is_busy():
                    try:
                        self.system.emit("Error: Busy. Please wait.")
                    except Exception:
                        pass
                    return
            except Exception:
                # If controller introspection fails, allow submit to attempt
                pass

            # Deduplicate identical repeated submissions within short window
            now = time.time()
            if t == self._last_text and (now - self._last_ts) < 0.8:
                return

            # Echo must happen before submitting
            if echo:
                try:
                    self.submitted.emit(t)
                except Exception:
                    pass

            # Forward to executor if provided (central runtime). Otherwise fall back to controller.
            if self.command_executor:
                try:
                    self.command_executor(t)
                except Exception as e:
                    print("InputRouter: command_executor raised:", e)
            else:
                if self.controller:
                    self.controller.submit(t)

            # record last submission
            self._last_text = t
            self._last_ts = now

        except Exception as e:
            # Keep router simple: don't crash the caller
            print("InputRouter.submit_text error:", e)
