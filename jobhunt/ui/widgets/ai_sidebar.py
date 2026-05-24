from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QThread, QObject
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
    QScrollArea, QSizePolicy,
)

from ... import config
from ...llm import get_provider
from ...llm import keys as llm_keys


EXPANDED_WIDTH = 320
COLLAPSED_WIDTH = 36


class _RecsWorker(QObject):
    done = Signal(list, str, str)

    def __init__(self, context: dict):
        super().__init__()
        self._context = context

    def run(self):
        try:
            provider = get_provider()
            items = provider.recommend(self._context)
            self.done.emit(items, provider.name, "")
        except Exception as exc:
            self.done.emit([], "error", str(exc))


class AISidebar(QFrame):
    """Right-side panel that renders context-aware recommendations for the current page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AISidebar")
        self._expanded = True
        self._current_context: dict | None = None
        self._worker_thread: QThread | None = None
        self._worker: _RecsWorker | None = None

        self.setFixedWidth(EXPANDED_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        self._build_expanded()
        self._build_collapsed()

    def _build_expanded(self):
        self._expanded_widget = QWidget()
        self._expanded_widget.setObjectName("AISidebarExpanded")
        v = QVBoxLayout(self._expanded_widget)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        header = QFrame()
        header.setObjectName("AISidebarHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 14, 14, 14)
        h.setSpacing(8)

        dot = QLabel("●")
        dot.setStyleSheet(f"color: {config.COLOR_ACCENT}; font-size: 14px;")
        h.addWidget(dot)
        title = QLabel("AI Assistant")
        title_font = title.font()
        title_font.setPointSize(11)
        title_font.setWeight(QFont.DemiBold)
        title.setFont(title_font)
        h.addWidget(title)
        h.addStretch(1)

        self._collapse_btn = QPushButton("›")
        self._collapse_btn.setObjectName("GhostButton")
        self._collapse_btn.setFixedSize(28, 28)
        self._collapse_btn.setToolTip("Collapse sidebar")
        self._collapse_btn.clicked.connect(self._toggle)
        h.addWidget(self._collapse_btn)

        v.addWidget(header)

        self._context_label = QLabel("No page selected yet.")
        self._context_label.setObjectName("SectionDescription")
        self._context_label.setWordWrap(True)
        self._context_label.setTextFormat(Qt.RichText)
        self._context_label.setStyleSheet(
            f"color: {config.COLOR_TEXT_DIM}; padding: 14px 18px 10px 18px;"
        )
        v.addWidget(self._context_label)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(f"background-color: {config.COLOR_BG_AI_PANEL};")
        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(14, 6, 14, 14)
        self._body_layout.setSpacing(8)
        self._body_layout.addStretch(1)
        self._scroll.setWidget(self._body)
        v.addWidget(self._scroll, 1)

        footer = QFrame()
        footer.setObjectName("AISidebarHeader")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(14, 10, 14, 12)
        fl.setSpacing(8)
        self._provider_label = QLabel("")
        self._provider_label.setStyleSheet(f"color: {config.COLOR_TEXT_FAINT}; font-size: 11px;")
        fl.addWidget(self._provider_label)
        fl.addStretch(1)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setObjectName("PrimaryButton")
        self._refresh_btn.clicked.connect(self.refresh)
        fl.addWidget(self._refresh_btn)
        v.addWidget(footer)

        self._outer.addWidget(self._expanded_widget)
        self._show_placeholder("Switch to a page, then click Refresh for tailored suggestions.")

    def _build_collapsed(self):
        self._collapsed_widget = QWidget()
        self._collapsed_widget.setObjectName("AISidebarCollapsed")
        v = QVBoxLayout(self._collapsed_widget)
        v.setContentsMargins(0, 10, 0, 10)
        v.setSpacing(6)
        v.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        self._expand_btn = QPushButton("‹")
        self._expand_btn.setObjectName("GhostButton")
        self._expand_btn.setFixedSize(28, 28)
        self._expand_btn.setToolTip("Expand AI sidebar")
        self._expand_btn.clicked.connect(self._toggle)
        v.addWidget(self._expand_btn, alignment=Qt.AlignHCenter)

        label = QLabel("AI")
        label.setStyleSheet(f"color: {config.COLOR_ACCENT}; font-size: 11px; font-weight: 600;")
        label.setAlignment(Qt.AlignHCenter)
        v.addWidget(label)
        v.addStretch(1)

        self._outer.addWidget(self._collapsed_widget)
        self._collapsed_widget.setVisible(False)

    def _toggle(self):
        self._expanded = not self._expanded
        self._expanded_widget.setVisible(self._expanded)
        self._collapsed_widget.setVisible(not self._expanded)
        self.setFixedWidth(EXPANDED_WIDTH if self._expanded else COLLAPSED_WIDTH)

    def set_context(self, context: dict | None):
        self._current_context = context
        if not context:
            self._context_label.setText("No page context available.")
            self._show_placeholder("Switch to a page, then click Refresh.")
            return
        page = context.get("page", "")
        summary = context.get("summary", "")
        text = f"<b style='color:{config.COLOR_SILVER}'>{page}</b>"
        if summary:
            text += f"<br><span style='color:{config.COLOR_TEXT_DIM}'>{summary}</span>"
        self._context_label.setText(text)
        self._show_placeholder("Click Refresh for recommendations on this screen.")

    def refresh(self):
        if not self._current_context:
            return
        if self._worker_thread and self._worker_thread.isRunning():
            return
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("Thinking…")
        self._show_placeholder("Generating recommendations…")

        thread = QThread(self)
        worker = _RecsWorker(self._current_context)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_done)
        worker.done.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        self._worker_thread = thread
        self._worker = worker
        thread.start()

    def _on_done(self, items: list[str], provider_name: str, err: str):
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("Refresh")
        self._worker = None
        self._worker_thread = None
        if err:
            self._show_placeholder(f"Error: {err}")
            self._provider_label.setText("")
            return
        self._render_items(items)
        if provider_name == "rule_based":
            keys_msg = "Rule-based · add an API key for AI"
        else:
            keys_msg = f"via {provider_name}"
        self._provider_label.setText(keys_msg)

    def _clear_body(self):
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _render_items(self, items: list[str]):
        self._clear_body()
        if not items:
            self._show_placeholder("No recommendations returned. Try again later.")
            return
        for i, text in enumerate(items, start=1):
            card = QFrame()
            card.setObjectName("RecommendationCard")
            cl = QHBoxLayout(card)
            cl.setContentsMargins(12, 10, 12, 10)
            cl.setSpacing(10)
            num = QLabel(str(i))
            num.setStyleSheet(
                f"color: {config.COLOR_ACCENT}; font-size: 14px; font-weight: 700;"
                f" min-width: 16px;"
            )
            num.setAlignment(Qt.AlignTop)
            cl.addWidget(num)
            body = QLabel(text)
            body.setWordWrap(True)
            body.setStyleSheet(f"color: {config.COLOR_TEXT}; font-size: 12px;")
            cl.addWidget(body, 1)
            self._body_layout.addWidget(card)
        self._body_layout.addStretch(1)

    def _show_placeholder(self, text: str):
        self._clear_body()
        msg = QLabel(text)
        msg.setStyleSheet(f"color: {config.COLOR_TEXT_FAINT}; font-size: 12px; padding: 20px 4px;")
        msg.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        msg.setWordWrap(True)
        self._body_layout.addWidget(msg)
        self._body_layout.addStretch(1)
        configured = llm_keys.configured_providers()
        if configured:
            self._provider_label.setText(f"Provider: {configured[0]}")
        else:
            self._provider_label.setText("No API key · rule-based")
