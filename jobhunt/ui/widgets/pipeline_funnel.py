from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPen, QBrush
from PySide6.QtWidgets import QWidget, QSizePolicy

from ... import config


class PipelineFunnel(QWidget):
    """Horizontal-bar funnel showing application counts per pipeline stage."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stages: list[dict] = []
        self.setMinimumHeight(260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)

    def set_data(self, stages: list[dict]):
        """stages: list of {name, count, color}."""
        self._stages = stages
        self.update()

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(600, 280)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(16, 16, -16, -16)

        if not self._stages:
            p.setPen(QColor(config.COLOR_TEXT_FAINT))
            p.setFont(QFont("Segoe UI", 11))
            p.drawText(rect, Qt.AlignCenter, "No applications yet.\nClick 'Add application' to get started.")
            p.end()
            return

        max_count = max((s["count"] for s in self._stages), default=0)
        if max_count == 0:
            max_count = 1

        row_count = len(self._stages)
        row_gap = 8
        row_height = max(28, (rect.height() - row_gap * (row_count - 1)) // row_count)

        label_width = 110
        count_width = 50
        bar_x = rect.left() + label_width + 8
        bar_max_width = rect.width() - label_width - count_width - 16

        font_label = QFont("Segoe UI", 10, QFont.DemiBold)
        font_count = QFont("Segoe UI", 11, QFont.Bold)
        fm_label = QFontMetrics(font_label)

        y = rect.top()
        for stage in self._stages:
            name = stage["name"]
            count = stage["count"]
            color = QColor(stage.get("color") or config.COLOR_ACCENT)

            p.setFont(font_label)
            p.setPen(QColor(config.COLOR_TEXT))
            label_rect = QRectF(rect.left(), y, label_width, row_height)
            elided = fm_label.elidedText(name, Qt.ElideRight, label_width)
            p.drawText(label_rect, Qt.AlignVCenter | Qt.AlignLeft, elided)

            track_rect = QRectF(bar_x, y + row_height / 2 - 9, bar_max_width, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(config.COLOR_BG))
            p.drawRoundedRect(track_rect, 4, 4)

            bar_width = (count / max_count) * bar_max_width if count else 0
            if bar_width > 0:
                bar_rect = QRectF(bar_x, y + row_height / 2 - 9, bar_width, 18)
                p.setBrush(QBrush(color))
                p.drawRoundedRect(bar_rect, 4, 4)

            p.setFont(font_count)
            p.setPen(QColor(config.COLOR_TEXT))
            count_rect = QRectF(bar_x + bar_max_width + 4, y, count_width, row_height)
            p.drawText(count_rect, Qt.AlignVCenter | Qt.AlignRight, str(count))

            y += row_height + row_gap

        p.end()
