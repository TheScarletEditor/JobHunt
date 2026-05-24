from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QComboBox, QDateEdit,
    QTextEdit, QVBoxLayout, QLabel, QHBoxLayout, QPushButton,
)

from ... import config
from ...db import DB
from ..widgets.dark_titlebar import apply_dark_title_bar


class AddApplicationDialog(QDialog):
    """Modal dialog used for both adding a new application and editing an existing one.
    Pass `application_id` to load an existing row; leave None to add."""

    def __init__(self, application_id: int | None = None, parent=None):
        super().__init__(parent)
        self.application_id = application_id
        is_edit = application_id is not None
        title_text = "Edit Application" if is_edit else "Add Application"

        self.setWindowTitle(title_text)
        self.setMinimumWidth(560)
        self.setModal(True)
        apply_dark_title_bar(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 22, 22, 22)
        outer.setSpacing(14)

        title = QLabel(title_text)
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)

        self.company = QLineEdit()
        self.company.setPlaceholderText("e.g. Stripe")
        self.role = QLineEdit()
        self.role.setPlaceholderText("e.g. Senior Software Engineer")

        self.source = QComboBox()
        self.source.addItems(config.DEFAULT_SOURCES)

        self.date_applied = QDateEdit()
        self.date_applied.setCalendarPopup(True)
        self.date_applied.setDisplayFormat("yyyy-MM-dd")
        self.date_applied.setDate(QDate.currentDate())

        self.stage = QComboBox()
        self._stages = DB.query("SELECT id, name FROM pipeline_stages ORDER BY sort_order")
        for s in self._stages:
            self.stage.addItem(s["name"], s["id"])

        self.listing_url = QLineEdit()
        self.listing_url.setPlaceholderText("https://...")

        self.listing_text = QTextEdit()
        self.listing_text.setPlaceholderText(
            "Paste the job listing text here (optional). "
            "Used by 'Generate resume' and 'Generate cover letter' on this application."
        )
        self.listing_text.setFixedHeight(120)

        self.notes = QTextEdit()
        self.notes.setPlaceholderText("Personal notes (optional)")
        self.notes.setFixedHeight(80)

        form.addRow("Company *", self.company)
        form.addRow("Role *", self.role)
        form.addRow("Source", self.source)
        form.addRow("Date applied", self.date_applied)
        form.addRow("Stage", self.stage)
        form.addRow("Listing URL", self.listing_url)
        form.addRow("Listing text", self.listing_text)
        form.addRow("Notes", self.notes)
        outer.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        save = QPushButton("Save")
        save.setObjectName("PrimaryButton")
        save.setDefault(True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        outer.addLayout(buttons)

        if is_edit:
            self._load_existing()

    def _load_existing(self):
        row = DB.query_one(
            """SELECT company, role, source, date_applied, current_stage_id,
                      listing_url, listing_text, notes
               FROM applications WHERE id = ?""",
            (self.application_id,),
        )
        if not row:
            return
        self.company.setText(row["company"] or "")
        self.role.setText(row["role"] or "")
        if row["source"]:
            idx = self.source.findText(row["source"])
            if idx >= 0:
                self.source.setCurrentIndex(idx)
        if row["date_applied"]:
            d = QDate.fromString(row["date_applied"], "yyyy-MM-dd")
            if d.isValid():
                self.date_applied.setDate(d)
        if row["current_stage_id"] is not None:
            idx = self.stage.findData(row["current_stage_id"])
            if idx >= 0:
                self.stage.setCurrentIndex(idx)
        self.listing_url.setText(row["listing_url"] or "")
        self.listing_text.setPlainText(row["listing_text"] or "")
        self.notes.setPlainText(row["notes"] or "")

    def _save(self):
        company = self.company.text().strip()
        role = self.role.text().strip()
        if not company or not role:
            self.company.setFocus()
            return

        stage_id = self.stage.currentData()
        values = (
            company,
            role,
            self.source.currentText(),
            self.date_applied.date().toString("yyyy-MM-dd"),
            stage_id,
            self.listing_url.text().strip() or None,
            self.listing_text.toPlainText().strip() or None,
            self.notes.toPlainText().strip() or None,
        )

        if self.application_id is None:
            DB.execute(
                """INSERT INTO applications
                   (company, role, source, date_applied, current_stage_id,
                    listing_url, listing_text, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
            DB.log_audit("application_added", {"company": company, "role": role})
        else:
            DB.execute(
                """UPDATE applications SET
                   company = ?, role = ?, source = ?, date_applied = ?,
                   current_stage_id = ?, listing_url = ?, listing_text = ?,
                   notes = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (*values, self.application_id),
            )
            DB.log_audit("application_edited", {"id": self.application_id})
        self.accept()
