from . import config as c


def stylesheet() -> str:
    return f"""
    QMainWindow, QWidget#RootWindow {{
        background-color: {c.COLOR_BG};
        color: {c.COLOR_TEXT};
    }}

    QWidget {{
        background-color: {c.COLOR_BG};
        color: {c.COLOR_TEXT};
        font-family: "Segoe UI", "Inter", sans-serif;
        font-size: 14px;
    }}

    QLabel, QRadioButton, QCheckBox, QGroupBox {{
        background-color: transparent;
    }}

    QFrame#Sidebar {{
        background-color: {c.COLOR_BG_SIDEBAR};
        border: none;
    }}

    QFrame#AISidebar {{
        background-color: {c.COLOR_BG_AI_PANEL};
        border: none;
    }}

    QFrame#AISidebarHeader {{
        background-color: {c.COLOR_BG_AI_PANEL};
        border: none;
    }}

    QLabel#LogoPlaceholder {{
        background-color: {c.COLOR_BG_RAISED};
        border: none;
        border-radius: 10px;
        color: {c.COLOR_TEXT_FAINT};
        font-size: 10px;
        qproperty-alignment: AlignCenter;
    }}

    QPushButton#NavButton {{
        background-color: transparent;
        color: {c.COLOR_TEXT_DIM};
        border: none;
        text-align: left;
        padding: 11px 16px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 600;
    }}

    QPushButton#NavButton:hover {{
        background-color: {c.COLOR_BG_HOVER};
        color: {c.COLOR_TEXT};
    }}

    QPushButton#NavButton:checked {{
        background-color: {c.COLOR_ACCENT_SOFT};
        color: {c.COLOR_ACCENT};
        font-weight: 600;
    }}

    QLabel#PageTitle {{
        color: {c.COLOR_TEXT};
        font-size: 28px;
        font-weight: 700;
        padding-bottom: 4px;
    }}

    QLabel#SectionTitle {{
        color: {c.COLOR_SILVER};
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 1.2px;
    }}

    QLabel#SectionDescription {{
        color: {c.COLOR_TEXT_DIM};
        font-size: 13px;
        padding-bottom: 4px;
    }}

    QLabel#FormLabel {{
        color: {c.COLOR_FORM_LABEL};
        font-size: 13px;
        font-weight: 600;
        padding: 8px 4px 0 0;
    }}

    QLabel#GroupHeader {{
        color: {c.COLOR_ACCENT};
        font-size: 14px;
        font-weight: 700;
        padding: 18px 0 6px 0;
    }}

    QLabel#StatLabel {{
        color: {c.COLOR_TEXT_DIM};
        font-size: 12px;
        letter-spacing: 0.5px;
    }}

    QLabel#StatValue {{
        color: {c.COLOR_TEXT};
        font-size: 34px;
        font-weight: 700;
    }}

    QLabel#StatValueAccent {{
        color: {c.COLOR_ACCENT};
        font-size: 34px;
        font-weight: 700;
    }}

    QFrame#Card {{
        background-color: {c.COLOR_BG_RAISED};
        border: none;
        border-radius: 12px;
    }}

    QFrame#SubCard {{
        background-color: {c.COLOR_BG};
        border: none;
        border-radius: 10px;
    }}

    QPushButton {{
        background-color: {c.COLOR_INPUT_BG};
        color: {c.COLOR_TEXT};
        border: none;
        border-radius: 8px;
        padding: 9px 16px;
        font-size: 14px;
        font-weight: 600;
    }}

    QPushButton:hover {{
        background-color: {c.COLOR_INPUT_BG_HOVER};
        color: {c.COLOR_TEXT};
    }}

    QPushButton:pressed {{
        background-color: {c.COLOR_BG};
    }}

    QPushButton:disabled {{
        color: {c.COLOR_TEXT_FAINT};
        background-color: {c.COLOR_BG_RAISED};
    }}

    QPushButton#PrimaryButton {{
        background-color: {c.COLOR_ACCENT};
        color: white;
        border: none;
        font-weight: 600;
    }}

    QPushButton#PrimaryButton:hover {{
        background-color: {c.COLOR_ACCENT_HOVER};
    }}

    QPushButton#PrimaryButton:disabled {{
        background-color: {c.COLOR_ACCENT_DIM};
        color: {c.COLOR_TEXT_DIM};
    }}

    QPushButton#GhostButton {{
        background-color: transparent;
        color: {c.COLOR_TEXT_DIM};
        border: none;
    }}

    QPushButton#GhostButton:hover {{
        background-color: {c.COLOR_BG_HOVER};
        color: {c.COLOR_TEXT};
    }}

    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDateEdit, QDateTimeEdit {{
        background-color: transparent;
        color: {c.COLOR_TEXT};
        border: none;
        border-bottom: 1px solid {c.COLOR_BORDER_LIGHT};
        border-radius: 0;
        padding: 8px 4px 12px 4px;
        min-height: 22px;
        selection-background-color: {c.COLOR_ACCENT};
        selection-color: white;
    }}

    QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QComboBox:hover,
    QSpinBox:hover, QDateEdit:hover, QDateTimeEdit:hover {{
        background-color: transparent;
        border-bottom-color: {c.COLOR_TEXT_FAINT};
    }}

    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
    QSpinBox:focus, QDateEdit:focus, QDateTimeEdit:focus {{
        background-color: transparent;
        border: none;
        border-bottom: 2px solid {c.COLOR_ACCENT};
        padding-bottom: 11px;
    }}

    QLineEdit:read-only {{
        background-color: transparent;
        color: {c.COLOR_TEXT_DIM};
        border-bottom-color: transparent;
    }}

    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}

    QComboBox::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {c.COLOR_SILVER};
        margin-right: 8px;
    }}

    QComboBox QAbstractItemView {{
        background-color: {c.COLOR_BG_RAISED};
        color: {c.COLOR_TEXT};
        border: none;
        border-radius: 8px;
        selection-background-color: {c.COLOR_ACCENT};
        selection-color: white;
        padding: 4px;
        outline: none;
    }}

    QListWidget, QTableWidget, QTreeWidget {{
        background-color: {c.COLOR_BG_RAISED};
        color: {c.COLOR_TEXT};
        border: none;
        border-radius: 10px;
        gridline-color: transparent;
        alternate-background-color: {c.COLOR_BG_HOVER};
        outline: none;
    }}

    QListWidget::item, QTableWidget::item {{
        padding: 9px 10px;
        border: none;
    }}

    QListWidget::item:hover, QTableWidget::item:hover {{
        background-color: {c.COLOR_BG_HOVER};
    }}

    QListWidget::item:selected, QTableWidget::item:selected {{
        background-color: {c.COLOR_ACCENT_SOFT};
        color: white;
    }}

    QHeaderView::section {{
        background-color: {c.COLOR_BG_RAISED};
        color: {c.COLOR_TEXT_DIM};
        border: none;
        padding: 11px 10px;
        font-weight: 700;
        font-size: 12px;
        letter-spacing: 0.6px;
    }}

    QHeaderView {{
        background-color: {c.COLOR_BG_RAISED};
        border: none;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
        border: none;
    }}

    QScrollBar::handle:vertical {{
        background: {c.COLOR_BORDER_LIGHT};
        border-radius: 4px;
        min-height: 30px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {c.COLOR_TEXT_DIM};
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}

    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}

    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
        border: none;
    }}

    QScrollBar::handle:horizontal {{
        background: {c.COLOR_BORDER_LIGHT};
        border-radius: 4px;
        min-width: 30px;
    }}

    QScrollBar::handle:horizontal:hover {{
        background: {c.COLOR_TEXT_DIM};
    }}

    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}

    QScrollArea {{
        background-color: transparent;
        border: none;
    }}

    QTabWidget::pane {{
        border: none;
        background-color: transparent;
        top: 0;
    }}

    QTabBar {{
        background: transparent;
        border: none;
    }}

    QTabBar::tab {{
        background: transparent;
        color: {c.COLOR_TEXT_DIM};
        padding: 10px 10px 12px 10px;
        border: none;
        margin-right: 2px;
        font-size: 14px;
        font-weight: 600;
    }}

    QTabBar::tab:hover {{
        color: {c.COLOR_TEXT};
    }}

    QTabBar::tab:selected {{
        color: {c.COLOR_ACCENT};
        font-weight: 600;
        border-bottom: 2px solid {c.COLOR_ACCENT};
    }}

    QRadioButton, QCheckBox {{
        spacing: 10px;
        color: {c.COLOR_TEXT};
        padding: 4px 0;
    }}

    QRadioButton::indicator, QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 2px solid {c.COLOR_BORDER_LIGHT};
        background-color: {c.COLOR_INPUT_BG};
        border-radius: 9px;
    }}

    QCheckBox::indicator {{
        border-radius: 4px;
    }}

    QRadioButton::indicator:checked, QCheckBox::indicator:checked {{
        background-color: {c.COLOR_ACCENT};
        border-color: {c.COLOR_ACCENT};
    }}

    QToolTip {{
        background-color: {c.COLOR_BG_RAISED};
        color: {c.COLOR_TEXT};
        border: none;
        padding: 8px 10px;
        border-radius: 6px;
    }}

    QMenu {{
        background-color: {c.COLOR_BG_RAISED};
        color: {c.COLOR_TEXT};
        border: none;
        border-radius: 8px;
        padding: 6px;
    }}

    QMenu::item {{
        padding: 8px 22px;
        border-radius: 5px;
    }}

    QMenu::item:selected {{
        background-color: {c.COLOR_ACCENT};
        color: white;
    }}

    QStatusBar {{
        background-color: {c.COLOR_BG_SIDEBAR};
        color: {c.COLOR_TEXT_DIM};
        border-top: none;
    }}

    QFrame#RecommendationCard {{
        background-color: {c.COLOR_BG_HOVER};
        border: none;
        border-left: 3px solid {c.COLOR_ACCENT};
        border-radius: 8px;
    }}

    QDialog {{
        background-color: {c.COLOR_BG};
    }}

    QSplitter::handle {{
        background-color: transparent;
    }}
    """
