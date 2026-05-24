"""Interview + attendee CRUD + list queries."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..db import DB


log = logging.getLogger(__name__)


ROUND_TYPES = [
    "Phone screen",
    "Recruiter chat",
    "Hiring manager",
    "Technical",
    "System design",
    "Pair programming",
    "Take-home review",
    "Behavioral",
    "Panel",
    "Onsite",
    "Final",
    "Other",
]


@dataclass
class Attendee:
    id: int | None = None
    interview_id: int | None = None
    name: str = ""
    title: str = ""
    email: str = ""
    linkedin_url: str = ""
    research_brief: str = ""

    @classmethod
    def from_row(cls, row) -> "Attendee":
        return cls(
            id=row["id"],
            interview_id=row["interview_id"],
            name=row["name"] or "",
            title=row["title"] or "",
            email=(row["email"] if "email" in row.keys() else "") or "",
            linkedin_url=row["linkedin_url"] or "",
            research_brief=(row["research_brief"] if "research_brief" in row.keys() else "") or "",
        )


@dataclass
class Interview:
    id: int | None = None
    application_id: int | None = None
    interview_datetime: str | None = None  # ISO 8601
    duration_minutes: int = 60
    round_type: str = ""
    location: str = ""
    meeting_url: str = ""
    prep_notes: str = ""
    debrief: str = ""
    outlook_event_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    attendees: list[Attendee] = field(default_factory=list)
    # Joined-on-read display fields:
    company: str = ""
    role: str = ""

    @classmethod
    def from_row(cls, row, *, include_app: bool = False) -> "Interview":
        keys = row.keys()
        return cls(
            id=row["id"],
            application_id=row["application_id"],
            interview_datetime=row["interview_datetime"],
            duration_minutes=int(
                (row["duration_minutes"] if "duration_minutes" in keys else None) or 60
            ),
            round_type=row["round_type"] or "",
            location=(row["location"] if "location" in keys else "") or "",
            meeting_url=(row["meeting_url"] if "meeting_url" in keys else "") or "",
            prep_notes=row["prep_notes"] or "",
            debrief=row["debrief"] or "",
            outlook_event_id=(row["outlook_event_id"] if "outlook_event_id" in keys else None),
            created_at=(row["created_at"] if "created_at" in keys else None),
            updated_at=(row["updated_at"] if "updated_at" in keys else None),
            company=(row["company"] if include_app and "company" in keys else ""),
            role=(row["role"] if include_app and "role" in keys else ""),
        )


# ============================================================================
# Reads
# ============================================================================


def list_interviews() -> list[Interview]:
    """All interviews, sorted by datetime (most recent / soonest first by sign)."""
    rows = DB.query(
        """
        SELECT i.*, a.company, a.role
        FROM interviews i
        LEFT JOIN applications a ON a.id = i.application_id
        ORDER BY
            CASE WHEN i.interview_datetime IS NULL THEN 1 ELSE 0 END,
            i.interview_datetime DESC
        """
    )
    interviews = [Interview.from_row(r, include_app=True) for r in rows]
    if interviews:
        # Pull attendees for all in one query
        ids = [iv.id for iv in interviews if iv.id is not None]
        if ids:
            placeholders = ",".join("?" * len(ids))
            attendee_rows = DB.query(
                f"SELECT * FROM interview_attendees WHERE interview_id IN ({placeholders}) "
                "ORDER BY id",
                tuple(ids),
            )
            by_iv: dict[int, list[Attendee]] = {iid: [] for iid in ids}
            for ar in attendee_rows:
                a = Attendee.from_row(ar)
                if a.interview_id in by_iv:
                    by_iv[a.interview_id].append(a)
            for iv in interviews:
                iv.attendees = by_iv.get(iv.id, [])
    return interviews


def split_by_upcoming(interviews: list[Interview]) -> tuple[list[Interview], list[Interview]]:
    """Partition into (upcoming, past) using now-UTC as the cut.
    Items with no datetime go to past."""
    now = datetime.now(timezone.utc)
    upcoming: list[Interview] = []
    past: list[Interview] = []
    for iv in interviews:
        dt = _parse_iso(iv.interview_datetime)
        if dt is None or dt < now:
            past.append(iv)
        else:
            upcoming.append(iv)
    # Upcoming: soonest first
    upcoming.sort(key=lambda iv: _parse_iso(iv.interview_datetime) or datetime.max.replace(tzinfo=timezone.utc))
    # Past: most recent first
    past.sort(key=lambda iv: _parse_iso(iv.interview_datetime) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return upcoming, past


def get_interview(interview_id: int) -> Interview | None:
    row = DB.query_one(
        """
        SELECT i.*, a.company, a.role
        FROM interviews i
        LEFT JOIN applications a ON a.id = i.application_id
        WHERE i.id = ?
        """,
        (interview_id,),
    )
    if not row:
        return None
    iv = Interview.from_row(row, include_app=True)
    attendee_rows = DB.query(
        "SELECT * FROM interview_attendees WHERE interview_id = ? ORDER BY id",
        (interview_id,),
    )
    iv.attendees = [Attendee.from_row(ar) for ar in attendee_rows]
    return iv


# ============================================================================
# Writes
# ============================================================================


def create_interview(iv: Interview) -> int:
    new_id = DB.execute(
        """
        INSERT INTO interviews
            (application_id, interview_datetime, duration_minutes, round_type,
             location, meeting_url, prep_notes, debrief, outlook_event_id,
             created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (
            iv.application_id,
            iv.interview_datetime,
            int(iv.duration_minutes or 60),
            iv.round_type or "",
            iv.location or "",
            iv.meeting_url or "",
            iv.prep_notes or "",
            iv.debrief or "",
            iv.outlook_event_id,
        ),
    )
    for a in iv.attendees:
        a.interview_id = new_id
        _insert_attendee(a)
    DB.log_audit("interview_created", {"id": new_id, "application_id": iv.application_id})
    return new_id


def update_interview(iv: Interview) -> None:
    if iv.id is None:
        raise ValueError("update_interview requires an id")
    DB.execute(
        """
        UPDATE interviews
        SET application_id = ?, interview_datetime = ?, duration_minutes = ?,
            round_type = ?, location = ?, meeting_url = ?, prep_notes = ?,
            debrief = ?, outlook_event_id = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            iv.application_id,
            iv.interview_datetime,
            int(iv.duration_minutes or 60),
            iv.round_type or "",
            iv.location or "",
            iv.meeting_url or "",
            iv.prep_notes or "",
            iv.debrief or "",
            iv.outlook_event_id,
            iv.id,
        ),
    )
    # Replace attendees: simplest correct behavior.
    DB.execute("DELETE FROM interview_attendees WHERE interview_id = ?", (iv.id,))
    for a in iv.attendees:
        a.interview_id = iv.id
        _insert_attendee(a)
    DB.log_audit("interview_updated", {"id": iv.id})


def delete_interview(interview_id: int) -> None:
    DB.execute("DELETE FROM interviews WHERE id = ?", (interview_id,))
    DB.log_audit("interview_deleted", {"id": interview_id})


def _insert_attendee(a: Attendee) -> int:
    return DB.execute(
        "INSERT INTO interview_attendees "
        "(interview_id, name, title, email, linkedin_url, research_brief) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (a.interview_id, a.name, a.title, a.email, a.linkedin_url, a.research_brief),
    )


# ============================================================================
# Date helpers
# ============================================================================


def _parse_iso(text: str | None) -> datetime | None:
    """Lenient ISO 8601 parser — handles 'YYYY-MM-DDTHH:MM:SS', SQLite's
    'YYYY-MM-DD HH:MM:SS', and tz-suffixed forms."""
    if not text:
        return None
    s = text.strip().replace("T", " ")
    if s.endswith("Z"):
        s = s[:-1]
    # Strip trailing tz offset if present (we treat naive as UTC)
    if len(s) > 19 and (s[19] == "+" or s[19] == "-"):
        s = s[:19]
    try:
        dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return dt.replace(tzinfo=timezone.utc)
