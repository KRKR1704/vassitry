import sys
from pathlib import Path

proj_root = str(Path(__file__).resolve().parent.parent)
if proj_root not in sys.path:
    sys.path.insert(0, proj_root)

try:
    from PySide6.QtWidgets import QApplication
except Exception as e:
    print("PySide6 import failed:", e)
    raise

from ultron.ui.state import UIStateManager
from ultron.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    sm = UIStateManager()
    win = MainWindow(state_manager=sm)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
