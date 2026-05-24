"""Interviews — chronological list (upcoming → past), drill-in detail dialog.

Each card opens a full editor with prep notes, debrief, attendees, and AI
helpers (prep generator, debrief structurer, per-attendee research) plus
one-click push to Google Calendar or Outlook.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QMessageBox, QSizePolicy,
)

from ... import config
from ...db import DB
from ...interviews import store as iv_store
from ..dialogs.interview_detail import InterviewDetailDialog


def _styled_label(text: str, *, color: str, point: int, bold: bool) -> QLabel:
    lbl = QLabel(text)
    f = QFont("Segoe UI", point); f.setBold(bold)
    lbl.setFont(f)
    lbl.setStyleSheet(
        f"QLabel {{ color: {color}; background-color: transparent; padding: 0; margin: 0; }}"
    )
    return lbl


def _format_datetime(iso: str | None) -> tuple[str, str]:
    """Return (day_label, time_label) — e.g. ('Tue · May 27', '2:30 PM').
    Windows strftime doesn't support %-d / %-I so we strip leading zeros by hand."""
    dt = iv_store._parse_iso(iso)
    if dt is None:
        return ("Date TBD", "")
    local = dt.astimezone()
    # "Tue · May 27" — strip leading zero from day-of-month
    day = local.strftime("%a · %b %d")
    day = day.replace(" 0", " ")
    # "2:30 PM" — strip leading zero from 12-hour clock
    time_str = local.strftime("%I:%M %p").lstrip("0")
    return (day, time_str)


class _InterviewCard(QFrame):
    clicked = Signal(int)

    def __init__(self, iv: iv_store.Interview, *, is_upcoming: bool, parent=None):
        super().__init__(parent)
        self.iv = iv
        self.setObjectName("Card")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"#Card {{ background: {config.COLOR_BG_RAISED}; border-radius: 10px; }}"
            f"#Card:hover {{ background: {config.COLOR_BG_HOVER}; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(18)

        # Date block (left)
        day_lbl, time_lbl = _format_datetime(iv.interview_datetime)
        date_box = QVBoxLayout()
        date_box.setSpacing(2)
        day = _styled_label(
            day_lbl, color=config.COLOR_ACCENT if is_upcoming else config.COLOR_TEXT_DIM,
            point=11, bold=True,
        )
        time = _styled_label(
            time_lbl, color=config.COLOR_TEXT, point=14, bold=True,
        )
        date_box.addWidget(day)
        date_box.addWidget(time)
        date_wrap = QWidget()
        date_wrap.setLayout(date_box)
        date_wrap.setFixedWidth(150)
        layout.addWidget(date_wrap)

        # Middle: company + role + round
        mid = QVBoxLayout()
        mid.setSpacing(2)
        company_role = f"{iv.company or '(no company)'} — {iv.role or '(no role)'}"
        cr_lbl = _styled_label(company_role, color=config.COLOR_TEXT, point=13, bold=True)
        mid.addWidget(cr_lbl)
        meta_bits = []
        if iv.round_type:
            meta_bits.append(iv.round_type)
        if iv.duration_minutes:
            meta_bits.append(f"{iv.duration_minutes} min")
        if iv.location:
            meta_bits.append(iv.location)
        if iv.attendees:
            n = len(iv.attendees)
            meta_bits.append(f"{n} attendee{'s' if n != 1 else ''}")
        meta = QLabel(" · ".join(meta_bits) or "(no details yet)")
        meta.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 12px;")
        mid.addWidget(meta)
        mid_wrap = QWidget()
        mid_wrap.setLayout(mid)
        mid_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(mid_wrap, 1)

        # Right: signal indicators
        if iv.meeting_url:
            video_chip = QLabel("🎥")
            video_chip.setStyleSheet("font-size: 16px;")
            video_chip.setToolTip(f"Meeting URL: {iv.meeting_url}")
            layout.addWidget(video_chip)
        if iv.prep_notes:
            prep_chip = QLabel("📝 prep")
            prep_chip.setStyleSheet(
                f"QLabel {{ color: {config.COLOR_TEXT_DIM}; background: {config.COLOR_BG_HOVER}; "
                f"padding: 3px 8px; border-radius: 10px; font-size: 11px; }}"
            )
            layout.addWidget(prep_chip)
        if iv.debrief:
            debrief_chip = QLabel("✓ debriefed")
            debrief_chip.setStyleSheet(
                f"QLabel {{ color: white; background: #43a047; "
                f"padding: 3px 8px; border-radius: 10px; font-size: 11px; }}"
            )
            layout.addWidget(debrief_chip)

    def mousePressEvent(self, event):
        if self.iv.id is not None:
            self.clicked.emit(self.iv.id)
        super().mousePressEvent(event)


class InterviewsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 30, 36, 30)
        outer.setSpacing(20)

        header = QHBoxLayout()
        title = QLabel("Interviews & Contacts")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        new_btn = QPushButton("+ New interview")
        new_btn.setObjectName("PrimaryButton")
        new_btn.clicked.connect(self._on_new)
        header.addWidget(new_btn)
        outer.addLayout(header)

        intro = QLabel(
            "Round-by-round tracker. Add prep notes before each interview and "
            "debrief notes after. Click any card to open the editor — it has "
            "AI prep / debrief helpers, per-attendee research, and one-click "
            "push to Google Calendar or Outlook."
        )
        intro.setTextFormat(Qt.RichText)
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 13px;")
        outer.addWidget(intro)

        # Counters strip
        self.counters_label = QLabel("")
        self.counters_label.setStyleSheet(
            f"color: {config.COLOR_TEXT_DIM}; font-size: 12px;"
        )
        outer.addWidget(self.counters_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        self._content_layout = QVBoxLayout(host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(20)
        self._content_layout.addStretch(1)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        self._widgets: list = []
        self._load()

    def refresh(self):
        self._load()

    # ------------------------------------------------------------------ render

    def _load(self):
        for w in list(self._widgets):
            self._content_layout.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self._widgets.clear()

        interviews = iv_store.list_interviews()
        upcoming, past = iv_store.split_by_upcoming(interviews)

        self.counters_label.setText(
            f"{len(upcoming)} upcoming · {len(past)} past · {len(interviews)} total"
        )

        if not interviews:
            empty = QLabel(
                "No interviews tracked yet.\n\n"
                "Click <b>+ New interview</b> to add one manually. JobHunt also "
                "auto-creates rows from email classifications when an interview "
                "invite is detected (confidence ≥ 0.7)."
            )
            empty.setTextFormat(Qt.RichText)
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; padding: 80px;")
            self._insert(empty)
            return

        if upcoming:
            self._insert(self._section_header(f"Upcoming ({len(upcoming)})", accent=True))
            for iv in upcoming:
                self._insert(self._make_card(iv, is_upcoming=True))

        if past:
            self._insert(self._section_header(f"Past ({len(past)})", accent=False))
            for iv in past:
                self._insert(self._make_card(iv, is_upcoming=False))

    def _section_header(self, text: str, *, accent: bool) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"QLabel {{ color: {config.COLOR_ACCENT if accent else config.COLOR_TEXT_DIM}; "
            f"font-size: 13px; font-weight: 700; letter-spacing: 0.6px; "
            f"padding: 8px 0 4px 0; "
            f"border-bottom: 1px solid {config.COLOR_BORDER_LIGHT}; }}"
        )
        return lbl

    def _make_card(self, iv: iv_store.Interview, *, is_upcoming: bool) -> _InterviewCard:
        card = _InterviewCard(iv, is_upcoming=is_upcoming)
        card.clicked.connect(self._on_open)
        return card

    def _insert(self, widget):
        insert_at = max(0, self._content_layout.count() - 1)
        self._content_layout.insertWidget(insert_at, widget)
        self._widgets.append(widget)

    # ------------------------------------------------------------------ actions

    def _on_new(self):
        # Pre-flight: need at least one application to link to
        any_app = DB.query_one("SELECT COUNT(*) AS n FROM applications")
        if not any_app or any_app["n"] == 0:
            QMessageBox.information(
                self, "No applications",
                "You need to track at least one application before scheduling an "
                "interview against it.\n\n"
                "Add an application via the Pipeline page, then come back here.",
            )
            return
        dlg = InterviewDetailDialog(parent=self)
        if dlg.exec() and dlg.saved_id is not None:
            self._load()

    def _on_open(self, interview_id: int):
        iv = iv_store.get_interview(interview_id)
        if iv is None:
            QMessageBox.warning(self, "Not found", "That interview was deleted.")
            self._load()
            return
        dlg = InterviewDetailDialog(interview=iv, parent=self)
        if dlg.exec():
            self._load()

    # ------------------------------------------------------------------ AI ctx

    def ai_context(self) -> dict:
        interviews = iv_store.list_interviews()
        upcoming, past = iv_store.split_by_upcoming(interviews)
        return {
            "page": "Interviews & Contacts",
            "summary": f"{len(upcoming)} upcoming · {len(past)} past",
            "data": {
                "total_count": len(interviews),
                "upcoming_count": len(upcoming),
                "past_count": len(past),
                "next_up": (
                    f"{upcoming[0].company} — {upcoming[0].role} "
                    f"({upcoming[0].interview_datetime})"
                    if upcoming else None
                ),
                "missing_debriefs": sum(
                    1 for iv in past
                    if not iv.debrief and iv.interview_datetime is not None
                ),
            },
            "rule_based_hints": [
                "Click + New interview to log a round you've scheduled.",
                "Fill prep notes BEFORE the interview, debrief AFTER.",
                "Add attendees with LinkedIn URLs so AI research can use them later.",
                "Set the meeting URL so the date card shows the 🎥 indicator.",
            ],
        }
