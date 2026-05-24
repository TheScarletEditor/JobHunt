"""Small visual helpers — soft shadows on cards, etc."""
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget


def apply_card_shadow(widget: QWidget, blur: int = 26, opacity: int = 110, offset_y: int = 4):
    """Apply a soft drop shadow to a card-style widget for gentle depth without borders."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setColor(QColor(0, 0, 0, opacity))
    effect.setOffset(0, offset_y)
    widget.setGraphicsEffect(effect)
