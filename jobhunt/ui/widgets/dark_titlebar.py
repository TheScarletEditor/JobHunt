"""Apply the Windows DWM dark title bar to a top-level widget."""
from __future__ import annotations

import ctypes

from PySide6.QtWidgets import QWidget


def apply_dark_title_bar(widget: QWidget):
    if not widget.isWindow():
        return
    try:
        hwnd = int(widget.winId())
        value = ctypes.c_int(1)
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
        )
        if result != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:
        pass
