"""Edit / view dialog for a single interview row.

Full CRUD plus AI helpers (prep generator, debrief structurer, attendee
research) and one-click calendar push (Google or Outlook, auto-detected
from the user's profile email).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QObject, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ... import config
from ...db import DB
from ...interviews.store import (
    Attendee, Interview, ROUND_TYPES, create_interview, delete_interview,
    update_interview,
)
from ..widgets.dark_titlebar import apply_dark_title_bar


# ============================================================================
# Background AI workers
# ============================================================================


class _PrepWorker(QObject):
    done = Signal(str, str)  # (text, error)

    def __init__(self, resume, company, role, round_type, listing_text=""):
        super().__init__()
        self._args = (resume, company, role, round_type, listing_text)

    def run(self):
        try:
            from ...llm import get_provider
            text = get_provider().interview_prep(*self._args)
            self.done.emit(text, "")
        except Exception as e:
            self.done.emit("", f"{type(e).__name__}: {e}")


class _DebriefWorker(QObject):
    done = Signal(str, str)

    def __init__(self, brain_dump, company, role):
        super().__init__()
        self._brain_dump = brain_dump
        self._company = company
        self._role = role

    def run(self):
        try:
            from ...llm import get_provider
            text = get_provider().interview_debrief(
                self._brain_dump, company=self._company, role=self._role,
            )
            self.done.emit(text, "")
        except Exception as e:
            self.done.emit("", f"{type(e).__name__}: {e}")


class _AttendeeResearchWorker(QObject):
    done = Signal(str, str)

    def __init__(self, name, title, company, linkedin_url):
        super().__init__()
        self._args = (name, title, company, linkedin_url)

    def run(self):
        try:
            from ...llm import get_provider
            text = get_provider().attendee_research(*self._args)
            self.done.emit(text, "")
        except Exception as e:
            self.done.emit("", f"{type(e).__name__}: {e}")


def _label(text: str, *, color: str, point: int = 11, bold: bool = True,
           min_height: int = 24) -> QLabel:
    lbl = QLabel(text)
    f = QFont("Segoe UI", point); f.setBold(bold)
    lbl.setFont(f)
    lbl.setStyleSheet(
        f"QLabel {{ color: {color}; background-color: transparent; padding: 0; margin: 0; }}"
    )
    lbl.setMinimumHeight(min_height)
    return lbl


class _AttendeeRow(QFrame):
    remove_clicked = Signal(object)
    research_clicked = Signal(object)

    def __init__(self, attendee: Attendee | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("AttendeeRow")
        self.setStyleSheet(
            f"#AttendeeRow {{ background: {config.COLOR_BG_HOVER}; "
            f"border-radius: 6px; }}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)

        self.name = QLineEdit()
        self.name.setPlaceholderText("Name")
        top.addWidget(self.name, 2)

        self.title = QLineEdit()
        self.title.setPlaceholderText("Title (e.g. Eng Manager)")
        top.addWidget(self.title, 2)

        self.email = QLineEdit()
        self.email.setPlaceholderText("Email (optional)")
        top.addWidget(self.email, 2)

        self.linkedin = QLineEdit()
        self.linkedin.setPlaceholderText("LinkedIn URL")
        top.addWidget(self.linkedin, 2)

        self.research_btn = QPushButton("🔍")
        self.research_btn.setFixedSize(28, 28)
        self.research_btn.setObjectName("GhostButton")
        self.research_btn.setToolTip("Generate AI prep brief for this attendee")
        self.research_btn.clicked.connect(lambda: self.research_clicked.emit(self))
        top.addWidget(self.research_btn)

        rm = QPushButton("✕")
        rm.setFixedSize(28, 28)
        rm.setObjectName("GhostButton")
        rm.setToolTip("Remove attendee")
        rm.clicked.connect(lambda: self.remove_clicked.emit(self))
        top.addWidget(rm)
        outer.addLayout(top)

        # Research brief is hidden until we have one.
        self.brief_label = QLabel("")
        self.brief_label.setWordWrap(True)
        self.brief_label.setTextFormat(Qt.RichText)
        self.brief_label.setStyleSheet(
            f"QLabel {{ color: {config.COLOR_TEXT}; font-size: 11px; "
            f"font-style: italic; padding: 6px 10px; "
            f"background: rgba(255,255,255,0.04); border-radius: 4px; "
            f"border-left: 2px solid {config.COLOR_ACCENT}; }}"
        )
        self.brief_label.setVisible(False)
        outer.addWidget(self.brief_label)

        self._existing_id: int | None = None
        self._research_brief = ""
        if attendee is not None:
            self.load(attendee)

    def load(self, a: Attendee):
        self._existing_id = a.id
        self.name.setText(a.name)
        self.title.setText(a.title)
        self.email.setText(a.email)
        self.linkedin.setText(a.linkedin_url)
        self.set_research_brief(a.research_brief or "")

    def set_research_brief(self, text: str):
        self._research_brief = text or ""
        if text:
            # Render markdown bullets simply
            html = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                       .replace("\n", "<br>"))
            self.brief_label.setText(html)
            self.brief_label.setVisible(True)
        else:
            self.brief_label.setText("")
            self.brief_label.setVisible(False)

    def dump(self) -> Attendee:
        return Attendee(
            id=self._existing_id,
            name=self.name.text().strip(),
            title=self.title.text().strip(),
            email=self.email.text().strip(),
            linkedin_url=self.linkedin.text().strip(),
            research_brief=self._research_brief,
        )


class InterviewDetailDialog(QDialog):
    def __init__(self, interview: Interview | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit interview" if interview and interview.id else "New interview")
        self.setModal(True)
        apply_dark_title_bar(self)

        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.resize(min(820, int(geo.width() * 0.85)),
                        min(880, int(geo.height() * 0.85)))
        else:
            self.resize(820, 880)
        self.setMinimumSize(640, 520)

        self._interview = interview or Interview()
        self.saved_id: int | None = self._interview.id
        self.deleted: bool = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 22, 22, 22)
        outer.setSpacing(14)

        title_text = "Edit interview" if (interview and interview.id) else "New interview"
        title = QLabel(title_text)
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        body_scroll = QScrollArea()
        body_scroll.setWidgetResizable(True)
        body_scroll.setFrameShape(QFrame.NoFrame)
        body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body_host = QWidget()
        body_layout = QVBoxLayout(body_host)
        body_layout.setContentsMargins(0, 0, 12, 0)
        body_layout.setSpacing(18)
        body_scroll.setWidget(body_host)
        outer.addWidget(body_scroll, 1)

        # ---- Top grid: application, round, datetime, duration, location, URL ----
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(36)
        grid.setVerticalSpacing(22)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 200)

        row = 0
        grid.addWidget(_label("Application", color=config.COLOR_FORM_LABEL), row, 0)
        self.app_combo = QComboBox()
        self._populate_app_combo()
        grid.addWidget(self.app_combo, row, 1); row += 1

        grid.addWidget(_label("Round type", color=config.COLOR_FORM_LABEL), row, 0)
        self.round_combo = QComboBox()
        self.round_combo.setEditable(True)
        for rt in ROUND_TYPES:
            self.round_combo.addItem(rt)
        grid.addWidget(self.round_combo, row, 1); row += 1

        grid.addWidget(_label("Date / time", color=config.COLOR_FORM_LABEL), row, 0)
        self.datetime_edit = QDateTimeEdit()
        self.datetime_edit.setCalendarPopup(True)
        self.datetime_edit.setDisplayFormat("yyyy-MM-dd  hh:mm AP")
        # Default: next business hour, top of the hour
        default_dt = (datetime.now() + timedelta(hours=1)).replace(minute=0, second=0)
        self.datetime_edit.setDateTime(default_dt)
        grid.addWidget(self.datetime_edit, row, 1); row += 1

        grid.addWidget(_label("Duration (minutes)", color=config.COLOR_FORM_LABEL), row, 0)
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(5, 480)
        self.duration_spin.setSingleStep(15)
        self.duration_spin.setValue(60)
        grid.addWidget(self.duration_spin, row, 1); row += 1

        grid.addWidget(_label("Location", color=config.COLOR_FORM_LABEL), row, 0)
        self.location = QLineEdit()
        self.location.setPlaceholderText("Remote, office address, or building")
        grid.addWidget(self.location, row, 1); row += 1

        grid.addWidget(_label("Meeting URL", color=config.COLOR_FORM_LABEL), row, 0)
        self.meeting_url = QLineEdit()
        self.meeting_url.setPlaceholderText("Zoom / Google Meet / etc.")
        grid.addWidget(self.meeting_url, row, 1); row += 1

        body_layout.addLayout(grid)

        # ---- Attendees ----
        body_layout.addWidget(_label("Attendees", color=config.COLOR_ACCENT, point=13))
        self._attendees_layout = QVBoxLayout()
        self._attendees_layout.setSpacing(6)
        body_layout.addLayout(self._attendees_layout)
        add_att = QPushButton("+ Add attendee")
        add_att.setObjectName("GhostButton")
        add_att.clicked.connect(self._add_blank_attendee)
        att_row = QHBoxLayout()
        att_row.addWidget(add_att)
        att_row.addStretch(1)
        body_layout.addLayout(att_row)
        self._attendee_rows: list[_AttendeeRow] = []

        # ---- Prep + Debrief ----
        prep_header = QHBoxLayout()
        prep_header.setSpacing(8)
        prep_header.addWidget(_label("Prep notes", color=config.COLOR_ACCENT, point=13))
        prep_header.addStretch(1)
        self.prep_ai_btn = QPushButton("✨ Generate prep")
        self.prep_ai_btn.setObjectName("GhostButton")
        self.prep_ai_btn.setToolTip(
            "AI prep brief tailored to this round + your resume. Fills the prep "
            "notes field below; you can edit afterwards."
        )
        self.prep_ai_btn.clicked.connect(self._on_generate_prep)
        prep_header.addWidget(self.prep_ai_btn)
        body_layout.addLayout(prep_header)
        self.prep_edit = QPlainTextEdit()
        self.prep_edit.setPlaceholderText(
            "What you want to ask, talking points, research, STAR stories you might pull from. "
            "Markdown supported."
        )
        self.prep_edit.setMinimumHeight(180)
        body_layout.addWidget(self.prep_edit)

        debrief_header = QHBoxLayout()
        debrief_header.setSpacing(8)
        debrief_header.addWidget(_label("Debrief", color=config.COLOR_ACCENT, point=13))
        debrief_header.addStretch(1)
        self.debrief_ai_btn = QPushButton("✨ Structure my notes")
        self.debrief_ai_btn.setObjectName("GhostButton")
        self.debrief_ai_btn.setToolTip(
            "Paste a rambling post-interview brain-dump, then click this. AI returns "
            "structured STAR-format notes preserving your specific details."
        )
        self.debrief_ai_btn.clicked.connect(self._on_structure_debrief)
        debrief_header.addWidget(self.debrief_ai_btn)
        body_layout.addLayout(debrief_header)
        self.debrief_edit = QPlainTextEdit()
        self.debrief_edit.setPlaceholderText(
            "Filled out after the interview — questions asked, your answers, signals, follow-ups. "
            "Drop a raw brain-dump here and click '✨ Structure my notes' to format it."
        )
        self.debrief_edit.setMinimumHeight(180)
        body_layout.addWidget(self.debrief_edit)

        body_layout.addStretch(1)

        # Background workers — held as instance attrs so they're not GC'd mid-run.
        self._prep_thread: QThread | None = None
        self._prep_worker: _PrepWorker | None = None
        self._debrief_thread: QThread | None = None
        self._debrief_worker: _DebriefWorker | None = None
        self._research_thread: QThread | None = None
        self._research_worker: _AttendeeResearchWorker | None = None
        self._research_row: _AttendeeRow | None = None

        # ---- Footer ----
        footer = QHBoxLayout()
        if interview and interview.id is not None:
            delete_btn = QPushButton("Delete interview")
            delete_btn.setStyleSheet(
                f"QPushButton {{ color: {config.COLOR_ACCENT}; border: 1px solid "
                f"{config.COLOR_BORDER_LIGHT}; padding: 8px 16px; border-radius: 4px; "
                f"background: transparent; }}"
                f"QPushButton:hover {{ background: {config.COLOR_ACCENT_SOFT}; }}"
            )
            delete_btn.clicked.connect(self._on_delete)
            footer.addWidget(delete_btn)
        footer.addStretch(1)

        from ...interviews.calendar import availability as _cal_availability
        cal = _cal_availability()
        if interview and interview.outlook_event_id:
            cal_label = cal.label.replace("Push to", "Update")
        else:
            cal_label = cal.label
        self.cal_btn = QPushButton(cal_label)
        tooltip = (
            f"Connected: {cal.connected_email}" if cal.available and cal.connected_email
            else (cal.reason or "Set up calendar integration in Settings.")
        )
        self.cal_btn.setToolTip(tooltip)
        self.cal_btn.clicked.connect(self._on_push_calendar)
        footer.addWidget(self.cal_btn)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        save_btn = btns.button(QDialogButtonBox.Save)
        save_btn.setObjectName("PrimaryButton")
        btns.accepted.connect(self._on_save)
        btns.rejected.connect(self.reject)
        footer.addWidget(btns)
        outer.addLayout(footer)

        self._populate_from_interview()

    # ------------------------------------------------------------------ helpers

    def _populate_app_combo(self):
        self.app_combo.clear()
        self.app_combo.addItem("(no application linked)", None)
        rows = DB.query(
            "SELECT id, company, role FROM applications ORDER BY date_applied DESC, id DESC"
        )
        for r in rows:
            label = f"{r['company']} — {r['role']}"
            self.app_combo.addItem(label, r["id"])

    def _populate_from_interview(self):
        iv = self._interview
        if iv.application_id is not None:
            idx = self.app_combo.findData(iv.application_id)
            if idx >= 0:
                self.app_combo.setCurrentIndex(idx)
        if iv.round_type:
            idx = self.round_combo.findText(iv.round_type)
            if idx >= 0:
                self.round_combo.setCurrentIndex(idx)
            else:
                self.round_combo.setEditText(iv.round_type)
        if iv.interview_datetime:
            from PySide6.QtCore import QDateTime
            dt = QDateTime.fromString(iv.interview_datetime.replace("T", " ")[:19],
                                       "yyyy-MM-dd HH:mm:ss")
            if dt.isValid():
                self.datetime_edit.setDateTime(dt)
        self.duration_spin.setValue(int(iv.duration_minutes or 60))
        self.location.setText(iv.location)
        self.meeting_url.setText(iv.meeting_url)
        self.prep_edit.setPlainText(iv.prep_notes)
        self.debrief_edit.setPlainText(iv.debrief)
        for a in iv.attendees:
            self._add_attendee_row(a)

    def _add_blank_attendee(self):
        self._add_attendee_row(Attendee())

    def _add_attendee_row(self, a: Attendee):
        row = _AttendeeRow(a)
        row.remove_clicked.connect(self._on_remove_attendee)
        row.research_clicked.connect(self._on_research_attendee)
        self._attendee_rows.append(row)
        self._attendees_layout.addWidget(row)

    def _on_remove_attendee(self, row: _AttendeeRow):
        if row in self._attendee_rows:
            self._attendee_rows.remove(row)
            self._attendees_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()

    # ------------------------------------------------------------------ AI handlers

    def _current_app_company_role(self) -> tuple[str, str]:
        app_id = self.app_combo.currentData()
        if app_id is None:
            return ("", "")
        row = DB.query_one(
            "SELECT company, role, listing_text FROM applications WHERE id = ?",
            (app_id,),
        )
        if not row:
            return ("", "")
        return (row["company"] or "", row["role"] or "")

    def _current_app_full(self) -> tuple[str, str, str]:
        app_id = self.app_combo.currentData()
        if app_id is None:
            return ("", "", "")
        row = DB.query_one(
            "SELECT company, role, listing_text FROM applications WHERE id = ?",
            (app_id,),
        )
        if not row:
            return ("", "", "")
        return (row["company"] or "", row["role"] or "", row["listing_text"] or "")

    def _load_default_resume(self):
        """Most-recently-touched resume's latest version, or None."""
        from ...documents import versions as ver
        row = DB.query_one(
            "SELECT t.id FROM resume_types t "
            "JOIN resume_versions v ON v.resume_type_id = t.id "
            "GROUP BY t.id ORDER BY MAX(v.created_at) DESC LIMIT 1"
        )
        if not row:
            return None
        versions = ver.list_versions(row["id"])
        if not versions:
            return None
        loaded = ver.get_version(versions[0]["id"])
        if not loaded:
            return None
        content, _meta = loaded
        return content

    def _on_generate_prep(self):
        resume = self._load_default_resume()
        if resume is None:
            QMessageBox.information(
                self, "No resume",
                "Import or create a resume on the Resume page first — the prep "
                "generator needs your resume as context."
            )
            return
        company, role, listing = self._current_app_full()
        round_type = self.round_combo.currentText().strip()

        self.prep_ai_btn.setEnabled(False)
        self.prep_ai_btn.setText("✨ Thinking…")

        self._prep_thread = QThread(self)
        self._prep_worker = _PrepWorker(resume, company, role, round_type, listing)
        self._prep_worker.moveToThread(self._prep_thread)
        self._prep_thread.started.connect(self._prep_worker.run)
        self._prep_worker.done.connect(self._on_prep_done)
        self._prep_worker.done.connect(self._prep_thread.quit)
        self._prep_thread.finished.connect(self._prep_thread.deleteLater)
        self._prep_thread.start()

    def _on_prep_done(self, text: str, error: str):
        self._prep_thread = None
        self._prep_worker = None
        self.prep_ai_btn.setEnabled(True)
        self.prep_ai_btn.setText("✨ Generate prep")
        if error:
            QMessageBox.warning(self, "Prep generator failed", error)
            return
        # Replace existing content so users get a fresh brief
        self.prep_edit.setPlainText(text)

    def _on_structure_debrief(self):
        raw = self.debrief_edit.toPlainText().strip()
        if not raw:
            QMessageBox.information(
                self, "No notes to structure",
                "Type a rough brain-dump in the Debrief field first, then click this."
            )
            return
        company, role = self._current_app_company_role()
        self.debrief_ai_btn.setEnabled(False)
        self.debrief_ai_btn.setText("✨ Thinking…")

        self._debrief_thread = QThread(self)
        self._debrief_worker = _DebriefWorker(raw, company, role)
        self._debrief_worker.moveToThread(self._debrief_thread)
        self._debrief_thread.started.connect(self._debrief_worker.run)
        self._debrief_worker.done.connect(self._on_debrief_done)
        self._debrief_worker.done.connect(self._debrief_thread.quit)
        self._debrief_thread.finished.connect(self._debrief_thread.deleteLater)
        self._debrief_thread.start()

    def _on_debrief_done(self, text: str, error: str):
        self._debrief_thread = None
        self._debrief_worker = None
        self.debrief_ai_btn.setEnabled(True)
        self.debrief_ai_btn.setText("✨ Structure my notes")
        if error:
            QMessageBox.warning(self, "Debrief structurer failed", error)
            return
        self.debrief_edit.setPlainText(text)

    def _on_research_attendee(self, row: _AttendeeRow):
        a = row.dump()
        if not a.name and not a.title:
            QMessageBox.information(
                self, "Need attendee info",
                "Fill in at least the attendee's name and title before researching."
            )
            return
        if self._research_worker is not None:
            QMessageBox.information(
                self, "Already researching",
                "Wait for the current research run to finish before starting another.",
            )
            return
        company, _role = self._current_app_company_role()
        row.research_btn.setEnabled(False)
        row.research_btn.setText("…")

        self._research_row = row
        self._research_thread = QThread(self)
        self._research_worker = _AttendeeResearchWorker(
            a.name, a.title, company, a.linkedin_url,
        )
        self._research_worker.moveToThread(self._research_thread)
        self._research_thread.started.connect(self._research_worker.run)
        self._research_worker.done.connect(self._on_research_done)
        self._research_worker.done.connect(self._research_thread.quit)
        self._research_thread.finished.connect(self._research_thread.deleteLater)
        self._research_thread.start()

    def _on_research_done(self, text: str, error: str):
        row = self._research_row
        self._research_row = None
        self._research_thread = None
        self._research_worker = None
        if row is not None:
            row.research_btn.setEnabled(True)
            row.research_btn.setText("🔍")
        if error:
            QMessageBox.warning(self, "Research failed", error)
            return
        if row is not None:
            row.set_research_brief(text)

    # ------------------------------------------------------------------ save / delete

    def _on_save(self):
        dt = self.datetime_edit.dateTime().toString("yyyy-MM-dd HH:mm:ss")
        attendees = [r.dump() for r in self._attendee_rows
                     if r.dump().name or r.dump().email or r.dump().linkedin_url]

        iv = Interview(
            id=self._interview.id,
            application_id=self.app_combo.currentData(),
            interview_datetime=dt,
            duration_minutes=self.duration_spin.value(),
            round_type=self.round_combo.currentText().strip(),
            location=self.location.text().strip(),
            meeting_url=self.meeting_url.text().strip(),
            prep_notes=self.prep_edit.toPlainText().strip(),
            debrief=self.debrief_edit.toPlainText().strip(),
            outlook_event_id=self._interview.outlook_event_id,
            attendees=attendees,
        )

        try:
            if iv.id is None:
                self.saved_id = create_interview(iv)
            else:
                update_interview(iv)
                self.saved_id = iv.id
        except Exception as e:
            QMessageBox.warning(self, "Save error", f"Couldn't save: {e}")
            return
        self.accept()

    def _on_push_calendar(self):
        from ...interviews.calendar import (
            availability, push_event, CalendarPushError,
            PROVIDER_GOOGLE, PROVIDER_OUTLOOK,
        )
        from ...interviews import google_calendar as gcal

        avail = availability()

        # Google: if the user is a Gmail user but not connected, run the OAuth flow first.
        if not avail.available and avail.provider == PROVIDER_GOOGLE:
            from ... import config as cfg
            if not cfg.GOOGLE_CLIENT_ID:
                QMessageBox.warning(
                    self, "Google Calendar not configured",
                    "Google Calendar needs a one-time setup:\n\n"
                    "  1. Open https://console.cloud.google.com/\n"
                    "  2. Create a project + enable the Google Calendar API\n"
                    "  3. Create an OAuth client of type 'Desktop application'\n"
                    "  4. Paste the client_id into GOOGLE_CLIENT_ID in jobhunt/config.py\n"
                    "  5. Reload JobHunt and try again."
                )
                return
            confirm = QMessageBox.question(
                self, "Connect Google Calendar",
                "Sign in to Google to authorize calendar event creation?\n\n"
                "Your browser will open. Approve, then return here.",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
            )
            if confirm != QMessageBox.Yes:
                return
            self.cal_btn.setEnabled(False)
            self.cal_btn.setText("📅 Waiting for sign-in…")
            try:
                result = gcal.run_auth_code_flow()
            except gcal.GoogleAuthError as e:
                QMessageBox.warning(self, "Sign-in failed", str(e))
                self.cal_btn.setEnabled(True)
                self.cal_btn.setText(avail.label)
                return
            email = result.get("email") or "(unknown email)"
            QMessageBox.information(
                self, "Connected",
                f"Signed in as {email}. You can now push events from this dialog."
            )
            self.cal_btn.setEnabled(True)
            self.cal_btn.setText("📅 Push to Google Calendar")
            return  # let the user click Push again to actually push

        if not avail.available:
            QMessageBox.warning(self, "Calendar not available", avail.reason)
            return

        # Save the interview first if it's brand new — otherwise we can't push.
        if self._interview.id is None:
            confirm = QMessageBox.question(
                self, "Save first?",
                "The interview needs to be saved before it can be pushed to your calendar.\n\n"
                "Save now and then push?",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
            )
            if confirm != QMessageBox.Yes:
                return
            dt = self.datetime_edit.dateTime().toString("yyyy-MM-dd HH:mm:ss")
            attendees = [r.dump() for r in self._attendee_rows
                         if r.dump().name or r.dump().email or r.dump().linkedin_url]
            iv = Interview(
                application_id=self.app_combo.currentData(),
                interview_datetime=dt,
                duration_minutes=self.duration_spin.value(),
                round_type=self.round_combo.currentText().strip(),
                location=self.location.text().strip(),
                meeting_url=self.meeting_url.text().strip(),
                prep_notes=self.prep_edit.toPlainText().strip(),
                debrief=self.debrief_edit.toPlainText().strip(),
                attendees=attendees,
            )
            try:
                self.saved_id = create_interview(iv)
                iv.id = self.saved_id
                self._interview = iv
            except Exception as e:
                QMessageBox.warning(self, "Save error", f"Couldn't save: {e}")
                return

        from ...interviews.store import get_interview
        iv = get_interview(self._interview.id)
        if iv is None:
            QMessageBox.warning(self, "Push failed", "Interview no longer exists.")
            return

        self.cal_btn.setEnabled(False)
        self.cal_btn.setText("📅 Pushing…")
        try:
            event_id, provider = push_event(iv)
        except CalendarPushError as e:
            QMessageBox.warning(self, "Calendar push failed", str(e))
            self.cal_btn.setEnabled(True)
            self.cal_btn.setText(avail.label)
            return
        except Exception as e:
            QMessageBox.warning(self, "Calendar push failed",
                                f"{type(e).__name__}: {e}")
            self.cal_btn.setEnabled(True)
            self.cal_btn.setText(avail.label)
            return

        self._interview.outlook_event_id = event_id
        self.cal_btn.setEnabled(True)
        provider_name = "Google Calendar" if provider == PROVIDER_GOOGLE else "Outlook"
        self.cal_btn.setText(f"📅 Update {provider_name}")
        QMessageBox.information(
            self, f"{provider_name} event created",
            f"The event was pushed to {provider_name} successfully. "
            "Reminder is set for 15 minutes before.",
        )

    def _on_delete(self):
        confirm = QMessageBox.question(
            self, "Delete interview",
            "Permanently delete this interview?\n\nPrep notes, debrief, and attendees "
            "are removed too. The linked application stays.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return
        if self._interview.id is not None:
            delete_interview(self._interview.id)
            self.deleted = True
        self.accept()
