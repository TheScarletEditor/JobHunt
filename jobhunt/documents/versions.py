from __future__ import annotations

import json
from typing import Optional

from ..db import DB
from .model import ResumeContent


MAX_VERSIONS_PER_TYPE = 5


def list_resume_types() -> list[dict]:
    return [dict(r) for r in DB.query("SELECT id, name FROM resume_types ORDER BY name")]


def create_resume_type(name: str) -> int:
    return DB.execute("INSERT INTO resume_types (name) VALUES (?)", (name,))


def get_or_create_resume_type(name: str) -> int:
    row = DB.query_one("SELECT id FROM resume_types WHERE name = ?", (name,))
    if row:
        return row["id"]
    return create_resume_type(name)


def rename_resume_type(type_id: int, new_name: str):
    DB.execute("UPDATE resume_types SET name = ? WHERE id = ?", (new_name, type_id))


def delete_resume_type(type_id: int):
    DB.execute("DELETE FROM resume_types WHERE id = ?", (type_id,))


def list_versions(resume_type_id: int) -> list[dict]:
    rows = DB.query(
        """SELECT id, version_number, label, source_format, created_at
           FROM resume_versions
           WHERE resume_type_id = ?
           ORDER BY version_number DESC""",
        (resume_type_id,),
    )
    return [dict(r) for r in rows]


def get_version(version_id: int) -> Optional[tuple[ResumeContent, dict]]:
    row = DB.query_one(
        """SELECT id, resume_type_id, version_number, label, content_json,
                  source_format, created_at
           FROM resume_versions WHERE id = ?""",
        (version_id,),
    )
    if not row:
        return None
    content = ResumeContent.from_json(row["content_json"]) if row["content_json"] else ResumeContent()
    return content, dict(row)


def save_version(
    resume_type_id: int,
    content: ResumeContent,
    label: Optional[str] = None,
    source_format: str = "manual",
) -> int:
    max_row = DB.query_one(
        "SELECT COALESCE(MAX(version_number), 0) AS v FROM resume_versions WHERE resume_type_id = ?",
        (resume_type_id,),
    )
    next_version = int(max_row["v"]) + 1 if max_row else 1

    new_id = DB.execute(
        """INSERT INTO resume_versions
           (resume_type_id, version_number, label, content_json, source_format)
           VALUES (?, ?, ?, ?, ?)""",
        (resume_type_id, next_version, label, content.to_json(), source_format),
    )
    prune(resume_type_id)
    DB.log_audit("resume_version_saved", {"resume_type_id": resume_type_id, "version_id": new_id})
    return new_id


def prune(resume_type_id: int, keep: int = MAX_VERSIONS_PER_TYPE):
    keep_ids_rows = DB.query(
        """SELECT id FROM resume_versions
           WHERE resume_type_id = ?
           ORDER BY version_number DESC
           LIMIT ?""",
        (resume_type_id, keep),
    )
    keep_ids = {r["id"] for r in keep_ids_rows}
    if not keep_ids:
        return
    placeholders = ",".join("?" * len(keep_ids))
    DB.execute(
        f"DELETE FROM resume_versions WHERE resume_type_id = ? AND id NOT IN ({placeholders})",
        (resume_type_id, *keep_ids),
    )


def delete_version(version_id: int):
    DB.execute("DELETE FROM resume_versions WHERE id = ?", (version_id,))
