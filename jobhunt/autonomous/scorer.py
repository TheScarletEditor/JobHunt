"""Fit-score every 'new' job in the queue against its saved-search's resume.

After scanning, the queue is full of `status='new'` rows. The scorer:
  1. Loads the saved-search's resume_type (latest version) — or the user's
     default if the search has no resume linked.
  2. For each new row, calls the LLM `score_fit(resume, listing_text)`.
  3. If score < threshold → status='filtered'.
  4. Else → status='queued' with fit_score + fit_reason saved.

Each row is committed individually so a mid-run cancel/crash doesn't waste
already-scored items.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..db import DB
from ..documents import versions as ver
from ..documents.model import ResumeContent
from ..llm import get_provider
from .searches import SavedSearch


log = logging.getLogger(__name__)


@dataclass
class ScoreResult:
    scored: int = 0
    queued: int = 0
    filtered: int = 0
    errors: int = 0
    skipped_no_resume: int = 0

    def summary(self) -> str:
        bits = [f"scored {self.scored}"]
        if self.queued:
            bits.append(f"{self.queued} above threshold")
        if self.filtered:
            bits.append(f"{self.filtered} below threshold")
        if self.errors:
            bits.append(f"{self.errors} errors")
        if self.skipped_no_resume:
            bits.append(f"{self.skipped_no_resume} skipped (no resume)")
        return " · ".join(bits)


def score_pending(
    search: SavedSearch,
    *,
    progress_cb=None,
    cancel_cb=None,
) -> ScoreResult:
    """Score every job_queue row for `search` with status='new'.
    `progress_cb(done, total)` is called after each row so the UI can update.
    `cancel_cb()` returns True if the operation should abort early."""
    result = ScoreResult()
    if search.id is None:
        return result

    resume = _load_resume_for_search(search)
    if resume is None:
        # Mark all pending rows as filtered with a reason, so they don't pile up.
        DB.execute(
            "UPDATE job_queue SET status='filtered', "
            "error_message='No resume linked to saved search' "
            "WHERE saved_search_id = ? AND status = 'new'",
            (search.id,),
        )
        rows = DB.query(
            "SELECT COUNT(*) AS n FROM job_queue WHERE saved_search_id = ?",
            (search.id,),
        )
        result.skipped_no_resume = int(rows[0]["n"]) if rows else 0
        return result

    provider = get_provider()
    pending = DB.query(
        "SELECT id, listing_text, role, company FROM job_queue "
        "WHERE saved_search_id = ? AND status = 'new' "
        "ORDER BY id",
        (search.id,),
    )
    total = len(pending)
    for i, row in enumerate(pending):
        if cancel_cb and cancel_cb():
            log.info("Scoring cancelled at %d/%d for search %s", i, total, search.id)
            break

        try:
            score, reason = provider.score_fit(resume, row["listing_text"] or "")
        except Exception as e:
            log.warning("score_fit failed for queue row %s: %s", row["id"], e)
            DB.execute(
                "UPDATE job_queue SET status='error', error_message=?, "
                "processed_at=CURRENT_TIMESTAMP WHERE id = ?",
                (f"{type(e).__name__}: {e}", row["id"]),
            )
            result.errors += 1
            if progress_cb:
                progress_cb(i + 1, total)
            continue

        new_status = "queued" if score >= search.threshold else "filtered"
        DB.execute(
            "UPDATE job_queue SET fit_score=?, fit_reason=?, status=?, "
            "processed_at=CURRENT_TIMESTAMP WHERE id = ?",
            (int(score), reason, new_status, row["id"]),
        )
        result.scored += 1
        if new_status == "queued":
            result.queued += 1
        else:
            result.filtered += 1

        if progress_cb:
            progress_cb(i + 1, total)

    DB.log_audit("saved_search_scored", {
        "id": search.id,
        "scored": result.scored,
        "queued": result.queued,
        "filtered": result.filtered,
        "errors": result.errors,
    })
    return result


def _load_resume_for_search(search: SavedSearch) -> ResumeContent | None:
    """Return the latest version of the search's linked resume_type, or any
    resume's latest version if the search isn't linked to one."""
    type_id = search.resume_type_id
    if type_id is None:
        row = DB.query_one(
            "SELECT t.id FROM resume_types t "
            "JOIN resume_versions v ON v.resume_type_id = t.id "
            "GROUP BY t.id ORDER BY MAX(v.created_at) DESC LIMIT 1"
        )
        if not row:
            return None
        type_id = row["id"]
    versions = ver.list_versions(type_id)
    if not versions:
        return None
    latest_id = versions[0]["id"]  # list_versions returns DESC by version_number
    loaded = ver.get_version(latest_id)
    if not loaded:
        return None
    content, _meta = loaded
    return content
