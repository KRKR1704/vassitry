from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout
from PySide6.QtCore import Qt, QTimer, Signal
from .state import UIStateManager, UltronMode
from .panels.left_panel import LeftPanel
from .panels.core_panel import CorePanel
from .panels.chat_panel import ChatPanel
from .controller import CommandController
from .input_router import InputRouter
from ..memory.chat_store import ChatStore


class MainWindow(QMainWindow):
    add_ultron_message = Signal(str)

    def __init__(self, *args, **kwargs):
        # Extract known kwargs so they are NOT passed to QMainWindow.__init__
        state_manager = kwargs.pop('state_manager', None)
        command_executor = kwargs.pop('command_executor', None)

        super().__init__(*args, **kwargs)

        # Store for later wiring
        self.state_manager = state_manager
        self.command_executor = command_executor

        # Persistence: chat history store (UI renders only; does not own storage)
        try:
            self.chat_store = ChatStore()
        except Exception:
            self.chat_store = None

        # Build UI after state_manager is set so panels receive it
        # NOTE: defer actual UI construction until after controller/input_router
        # are created to avoid attribute access errors in _init_ui.

        print("[UI DEBUG] MainWindow init id:", id(self))
        try:
            self.add_ultron_message.connect(self._on_ultron_message)
        except Exception as _e:
            print("MainWindow: failed to connect add_ultron_message signal:", _e)

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

        # Restore persisted history (UI renders but does not own storage)
        try:
            if getattr(self, 'chat_store', None) and self.chat_store.messages:
                for msg in self.chat_store.messages:
                    role = 'USER' if msg.get('role') == 'user' else 'ULTRON'
                    try:
                        self.chat.append_message(role, msg.get('text', ''))
                    except Exception:
                        pass
        except Exception:
            pass

        # Wire chat commands: route ALL submissions through InputRouter.
        try:
            if self.controller and self.input_router:
                # ChatPanel -> InputRouter (router will emit `submitted` for UI echo)
                try:
                    self.chat.command_submitted.connect(lambda txt: self.input_router.submit_text(txt, echo=True))
                except Exception:
                    pass

                # When router emits submitted, route USER message to add_message
                try:
                    self.input_router.submitted.connect(self.on_command)
                except Exception:
                    pass

                # Execution gate: router emits execute -> MainWindow controls when execution runs
                try:
                    self.input_router.execute.connect(self._execute_command)
                except Exception:
                    pass

                # system messages from router (e.g., busy) → route through MainWindow.add_message
                try:
                    self.input_router.system.connect(lambda msg: self.add_message(msg, is_user=False))
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

        # Layout: Left | Core | Chat — explicit stretch for predictability
        layout.addWidget(self.left)
        layout.addWidget(self.core)
        layout.addWidget(self.chat)

        # Explicit stretch indices: left=1, core=1, chat=4 (chat gets most space)
        try:
            layout.setStretch(0, 1)
            layout.setStretch(1, 1)
            layout.setStretch(2, 4)
        except Exception:
            pass

        root.setLayout(layout)

        # Minimal sizing hints
        self.setMinimumSize(800, 480)
        self.resize(1100, 640)

    # Backwards-compatible builder wrapper expected by new init
    def _build_chat_ui(self):
        # If _init_ui exists, use it; otherwise create UI here.
        try:
            return self._init_ui()
        except Exception:
            # Fallback: recreate minimal UI if _init_ui missing
            try:
                root = QWidget()
                self.setCentralWidget(root)
                layout = QHBoxLayout()
                root.setLayout(layout)
            except Exception:
                pass

    def _on_ultron_message(self, text):
        print("[UI DEBUG] signal received:", text)
        try:
            # Route through ChatPanel.append_message to centralize creation
            try:
                self.chat.append_message("ULTRON", text)
            except Exception:
                self.add_message(text, is_user=False)
        except Exception as e:
            print("MainWindow._on_ultron_message error:", e)

    def on_command(self, text: str):
        try:
            # Route all UI-visible messages through MainWindow.add_message
            self.add_message(text, is_user=True)
        except Exception as e:
            print("MainWindow.on_command error:", e)

    def _on_command_submitted(self, text: str):
        # Fallback handler when InputRouter is not available: append and do nothing else
        try:
            self.add_message(text, is_user=True)
        except Exception:
            pass

    def on_command_started(self):
        try:
            # Show typing indicator when a command begins executing
            try:
                self.chat.show_typing_indicator()
            except Exception:
                pass
            # reflect active processing state in the core panel
            try:
                if getattr(self, 'state_manager', None):
                    self.state_manager.set_mode(UltronMode.THINKING)
            except Exception:
                pass
        except Exception as e:
            print("MainWindow.on_command_started error:", e)

    def on_command_finished(self, result):
        try:
            # result is CommandResult: hide typing and show result message
            try:
                self.chat.hide_typing_indicator()
            except Exception:
                pass
            self.add_message(result.message, is_user=False)
            self.state_manager.set_mode(UltronMode.IDLE)
        except Exception as e:
            print("MainWindow.on_command_finished error:", e)

    def on_command_error(self, err: str):
        try:
            try:
                self.chat.hide_typing_indicator()
            except Exception:
                pass
            self.add_message(f"Error: {err}", is_user=False)
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

    def _execute_command(self, text: str):
        try:
            if not text:
                return
            # Defer execution to allow Qt to paint the USER bubble first.
            if hasattr(self, 'command_executor') and self.command_executor:
                try:
                    QTimer.singleShot(0, lambda t=text: self.command_executor(t))
                    return
                except Exception as _e:
                    print("MainWindow._execute_command: scheduling command_executor failed:", _e)

            # Fallback: schedule controller.submit
            if self.controller:
                try:
                    QTimer.singleShot(0, lambda t=text: self.controller.submit(t))
                except Exception as _e:
                    print("MainWindow._execute_command: scheduling controller.submit failed:", _e)
        except Exception as e:
            print("MainWindow._execute_command error:", e)

    def add_message(self, text: str, is_user: bool = False):
        """Convenience API for main.py to add Ultron messages.

        Keeps compatibility with `ui_say` which calls MAIN_WINDOW.add_message(...)
        """
        try:
            # Persist to chat store (if available)
            role = 'user' if is_user else 'ultron'
            try:
                if getattr(self, 'chat_store', None):
                    self.chat_store.add(role, text)
            except Exception:
                pass

            # Centralize message creation in ChatPanel.append_message
            who = "USER" if is_user else "ULTRON"
            try:
                self.chat.append_message(who, text)
            except Exception:
                # Fallback for older API
                try:
                    self.chat.add_bubble(text=text, is_user=is_user)
                except Exception:
                    pass
        except Exception as e:
            print("MainWindow.add_message error:", e)
