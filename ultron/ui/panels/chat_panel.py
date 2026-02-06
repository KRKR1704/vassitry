from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTextBrowser, QLineEdit, QPushButton
from PySide6.QtCore import Qt, Signal
from ..state import UIStateManager


class ChatPanel(QWidget):
    command_submitted = Signal(str)

    def __init__(self, state_manager: UIStateManager):
        super().__init__()
        self.state_manager = state_manager
        self._init_ui()
        # ChatPanel intentionally does NOT subscribe to state changes.
        # Chat messages should be emitted only by the MainWindow/controller.

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # Read-only append-only browser for messages
        self.history = QTextBrowser()
        self.history.setReadOnly(True)
        layout.addWidget(self.history)

        self.input = QLineEdit()
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.on_send)
        # Enter key should submit the command
        try:
            self.input.returnPressed.connect(self.on_send)
        except Exception as e:
            print("ChatPanel: failed to connect returnPressed:", e)

        input_row = QVBoxLayout()
        input_row.addWidget(self.input)
        input_row.addWidget(self.send_btn)

        layout.addLayout(input_row)

        self.setLayout(layout)

    def on_send(self):
        text = self.input.text().strip()
        if not text:
            return
        # Panels are dumb: emit command submission signal and clear input
        try:
            self.command_submitted.emit(text)
        except Exception as e:
            print("ChatPanel command_submitted emit error:", e)
        self.input.clear()

    def append_message(self, who: str, text: str):
        # Enforce message type labels: USER, ULTRON, SYSTEM
        try:
            self.history.append(f"{who}: {text}")
        except Exception as e:
            print("ChatPanel.append_message error:", e)

    # Note: on_last_action removed — MainWindow is the single source of chat messages.
