"""Read + action helpers for job_queue rows."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..db import DB


log = logging.getLogger(__name__)


STATUS_NEW = "new"             # just scanned, awaiting score
STATUS_QUEUED = "queued"       # scored, above threshold, awaiting user action
STATUS_FILTERED = "filtered"   # scored, below threshold (or no resume)
STATUS_APPLIED = "applied"     # user clicked Apply / opened in browser
STATUS_SKIPPED = "skipped"     # user dismissed
STATUS_AUTO_SUBMITTED = "auto_submitted"  # Fire mode submitted on the user's behalf
STATUS_ERROR = "error"


@dataclass
class QueuedJob:
    id: int
    saved_search_id: int
    source_url: str
    company: str
    role: str
    location: str
    posted_at: str | None
    fit_score: int | None
    fit_reason: str | None
    status: str
    queued_at: str | None
    processed_at: str | None
    listing_text: str = ""

    @classmethod
    def from_row(cls, row) -> "QueuedJob":
        return cls(
            id=row["id"],
            saved_search_id=row["saved_search_id"],
            source_url=row["source_url"] or "",
            company=row["company"] or "",
            role=row["role"] or "",
            location=row["location"] or "",
            posted_at=row["posted_at"],
            fit_score=row["fit_score"],
            fit_reason=row["fit_reason"],
            status=row["status"] or STATUS_NEW,
            queued_at=row["queued_at"],
            processed_at=row["processed_at"],
            listing_text=row["listing_text"] or "",
        )


def list_queued(*, search_id: int | None = None, limit: int = 200) -> list[QueuedJob]:
    """Return rows with status='queued', sorted by fit score desc then queued_at desc.
    These are the items the user actively reviews."""
    if search_id is None:
        rows = DB.query(
            "SELECT * FROM job_queue WHERE status = ? "
            "ORDER BY fit_score DESC, queued_at DESC LIMIT ?",
            (STATUS_QUEUED, limit),
        )
    else:
        rows = DB.query(
            "SELECT * FROM job_queue WHERE status = ? AND saved_search_id = ? "
            "ORDER BY fit_score DESC, queued_at DESC LIMIT ?",
            (STATUS_QUEUED, search_id, limit),
        )
    return [QueuedJob.from_row(r) for r in rows]


def count_by_status(search_id: int | None = None) -> dict[str, int]:
    if search_id is None:
        rows = DB.query("SELECT status, COUNT(*) AS n FROM job_queue GROUP BY status")
    else:
        rows = DB.query(
            "SELECT status, COUNT(*) AS n FROM job_queue WHERE saved_search_id = ? GROUP BY status",
            (search_id,),
        )
    return {r["status"]: int(r["n"]) for r in rows}


def mark_applied(job_id: int) -> None:
    DB.execute(
        "UPDATE job_queue SET status = ?, processed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (STATUS_APPLIED, job_id),
    )
    DB.log_audit("queue_job_applied", {"id": job_id})


def mark_skipped(job_id: int) -> None:
    DB.execute(
        "UPDATE job_queue SET status = ?, processed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (STATUS_SKIPPED, job_id),
    )
    DB.log_audit("queue_job_skipped", {"id": job_id})


def delete_job(job_id: int) -> None:
    DB.execute("DELETE FROM job_queue WHERE id = ?", (job_id,))
    DB.log_audit("queue_job_deleted", {"id": job_id})


def clear_processed(search_id: int | None = None) -> int:
    """Delete all processed (applied/skipped/auto_submitted/error/filtered) rows.
    Returns the number deleted."""
    statuses = (STATUS_APPLIED, STATUS_SKIPPED, STATUS_AUTO_SUBMITTED,
                STATUS_ERROR, STATUS_FILTERED)
    placeholders = ",".join("?" * len(statuses))
    if search_id is None:
        before = DB.query_one(
            f"SELECT COUNT(*) AS n FROM job_queue WHERE status IN ({placeholders})",
            statuses,
        )
        DB.execute(
            f"DELETE FROM job_queue WHERE status IN ({placeholders})",
            statuses,
        )
    else:
        params = statuses + (search_id,)
        before = DB.query_one(
            f"SELECT COUNT(*) AS n FROM job_queue WHERE status IN ({placeholders}) "
            f"AND saved_search_id = ?",
            params,
        )
        DB.execute(
            f"DELETE FROM job_queue WHERE status IN ({placeholders}) "
            f"AND saved_search_id = ?",
            params,
        )
    return int(before["n"]) if before else 0
