from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QWidget

from .effects import apply_card_shadow


class StatCard(QFrame):
    def __init__(self, label: str, value: str = "0", accent: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumHeight(118)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(6)

        self.label = QLabel(label)
        self.label.setObjectName("StatLabel")
        self.value = QLabel(value)
        self.value.setObjectName("StatValueAccent" if accent else "StatValue")

        layout.addWidget(self.label)
        layout.addStretch(1)
        layout.addWidget(self.value)

        apply_card_shadow(self)

    def set_value(self, value: str):
        self.value.setText(value)


class StatsStrip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.this_week = StatCard("Applications this week")
        self.response_rate = StatCard("Response rate", "0%", accent=True)
        self.active = StatCard("Active in pipeline")
        self.next_interview = StatCard("Next interview", "None scheduled")

        for card in (self.this_week, self.response_rate, self.active, self.next_interview):
            layout.addWidget(card, 1)
