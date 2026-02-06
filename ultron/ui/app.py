import sys
from PySide6.QtWidgets import QApplication
from .main_window import MainWindow
from .state import UIStateManager


def run_ui(state_manager: UIStateManager | None = None):
    app = QApplication(sys.argv)
    sm = state_manager or UIStateManager()
    win = MainWindow(state_manager=sm)
    win.show()
    return app.exec()


if __name__ == "__main__":
    run_ui()
