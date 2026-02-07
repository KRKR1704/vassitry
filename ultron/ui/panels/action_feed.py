from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QHBoxLayout
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QGraphicsOpacityEffect
from PySide6.QtCore import QPropertyAnimation


class ActionFeed(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(6, 6, 6, 6)
        self.layout.setSpacing(6)
        # newest at top
        self.layout.addStretch()

    def add_action(self, text: str, icon: QIcon | None = None, duration_ms: int = 6000):
        try:
            card = QFrame()
            card.setObjectName('ActionCard')
            row = QHBoxLayout(card)
            row.setContentsMargins(10, 6, 10, 6)
            if icon:
                lbl_icon = QLabel()
                lbl_icon.setPixmap(icon.pixmap(20, 20))
                row.addWidget(lbl_icon)
            label = QLabel(text)
            label.setWordWrap(False)
            row.addWidget(label)
            row.addStretch()

            # insert at top (before the stretch)
            self.layout.insertWidget(0, card)

            # fade out after duration
            def _start_fade():
                try:
                    effect = QGraphicsOpacityEffect(card)
                    card.setGraphicsEffect(effect)
                    anim = QPropertyAnimation(effect, b"opacity", card)
                    anim.setDuration(800)
                    anim.setStartValue(1.0)
                    anim.setEndValue(0.0)
                    anim.start(QPropertyAnimation.DeleteWhenStopped)

                    def _remove():
                        try:
                            card.setParent(None)
                        except Exception:
                            pass

                    # remove after animation finishes
                    QTimer.singleShot(900, _remove)
                except Exception:
                    try:
                        card.setParent(None)
                    except Exception:
                        pass

            QTimer.singleShot(duration_ms, _start_fade)

        except Exception as e:
            print("ActionFeed.add_action error:", e)
