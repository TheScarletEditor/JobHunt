from __future__ import annotations

import json
import re

from PySide6.QtCore import Qt, Signal, QThread, QObject
from PySide6.QtGui import QTextCharFormat, QTextCursor, QColor, QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QFrame, QSplitter, QTextEdit, QInputDialog, QMessageBox,
)

from ... import config
from ...db import DB
from ...documents import url_fetch
from ...documents.diff import line_diff
from ...documents.model import ResumeContent
from ...documents import versions as ver
from ...llm import get_provider
from ..widgets.dark_titlebar import apply_dark_title_bar


URL_RE = re.compile(r"^(?:https?://|www\.)", re.IGNORECASE)


def _load_synonym_groups() -> list[list[str]]:
    rows = DB.query("SELECT terms_json FROM synonym_groups")
    out: list[list[str]] = []
    for r in rows:
        try:
            terms = json.loads(r["terms_json"])
        except Exception:
            continue
        if isinstance(terms, list):
            cleaned = [str(t).strip() for t in terms if str(t).strip()]
            if len(cleaned) >= 2:
                out.append(cleaned)
    return out


class _TailorWorker(QObject):
    done = Signal(object, str, str, str)

    def __init__(self, source_text: str, original: ResumeContent,
                 synonym_groups: list[list[str]] | None = None):
        super().__init__()
        self._source = source_text
        self._original = original
        self._synonym_groups = synonym_groups or []

    def run(self):
        try:
            text = self._source.strip()
            if "\n" not in text and URL_RE.match(text):
                text = url_fetch.fetch_job_listing(text)
            provider = get_provider()
            tailored = provider.tailor_resume(
                self._original, text, synonym_groups=self._synonym_groups,
            )
            self.done.emit(tailored, text, provider.name, "")
        except url_fetch.FetchError as e:
            self.done.emit(None, "", "", f"Fetch error: {e}")
        except Exception as e:
            self.done.emit(None, "", "", f"Tailor error: {e}")


class TailorResumeDialog(QDialog):
    def __init__(self, original: ResumeContent, resume_type_id: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tailor Resume for Job")
        self.resize(1200, 780)
        self.setModal(True)
        apply_dark_title_bar(self)

        self._original = original
        self._type_id = resume_type_id
        self._tailored: ResumeContent | None = None
        self._listing_text = ""
        self._provider_name = ""
        self.saved_version_id: int | None = None
        self._thread: QThread | None = None
        self._worker: _TailorWorker | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 22, 22, 22)
        outer.setSpacing(14)

        title = QLabel("Tailor Resume for Job")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        source_card = QFrame()
        source_card.setObjectName("Card")
        sc = QVBoxLayout(source_card)
        sc.setContentsMargins(24, 18, 24, 18)
        sc.setSpacing(8)

        s_title = QLabel("Job listing — paste text or a URL")
        s_title.setObjectName("SectionTitle")
        sc.addWidget(s_title)

        info = QLabel(
            "Paste the job description directly, or paste a URL from Greenhouse, Lever, "
            "Ashby, Workable, or SmartRecruiters and we'll fetch it. "
            "LinkedIn / Indeed / Glassdoor block fetching — paste their text manually."
        )
        info.setWordWrap(True)
        info.setObjectName("SectionDescription")
        sc.addWidget(info)

        self.source_input = QPlainTextEdit()
        self.source_input.setPlaceholderText(
            "https://boards.greenhouse.io/...   OR   paste the listing here"
        )
        self.source_input.setFixedHeight(130)
        sc.addWidget(self.source_input)

        ctrl_row = QHBoxLayout()
        self.status_label = QLabel("Paste a job listing above and click 'Tailor with AI' to begin.")
        self.status_label.setStyleSheet(f"color: {config.COLOR_TEXT_DIM};")
        ctrl_row.addWidget(self.status_label, 1)
        self.tailor_btn = QPushButton("Tailor with AI")
        self.tailor_btn.setObjectName("PrimaryButton")
        self.tailor_btn.clicked.connect(self._on_tailor)
        ctrl_row.addWidget(self.tailor_btn)
        sc.addLayout(ctrl_row)

        outer.addWidget(source_card)

        diff_card = QFrame()
        diff_card.setObjectName("Card")
        dl = QVBoxLayout(diff_card)
        dl.setContentsMargins(24, 18, 24, 18)
        dl.setSpacing(10)

        diff_title = QLabel("Diff — original vs. tailored")
        diff_title.setObjectName("SectionTitle")
        dl.addWidget(diff_title)

        legend = QHBoxLayout()
        legend.setSpacing(20)
        legend.addWidget(self._legend_chip("Removed", "#2a0c11"))
        legend.addWidget(self._legend_chip("Added", "#0e2a14"))
        legend.addStretch(1)
        dl.addLayout(legend)

        headers_row = QHBoxLayout()
        h_left = QLabel("Original")
        h_left.setStyleSheet(f"color: {config.COLOR_FORM_LABEL}; font-weight: 600;")
        h_right = QLabel("Tailored")
        h_right.setStyleSheet(f"color: {config.COLOR_ACCENT}; font-weight: 600;")
        headers_row.addWidget(h_left, 1)
        headers_row.addWidget(h_right, 1)
        dl.addLayout(headers_row)

        splitter = QSplitter(Qt.Horizontal)
        self.left_view = QTextEdit()
        self.right_view = QTextEdit()
        for v in (self.left_view, self.right_view):
            v.setReadOnly(True)
            v.setLineWrapMode(QTextEdit.WidgetWidth)
            mono = QFont("Cascadia Mono", 10)
            mono.setStyleHint(QFont.Monospace)
            v.setFont(mono)
        splitter.addWidget(self.left_view)
        splitter.addWidget(self.right_view)
        splitter.setSizes([1, 1])
        dl.addWidget(splitter, 1)

        self._syncing = False
        self.left_view.verticalScrollBar().valueChanged.connect(
            lambda v: self._sync_scroll(self.right_view, v)
        )
        self.right_view.verticalScrollBar().valueChanged.connect(
            lambda v: self._sync_scroll(self.left_view, v)
        )

        outer.addWidget(diff_card, 1)

        footer = QHBoxLayout()
        self._provider_label = QLabel("")
        self._provider_label.setStyleSheet(f"color: {config.COLOR_TEXT_FAINT};")
        footer.addWidget(self._provider_label)
        footer.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn = QPushButton("Save tailored version")
        self.save_btn.setObjectName("PrimaryButton")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save)
        footer.addWidget(self.cancel_btn)
        footer.addWidget(self.save_btn)
        outer.addLayout(footer)

        self._render_diff(self._original, self._original)

    def _legend_chip(self, label: str, color: str) -> QLabel:
        chip = QLabel(f"  {label}  ")
        chip.setStyleSheet(
            f"background-color: {color}; color: {config.COLOR_TEXT}; "
            f"padding: 3px 10px; border-radius: 4px; font-size: 11px;"
        )
        return chip

    def _sync_scroll(self, target: QTextEdit, value: int):
        if self._syncing:
            return
        self._syncing = True
        target.verticalScrollBar().setValue(value)
        self._syncing = False

    def _on_tailor(self):
        source = self.source_input.toPlainText().strip()
        if not source:
            self.status_label.setText("Paste a job listing or URL first.")
            self.status_label.setStyleSheet(f"color: {config.COLOR_ACCENT};")
            return
        if self._thread and self._thread.isRunning():
            return
        self.tailor_btn.setEnabled(False)
        self.tailor_btn.setText("Thinking…")
        self.save_btn.setEnabled(False)
        self.status_label.setText("Fetching / tailoring…")
        self.status_label.setStyleSheet(f"color: {config.COLOR_TEXT_DIM};")

        synonym_groups = _load_synonym_groups()
        self._thread = QThread(self)
        self._worker = _TailorWorker(source, self._original, synonym_groups)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_done(self, tailored, listing_text: str, provider_name: str, err: str):
        self.tailor_btn.setEnabled(True)
        self.tailor_btn.setText("Tailor with AI")
        self._thread = None
        self._worker = None
        if err:
            self.status_label.setText(err)
            self.status_label.setStyleSheet(f"color: {config.COLOR_ACCENT};")
            return
        self._tailored = tailored
        self._listing_text = listing_text
        self._provider_name = provider_name
        self._render_diff(self._original, tailored)
        self.save_btn.setEnabled(True)
        self.status_label.setText("Tailored. Review the diff and click 'Save tailored version' to keep.")
        self.status_label.setStyleSheet(f"color: {config.COLOR_TEXT_DIM};")
        self._provider_label.setText(
            "Generated via rule-based fallback — add an API key in Settings for AI tailoring"
            if provider_name == "rule_based"
            else f"Generated via {provider_name}"
        )

    def _render_diff(self, original: ResumeContent, tailored: ResumeContent):
        left_rows, right_rows = line_diff(original.to_plain_text(), tailored.to_plain_text())
        self._populate_view(self.left_view, left_rows)
        self._populate_view(self.right_view, right_rows)

    def _populate_view(self, view: QTextEdit, rows: list[tuple[str, str]]):
        view.clear()
        cursor = view.textCursor()
        for text, status in rows:
            fmt = QTextCharFormat()
            if status == "removed":
                fmt.setBackground(QColor("#2a0c11"))
                fmt.setForeground(QColor(config.COLOR_TEXT))
            elif status == "added":
                fmt.setBackground(QColor("#0e2a14"))
                fmt.setForeground(QColor(config.COLOR_TEXT))
            elif status == "pad":
                fmt.setForeground(QColor(config.COLOR_TEXT_FAINT))
            else:
                fmt.setForeground(QColor(config.COLOR_TEXT))
            display = text if text else " "
            cursor.insertText(display + "\n", fmt)
        view.moveCursor(QTextCursor.Start)

    def _on_save(self):
        if not self._tailored:
            return
        label, ok = QInputDialog.getText(
            self, "Label",
            "Optional label (e.g. 'stripe-eng-2026'). Leave blank for none:",
        )
        if not ok:
            return
        label = label.strip() or None
        try:
            new_id = ver.save_version(
                self._type_id, self._tailored,
                label=label, source_format="ai-tailored",
            )
        except Exception as e:
            QMessageBox.warning(self, "Save error", f"Couldn't save: {e}")
            return
        self.saved_version_id = new_id
        self.accept()
