"""App-wide filter that makes every QLabel's text selectable by mouse + keyboard."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QLabel


class SelectableLabelFilter(QObject):
    """Install on QApplication once. Adds selection flags to every QLabel
    at Polish time, preserving any existing interaction flags (e.g. links)."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Polish and isinstance(obj, QLabel):
            flags = obj.textInteractionFlags()
            wanted = flags | Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
            if flags != wanted:
                obj.setTextInteractionFlags(wanted)
        return False
