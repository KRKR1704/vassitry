"""
Simple smoke test for the PySide6 UI spine.
Run with: python tests/test_ui_smoke.py

If PySide6 is not installed the script exits with code 2.
The test opens the MainWindow briefly and quits automatically.
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
    from ultron.ui.state import UIStateManager
    from ultron.ui.main_window import MainWindow
except Exception as e:
    print("Failed to import ultron UI modules:", e)
    traceback.print_exc()
    sys.exit(3)


def main():
    # New interactive smoke test (Phase 3): inject a command and verify flow
    sm = UIStateManager()
    sm.set_last_action("Smoke test start")

    app = QApplication(sys.argv)
    win = MainWindow(state_manager=sm)
    win.show()

    # Collect mode changes for verification
    modes = []

    def on_mode(m):
        try:
            modes.append(getattr(m, 'value', str(m)).lower())
        except Exception:
            modes.append(str(m))

    sm.mode_changed.connect(on_mode)

    # After 200ms, submit a command programmatically
    def submit_test_command():
        try:
            # emit the command as if the user pressed Enter
            win.chat.command_submitted.emit("test command")
        except Exception:
            pass

    QTimer.singleShot(200, submit_test_command)

    # After 1200ms, validate results and quit
    result = {"ok": False}

    def finalize():
        text = win.chat.history.toPlainText() if win and win.chat and win.chat.history else ""
        user_seen = "USER: test command" in text
        ultron_seen = "ULTRON:" in text
        thinking_seen = any(m == "thinking" for m in modes)
        idle_seen = any(m == "idle" for m in modes)
        result["ok"] = user_seen and ultron_seen and thinking_seen and idle_seen
        if not result["ok"]:
            print("Smoke test assertions failed:\n", {
                "modes": modes,
                "text": text,
                "user_seen": user_seen,
                "ultron_seen": ultron_seen,
            })
        QTimer.singleShot(10, app.quit)

    QTimer.singleShot(1200, finalize)

    try:
        rc = app.exec()
    except Exception:
        traceback.print_exc()
        rc = 1

    ok = result.get("ok", False)
    print("Smoke test finished, ui_ok=", ok, "exit_rc=", rc)
    sys.exit(0 if (rc == 0 and ok) else 1)


if __name__ == "__main__":
    main()
