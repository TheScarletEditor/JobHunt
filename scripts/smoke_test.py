"""Headless smoke test: verifies the app can construct and shut down cleanly."""
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from jobhunt import theme
from jobhunt.db import DB
from jobhunt.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.stylesheet())
    DB.connect()
    window = MainWindow()
    window.show()
    for key in ("dashboard", "pipeline", "resume", "cover_letter", "browser",
                "autonomous", "interviews", "reports", "settings", "dashboard"):
        window._on_nav(key)
    QTimer.singleShot(200, app.quit)
    rc = app.exec()
    print(f"smoke_test: exit code {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
