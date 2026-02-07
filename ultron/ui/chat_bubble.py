from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout
from PySide6.QtCore import Qt


class ChatBubble(QFrame):
    def __init__(self, text: str, is_user: bool = False):
        super().__init__()

        self.setMaximumWidth(420)
        self.setObjectName("UserBubble" if is_user else "UltronBubble")

        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.setContentsMargins(14, 10, 14, 10)

        # Polished styles: distinct visuals for user vs ultron
        self.setStyleSheet("""
        QFrame#UserBubble {
            background-color: #2563EB;
            color: white;
            border-radius: 14px;
            padding: 10px;
        }
        QFrame#UltronBubble {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2a2a2a, stop:1 #1f1f1f);
            color: white;
            border-radius: 12px;
            padding: 10px;
        }
        """)
