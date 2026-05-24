"""Background scheduler for saved-search scans.

Mirrors jobhunt/mail/scheduler.py — a QObject with a QTimer that ticks once a
minute, walks every enabled saved search, and triggers a scan + scoring run
for any whose schedule_cron interval has elapsed since last_run_at.

One scan/score runs at a time globally to keep LLM cost predictable and to
avoid the SQLite write contention you'd hit running concurrent ingests.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from ..db import DB
from . import searches as svc
from . import scanner as scanner_mod
from . import scorer as scorer_mod


log = logging.getLogger(__name__)

# How often we check whether any search is due. 60s gives 1-minute granularity
# which is fine for hourly/6h/daily cadences.
TICK_INTERVAL_MS = 60_000

_INTERVAL_BY_CRON: dict[str, timedelta | None] = {
    "none":     None,
    "hourly":   timedelta(hours=1),
    "every_6h": timedelta(hours=6),
    "daily":    timedelta(days=1),
}


class AutonomousScheduler(QObject):
    """Periodically runs due saved-search scans + scoring in the background."""

    scan_started = Signal(int, str)        # (search_id, search_name)
    scan_progress = Signal(int, str)       # (search_id, status_message)
    scan_finished = Signal(int, dict)      # (search_id, summary_dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._active_thread: QThread | None = None
        self._active_worker: _Worker | None = None
        self._enabled = True

    def start(self):
        # Run a first check shortly after launch so the first due-search doesn't
        # have to wait a full minute.
        QTimer.singleShot(5_000, self._tick)
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)

    # ------------------------------------------------------------------ tick

    def _tick(self):
        if not self._enabled or self._active_thread is not None:
            return
        due = _find_due_search()
        if due is None:
            return
        self._run_search(due)

    def _run_search(self, search: svc.SavedSearch):
        self.scan_started.emit(search.id, search.name)
        self._active_thread = QThread(self)
        self._active_worker = _Worker(search)
        self._active_worker.moveToThread(self._active_thread)
        self._active_thread.started.connect(self._active_worker.run)
        self._active_worker.progress.connect(
            lambda msg, sid=search.id: self.scan_progress.emit(sid, msg)
        )
        self._active_worker.finished.connect(self._on_worker_finished)
        self._active_worker.finished.connect(self._active_thread.quit)
        self._active_thread.finished.connect(self._active_thread.deleteLater)
        self._active_thread.start()

    def _on_worker_finished(self, search_id: int, summary: dict):
        self._active_thread = None
        self._active_worker = None
        self.scan_finished.emit(search_id, summary)


class _Worker(QObject):
    progress = Signal(str)
    finished = Signal(int, dict)

    def __init__(self, search: svc.SavedSearch):
        super().__init__()
        self._search = search

    def run(self):
        scan_result = scanner_mod.scan(self._search)
        summary = {
            "search_id": self._search.id,
            "search_name": self._search.name,
            "scan": scan_result.summary(),
            "scan_errors": list(scan_result.errors),
            "scored": 0,
            "queued": 0,
        }
        if scan_result.new_count > 0:
            self.progress.emit(
                f"Scoring {scan_result.new_count} new listing(s) "
                f"for '{self._search.name}'…"
            )
            score_result = scorer_mod.score_pending(self._search)
            summary["scored"] = score_result.scored
            summary["queued"] = score_result.queued
            summary["score_summary"] = score_result.summary()
        self.finished.emit(self._search.id, summary)


# ============================================================================
# Due-search resolution
# ============================================================================


def _find_due_search() -> svc.SavedSearch | None:
    """Return the saved search that's been waiting the longest past its
    schedule, or None if nothing is due."""
    candidates: list[tuple[float, svc.SavedSearch]] = []
    now = datetime.now(timezone.utc)
    for search in svc.list_searches():
        if not search.enabled or search.id is None:
            continue
        interval = _INTERVAL_BY_CRON.get(search.schedule_cron)
        if interval is None:
            continue
        last_run = _parse_iso(search.last_run_at)
        if last_run is None:
            # Never run before — fire immediately.
            overdue_s = interval.total_seconds()
        else:
            elapsed = (now - last_run).total_seconds()
            overdue_s = elapsed - interval.total_seconds()
        if overdue_s >= 0:
            candidates.append((overdue_s, search))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


def _parse_iso(text: str | None) -> datetime | None:
    if not text:
        return None
    # SQLite CURRENT_TIMESTAMP gives "YYYY-MM-DD HH:MM:SS" with no tz; treat as UTC.
    try:
        clean = text.replace("T", " ").rstrip("Z").strip()
        return datetime.strptime(clean[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (ValueError, IndexError):
        return None
