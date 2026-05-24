"""Runs a saved search end-to-end: fetch → filter → dedupe → queue.

Fit scoring (scorer.py) and auto-submit (fire.py + browser fire flow) both
consume what this writes into the job_queue table.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass

from ..db import DB
from .searches import SavedSearch, SOURCE_COMPANY_ATS, SOURCE_ADZUNA
from .sources import (
    JobListing, fetch_company_ats, fetch_adzuna, matches_criteria, SourceError,
)


log = logging.getLogger(__name__)


@dataclass
class ScanResult:
    new_count: int = 0
    duplicate_count: int = 0
    filtered_out_count: int = 0
    errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    @property
    def total_fetched(self) -> int:
        return self.new_count + self.duplicate_count + self.filtered_out_count

    def summary(self) -> str:
        bits = [f"{self.new_count} new"]
        if self.duplicate_count:
            bits.append(f"{self.duplicate_count} already seen")
        if self.filtered_out_count:
            bits.append(f"{self.filtered_out_count} filtered out")
        if self.errors:
            bits.append(f"{len(self.errors)} source error(s)")
        return " · ".join(bits)


def scan(search: SavedSearch, *, cancel_cb=None) -> ScanResult:
    """Fetch jobs for `search`, drop duplicates, drop non-matching, insert the
    rest into job_queue with status='new'. Update last_run_at regardless.

    `cancel_cb()` returns True if the scan should stop early. Partial results
    are kept (we commit each row individually)."""
    if search.id is None:
        raise ValueError("Saved search has no id — save before scanning")

    result = ScanResult()
    cancelled = False

    def _cancelled() -> bool:
        return bool(cancel_cb and cancel_cb())

    try:
        if search.source_type == SOURCE_COMPANY_ATS:
            iterator = fetch_company_ats(search.criteria)
            for job, error in iterator:
                if _cancelled():
                    cancelled = True
                    break
                if error:
                    result.errors.append(error)
                    continue
                if job is None:
                    continue
                _ingest_one(search.id, job, search.criteria,
                            apply_local_filter=True, result=result)
        elif search.source_type == SOURCE_ADZUNA:
            for job in fetch_adzuna(search.criteria):
                if _cancelled():
                    cancelled = True
                    break
                _ingest_one(search.id, job, search.criteria,
                            apply_local_filter=False, result=result)
        else:
            result.errors.append(f"Unknown source type: {search.source_type!r}")
    except SourceError as e:
        result.errors.append(str(e))
    except Exception as e:
        log.exception("Scan failed for search %s", search.id)
        result.errors.append(f"{type(e).__name__}: {e}")

    if cancelled:
        result.errors.append("Cancelled by user — partial results kept.")

    DB.execute(
        "UPDATE saved_searches SET last_run_at = CURRENT_TIMESTAMP WHERE id = ?",
        (search.id,),
    )
    DB.log_audit("saved_search_scanned", {
        "id": search.id,
        "new": result.new_count,
        "duplicates": result.duplicate_count,
        "filtered": result.filtered_out_count,
        "errors": len(result.errors),
    })
    return result


def _ingest_one(search_id: int, job: JobListing, criteria: dict,
                *, apply_local_filter: bool, result: ScanResult) -> None:
    if not job.source_url:
        # Can't dedupe without a URL — skip rather than queue an unrunnable item.
        result.filtered_out_count += 1
        return
    if apply_local_filter and not matches_criteria(job, criteria):
        result.filtered_out_count += 1
        return
    if _try_insert_queue(search_id, job):
        result.new_count += 1
    else:
        result.duplicate_count += 1


def _try_insert_queue(search_id: int, job: JobListing) -> bool:
    """Insert into job_queue. Returns True on insert, False on dedupe collision."""
    url_hash = hashlib.sha256(job.source_url.encode("utf-8")).hexdigest()
    try:
        DB.execute(
            """
            INSERT INTO job_queue
                (saved_search_id, source_url, source_url_hash, company, role,
                 location, posted_at, listing_text, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new')
            """,
            (
                search_id,
                job.source_url,
                url_hash,
                job.company,
                job.role,
                job.location,
                job.posted_at,
                job.listing_text,
            ),
        )
        return True
    except sqlite3.IntegrityError:
        # Unique constraint on source_url_hash means this URL is already queued.
        return False
