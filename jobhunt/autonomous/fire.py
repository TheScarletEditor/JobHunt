"""Fire mode guardrails: ATS whitelist + daily-cap enforcement + per-search arming.

A queue item is eligible for auto-submit iff:
  1. The listing URL host matches a trusted ATS pattern (Greenhouse / Lever /
     Ashby / Workable).
  2. The saved search the item came from is in MODE_FIRE.
  3. The "auto-submit today" counter for this saved search is below
     `saved_search.daily_cap`.
  4. The saved search itself is enabled.

The submitting code (BrowserPage) is responsible for the actual click; this
module is the gate it consults before doing anything.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from ..db import DB
from . import queue as queue_mod
from . import searches as svc


log = logging.getLogger(__name__)


# Hostname patterns for ATSes whose form structure we've verified our autofill
# handles reliably. Each pattern is a regex on the hostname (case-insensitive).
TRUSTED_ATS_PATTERNS: list[tuple[str, str]] = [
    ("Greenhouse", r"(?:boards|job-boards)\.greenhouse\.io$|^.+\.greenhouse\.io$"),
    ("Lever",      r"jobs\.lever\.co$"),
    ("Ashby",      r"jobs\.ashbyhq\.com$|^.+\.ashbyhq\.com$"),
    ("Workable",   r"apply\.workable\.com$|^.+\.workable\.com$"),
]

_COMPILED_PATTERNS = [(name, re.compile(rx, re.IGNORECASE))
                      for name, rx in TRUSTED_ATS_PATTERNS]


@dataclass
class FireEligibility:
    eligible: bool
    ats_name: str | None = None
    reason: str = ""

    @classmethod
    def yes(cls, ats_name: str) -> "FireEligibility":
        return cls(True, ats_name=ats_name, reason="")

    @classmethod
    def no(cls, reason: str) -> "FireEligibility":
        return cls(False, reason=reason)


def detect_ats(url: str) -> str | None:
    """Return the trusted-ATS name for this URL, or None if it doesn't match."""
    if not url:
        return None
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return None
    if not host:
        return None
    for name, pattern in _COMPILED_PATTERNS:
        if pattern.search(host):
            return name
    return None


def can_fire(job: queue_mod.QueuedJob) -> FireEligibility:
    """Run all guardrail checks on a single queued job."""
    if not job.source_url:
        return FireEligibility.no("Job has no source URL.")
    ats = detect_ats(job.source_url)
    if ats is None:
        return FireEligibility.no(
            "Listing is not on a trusted ATS (Greenhouse / Lever / Ashby / Workable). "
            "Fire mode is whitelist-only."
        )
    search = svc.get_search(job.saved_search_id)
    if search is None:
        return FireEligibility.no("Saved search no longer exists.")
    if not search.enabled:
        return FireEligibility.no("Saved search is paused.")
    if search.mode != svc.MODE_FIRE:
        return FireEligibility.no(
            "Saved search is in Queue mode. Switch to Fire mode in its settings to enable auto-submit."
        )
    cap = max(1, int(search.daily_cap or 1))
    used = count_today(search.id)
    if used >= cap:
        return FireEligibility.no(
            f"Daily auto-submit cap of {cap} already reached for this saved search ({used} fired today)."
        )
    return FireEligibility.yes(ats)


def count_today(saved_search_id: int) -> int:
    """How many auto_submitted rows for this saved search dated today (UTC)?"""
    today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = DB.query_one(
        "SELECT COUNT(*) AS n FROM job_queue "
        "WHERE saved_search_id = ? AND status = ? "
        "AND substr(coalesce(processed_at, ''), 1, 10) = ?",
        (saved_search_id, queue_mod.STATUS_AUTO_SUBMITTED, today_prefix),
    )
    return int(row["n"]) if row else 0


def mark_auto_submitted(job_id: int, *, ats_name: str) -> None:
    """Flip the queue row to auto_submitted, audit-log, and create an
    application row so the submission shows up in the pipeline."""
    row = DB.query_one(
        "SELECT * FROM job_queue WHERE id = ?", (job_id,),
    )
    if row is None:
        return
    DB.execute(
        "UPDATE job_queue SET status = ?, processed_at = CURRENT_TIMESTAMP, "
        "error_message = NULL WHERE id = ?",
        (queue_mod.STATUS_AUTO_SUBMITTED, job_id),
    )
    try:
        DB.execute(
            "INSERT INTO applications "
            "(company, role, source, listing_url, listing_text, autonomous_flag, fit_score) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (
                row["company"] or "(unknown)",
                row["role"] or "(unknown)",
                f"autonomous_fire:{ats_name.lower()}",
                row["source_url"],
                row["listing_text"],
                row["fit_score"],
            ),
        )
    except Exception as e:
        log.warning("Failed to create application row for fired job %s: %s", job_id, e)
    DB.log_audit("queue_job_auto_submitted", {
        "id": job_id,
        "ats": ats_name,
        "company": row["company"],
        "role": row["role"],
        "url": row["source_url"],
        "fit_score": row["fit_score"],
    })


def mark_fire_error(job_id: int, message: str) -> None:
    DB.execute(
        "UPDATE job_queue SET status = ?, processed_at = CURRENT_TIMESTAMP, "
        "error_message = ? WHERE id = ?",
        (queue_mod.STATUS_ERROR, message[:500], job_id),
    )
    DB.log_audit("queue_job_fire_failed", {"id": job_id, "message": message[:200]})
