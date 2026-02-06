"""
Phase 6A hotkey smoke test: simulate a hotkey action routed through InputRouter.
Run with: python tests/test_ui_hotkey_smoke.py
Exits 0 on success, non-zero otherwise.
"""
import sys
import traceback
from pathlib import Path

proj_root = str(Path(__file__).resolve().parent.parent)
if proj_root not in sys.path:
    sys.path.insert(0, proj_root)

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
except Exception as e:
    print("PySide6 import failed:", e)
    sys.exit(2)

try:
    from ultron.ui.state import UIStateManager
    from ultron.ui.main_window import MainWindow
    from ultron.ui.state import UltronMode
except Exception as e:
    print("Failed to import UI modules:", e)
    traceback.print_exc()
    sys.exit(3)


def main():
    sm = UIStateManager()
    app = QApplication(sys.argv)
    win = MainWindow(state_manager=sm)
    win.show()

    modes = []
    def on_mode(m):
        try:
            modes.append(getattr(m, 'value', str(m)).lower())
        except Exception:
            modes.append(str(m))
    sm.mode_changed.connect(on_mode)

    # simulate hotkey after 200ms: InputRouter should echo+submit when echo=True
    def send_hotkey():
        try:
            if hasattr(win, 'input_router') and win.input_router:
                win.input_router.submit_text("minimize window", echo=True)
            else:
                # fallback: emit chat signal
                win.chat.command_submitted.emit("minimize window")
        except Exception as e:
            print("Failed to invoke hotkey simulation:", e)

    QTimer.singleShot(200, send_hotkey)

    # finalize after 1500ms
    result = {"ok": False}
    def finalize():
        text = win.chat.history.toPlainText() if win and win.chat and win.chat.history else ""
        user_seen = "USER: minimize window" in text
        executing_seen = "SYSTEM: Executing command" in text
        minimized_seen = "Window minimized" in text
        thinking_seen = any(m == "thinking" for m in modes)
        executing_mode_seen = any(m == "executing" for m in modes)
        idle_seen = any(m == "idle" for m in modes)
        result["ok"] = all([user_seen, executing_seen, minimized_seen, thinking_seen, executing_mode_seen, idle_seen])
        if not result["ok"]:
            print("Hotkey smoke failed:\n", {"modes": modes, "text": text})
        QTimer.singleShot(10, app.quit)

    QTimer.singleShot(1500, finalize)

    try:
        rc = app.exec()
    except Exception:
        traceback.print_exc()
        rc = 1

    ok = result.get("ok", False)
    print("Hotkey smoke finished, ok=", ok, "exit_rc=", rc)
    sys.exit(0 if (rc == 0 and ok) else 1)


if __name__ == "__main__":
    main()
