from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import Qt, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor
from ..state import UIStateManager, UltronMode


class CircleIndicator(QWidget):
    def __init__(self, size=72, parent=None):
        super().__init__(parent)
        self._scale = 1.0
        self._rotation = 0.0
        self._ring_phase = 0.0
        self._glow = 0.0
        self._opacity = 1.0
        self._color = QColor("#888888")
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setOpacity(self._opacity)

        r = self.rect()
        cx, cy = r.width() / 2, r.height() / 2

        # 1) glow halo (expanded, soft)
        if self._glow and self._glow > 0.001:
            painter.save()
            painter.setOpacity(self._glow)
            glow_color = self._color.lighter(140)
            painter.setBrush(glow_color)
            painter.setPen(Qt.NoPen)
            expand = int(min(r.width(), r.height()) * 0.18)
            painter.drawEllipse(r.adjusted(-expand, -expand, expand, expand))
            painter.restore()

        # 2) rotating outer ring (uses ring_phase)
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self._ring_phase)
        painter.translate(-cx, -cy)
        painter.setPen(Qt.NoPen)
        ring_color = self._color.darker(110)
        painter.setBrush(ring_color)
        ring_inset = int(min(r.width(), r.height()) * 0.06)
        ring_rect = r.adjusted(ring_inset, ring_inset, -ring_inset, -ring_inset)
        painter.drawEllipse(ring_rect)
        painter.restore()

        # 3) inner core (scale pulse)
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self._rotation)
        painter.scale(self._scale, self._scale)
        painter.translate(-cx, -cy)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        core_inset = int(min(r.width(), r.height()) * 0.18)
        core_rect = r.adjusted(core_inset, core_inset, -core_inset, -core_inset)
        painter.drawEllipse(core_rect)
        painter.restore()

    # ---- properties ----
    def getScale(self):
        return self._scale

    def setScale(self, v):
        self._scale = v
        self.update()

    scale = Property(float, getScale, setScale)

    def getRotation(self):
        return self._rotation

    def setRotation(self, v):
        self._rotation = v
        self.update()

    rotation = Property(float, getRotation, setRotation)

    def getOpacity(self):
        return self._opacity

    def setOpacity(self, v):
        self._opacity = v
        self.update()

    def getRingPhase(self):
        return self._ring_phase

    def setRingPhase(self, v):
        self._ring_phase = float(v)
        self.update()

    ring_phase = Property(float, getRingPhase, setRingPhase)

    def getGlow(self):
        return self._glow

    def setGlow(self, v):
        self._glow = float(v)
        self.update()

    glow = Property(float, getGlow, setGlow)

    opacity = Property(float, getOpacity, setOpacity)

    def setColor(self, hexcolor: str):
        self._color = QColor(hexcolor)
        self.update()


class CorePanel(QWidget):
    def __init__(self, state_manager: UIStateManager):
        super().__init__()
        self.state_manager = state_manager

        self.anims: list = []  # keep persistent refs to animations
        self.indicator = CircleIndicator()

        layout = QVBoxLayout(self)
        layout.addStretch()
        layout.addWidget(self.indicator, alignment=Qt.AlignHCenter)
        layout.addStretch()

        try:
            self.state_manager.mode_changed.connect(self.on_mode_changed)
        except Exception:
            pass

        # ensure initial state
        try:
            self.on_mode_changed(UltronMode.IDLE)
        except Exception:
            pass

    # ---------------- core helpers ----------------

    def _reset_visuals(self):
        self.indicator.scale = 1.0
        self.indicator.rotation = 0.0
        self.indicator.opacity = 1.0
        self.indicator.ring_phase = 0.0
        self.indicator.glow = 0.0

    def _stop_anim(self):
        # stop and clear all persistent animations to avoid GC
        try:
            for a in list(self.anims):
                try:
                    a.stop()
                except Exception:
                    pass
            self.anims.clear()
        except Exception:
            self.anims = []

    # ---------------- animations ----------------

    def animate_idle(self):
        self.indicator.setColor("#888888")
        self._pulse(self.indicator, 1.0, 1.03, 2800)

    def animate_listening(self):
        self.indicator.setColor("#0a84ff")
        # scale pulse
        self._pulse(self.indicator, 1.0, 1.12, 700)
        # rotating ring
        self._loop(self.indicator, b"ring_phase", 0, 360, 1400)
        # glow breathe
        self._loop(self.indicator, b"glow", 0.12, 0.36, 900)

    def animate_thinking(self):
        self.indicator.setColor("#ffb020")
        # thinking = continuous outer ring rotation
        self._loop(self.indicator, b"ring_phase", 0, 360, 1200)

    def animate_speaking(self):
        self.indicator.setColor("#7b61ff")
        self._pulse(self.indicator, 1.0, 1.08, 420)
        # subtle glow while speaking
        self._loop(self.indicator, b"glow", 0.06, 0.18, 420)

    def animate_error(self):
        self.indicator.setColor("#ff3b30")
        # flash glow quickly a few times
        a = QPropertyAnimation(self.indicator, b"glow")
        a.setStartValue(0.0)
        a.setEndValue(0.8)
        a.setDuration(180)
        a.setLoopCount(3)
        a.start()
        self.anims.append(a)

    # ---------------- small animation helpers ----------------

    def _loop(self, target, prop, a, b, dur, easing=None, loop=-1):
        try:
            anim = QPropertyAnimation(target, prop)
            anim.setStartValue(a)
            anim.setEndValue(b)
            anim.setDuration(dur)
            if easing:
                anim.setEasingCurve(easing)
            anim.setLoopCount(loop)
            anim.start()
            self.anims.append(anim)
        except Exception:
            pass

    def _pulse(self, target, a, b, dur):
        try:
            anim = QPropertyAnimation(target, b"scale")
            anim.setStartValue(a)
            anim.setEndValue(b)
            anim.setEasingCurve(QEasingCurve.InOutSine)
            anim.setDuration(dur)
            anim.setLoopCount(-1)
            anim.start()
            self.anims.append(anim)
        except Exception:
            pass

    # ---------------- state hook ----------------

    def on_mode_changed(self, mode: UltronMode):
        # diagnostic
        try:
            print("[CorePanel] mode:", mode)
        except Exception:
            pass

        # stop and reset visuals to a clean baseline, then start one animation
        try:
            self._stop_anim()
            self._reset_visuals()

            if mode == UltronMode.IDLE:
                self.animate_idle()
            elif mode == UltronMode.LISTENING:
                self.animate_listening()
            elif mode == UltronMode.THINKING:
                self.animate_thinking()
            elif mode == UltronMode.SPEAKING:
                self.animate_speaking()
            elif mode == UltronMode.ERROR:
                self.animate_error()
            else:
                self.animate_idle()
        except Exception:
            pass


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
