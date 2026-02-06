from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool


class CommandResult:
    def __init__(self, intent: str, message: str, success: bool = True):
        self.intent = intent
        self.message = message
        self.success = success


class _CommandTask(QRunnable):
    """Worker runnable: parses intent and executes ONE safe command.
    NEVER touches UI directly. Emits controller signals (thread-safe queued signals).
    """
    def __init__(self, text: str, controller: "CommandController"):
        super().__init__()
        self.text = text
        self.controller = controller

    def run(self):
        pythoncom = None
        try:
            try:
                import pythoncom
                pythoncom.CoInitialize()
                pythoncom = pythoncom
            except Exception:
                pythoncom = None

            from ultron.nlp.intent import parse_intent

            result = parse_intent(self.text)

            # only implement a single safe real command for v1
            if result.intent == "window_minimize":
                try:
                    from ultron.skills.system import minimize_active_window
                    ok = minimize_active_window()
                    msg = "Window minimized" if ok else "Failed to minimize window"
                    cr = CommandResult(intent=result.intent, message=msg, success=bool(ok))
                except Exception as e:
                    cr = CommandResult(intent=result.intent, message=f"Error: {e}", success=False)
            else:
                cr = CommandResult(intent=result.intent, message=f"Intent: {result.intent}", success=True)

            # SAFE: emit finished on controller (Qt queues across threads)
            try:
                self.controller.finished.emit(cr)
            except Exception:
                pass

        except Exception as e:
            try:
                self.controller.error.emit(str(e))
            except Exception:
                pass
        finally:
            if pythoncom is not None:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass


class CommandController(QObject):
    """Controller bridging UI commands to intent parsing + safe system actions.

    Emits signals back to the UI thread only.
    """

    started = Signal()
    finished = Signal(object)  # CommandResult
    error = Signal(str)

    def __init__(self, state_manager):
        super().__init__()
        self.state_manager = state_manager
        self.pool = QThreadPool.globalInstance()
        self._busy = False
        # Connect internal signals to reset busy flag on UI thread
        try:
            self.finished.connect(self._on_finished)
            self.error.connect(self._on_error)
            # When started emits, update state manager to EXECUTING
            self.started.connect(self._on_started_signal)
        except Exception as e:
            print("CommandController: signal connection error:", e)

    def _on_started_signal(self):
        try:
            from .state import UltronMode
            # set executing state and a system action label
            self.state_manager.set_mode(UltronMode.EXECUTING)
            self.state_manager.set_last_action("Executing command")
        except Exception as e:
            print("CommandController._on_started_signal error:", e)

    def submit(self, text: str):
        if self._busy:
            try:
                self.error.emit("Busy. Please wait.")
            except Exception:
                pass
            return

        self._busy = True
        # transition to THINKING immediately
        try:
            from .state import UltronMode
            self.state_manager.set_mode(UltronMode.THINKING)
            self.state_manager.set_last_action("Thinking")
        except Exception as e:
            print("CommandController.submit state update error:", e)
        # emit started now (UI->EXECUTING transition will be handled by slot)
        try:
            self.started.emit()
        except Exception:
            pass

        task = _CommandTask(text=text, controller=self)
        self.pool.start(task)

    def is_busy(self) -> bool:
        return bool(self._busy)
    # --- slots executed in UI thread when worker emits queued signals ---
    def _on_finished(self, result: CommandResult):
        self._busy = False
        # re-emit to external listeners (already emitted by worker, but keep consistent hook)
        try:
            # finished already emitted from worker; this slot ensures _busy reset
            pass
        except Exception as e:
            print("CommandController._on_finished error:", e)

    def _on_error(self, err: str):
        self._busy = False
        try:
            pass
        except Exception as e:
            print("CommandController._on_error error:", e)
