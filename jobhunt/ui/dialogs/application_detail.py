from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QComboBox, QTabWidget, QListWidget, QListWidgetItem, QTextEdit,
    QSplitter, QPlainTextEdit, QWidget, QMessageBox,
)

from ... import config
from ...db import DB
from ...documents.model import ResumeContent
from ..widgets.dark_titlebar import apply_dark_title_bar


def _label(text: str, *, size: int | None = None, color: str | None = None,
           weight: int | None = None) -> QLabel:
    lbl = QLabel(text)
    style = []
    if size:
        style.append(f"font-size: {size}px")
    if color:
        style.append(f"color: {color}")
    if weight:
        style.append(f"font-weight: {weight}")
    if style:
        lbl.setStyleSheet("; ".join(style))
    return lbl


class ApplicationDetailDialog(QDialog):
    def __init__(self, application_id: int, parent=None):
        super().__init__(parent)
        self.application_id = application_id
        self.setWindowTitle("Application")
        self.setMinimumSize(880, 640)
        self.resize(960, 720)
        apply_dark_title_bar(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)
        self._outer_layout = outer
        self._build()

    def _build(self):
        app = DB.query_one(
            """SELECT a.id, a.company, a.role, a.source, a.date_applied,
                      a.current_stage_id, a.fit_score, a.listing_url,
                      a.listing_text, a.notes, a.autonomous_flag,
                      s.name AS stage_name
               FROM applications a
               LEFT JOIN pipeline_stages s ON s.id = a.current_stage_id
               WHERE a.id = ?""",
            (self.application_id,),
        )
        if not app:
            QMessageBox.warning(self, "Not found",
                                "This application was deleted from the database.")
            self.reject()
            return

        outer = self._outer_layout

        header = QFrame()
        header.setObjectName("Card")
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(24, 20, 24, 20)
        h_layout.setSpacing(8)

        company = QLabel(app["company"] or "Unknown company")
        company.setObjectName("PageTitle")
        h_layout.addWidget(company)

        role = _label(
            app["role"] or "Unknown role",
            size=16, color=config.COLOR_TEXT_DIM,
        )
        h_layout.addWidget(role)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(20)

        stage_box = QVBoxLayout()
        stage_box.setSpacing(2)
        stage_box.addWidget(_label("STAGE", size=10, color=config.COLOR_SILVER, weight=600))
        self.stage_combo = QComboBox()
        stages = DB.query("SELECT id, name FROM pipeline_stages ORDER BY sort_order")
        for s in stages:
            self.stage_combo.addItem(s["name"], s["id"])
        if app["current_stage_id"] is not None:
            idx = self.stage_combo.findData(app["current_stage_id"])
            if idx >= 0:
                self.stage_combo.setCurrentIndex(idx)
        self.stage_combo.currentIndexChanged.connect(self._on_stage_changed)
        stage_box.addWidget(self.stage_combo)
        meta_row.addLayout(stage_box)

        meta_row.addLayout(self._meta_block("SOURCE", app["source"] or "—"))
        meta_row.addLayout(self._meta_block("APPLIED", app["date_applied"] or "—"))
        meta_row.addLayout(self._meta_block(
            "FIT SCORE",
            str(app["fit_score"]) if app["fit_score"] is not None else "—",
        ))
        meta_row.addStretch(1)
        h_layout.addLayout(meta_row)

        if app["listing_url"]:
            url_row = QHBoxLayout()
            url_row.setSpacing(8)
            url_row.addWidget(_label("LISTING:", size=10, color=config.COLOR_SILVER, weight=600))
            url_btn = QPushButton(app["listing_url"][:80] + ("…" if len(app["listing_url"]) > 80 else ""))
            url_btn.setObjectName("GhostButton")
            url_btn.setCursor(Qt.PointingHandCursor)
            url_btn.setStyleSheet(f"text-align: left; color: {config.COLOR_ACCENT};")
            url_btn.clicked.connect(
                lambda _checked=False, u=app["listing_url"]: QDesktopServices.openUrl(QUrl(u))
            )
            url_row.addWidget(url_btn, 1)
            h_layout.addLayout(url_row)

        outer.addWidget(header)

        tabs = QTabWidget()
        tabs.addTab(self._build_emails_tab(), "Emails")
        tabs.addTab(self._build_interviews_tab(), "Interviews")
        tabs.addTab(self._build_notes_tab(app["notes"] or ""), "Notes")
        outer.addWidget(tabs, 1)

        footer = QHBoxLayout()
        edit_btn = QPushButton("Edit details…")
        edit_btn.clicked.connect(self._on_edit)
        footer.addWidget(edit_btn)
        gen_resume_btn = QPushButton("Generate resume…")
        gen_resume_btn.setToolTip(
            "Tailor your master resume for this job listing and save it linked to this application"
        )
        gen_resume_btn.clicked.connect(self._on_generate_resume)
        footer.addWidget(gen_resume_btn)
        gen_cover_btn = QPushButton("Generate cover letter…")
        gen_cover_btn.setToolTip(
            "Generate a cover letter tailored to this job and save it linked to this application"
        )
        gen_cover_btn.clicked.connect(self._on_generate_cover_letter)
        footer.addWidget(gen_cover_btn)
        delete_btn = QPushButton("Delete")
        delete_btn.setStyleSheet(f"color: {config.COLOR_ACCENT};")
        delete_btn.setToolTip("Permanently delete this application")
        delete_btn.clicked.connect(self._on_delete)
        footer.addWidget(delete_btn)
        footer.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("PrimaryButton")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        outer.addLayout(footer)

    def _meta_block(self, label: str, value: str) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(2)
        box.addWidget(_label(label, size=10, color=config.COLOR_SILVER, weight=600))
        box.addWidget(_label(value, size=14))
        return box

    def _build_emails_tab(self) -> QWidget:
        emails = DB.query(
            """SELECT id, subject, sender, received_at, detected_stage, raw_body
               FROM emails
               WHERE application_id = ?
               ORDER BY received_at DESC, id DESC""",
            (self.application_id,),
        )

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(0)

        if not emails:
            empty = _label(
                "No emails linked to this application yet. "
                "Run Settings → IMAP → Scan now to fetch and classify your inbox.",
                color=config.COLOR_TEXT_DIM,
            )
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            layout.addStretch(1)
            layout.addWidget(empty)
            layout.addStretch(1)
            return container

        splitter = QSplitter(Qt.Horizontal)

        self._email_list = QListWidget()
        self._email_list.setMinimumWidth(280)
        for e in emails:
            item = QListWidgetItem()
            received = (e["received_at"] or "")[:16].replace("T", " ")
            stage = (e["detected_stage"] or "").upper()
            stage_chip = f"  [{stage}]" if stage and stage != "UNRELATED" else ""
            item.setText(f"{e['subject'] or '(no subject)'}\n{e['sender'] or ''}\n{received}{stage_chip}")
            item.setData(Qt.UserRole, e["raw_body"] or "")
            self._email_list.addItem(item)
        self._email_list.currentItemChanged.connect(self._on_email_selected)

        self._email_body = QTextEdit()
        self._email_body.setReadOnly(True)
        body_font = QFont("Segoe UI", 11)
        self._email_body.setFont(body_font)
        self._email_body.setPlaceholderText("Select an email on the left to read its body.")

        splitter.addWidget(self._email_list)
        splitter.addWidget(self._email_body)
        splitter.setSizes([320, 600])
        layout.addWidget(splitter)

        if self._email_list.count() > 0:
            self._email_list.setCurrentRow(0)

        return container

    def _on_email_selected(self, current, _previous):
        if current is None:
            self._email_body.clear()
            return
        body = current.data(Qt.UserRole) or ""
        self._email_body.setPlainText(body)

    def _build_interviews_tab(self) -> QWidget:
        rows = DB.query(
            """SELECT id, interview_datetime, round_type, prep_notes, debrief
               FROM interviews
               WHERE application_id = ?
               ORDER BY interview_datetime DESC""",
            (self.application_id,),
        )

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(12)

        if not rows:
            empty = _label(
                "No interviews recorded yet. JobHunt auto-creates rows when an email "
                "classifies as 'interview' with a parsed date/time, or you can add "
                "them manually on the Interviews page.",
                color=config.COLOR_TEXT_DIM,
            )
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            layout.addStretch(1)
            layout.addWidget(empty)
            layout.addStretch(1)
            return container

        for r in rows:
            card = QFrame()
            card.setObjectName("Card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(18, 14, 18, 14)
            cl.setSpacing(6)
            when = (r["interview_datetime"] or "")[:16].replace("T", " ")
            cl.addWidget(_label(when, size=15, weight=600))
            if r["round_type"]:
                cl.addWidget(_label(r["round_type"], color=config.COLOR_TEXT_DIM))
            if r["prep_notes"]:
                cl.addWidget(_label("Prep: " + r["prep_notes"], color=config.COLOR_TEXT_DIM))
            if r["debrief"]:
                cl.addWidget(_label("Debrief: " + r["debrief"], color=config.COLOR_TEXT_DIM))
            layout.addWidget(card)

        layout.addStretch(1)
        return container

    def _build_notes_tab(self, existing_notes: str) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(10)

        self._notes_edit = QPlainTextEdit()
        self._notes_edit.setPlainText(existing_notes)
        self._notes_edit.setPlaceholderText(
            "Free-form notes about this application — interview prep, recruiter contact, "
            "compensation discussion, etc."
        )
        layout.addWidget(self._notes_edit, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        save_btn = QPushButton("Save notes")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._save_notes)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        return container

    def _on_stage_changed(self, _idx):
        stage_id = self.stage_combo.currentData()
        if stage_id is None:
            return
        DB.execute(
            "UPDATE applications SET current_stage_id = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (stage_id, self.application_id),
        )
        DB.log_audit("stage_manually_changed", {
            "application_id": self.application_id,
            "new_stage_id": stage_id,
            "stage_name": self.stage_combo.currentText(),
        })

    def _save_notes(self):
        notes = self._notes_edit.toPlainText().strip() or None
        DB.execute(
            "UPDATE applications SET notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (notes, self.application_id),
        )
        DB.log_audit("notes_updated", {"application_id": self.application_id})
        QMessageBox.information(self, "Saved", "Notes saved.")

    def _rebuild(self):
        """Tear down and rebuild the dialog body — used after edits change shown fields."""
        layout = self._outer_layout
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            sub = item.layout()
            if sub is not None:
                self._drop_layout(sub)
        self._build()

    def _drop_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            sub = item.layout()
            if sub is not None:
                self._drop_layout(sub)

    def _on_edit(self):
        from .add_application import AddApplicationDialog
        dlg = AddApplicationDialog(application_id=self.application_id, parent=self)
        if dlg.exec():
            self._rebuild()

    def _on_generate_resume(self):
        type_row = DB.query_one(
            "SELECT id, name FROM resume_types ORDER BY id LIMIT 1"
        )
        if not type_row:
            QMessageBox.information(
                self, "No resume type",
                "Create a resume type first via the Resume page → Import or + Type.",
            )
            return
        type_id = type_row["id"]
        version_row = DB.query_one(
            """SELECT content_json FROM resume_versions
               WHERE resume_type_id = ?
               ORDER BY version_number DESC LIMIT 1""",
            (type_id,),
        )
        if not version_row or not version_row["content_json"]:
            QMessageBox.information(
                self, "No resume yet",
                "Build or import a resume in the Resume page first, then come back.",
            )
            return
        original = ResumeContent.from_json(version_row["content_json"])

        app = DB.query_one(
            "SELECT listing_text, listing_url FROM applications WHERE id = ?",
            (self.application_id,),
        )
        listing = ""
        if app:
            listing = (app["listing_text"] or app["listing_url"] or "").strip()

        from .tailor_resume import TailorResumeDialog
        dlg = TailorResumeDialog(original, type_id, parent=self)
        if listing:
            dlg.source_input.setPlainText(listing)
        if dlg.exec() and dlg.saved_version_id is not None:
            DB.execute(
                """UPDATE applications
                   SET resume_version_id = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (dlg.saved_version_id, self.application_id),
            )
            DB.log_audit("application_resume_linked", {
                "application_id": self.application_id,
                "resume_version_id": dlg.saved_version_id,
            })
            QMessageBox.information(
                self, "Saved",
                "Tailored resume saved and linked to this application.",
            )

    def _on_delete(self):
        confirm = QMessageBox.question(
            self, "Delete application",
            "Delete this application permanently?\n\n"
            "• Linked interviews and offers will be deleted.\n"
            "• Linked emails and cover letters stay in your library but get unlinked.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return
        DB.execute("DELETE FROM applications WHERE id = ?", (self.application_id,))
        DB.log_audit("application_deleted", {"id": self.application_id})
        self.accept()

    def _on_generate_cover_letter(self):
        app = DB.query_one(
            "SELECT listing_text, listing_url FROM applications WHERE id = ?",
            (self.application_id,),
        )
        listing = ""
        if app:
            listing = (app["listing_text"] or app["listing_url"] or "").strip()

        from .generate_cover_letter import GenerateCoverLetterDialog
        dlg = GenerateCoverLetterDialog(parent=self)
        if listing:
            dlg.source_input.setPlainText(listing)
        if dlg.exec() and dlg.generated_letter:
            DB.execute(
                "DELETE FROM cover_letters WHERE application_id = ?",
                (self.application_id,),
            )
            new_id = DB.execute(
                "INSERT INTO cover_letters (application_id, content) VALUES (?, ?)",
                (self.application_id, dlg.generated_letter),
            )
            DB.execute(
                "UPDATE applications SET cover_letter_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_id, self.application_id),
            )
            DB.log_audit("application_cover_letter_generated", {
                "application_id": self.application_id,
            })
            QMessageBox.information(
                self, "Saved",
                "Cover letter generated and saved for this application.",
            )
