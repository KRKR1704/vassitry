"""
Smoke test for CorePanel visualizing all Ultron modes.
Run with: python tests/test_ui_core_smoke.py
"""
import sys
import traceback
from pathlib import Path

# Ensure project root is on sys.path so `ultron` package can be imported
proj_root = str(Path(__file__).resolve().parent.parent)
if proj_root not in sys.path:
    sys.path.insert(0, proj_root)

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
except Exception as e:
    print("PySide6 not installed or failed to import:", e)
    sys.exit(2)

try:
    from ultron.ui.state import UIStateManager, UltronMode
    from ultron.ui.main_window import MainWindow
except Exception as e:
    print("Failed to import ultron UI modules:", e)
    traceback.print_exc()
    sys.exit(3)


def main():
    sm = UIStateManager()
    app = QApplication(sys.argv)
    win = MainWindow(state_manager=sm)
    win.show()

    modes = list(UltronMode)

    # schedule mode changes at 250ms intervals
    for i, m in enumerate(modes):
        def make_setter(mode):
            return lambda: (sm.set_mode(mode), sm.set_last_action(f"Mode: {mode.name}"))
        QTimer.singleShot(250 * (i + 1), make_setter(m))

    # quit after all modes cycled + small buffer
    QTimer.singleShot(250 * (len(modes) + 2), app.quit)

    try:
        rc = app.exec()
    except Exception:
        traceback.print_exc()
        rc = 1

    print("Core smoke finished, exit code", rc)
    sys.exit(0 if rc == 0 else 1)


if __name__ == "__main__":
    main()
