import sqlite3
import json
import threading
from contextlib import contextmanager
from typing import Any

from .. import config
from .schema import SCHEMA_SQL, SCHEMA_VERSION


class DBManager:
    def __init__(self, path=None):
        self.path = str(path or config.DB_PATH)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(SCHEMA_SQL)
            self._migrate()
            self._seed_defaults()
        return self._conn

    def _ensure_column(self, cur, table: str, column: str, definition: str):
        cur.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cur.fetchall()}
        if column not in existing:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _migrate(self):
        cur = self._conn.cursor()
        self._ensure_column(cur, "imap_accounts", "display_name", "TEXT")
        self._ensure_column(cur, "imap_accounts", "use_ssl", "INTEGER DEFAULT 1")
        self._ensure_column(cur, "imap_accounts", "last_uid", "INTEGER DEFAULT 0")
        self._ensure_column(cur, "imap_accounts", "last_scan_at", "TEXT")
        self._ensure_column(cur, "imap_accounts", "auth_type", "TEXT DEFAULT 'password'")
        self._ensure_column(cur, "imap_accounts", "oauth_access_token", "BLOB")
        self._ensure_column(cur, "imap_accounts", "oauth_refresh_token", "BLOB")
        self._ensure_column(cur, "imap_accounts", "oauth_expires_at", "TEXT")
        # Interviews — fields not in the v1 schema.
        self._ensure_column(cur, "interviews", "location", "TEXT")
        self._ensure_column(cur, "interviews", "meeting_url", "TEXT")
        self._ensure_column(cur, "interviews", "duration_minutes", "INTEGER DEFAULT 60")
        self._ensure_column(cur, "interviews", "created_at", "TEXT")
        self._ensure_column(cur, "interviews", "updated_at", "TEXT")
        self._ensure_column(cur, "interviews", "outlook_event_id", "TEXT")
        self._ensure_column(cur, "interview_attendees", "email", "TEXT")
        self._ensure_column(cur, "interview_attendees", "research_brief", "TEXT")
        # Demographics — voluntary self-disclosure used only for ATS auto-fill.
        self._ensure_column(cur, "profile", "pronouns", "TEXT")
        self._ensure_column(cur, "profile", "transgender_status", "TEXT")
        self._ensure_column(cur, "profile", "hispanic_latino", "TEXT")
        self._ensure_column(cur, "profile", "sexual_orientation", "TEXT")
        self._ensure_column(cur, "profile", "needs_sponsorship", "TEXT")
        self._ensure_column(cur, "profile", "date_of_birth", "TEXT")
        self._ensure_column(cur, "profile", "country_of_origin", "TEXT")
        # Phase 5 — Autonomous Apply
        self._ensure_column(cur, "saved_searches", "source_type", "TEXT DEFAULT 'company_ats'")
        self._ensure_column(cur, "saved_searches", "resume_type_id", "INTEGER")
        self._ensure_column(cur, "saved_searches", "last_run_at", "TEXT")
        self._ensure_column(cur, "saved_searches", "created_at", "TEXT")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS job_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                saved_search_id INTEGER NOT NULL,
                source_url TEXT NOT NULL,
                source_url_hash TEXT NOT NULL UNIQUE,
                company TEXT,
                role TEXT,
                location TEXT,
                posted_at TEXT,
                listing_text TEXT,
                fit_score INTEGER,
                fit_reason TEXT,
                status TEXT DEFAULT 'new',
                error_message TEXT,
                queued_at TEXT DEFAULT CURRENT_TIMESTAMP,
                processed_at TEXT,
                FOREIGN KEY (saved_search_id) REFERENCES saved_searches(id) ON DELETE CASCADE
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_job_queue_status ON job_queue(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_job_queue_search ON job_queue(saved_search_id)")
        # Clean out job-board shortcuts that were seeded with non-functional URLs.
        # These ATS sites (Greenhouse / Lever / Ashby / Workable) don't have aggregator
        # index pages; each company has its own subdomain. Removed from the seed list,
        # this clears any existing rows from earlier installs.
        for name in ("Ashby boards", "Greenhouse boards", "Lever boards", "Workable boards"):
            cur.execute("DELETE FROM settings_kv WHERE key = ?", (f"job_board:{name}",))
        cur.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
        self._conn.commit()

    @contextmanager
    def cursor(self):
        with self._lock:
            conn = self.connect()
            cur = conn.cursor()
            try:
                yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def execute(self, sql: str, params: tuple = ()) -> int:
        with self.cursor() as cur:
            cur.execute(sql, params)
            return cur.lastrowid or 0

    def _seed_defaults(self):
        cur = self._conn.cursor()
        cur.execute("SELECT version FROM schema_version")
        row = cur.fetchone()
        if row is None:
            cur.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))

        cur.execute("SELECT COUNT(*) FROM pipeline_stages")
        if cur.fetchone()[0] == 0:
            for name, order, color in config.DEFAULT_STAGES:
                cur.execute(
                    "INSERT INTO pipeline_stages (name, sort_order, color) VALUES (?, ?, ?)",
                    (name, order, color),
                )

        cur.execute("SELECT COUNT(*) FROM profile WHERE id = 1")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO profile (id) VALUES (1)")

        cur.execute("SELECT COUNT(*) FROM trusted_ats")
        if cur.fetchone()[0] == 0:
            for name, enabled in config.DEFAULT_TRUSTED_ATS:
                cur.execute(
                    "INSERT INTO trusted_ats (ats_name, enabled) VALUES (?, ?)",
                    (name, enabled),
                )

        self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.query_one("SELECT value FROM settings_kv WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        self.execute(
            "INSERT INTO settings_kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def log_audit(self, action_type: str, details: dict[str, Any] | None = None):
        self.execute(
            "INSERT INTO audit_log (action_type, details_json) VALUES (?, ?)",
            (action_type, json.dumps(details or {})),
        )


DB = DBManager()
