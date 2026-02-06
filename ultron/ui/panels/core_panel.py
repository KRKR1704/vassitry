from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt
from ..state import UIStateManager, UltronMode


class CorePanel(QWidget):
    def __init__(self, state_manager: UIStateManager):
        super().__init__()
        self.state_manager = state_manager
        self._init_ui()
        # subscribe to mode changes
        try:
            self.state_manager.mode_changed.connect(self.on_mode_changed)
        except Exception as e:
            print("CorePanel: failed to connect mode_changed:", e)

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # Circular indicator
        self.mode_indicator = QLabel()
        self.mode_indicator.setFixedSize(48, 48)
        self.mode_indicator.setAlignment(Qt.AlignCenter)
        # set initial style from MODE_COLORS (declared below)
        idle_label, idle_color = MODE_COLORS.get(UltronMode.IDLE, ("Idle", "#888888"))
        self.mode_indicator.setStyleSheet(f"background-color: {idle_color}; border-radius: 24px;")
        layout.addWidget(self.mode_indicator, alignment=Qt.AlignHCenter)

        self.mode_label = QLabel(idle_label)
        self.mode_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.mode_label)

        layout.addStretch(1)
        self.setLayout(layout)

    def on_mode_changed(self, mode: UltronMode):
        # mode is expected to be an UltronMode enum — use declarative mapping
        try:
            label_text, color = MODE_COLORS.get(mode, (getattr(mode, 'name', str(mode)), '#888888'))
            self.mode_indicator.setStyleSheet(f"background-color: {color}; border-radius: 24px;")
            self.mode_label.setText(label_text)
            self.mode_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        except Exception as e:
            print("CorePanel.on_mode_changed error:", e)


# Declarative mapping of modes → (label, color)
MODE_COLORS = {
    UltronMode.IDLE: ("Idle", "#888888"),
    UltronMode.LISTENING: ("Listening", "#0a84ff"),
    UltronMode.THINKING: ("Thinking", "#ffb020"),
    UltronMode.EXECUTING: ("Executing", "#28a745"),
    UltronMode.SPEAKING: ("Speaking", "#7b61ff"),
    UltronMode.ERROR: ("Error", "#ff3b30"),
    UltronMode.FOCUS: ("Focus", "#444444"),
}
