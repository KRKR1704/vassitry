from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout
from PySide6.QtCore import Qt, QTimer
from .state import UIStateManager, UltronMode
from .panels.left_panel import LeftPanel
from .panels.core_panel import CorePanel
from .panels.chat_panel import ChatPanel
from .controller import CommandController
from .input_router import InputRouter


class MainWindow(QMainWindow):
    def __init__(self, state_manager: UIStateManager, command_executor=None):
        super().__init__()
        self.state_manager = state_manager
        self.setWindowTitle("Ultron")
        # controller bridges UI → intent → system
        try:
            self.controller = CommandController(self.state_manager)
            # when worker starts executing, controller.started will update state via its own handler
        except Exception as e:
            print("MainWindow: failed to create CommandController:", e)
            self.controller = None

        # Router centralizes all input entry points (chat, hotkey, voice)
        try:
            self.input_router = InputRouter(self.controller, command_executor=command_executor)
        except Exception as e:
            print("MainWindow: failed to create InputRouter:", e)
            self.input_router = None

        self._init_ui()

    def _init_ui(self):
        root = QWidget()
        self.setCentralWidget(root)

        layout = QHBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.left = LeftPanel(self.state_manager)
        self.core = CorePanel(self.state_manager)
        self.chat = ChatPanel(self.state_manager)

        # Wire chat commands: route ALL submissions through InputRouter.
        try:
            if self.controller and self.input_router:
                # ChatPanel -> InputRouter (router will emit `submitted` for UI echo)
                try:
                    self.chat.command_submitted.connect(lambda txt: self.input_router.submit_text(txt, echo=True))
                except Exception:
                    pass

                # When router emits submitted, append USER message in UI
                try:
                    self.input_router.submitted.connect(self.on_command)
                except Exception:
                    pass

                # system messages from router (e.g., busy) → show SYSTEM
                try:
                    self.input_router.system.connect(lambda msg: self.chat.append_message("SYSTEM", msg))
                except Exception:
                    pass

                # controller signals → UI handlers
                self.controller.started.connect(self.on_command_started)
                self.controller.finished.connect(self.on_command_finished)
                self.controller.error.connect(self.on_command_error)
            else:
                # Fallback: keep previous behavior (append only)
                try:
                    self.chat.command_submitted.connect(self._on_command_submitted)
                except Exception:
                    pass
        except Exception as e:
            print("MainWindow: failed to wire command controller:", e)

        # NOTE: Hotkey bindings are handled centrally in main.py to avoid
        # duplicate triggers and conflicting behaviors (wake vs command hotkeys).

        # Layout: 20% | 20% | 60% — approximate via stretch factors
        layout.addWidget(self.left, 1)
        layout.addWidget(self.core, 1)
        layout.addWidget(self.chat, 3)

        root.setLayout(layout)

        # Minimal sizing hints
        self.setMinimumSize(800, 480)
        self.resize(1100, 640)

    def on_command(self, text: str):
        try:
            # Only append USER message. InputRouter is the single submit path.
            self.chat.append_message("USER", text)
        except Exception as e:
            print("MainWindow.on_command error:", e)

    def _on_command_submitted(self, text: str):
        # Fallback handler when InputRouter is not available: append and do nothing else
        try:
            self.chat.append_message("USER", text)
        except Exception:
            pass

    def on_command_started(self):
        try:
            # controller._on_started_signal will also set state; append system message
            self.chat.append_message("SYSTEM", "Executing command")
        except Exception as e:
            print("MainWindow.on_command_started error:", e)

    def on_command_finished(self, result):
        try:
            # result is CommandResult
            self.chat.append_message("SYSTEM", result.message)
            self.state_manager.set_mode(UltronMode.IDLE)
        except Exception as e:
            print("MainWindow.on_command_finished error:", e)

    def on_command_error(self, err: str):
        try:
            self.chat.append_message("SYSTEM", f"Error: {err}")
            self.state_manager.set_mode(UltronMode.ERROR)
            # briefly show error then return to idle
            QTimer.singleShot(300, lambda: self.state_manager.set_mode(UltronMode.IDLE))
        except Exception as e:
            print("MainWindow.on_command_error error:", e)

    def on_voice_recognized(self, text: str):
        """Called when voice/STT produces final text.

        Phase-6 rule: voice must behave identically to chat/hotkey.
        Route into InputRouter with echo so the UI shows the USER message
        and the `CommandController` handles execution.
        """
        try:
            if not text:
                return
            # Prefer the router (keeps single pipeline). Request echo so UI shows USER once.
            if hasattr(self, 'input_router') and self.input_router:
                try:
                    self.input_router.submit_text(text, echo=True)
                    return
                except Exception:
                    pass
            # Fallback: emit chat signal (echo + route will happen via existing wiring)
            try:
                self.chat.command_submitted.emit(text)
            except Exception:
                pass
        except Exception as e:
            print("MainWindow.on_voice_recognized error:", e)
