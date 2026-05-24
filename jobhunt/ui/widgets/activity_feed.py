from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QScrollArea, QWidget

from ... import config
from .effects import apply_card_shadow


class ActivityFeed(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 22)
        outer.setSpacing(12)

        title = QLabel("Recent activity")
        title.setObjectName("SectionTitle")
        outer.addWidget(title)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 4, 0, 0)
        self.body_layout.setSpacing(8)
        self.body_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background-color: transparent;")
        scroll.setWidget(self.body)
        outer.addWidget(scroll, 1)

        self._empty_label: QLabel | None = None
        self._show_empty()

        apply_card_shadow(self)

    def _clear(self):
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._empty_label = None

    def _show_empty(self):
        self._clear()
        self._empty_label = QLabel("No activity yet.")
        self._empty_label.setStyleSheet(f"color: {config.COLOR_TEXT_FAINT}; padding: 18px 0;")
        self.body_layout.addWidget(self._empty_label)
        self.body_layout.addStretch(1)

    def set_entries(self, entries: list[dict]):
        if not entries:
            self._show_empty()
            return
        self._clear()
        for e in entries:
            row = QLabel(f"<span style='color:{config.COLOR_TEXT_DIM}'>{e['timestamp']}</span>"
                         f"  &nbsp;  <span style='color:{config.COLOR_TEXT}'>{e['text']}</span>")
            row.setTextFormat(Qt.RichText)
            row.setStyleSheet("padding: 4px 0;")
            self.body_layout.addWidget(row)
        self.body_layout.addStretch(1)
