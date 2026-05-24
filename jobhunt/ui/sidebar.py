from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QLabel, QPushButton, QButtonGroup, QSpacerItem, QSizePolicy,
)

from .. import config
from ..__version__ import __version__


def _load_logo_pixmap(size: int = 72) -> QPixmap | None:
    """Decode the embedded Scarlet Raven PNG into a scaled QPixmap.
    Returns None if the embed module is missing (treat as a soft failure)."""
    try:
        from ..assets._logo_data import LOGO_PNG_BYTES
    except Exception:
        return None
    pix = QPixmap()
    if not pix.loadFromData(LOGO_PNG_BYTES, "PNG"):
        return None
    return pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


NAV_ITEMS = [
    ("Dashboard",     "dashboard"),
    ("Pipeline",      "pipeline"),
    ("Resume",        "resume"),
    ("Cover Letter",  "cover_letter"),
    ("Job Search",    "browser"),
    ("Autonomous",    "autonomous"),
    ("Interviews",    "interviews"),
    ("Reports",       "reports"),
    ("Settings",      "settings"),
]


class Sidebar(QFrame):
    nav_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 18, 12, 18)
        layout.setSpacing(8)

        logo = QLabel()
        logo.setFixedSize(72, 72)
        pix = _load_logo_pixmap(72)
        if pix is not None:
            logo.setPixmap(pix)
            logo.setStyleSheet("background: transparent; border: none;")
        else:
            # Embed module missing — graceful fallback so the app still runs.
            logo.setText("LOGO")
            logo.setObjectName("LogoPlaceholder")
        layout.addWidget(logo, alignment=Qt.AlignLeft)

        app_name = QLabel("JobHunt")
        app_name.setStyleSheet(
            f"color: {config.COLOR_TEXT}; font-size: 20px; font-weight: 700; "
            f"padding: 8px 0 0 0;"
        )
        layout.addWidget(app_name)

        tagline = QLabel("A Scarlet Raven app")
        tagline.setStyleSheet(
            f"QLabel {{ color: {config.COLOR_ACCENT}; font-size: 10px; "
            f"font-weight: 600; letter-spacing: 0.6px; "
            f"padding: 0 0 14px 0; background: transparent; }}"
        )
        layout.addWidget(tagline)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for label, key in NAV_ITEMS:
            btn = QPushButton(label)
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, k=key: self.nav_changed.emit(k))
            self._group.addButton(btn)
            self._buttons[key] = btn
            layout.addWidget(btn)

        layout.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))

        version = QLabel(f"v{__version__}")
        version.setStyleSheet(f"color: {config.COLOR_TEXT_FAINT}; font-size: 10px;")
        layout.addWidget(version, alignment=Qt.AlignLeft)

    def select(self, key: str):
        btn = self._buttons.get(key)
        if btn:
            btn.setChecked(True)
