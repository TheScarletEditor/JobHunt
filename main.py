import logging
import sys
import traceback

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox

from jobhunt import config, theme
from jobhunt.__version__ import __app_id__
from jobhunt.db import DB
from jobhunt.ui.main_window import MainWindow
from jobhunt.ui.widgets.label_selection import SelectableLabelFilter


def _set_windows_app_user_model_id():
    """Tell Windows to group our taskbar entries under JobHunt's identity.

    Without this, Windows uses the parent process (python.exe / the
    PyInstaller bootloader) to decide which taskbar icon to display and
    which app group new windows attach to. Setting an AppUserModelID
    explicitly is the documented fix — see
    https://learn.microsoft.com/windows/win32/shell/appids."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(__app_id__)
    except Exception:
        # Best-effort. Wrong icon grouping isn't worth a startup crash.
        pass


def _app_icon() -> QIcon:
    """Decode the embedded raven PNG into a QIcon for the window + taskbar."""
    try:
        from jobhunt.assets._logo_data import LOGO_PNG_BYTES
    except Exception:
        return QIcon()
    pix = QPixmap()
    if not pix.loadFromData(LOGO_PNG_BYTES, "PNG"):
        return QIcon()
    return QIcon(pix)


def _setup_logging():
    """Set up logging that survives the PyInstaller windowed-bundle quirks.

    Three gotchas this code defends against:

    1.  In a PyInstaller `console=False` bundle, sys.stderr is None at
        runtime. logging.StreamHandler(None) creates a handler that
        explodes on every emit; combined with logging's swallow-on-error
        contract, that hides errors silently. Solution: skip the
        StreamHandler entirely when stderr isn't usable.

    2.  logging.basicConfig is a no-op if any handler is already attached
        to the root logger. Some deps (or Python warnings machinery) can
        install a default handler before we run. force=True tears down
        whatever's there and installs *our* handlers cleanly.

    3.  If the FileHandler fails (disk full, permission denied, weird
        unicode path), the app should still launch — just without a log
        file. We wrap in try/except so logging breakage never blocks the
        UI from coming up."""
    handlers = []
    try:
        config.APPDATA_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(config.LOG_PATH, encoding="utf-8"))
    except Exception:
        # No log file — better than no app.
        pass
    # Only add a console handler if there's actually a stream to write to.
    # In PyInstaller windowed (console=False) builds, sys.stderr is None.
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers or [logging.NullHandler()],
        force=True,
    )


def _install_excepthook():
    def handler(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.error("Unhandled exception:\n%s", tb_str)
        try:
            QMessageBox.critical(
                None,
                "JobHunt — unexpected error",
                f"{exc_type.__name__}: {exc_value}\n\n"
                f"Full traceback logged to:\n{config.LOG_PATH}",
            )
        except Exception:
            pass

    sys.excepthook = handler


def main() -> int:
    _setup_logging()
    _install_excepthook()
    _set_windows_app_user_model_id()
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("JobHunt")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 11))
    app.setStyleSheet(theme.stylesheet())
    app.setWindowIcon(_app_icon())

    label_filter = SelectableLabelFilter(app)
    app.installEventFilter(label_filter)

    DB.connect()

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
