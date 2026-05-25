"""JSON-backup restore engine — full-replace semantics.

The companion to `_BackupTab._export` in `jobhunt/ui/pages/settings.py`:
that function dumps every table to a JSON file. This module loads such a
file back into a fresh database.

Safety contract:
  1. Before touching anything, copy the live `jobhunt.db` to a sibling
     `jobhunt.db.pre-restore-<timestamp>.bak`. If the restore explodes
     halfway, the user has a path back.
  2. Validate the JSON has at least the canonical core tables before
     committing — a typo'd file or a totally unrelated JSON won't wipe
     real data.
  3. Use a single transaction with FK enforcement off. Restored rows
     are inserted exactly as exported (including IDs) so references
     between tables (e.g. application -> resume_version) stay intact
     without re-mapping.
  4. Columns present in the backup but missing in the current schema are
     dropped silently — happens when restoring an older backup to a newer
     build. Columns added in newer schema versions stay NULL in restored
     rows; the schema migration runs after the load to backfill defaults.

Caller is expected to close the DB connection before invoking restore,
and re-establish it afterwards (or restart the app — easier).
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)


# Tables that MUST be present in a valid backup. If the JSON we're handed
# doesn't have all of these, we refuse to overwrite the live DB. These are
# the ones every install has — anything else is optional.
_REQUIRED_TABLES = {"profile", "pipeline_stages", "schema_version"}


class RestoreError(Exception):
    """Validation / IO failure during restore. Live DB is untouched."""


def _unwrap_value(v: Any) -> Any:
    """Reverse the `{"__bytes__": "<hex>"}` envelope written by export."""
    if isinstance(v, dict) and "__bytes__" in v and len(v) == 1:
        try:
            return bytes.fromhex(v["__bytes__"])
        except ValueError:
            log.warning("Malformed __bytes__ envelope; treating as None.")
            return None
    return v


def _summarize(snapshot: dict[str, list[dict]]) -> dict[str, int]:
    """Produce {table: row_count} for the preview dialog."""
    return {t: len(rows) for t, rows in snapshot.items() if isinstance(rows, list)}


def load_and_validate(path: str | Path) -> tuple[dict[str, list[dict]], dict[str, int]]:
    """Parse + sanity-check a backup file. Returns (snapshot, summary).
    Raises RestoreError on any problem. Does NOT touch the live DB."""
    p = Path(path)
    if not p.exists():
        raise RestoreError(f"File not found: {p}")
    try:
        with open(p, encoding="utf-8") as f:
            snapshot = json.load(f)
    except json.JSONDecodeError as e:
        raise RestoreError(f"Not a valid JSON file: {e}") from e
    if not isinstance(snapshot, dict):
        raise RestoreError("Top-level JSON must be an object mapping table names to row lists.")

    missing = _REQUIRED_TABLES - set(snapshot.keys())
    if missing:
        raise RestoreError(
            f"This doesn't look like a JobHunt backup — missing required tables: "
            f"{', '.join(sorted(missing))}"
        )
    for t, rows in snapshot.items():
        if not isinstance(rows, list):
            raise RestoreError(f"Table {t!r}: rows must be a JSON array, got {type(rows).__name__}.")
    return snapshot, _summarize(snapshot)


def _make_pre_restore_backup(db_path: Path) -> Path:
    """Copy the live DB next to itself with a timestamp suffix.
    Returns the path of the .bak file."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = db_path.with_suffix(db_path.suffix + f".pre-restore-{stamp}.bak")
    shutil.copy2(db_path, bak)
    log.info("Pre-restore safety copy: %s", bak)
    return bak


def _restore_into(conn: sqlite3.Connection, snapshot: dict[str, list[dict]]) -> dict[str, int]:
    """Inside a single transaction with FK off, replace every table's
    contents with the rows from the snapshot. Returns {table: inserted}."""
    cur = conn.cursor()
    inserted: dict[str, int] = {}

    # Discover the live schema once so we can drop unknown columns gracefully.
    live_tables = {
        r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    live_columns: dict[str, set[str]] = {}
    for t in live_tables:
        cur.execute(f"PRAGMA table_info({t})")
        live_columns[t] = {row[1] for row in cur.fetchall()}

    cur.execute("PRAGMA foreign_keys = OFF")
    try:
        # First wipe everything in the live schema — any table that the
        # current build knows about. Backup is the only source of truth now.
        for t in live_tables:
            cur.execute(f"DELETE FROM {t}")

        # Then load rows from backup, skipping tables/columns the current
        # schema doesn't have. Iterating in a stable order makes the audit
        # entry deterministic.
        for table in sorted(snapshot.keys()):
            rows = snapshot[table]
            if table not in live_tables:
                log.info("Skipping table %r — not in current schema.", table)
                continue
            cols_in_schema = live_columns[table]
            n = 0
            for row in rows:
                # Restrict to columns the current schema accepts.
                filtered = {k: _unwrap_value(v) for k, v in row.items() if k in cols_in_schema}
                if not filtered:
                    continue
                placeholders = ",".join("?" * len(filtered))
                col_list = ",".join(filtered.keys())
                cur.execute(
                    f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",
                    tuple(filtered.values()),
                )
                n += 1
            inserted[table] = n
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.execute("PRAGMA foreign_keys = ON")
    return inserted


def restore_from_file(db_path: str | Path, backup_json_path: str | Path) -> dict[str, Any]:
    """Top-level restore entry point.

    Caller must ensure no other thread holds the DB open. Returns a result
    dict with `pre_restore_backup` (path to the .bak we made) and `inserted`
    (per-table counts) on success. Raises RestoreError on validation or
    SQL failure — in either case the live DB is restored from .bak before
    raising, so the user is never left half-loaded."""
    db_path = Path(db_path)
    snapshot, _summary = load_and_validate(backup_json_path)

    bak = _make_pre_restore_backup(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        inserted = _restore_into(conn, snapshot)
    except Exception as e:
        log.exception("Restore failed mid-transaction; reverting from %s", bak)
        conn.close()
        # The transaction rolled back inside _restore_into, but we copy the
        # .bak over anyway as belt-and-suspenders. SQLite write-ahead log
        # quirks have bitten us before.
        shutil.copy2(bak, db_path)
        raise RestoreError(f"Restore failed; reverted to pre-restore state. ({e})") from e
    finally:
        conn.close()

    return {
        "pre_restore_backup": str(bak),
        "inserted": inserted,
        "total_rows": sum(inserted.values()),
    }
