"""DB layer for saved searches.

Each saved search row:
  - name           : display name
  - source_type    : "company_ats" | "adzuna"
  - criteria_json  : source-specific config (see CRITERIA_SHAPES below)
  - resume_type_id : which resume to score against (uses latest version)
  - threshold      : 0-100, minimum fit score for a match to enter the queue
  - mode           : "queue" (review each) | "fire" (auto-submit, trusted ATS only)
  - schedule_cron  : "none" | "hourly" | "every_6h" | "daily"
  - daily_cap      : max auto-submits per day (Fire mode safety net)
  - enabled        : 0/1
  - last_run_at    : ISO ts of last scan completion
  - created_at     : ISO ts

CRITERIA shapes (stored as JSON in criteria_json):

  company_ats:
    {
      "companies": [
        {"ats": "greenhouse" | "lever" | "ashby" | "workable", "slug": "stripe"},
        ...
      ],
      "keywords": ["python", "backend"],              # required, any-match in title
      "location_keywords": ["remote", "us", "ny"]     # optional, any-match in location
    }

  adzuna:
    {
      "query": "backend engineer",
      "where": "us",
      "max_age_days": 7,
      "salary_min": 100000
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..db import DB


SOURCE_COMPANY_ATS = "company_ats"
SOURCE_ADZUNA = "adzuna"

MODE_QUEUE = "queue"
MODE_FIRE = "fire"

SCHEDULE_OPTIONS = [
    ("none",     "Manual only"),
    ("hourly",   "Every hour"),
    ("every_6h", "Every 6 hours"),
    ("daily",    "Once a day"),
]

ATS_KINDS = ["greenhouse", "lever", "ashby", "workable"]


@dataclass
class SavedSearch:
    id: int | None = None
    name: str = ""
    source_type: str = SOURCE_COMPANY_ATS
    criteria: dict[str, Any] = field(default_factory=dict)
    resume_type_id: int | None = None
    threshold: int = 70
    mode: str = MODE_QUEUE
    schedule_cron: str = "daily"
    daily_cap: int = 15
    enabled: bool = True
    last_run_at: str | None = None
    created_at: str | None = None

    @classmethod
    def from_row(cls, row) -> "SavedSearch":
        try:
            criteria = json.loads(row["criteria_json"] or "{}")
        except Exception:
            criteria = {}
        if not isinstance(criteria, dict):
            criteria = {}
        return cls(
            id=row["id"],
            name=row["name"] or "",
            source_type=row["source_type"] or SOURCE_COMPANY_ATS,
            criteria=criteria,
            resume_type_id=row["resume_type_id"],
            threshold=int(row["threshold"] or 70),
            mode=row["mode"] or MODE_QUEUE,
            schedule_cron=row["schedule_cron"] or "daily",
            daily_cap=int(row["daily_cap"] or 15),
            enabled=bool(row["enabled"]),
            last_run_at=row["last_run_at"],
            created_at=row["created_at"],
        )


def list_searches() -> list[SavedSearch]:
    rows = DB.query("SELECT * FROM saved_searches ORDER BY created_at DESC, id DESC")
    return [SavedSearch.from_row(r) for r in rows]


def get_search(search_id: int) -> SavedSearch | None:
    row = DB.query_one("SELECT * FROM saved_searches WHERE id = ?", (search_id,))
    return SavedSearch.from_row(row) if row else None


def create_search(search: SavedSearch) -> int:
    new_id = DB.execute(
        """
        INSERT INTO saved_searches
            (name, source_type, criteria_json, resume_type_id, threshold,
             mode, schedule_cron, daily_cap, enabled, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            search.name.strip(),
            search.source_type,
            json.dumps(search.criteria, ensure_ascii=False),
            search.resume_type_id,
            int(search.threshold),
            search.mode,
            search.schedule_cron,
            int(search.daily_cap),
            1 if search.enabled else 0,
        ),
    )
    DB.log_audit("saved_search_created", {"id": new_id, "name": search.name})
    return new_id


def update_search(search: SavedSearch) -> None:
    if search.id is None:
        raise ValueError("update_search requires a saved id")
    DB.execute(
        """
        UPDATE saved_searches
           SET name = ?, source_type = ?, criteria_json = ?, resume_type_id = ?,
               threshold = ?, mode = ?, schedule_cron = ?, daily_cap = ?, enabled = ?
         WHERE id = ?
        """,
        (
            search.name.strip(),
            search.source_type,
            json.dumps(search.criteria, ensure_ascii=False),
            search.resume_type_id,
            int(search.threshold),
            search.mode,
            search.schedule_cron,
            int(search.daily_cap),
            1 if search.enabled else 0,
            search.id,
        ),
    )
    DB.log_audit("saved_search_updated", {"id": search.id, "name": search.name})


def delete_search(search_id: int) -> None:
    DB.execute("DELETE FROM saved_searches WHERE id = ?", (search_id,))
    DB.log_audit("saved_search_deleted", {"id": search_id})


def queue_count(search_id: int) -> int:
    row = DB.query_one(
        "SELECT COUNT(*) AS n FROM job_queue WHERE saved_search_id = ? AND status = 'new'",
        (search_id,),
    )
    return int(row["n"]) if row else 0
