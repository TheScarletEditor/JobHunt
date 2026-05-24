from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ... import config


class ReportsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        title = QLabel("Reports")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        placeholder = QLabel(
            "On-screen dashboards plus PDF / Excel / CSV export.\n"
            "Custom report builder — coming in Phase 6."
        )
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 14px;")
        layout.addStretch(1)
        layout.addWidget(placeholder)
        layout.addStretch(1)
