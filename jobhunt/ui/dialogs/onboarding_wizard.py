"""First-launch onboarding wizard.

Soft 4-step setup flow that fires when JobHunt detects a fresh install
(empty profile + no API keys configured). Every step has a Skip button —
the goal is to get a friend productive in 5 minutes, not gate the UI.

Steps:
  1. Welcome — explain what JobHunt is and what we're about to set up.
  2. API key — paste a Claude or OpenAI key. Stored encrypted via DPAPI.
  3. Profile basics — name, email, phone, location for later ATS auto-fill.
  4. Import resume — file picker → parser → create first resume type.

After the user closes the wizard (Done or X), `settings_kv.onboarded` is
set to '1' so we don't re-trigger it on subsequent launches even if all
fields end up empty. Power users can re-run from Settings → General if
we ever add a "Restart wizard" button.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget, QLabel, QPushButton,
    QLineEdit, QWidget, QFileDialog, QMessageBox, QSizePolicy,
)

from ... import config
from ...db import DB
from ...documents import parser, versions as ver
from ...llm import keys as llm_keys
from ..widgets.dark_titlebar import apply_dark_title_bar
from .parse_resume_progress import ParseResumeDialog


log = logging.getLogger(__name__)


def should_show_wizard() -> bool:
    """Trigger heuristic: empty profile (no name/email) AND no API keys
    configured, AND the user hasn't dismissed it before."""
    if DB.get_setting("onboarded", "0") == "1":
        return False
    profile = DB.query_one("SELECT legal_name, email FROM profile WHERE id = 1")
    has_profile = bool(profile and (profile["legal_name"] or profile["email"]))
    has_key = bool(llm_keys.configured_providers())
    return not (has_profile or has_key)


def mark_onboarded() -> None:
    DB.set_setting("onboarded", "1")


# ---------------------------------------------------------------------------
# Step widgets — each is a self-contained QWidget with a `commit()` method
# that persists whatever the user entered. Skipping just doesn't call commit.
# ---------------------------------------------------------------------------


class _StepBase(QWidget):
    """Common scaffolding: title + body, in the dark theme palette."""

    def __init__(self, title: str, body: str, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(14)

        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        self._layout.addWidget(title_label)

        if body:
            body_label = QLabel(body)
            body_label.setStyleSheet(
                f"color: {config.COLOR_TEXT_DIM}; font-size: 13px;"
            )
            body_label.setWordWrap(True)
            self._layout.addWidget(body_label)

    def commit(self) -> bool:
        """Persist this step. Return False if validation failed (stays on the
        step). Default: no-op success."""
        return True


class _WelcomeStep(_StepBase):
    def __init__(self, parent=None):
        super().__init__(
            "Welcome to JobHunt",
            "We'll set up the basics in about 2 minutes — API key, your contact "
            "info, and an initial resume. Every step has a Skip button if you'd "
            "rather come back to it later in Settings.",
            parent,
        )
        # Drop the raven mascot in the middle, centered.
        try:
            from ...assets._logo_data import LOGO_PNG_BYTES
            pix = QPixmap()
            if pix.loadFromData(LOGO_PNG_BYTES, "PNG"):
                logo_label = QLabel()
                logo_label.setPixmap(pix.scaled(
                    140, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation
                ))
                logo_label.setAlignment(Qt.AlignCenter)
                self._layout.addWidget(logo_label)
        except Exception:
            pass
        self._layout.addStretch(1)


class _ApiKeyStep(_StepBase):
    def __init__(self, parent=None):
        super().__init__(
            "Add an API key",
            "JobHunt's AI features (resume tailoring, cover letter assembly, "
            "fit scoring, email classification) need either a Claude or OpenAI "
            "key. Without one, the app falls back to deterministic rule-based "
            "mode — still useful but materially less capable.",
            parent,
        )

        form = QVBoxLayout()
        form.setSpacing(10)

        claude_label = QLabel("Anthropic Claude key")
        claude_label.setStyleSheet(f"color: {config.COLOR_FORM_LABEL}; font-size: 12px; font-weight: 600;")
        self.claude_field = QLineEdit()
        self.claude_field.setEchoMode(QLineEdit.Password)
        self.claude_field.setPlaceholderText("sk-ant-…")
        form.addWidget(claude_label)
        form.addWidget(self.claude_field)

        or_label = QLabel("— or —")
        or_label.setAlignment(Qt.AlignCenter)
        or_label.setStyleSheet(f"color: {config.COLOR_TEXT_FAINT}; font-size: 11px; padding: 4px;")
        form.addWidget(or_label)

        openai_label = QLabel("OpenAI key")
        openai_label.setStyleSheet(f"color: {config.COLOR_FORM_LABEL}; font-size: 12px; font-weight: 600;")
        self.openai_field = QLineEdit()
        self.openai_field.setEchoMode(QLineEdit.Password)
        self.openai_field.setPlaceholderText("sk-…")
        form.addWidget(openai_label)
        form.addWidget(self.openai_field)

        self._layout.addLayout(form)

        note = QLabel(
            "Keys are encrypted with Windows DPAPI before being written to disk. "
            "They never leave your machine except in outbound API calls."
        )
        note.setStyleSheet(f"color: {config.COLOR_TEXT_FAINT}; font-size: 11px;")
        note.setWordWrap(True)
        self._layout.addWidget(note)
        self._layout.addStretch(1)

    def commit(self) -> bool:
        claude = self.claude_field.text().strip()
        openai = self.openai_field.text().strip()
        # Either is fine, neither is fine (we treat "I have neither right now"
        # as a soft skip — the wizard's Next button only commits what's there).
        if claude:
            llm_keys.store_key("claude", claude)
            log.info("Onboarding: stored Claude key.")
        if openai:
            llm_keys.store_key("openai", openai)
            log.info("Onboarding: stored OpenAI key.")
        return True


class _ProfileStep(_StepBase):
    def __init__(self, parent=None):
        super().__init__(
            "Your basics",
            "Used to auto-fill application forms later. You can edit any of "
            "this anytime in Settings → Profile.",
            parent,
        )

        # Two-column grid, manually built so we don't have to wrestle with
        # QFormLayout in the dark theme.
        grid = QVBoxLayout()
        grid.setSpacing(10)

        def field_row(label: str, placeholder: str = "") -> QLineEdit:
            row = QVBoxLayout()
            row.setSpacing(4)
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {config.COLOR_FORM_LABEL}; font-size: 12px; font-weight: 600;")
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            row.addWidget(lbl)
            row.addWidget(edit)
            grid.addLayout(row)
            return edit

        self.name_field = field_row("Full name", "Pat Q. Public")
        self.email_field = field_row("Email", "pat@example.com")
        self.phone_field = field_row("Phone (optional)", "+1 555 123 4567")
        self.address_field = field_row("City, State (optional)", "San Francisco, CA")

        # Pre-fill from any existing profile row (so re-running the wizard
        # doesn't wipe data the user typed elsewhere).
        existing = DB.query_one("SELECT legal_name, email, phone, address FROM profile WHERE id = 1")
        if existing:
            self.name_field.setText(existing["legal_name"] or "")
            self.email_field.setText(existing["email"] or "")
            self.phone_field.setText(existing["phone"] or "")
            self.address_field.setText(existing["address"] or "")

        self._layout.addLayout(grid)
        self._layout.addStretch(1)

    def commit(self) -> bool:
        DB.execute(
            "UPDATE profile SET legal_name=?, email=?, phone=?, address=? WHERE id = 1",
            (
                self.name_field.text().strip() or None,
                self.email_field.text().strip() or None,
                self.phone_field.text().strip() or None,
                self.address_field.text().strip() or None,
            ),
        )
        log.info("Onboarding: profile basics saved.")
        return True


class _ResumeStep(_StepBase):
    def __init__(self, parent=None):
        super().__init__(
            "Import your resume",
            "Drop in a .docx, .pdf, or .txt resume and JobHunt will parse it "
            "into the editor as a starting point. You can tailor it to any "
            "specific listing later. Skip this if you'd rather start fresh.",
            parent,
        )
        self._selected_path: str | None = None

        row = QHBoxLayout()
        row.setSpacing(10)
        choose_btn = QPushButton("Choose file…")
        choose_btn.clicked.connect(self._pick_file)
        row.addWidget(choose_btn)
        self.path_label = QLabel("(no file selected)")
        self.path_label.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 12px;")
        self.path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(self.path_label, 1)
        self._layout.addLayout(row)

        tip = QLabel(
            "Scanned image-only PDFs won't parse (no OCR in v1). Plain-text "
            "and standard Word resumes work best."
        )
        tip.setStyleSheet(f"color: {config.COLOR_TEXT_FAINT}; font-size: 11px;")
        tip.setWordWrap(True)
        self._layout.addWidget(tip)
        self._layout.addStretch(1)

    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick a resume",
            filter="Resumes (*.docx *.pdf *.txt);;Word (*.docx);;PDF (*.pdf);;Text (*.txt);;All files (*.*)",
        )
        if not path:
            return
        self._selected_path = path
        self.path_label.setText(Path(path).name)
        self.path_label.setStyleSheet(f"color: {config.COLOR_TEXT}; font-size: 12px;")

    def commit(self) -> bool:
        if not self._selected_path:
            return True  # nothing to do — counts as skip
        path = self._selected_path
        raw = parser.extract_raw_text(Path(path))
        if not raw.strip():
            QMessageBox.warning(
                self, "Empty file",
                f"Couldn't extract any text from {Path(path).name}. "
                "Skipping this step — you can import again from the Resume page later."
            )
            return True
        # Parse on a background thread via the existing dialog. This dialog
        # already handles AI vs rule-based and surfaces errors.
        progress = ParseResumeDialog(raw, parent=self)
        if not progress.exec():
            return True
        content = progress.parsed_content
        if content is None:
            QMessageBox.warning(
                self, "Parse failed",
                f"Could not parse {Path(path).name}:\n{progress.error}\n\n"
                "You can retry later from the Resume page."
            )
            return True
        # Create a default resume type and save as v1.
        type_name = "Default"
        existing = DB.query_one("SELECT id FROM resume_types WHERE name = ?", (type_name,))
        type_id = existing["id"] if existing else ver.create_resume_type(type_name)
        ver.save_version(
            type_id, content,
            label=f"imported from {Path(path).name}",
            source_format="imported",
        )
        log.info("Onboarding: imported resume into type_id=%s", type_id)
        return True


# ---------------------------------------------------------------------------
# Wizard shell
# ---------------------------------------------------------------------------


class OnboardingWizard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to JobHunt")
        self.setMinimumSize(560, 540)
        self.resize(640, 600)
        self.setModal(True)
        apply_dark_title_bar(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)

        self.stack = QStackedWidget()
        self._welcome = _WelcomeStep()
        self._api = _ApiKeyStep()
        self._profile = _ProfileStep()
        self._resume = _ResumeStep()
        for step in (self._welcome, self._api, self._profile, self._resume):
            self.stack.addWidget(step)
        outer.addWidget(self.stack, 1)

        # Step indicator (1 of 4 etc).
        self.step_label = QLabel()
        self.step_label.setStyleSheet(f"color: {config.COLOR_TEXT_FAINT}; font-size: 11px;")
        self.step_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.step_label)

        # Footer: Back · spacer · Skip · Next/Done
        footer = QHBoxLayout()
        self.back_btn = QPushButton("Back")
        self.back_btn.setObjectName("GhostButton")
        self.back_btn.clicked.connect(self._on_back)
        footer.addWidget(self.back_btn)
        footer.addStretch(1)
        self.skip_btn = QPushButton("Skip for now")
        self.skip_btn.setObjectName("GhostButton")
        self.skip_btn.clicked.connect(self._on_skip)
        footer.addWidget(self.skip_btn)
        self.next_btn = QPushButton("Next")
        self.next_btn.setObjectName("PrimaryButton")
        self.next_btn.clicked.connect(self._on_next)
        footer.addWidget(self.next_btn)
        outer.addLayout(footer)

        self._sync_footer()

    def _sync_footer(self):
        idx = self.stack.currentIndex()
        last = self.stack.count() - 1
        self.step_label.setText(f"Step {idx + 1} of {self.stack.count()}")
        self.back_btn.setEnabled(idx > 0)
        # On the welcome step we don't have anything to skip — only "Next."
        self.skip_btn.setVisible(idx > 0 and idx < self.stack.count())
        self.next_btn.setText("Done" if idx == last else "Next")

    def _on_back(self):
        idx = self.stack.currentIndex()
        if idx > 0:
            self.stack.setCurrentIndex(idx - 1)
            self._sync_footer()

    def _on_skip(self):
        # Skip does NOT commit; just advances. If on the last step, treat as Done.
        idx = self.stack.currentIndex()
        if idx >= self.stack.count() - 1:
            self._finish()
            return
        self.stack.setCurrentIndex(idx + 1)
        self._sync_footer()

    def _on_next(self):
        idx = self.stack.currentIndex()
        current = self.stack.currentWidget()
        try:
            ok = current.commit() if hasattr(current, "commit") else True
        except Exception as e:
            log.exception("Onboarding step %d commit failed", idx)
            QMessageBox.warning(self, "Step failed", f"Couldn't save this step:\n{e}")
            return
        if not ok:
            return  # Step rejected — stay put
        if idx >= self.stack.count() - 1:
            self._finish()
            return
        self.stack.setCurrentIndex(idx + 1)
        self._sync_footer()

    def _finish(self):
        mark_onboarded()
        DB.log_audit("onboarding_completed", {})
        self.accept()

    def reject(self):
        # Closing the dialog (X / Esc) still counts as "I've seen it" — we
        # don't want to nag people who deliberately bailed.
        mark_onboarded()
        DB.log_audit("onboarding_dismissed", {})
        super().reject()
