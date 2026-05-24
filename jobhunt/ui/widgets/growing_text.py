from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QSizePolicy

from ... import config


class GrowingTextEdit(QPlainTextEdit):
    """A QPlainTextEdit that grows vertically to fit its content. Wraps at the
    widget width and never shows its own vertical scrollbar — the surrounding
    QScrollArea handles overflow so the text never gets cut off mid-paragraph."""

    def __init__(self, min_lines: int = 4, parent=None):
        super().__init__(parent)
        self._min_lines = min_lines
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setStyleSheet(
            "QPlainTextEdit { background: transparent; border: none; padding: 6px 2px; "
            f"color: {config.COLOR_TEXT}; }}"
        )
        self.document().contentsChanged.connect(self._resize_to_content)
        self.document().documentLayout().documentSizeChanged.connect(
            lambda *_: self._resize_to_content()
        )
        QTimer.singleShot(0, self._resize_to_content)

    def _resize_to_content(self):
        # QPlainTextEdit's document.size().height() is in block units, not
        # pixels, so we walk the blocks and sum their wrapped line counts.
        doc = self.document()
        viewport_w = self.viewport().width()
        if viewport_w > 0:
            doc.setTextWidth(viewport_w)
        line_h = self.fontMetrics().lineSpacing()
        total_lines = 0
        block = doc.firstBlock()
        while block.isValid():
            layout = block.layout()
            total_lines += max(1, layout.lineCount() if layout else 1)
            block = block.next()
        min_h = line_h * self._min_lines + 16
        doc_h = total_lines * line_h + 16
        target = max(min_h, doc_h)
        if self.height() != target:
            self.setFixedHeight(target)
            self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_to_content()
