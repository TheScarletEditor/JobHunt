"""Background polling for IMAP accounts on a user-configured interval."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from ..db import DB


DEFAULT_INTERVAL_MIN = 30


class _ScanWorker(QObject):
    done = Signal(dict)

    def __init__(self, account_ids: list[int]):
        super().__init__()
        self._ids = account_ids

    def run(self):
        from .scanner import scan_account
        from .classifier import classify_pending
        scans = [scan_account(aid) for aid in self._ids]
        classify = classify_pending(max_emails=50)
        self.done.emit({"scans": scans, "classify": classify})


class ScanScheduler(QObject):
    """Polls enabled IMAP accounts on the configured interval.
    Settings live in settings_kv: auto_scan_enabled ('0'/'1'),
    auto_scan_interval_min (int as str)."""

    scan_started = Signal()
    scan_completed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._thread: Optional[QThread] = None
        self._worker: Optional[_ScanWorker] = None

    def start(self):
        if not self.is_enabled():
            return
        interval_ms = self.interval_min() * 60 * 1000
        self._timer.start(interval_ms)

    def stop(self):
        self._timer.stop()

    def restart(self):
        self.stop()
        self.start()

    def is_enabled(self) -> bool:
        return DB.get_setting("auto_scan_enabled", "0") == "1"

    def interval_min(self) -> int:
        raw = DB.get_setting("auto_scan_interval_min", str(DEFAULT_INTERVAL_MIN))
        try:
            return max(1, int(raw or DEFAULT_INTERVAL_MIN))
        except (TypeError, ValueError):
            return DEFAULT_INTERVAL_MIN

    def is_running_now(self) -> bool:
        return bool(self._thread and self._thread.isRunning())

    def _tick(self):
        if self.is_running_now():
            return
        self._fire()

    def _fire(self):
        from .scanner import list_accounts
        accounts = list_accounts(enabled_only=True)
        if not accounts:
            return

        self.scan_started.emit()
        self._thread = QThread(self)
        self._worker = _ScanWorker([a["id"] for a in accounts])
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self.scan_completed.emit)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()


_INSTANCE: Optional[ScanScheduler] = None


def set_instance(scheduler: ScanScheduler):
    global _INSTANCE
    _INSTANCE = scheduler


def get_instance() -> Optional[ScanScheduler]:
    return _INSTANCE
