from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt
from ..state import UIStateManager


class LeftPanel(QWidget):
    def __init__(self, state_manager: UIStateManager):
        super().__init__()
        self.state_manager = state_manager
        self._init_ui()
        # subscribe to last_action changes
        try:
            self.state_manager.last_action_changed.connect(self.on_last_action)
        except Exception as e:
            print("LeftPanel: failed to connect last_action_changed:", e)

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        self.time_label = QLabel("00:00")
        self.time_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.time_label)

        self.events_label = QLabel("No upcoming events")
        self.events_label.setWordWrap(True)
        layout.addWidget(self.events_label)

        layout.addStretch(1)
        self.setLayout(layout)

    def on_state(self, state):
        # kept for backward-compat; not used when signals are available
        self.time_label.setText("Mic active" if state.mic_active else "Idle")

    def on_last_action(self, action: str):
        try:
            self.events_label.setText(action or "No recent actions")
        except Exception as e:
            print("LeftPanel.on_last_action error:", e)
