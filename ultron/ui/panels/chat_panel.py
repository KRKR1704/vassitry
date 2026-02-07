from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QWidget as QW,
    QHBoxLayout,
    QSizePolicy,
    QFrame,
)
from PySide6.QtCore import Qt, Signal, QTimer, QPoint
from PySide6.QtCore import QEasingCurve
from PySide6.QtCore import Property
from PySide6.QtCore import QPropertyAnimation
from ..state import UIStateManager
from ..chat_bubble import ChatBubble
from .action_feed import ActionFeed
import sys
import platform
try:
    import winsound
except Exception:
    winsound = None


class ChatPanel(QWidget):
    command_submitted = Signal(str)

    def __init__(self, state_manager: UIStateManager):
        super().__init__()
        self.state_manager = state_manager
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # Action feed: compact system/action cards (newest at top)
        self.action_feed = ActionFeed()
        layout.addWidget(self.action_feed)

        # Conversation spine: QScrollArea -> QWidget -> QVBoxLayout
        self.chat_container = QW()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setSpacing(12)
        self.chat_layout.setContentsMargins(12, 12, 12, 12)
        self.chat_layout.setAlignment(Qt.AlignTop)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.chat_container)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Make the scroll area take the remaining vertical space
        layout.addWidget(self.scroll_area, 1)

        # Input row (anchored to bottom)
        self.input = QLineEdit()
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.on_send)
        try:
            self.input.returnPressed.connect(self.on_send)
        except Exception as e:
            print("ChatPanel: failed to connect returnPressed:", e)

        input_row = QHBoxLayout()
        # Input should expand horizontally and remain fixed vertically
        self.input.setMinimumHeight(40)
        self.input.setMaximumHeight(48)
        self.input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.send_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        input_row.addWidget(self.input)
        input_row.addWidget(self.send_btn)

        # Wrap input_row in a frame to guarantee fixed bottom placement
        input_frame = QFrame()
        input_frame.setLayout(input_row)
        input_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        input_frame.setFrameShape(QFrame.NoFrame)

        layout.addWidget(input_frame, 0)

        self.setLayout(layout)

    def on_send(self):
        text = self.input.text().strip()
        if not text:
            return
        try:
            self.command_submitted.emit(text)
        except Exception as e:
            print("ChatPanel command_submitted emit error:", e)
        self.input.clear()

    def append_message(self, who: str, text: str):
        """
        Maintain old signature for callers. Map `who` to left/right styling.
        Do NOT prepend who labels in the UI; identity is via alignment/color.
        """
        is_user = True if who == "USER" or who == "user" else False
        try:
            # Create the bubble widget here and add via layout.addWidget only.
            bubble = ChatBubble(text, is_user=is_user)

            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            if is_user:
                row.addStretch()
                row.addWidget(bubble)
            else:
                row.addWidget(bubble)
                row.addStretch()

            # Add widget to the layout (append at bottom)
            self.chat_layout.addWidget(container)

            # Auto-scroll if user was near bottom
            sb = self.scroll_area.verticalScrollBar()
            if sb.value() >= (sb.maximum() - 40):
                sb.setValue(sb.maximum())
        except Exception as e:
            print("ChatPanel.append_message error:", e)

    def add_bubble(self, text: str, is_user: bool = False):
        """Add a ChatBubble widget into the chat layout.

        This is the canonical bubble insertion API that MainWindow must call.
        """
        try:
            # Delegate to append_message which handles widget creation and layout
            who = "USER" if is_user else "ULTRON"
            self.append_message(who, text)
        except Exception as e:
            print("ChatPanel.add_bubble error:", e)

    # Typing indicator management
    def show_typing_indicator(self):
        try:
            if getattr(self, '_typing_widget', None):
                return
            w = QWidget()
            layout = QHBoxLayout(w)
            label = QPushButton('Ultron is typing')
            label.setEnabled(False)
            layout.addWidget(label)
            layout.addStretch()
            layout.setContentsMargins(6, 6, 6, 6)
            self._typing_widget = w
            self.chat_layout.insertWidget(self.chat_layout.count() - 1, w)
            # simple animated dots using timer
            self._typing_dots = 0
            self._typing_timer = QTimer(self)
            def _tick():
                self._typing_dots = (self._typing_dots + 1) % 4
                label.setText('Ultron is typing' + '.' * self._typing_dots)
            self._typing_timer.timeout.connect(_tick)
            self._typing_timer.start(400)
        except Exception as e:
            print('show_typing_indicator error:', e)

    def hide_typing_indicator(self):
        try:
            if getattr(self, '_typing_timer', None):
                try:
                    self._typing_timer.stop()
                except Exception:
                    pass
                self._typing_timer = None
            if getattr(self, '_typing_widget', None):
                try:
                    self._typing_widget.setParent(None)
                except Exception:
                    pass
                self._typing_widget = None
        except Exception as e:
            print('hide_typing_indicator error:', e)

    def _animate_message(self, widget, from_left: bool):
        # Animations removed to avoid popup/positioning behavior.
        return

