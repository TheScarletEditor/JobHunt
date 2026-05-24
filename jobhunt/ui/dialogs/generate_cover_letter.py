from __future__ import annotations

import json
import re

from PySide6.QtCore import Qt, Signal, QThread, QObject
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QFrame, QMessageBox,
)

from ... import config
from ...db import DB
from ...documents import url_fetch
from ...documents.model import ResumeContent
from ...llm import get_provider
from ..widgets.dark_titlebar import apply_dark_title_bar


URL_RE = re.compile(r"^(?:https?://|www\.)", re.IGNORECASE)


class _GenerateWorker(QObject):
    done = Signal(str, str, str)

    def __init__(self, source: str, profile: dict, story_bank: list[dict], resume: ResumeContent):
        super().__init__()
        self._source = source
        self._profile = profile
        self._story_bank = story_bank
        self._resume = resume

    def run(self):
        try:
            text = self._source.strip()
            if "\n" not in text and URL_RE.match(text):
                text = url_fetch.fetch_job_listing(text)
            provider = get_provider()
            letter = provider.generate_cover_letter(
                text, self._profile, self._story_bank, self._resume,
            )
            self.done.emit(letter, provider.name, "")
        except url_fetch.FetchError as e:
            self.done.emit("", "", f"Fetch error: {e}")
        except Exception as e:
            self.done.emit("", "", f"Generation error: {e}")


class GenerateCoverLetterDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate Cover Letter")
        self.setMinimumWidth(720)
        self.resize(760, 540)
        self.setModal(True)
        apply_dark_title_bar(self)

        self.generated_letter: str = ""
        self.provider_name: str = ""
        self._thread: QThread | None = None
        self._worker: _GenerateWorker | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 22, 22, 22)
        outer.setSpacing(14)

        title = QLabel("Generate Cover Letter")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        source_card = QFrame()
        source_card.setObjectName("Card")
        sc = QVBoxLayout(source_card)
        sc.setContentsMargins(22, 18, 22, 18)
        sc.setSpacing(8)

        s_title = QLabel("Job listing")
        s_title.setObjectName("SectionTitle")
        sc.addWidget(s_title)

        info = QLabel(
            "Paste the job description directly, or paste a URL from Greenhouse, Lever, "
            "Ashby, Workable, or SmartRecruiters and we'll fetch it. "
            "The generator pulls from your saved profile, story bank, and most recent resume."
        )
        info.setWordWrap(True)
        info.setObjectName("SectionDescription")
        sc.addWidget(info)

        self.source_input = QPlainTextEdit()
        self.source_input.setPlaceholderText(
            "https://boards.greenhouse.io/...   OR   paste the listing here"
        )
        self.source_input.setMinimumHeight(180)
        sc.addWidget(self.source_input)

        outer.addWidget(source_card)

        self.status_label = QLabel("Ready.")
        self.status_label.setStyleSheet(f"color: {config.COLOR_TEXT_DIM};")
        outer.addWidget(self.status_label)

        outer.addStretch(1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.gen_btn = QPushButton("Generate")
        self.gen_btn.setObjectName("PrimaryButton")
        self.gen_btn.clicked.connect(self._on_generate)
        footer.addWidget(self.cancel_btn)
        footer.addWidget(self.gen_btn)
        outer.addLayout(footer)

    def _on_generate(self):
        source = self.source_input.toPlainText().strip()
        if not source:
            self.status_label.setText("Paste a job listing or URL first.")
            self.status_label.setStyleSheet(f"color: {config.COLOR_ACCENT};")
            return
        if self._thread and self._thread.isRunning():
            return

        self.gen_btn.setEnabled(False)
        self.gen_btn.setText("Thinking…")
        self.status_label.setText("Fetching / generating…")
        self.status_label.setStyleSheet(f"color: {config.COLOR_TEXT_DIM};")

        profile_row = DB.query_one("SELECT * FROM profile WHERE id = 1")
        profile = dict(profile_row) if profile_row else {}
        story_rows = DB.query("SELECT theme_tag, title, body FROM story_bank")
        story_bank = [dict(r) for r in story_rows]
        latest_resume_row = DB.query_one(
            "SELECT content_json FROM resume_versions ORDER BY id DESC LIMIT 1"
        )
        if latest_resume_row and latest_resume_row["content_json"]:
            resume = ResumeContent.from_json(latest_resume_row["content_json"])
        else:
            resume = ResumeContent()

        self._thread = QThread(self)
        self._worker = _GenerateWorker(source, profile, story_bank, resume)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_done(self, letter: str, provider_name: str, err: str):
        self.gen_btn.setEnabled(True)
        self.gen_btn.setText("Generate")
        self._thread = None
        self._worker = None
        if err:
            self.status_label.setText(err)
            self.status_label.setStyleSheet(f"color: {config.COLOR_ACCENT};")
            return
        if not letter.strip():
            self.status_label.setText("Empty response from provider.")
            self.status_label.setStyleSheet(f"color: {config.COLOR_ACCENT};")
            return
        self.generated_letter = letter.strip()
        self.provider_name = provider_name
        DB.log_audit("cover_letter_generated", {"provider": provider_name})
        self.accept()
