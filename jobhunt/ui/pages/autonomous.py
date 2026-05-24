"""Autonomous Apply page — saved searches + scored job queue.

Each scan runs in the background; when it finishes, the scorer kicks off
automatically to fit-score the new rows against the search's resume. The
Queue tab shows the resulting matches; clicking 🔥 Fire on an eligible match
hands off to the embedded browser for auto-fill + auto-submit.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QObject, QThread, Signal, QUrl
from PySide6.QtGui import QFont, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QMessageBox, QSizePolicy, QTabWidget, QComboBox,
)

from ... import config
from ...autonomous import searches as svc
from ...autonomous.searches import (
    SOURCE_COMPANY_ATS, SOURCE_ADZUNA, MODE_QUEUE, MODE_FIRE, SCHEDULE_OPTIONS,
)
from ...autonomous import queue as queue_mod
from ...autonomous import fire as fire_mod
from ...db import DB
from ..dialogs.saved_search import SavedSearchDialog


_SCHEDULE_LABELS = dict(SCHEDULE_OPTIONS)


# ============================================================================
# Background workers
# ============================================================================


class _ScanWorker(QObject):
    done = Signal(int, object)  # (search_id, ScanResult)

    def __init__(self, search: svc.SavedSearch):
        super().__init__()
        self._search = search
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        from ...autonomous import scanner as sc
        result = sc.scan(self._search, cancel_cb=lambda: self._cancel)
        self.done.emit(self._search.id, result)


class _ScoreWorker(QObject):
    progress = Signal(int, int)  # (done, total)
    done = Signal(int, object)   # (search_id, ScoreResult)

    def __init__(self, search: svc.SavedSearch):
        super().__init__()
        self._search = search
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        from ...autonomous import scorer as sc
        result = sc.score_pending(
            self._search,
            progress_cb=lambda d, t: self.progress.emit(d, t),
            cancel_cb=lambda: self._cancel,
        )
        self.done.emit(self._search.id, result)


# ============================================================================
# Helpers
# ============================================================================


def _styled_text_label(text: str, *, color: str, point: int, bold: bool) -> QLabel:
    lbl = QLabel(text)
    f = QFont("Segoe UI", point); f.setBold(bold)
    lbl.setFont(f)
    lbl.setStyleSheet(
        f"QLabel {{ color: {color}; background-color: transparent; padding: 0; margin: 0; }}"
    )
    return lbl


def _score_badge_color(score: int | None) -> str:
    if score is None:
        return config.COLOR_TEXT_FAINT
    if score >= 85:
        return "#43a047"   # green
    if score >= 70:
        return "#1e88e5"   # blue
    if score >= 50:
        return "#fb8c00"   # orange
    return config.COLOR_TEXT_FAINT


# ============================================================================
# Saved search card
# ============================================================================


class _SearchCard(QFrame):
    def __init__(self, search: svc.SavedSearch, queue_count: int, new_count: int,
                 on_edit, on_delete, on_run_now, parent=None):
        super().__init__(parent)
        self.search = search

        self.setObjectName("Card")
        self.setStyleSheet(
            f"#Card {{ background: {config.COLOR_BG_RAISED}; border-radius: 10px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(10)
        name = _styled_text_label(search.name or "(untitled)",
                                  color=config.COLOR_TEXT, point=14, bold=True)
        top.addWidget(name)
        top.addStretch(1)

        mode_badge = QLabel("FIRE" if search.mode == MODE_FIRE else "QUEUE")
        mode_color = config.COLOR_ACCENT if search.mode == MODE_FIRE else config.COLOR_TEXT_DIM
        mode_badge.setStyleSheet(
            f"QLabel {{ color: white; background: {mode_color}; "
            f"padding: 3px 10px; border-radius: 10px; font-size: 10px; font-weight: 700; }}"
        )
        top.addWidget(mode_badge)

        state_badge = QLabel("● enabled" if search.enabled else "○ paused")
        state_color = "#5fa83a" if search.enabled else config.COLOR_TEXT_FAINT
        state_badge.setStyleSheet(f"color: {state_color}; font-size: 11px;")
        top.addWidget(state_badge)
        layout.addLayout(top)

        source_label = (
            "Company ATS boards" if search.source_type == SOURCE_COMPANY_ATS
            else "Adzuna keyword search"
        )
        schedule_label = _SCHEDULE_LABELS.get(search.schedule_cron, search.schedule_cron)
        meta_bits = [
            f"<b>Source:</b> {source_label}",
            f"<b>Schedule:</b> {schedule_label}",
            f"<b>Min fit:</b> {search.threshold}",
        ]
        if queue_count > 0:
            meta_bits.append(f"<b style='color:{config.COLOR_ACCENT}'>"
                             f"{queue_count} in queue</b>")
        if new_count > 0:
            meta_bits.append(f"<span style='color:{config.COLOR_TEXT_DIM}'>"
                             f"{new_count} unscored</span>")
        meta = QLabel(" &nbsp; · &nbsp; ".join(meta_bits))
        meta.setTextFormat(Qt.RichText)
        meta.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 12px;")
        layout.addWidget(meta)

        if search.source_type == SOURCE_COMPANY_ATS:
            companies = search.criteria.get("companies") or []
            kws = search.criteria.get("keywords") or []
            preview = (
                f"<b>{len(companies)}</b> compan{'y' if len(companies) == 1 else 'ies'} · "
                f"keywords: {', '.join(kws) if kws else '(none)'}"
            )
        else:
            q = search.criteria.get("query") or "(no query)"
            where = (search.criteria.get("where") or "").upper()
            preview = f"Query: <b>{q}</b> · {where}"
        prev = QLabel(preview)
        prev.setTextFormat(Qt.RichText)
        prev.setWordWrap(True)
        prev.setStyleSheet(f"color: {config.COLOR_TEXT}; font-size: 12px;")
        layout.addWidget(prev)

        if search.last_run_at:
            ran = QLabel(f"Last run: {search.last_run_at[:16]}")
            ran.setStyleSheet(f"color: {config.COLOR_TEXT_FAINT}; font-size: 11px;")
            layout.addWidget(ran)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.run_btn = QPushButton("Run scan now")
        self.run_btn.setToolTip("Fetch jobs from this search's source, score them, queue the strong matches.")
        self.run_btn.clicked.connect(lambda: on_run_now(search))
        btn_row.addWidget(self.run_btn)
        btn_row.addStretch(1)
        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(lambda: on_edit(search))
        btn_row.addWidget(edit_btn)
        del_btn = QPushButton("Delete")
        del_btn.setStyleSheet(
            f"QPushButton {{ color: {config.COLOR_ACCENT}; border: 1px solid "
            f"{config.COLOR_BORDER_LIGHT}; padding: 6px 12px; border-radius: 4px; "
            f"background: transparent; }}"
            f"QPushButton:hover {{ background: {config.COLOR_ACCENT_SOFT}; }}"
        )
        del_btn.clicked.connect(lambda: on_delete(search))
        btn_row.addWidget(del_btn)
        layout.addLayout(btn_row)


# ============================================================================
# Queue card
# ============================================================================


class _QueueCard(QFrame):
    def __init__(self, job: queue_mod.QueuedJob, search_name: str,
                 on_apply, on_skip, on_open, on_delete, on_fire, parent=None):
        super().__init__(parent)
        self.job = job

        self.setObjectName("Card")
        self.setStyleSheet(
            f"#Card {{ background: {config.COLOR_BG_RAISED}; border-radius: 10px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(12)

        # Score badge
        score_text = f"{job.fit_score}" if job.fit_score is not None else "—"
        score_badge = QLabel(score_text)
        score_color = _score_badge_color(job.fit_score)
        score_badge.setStyleSheet(
            f"QLabel {{ color: white; background: {score_color}; "
            f"padding: 6px 12px; border-radius: 14px; font-size: 14px; "
            f"font-weight: 700; min-width: 32px; qproperty-alignment: AlignCenter; }}"
        )
        score_badge.setFixedHeight(32)
        top.addWidget(score_badge)

        # Title block
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        role_lbl = _styled_text_label(job.role or "(no role)",
                                      color=config.COLOR_TEXT, point=13, bold=True)
        title_box.addWidget(role_lbl)
        company_bits: list[str] = []
        if job.company:
            company_bits.append(job.company)
        if job.location:
            company_bits.append(job.location)
        if job.posted_at:
            company_bits.append(job.posted_at[:10])
        sub_lbl = QLabel(" · ".join(company_bits) or "(no metadata)")
        sub_lbl.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 12px;")
        title_box.addWidget(sub_lbl)
        title_wrap = QWidget()
        title_wrap.setLayout(title_box)
        title_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top.addWidget(title_wrap, 1)

        source_chip = QLabel(search_name)
        source_chip.setStyleSheet(
            f"QLabel {{ color: {config.COLOR_TEXT_DIM}; background: {config.COLOR_BG_HOVER}; "
            f"padding: 3px 10px; border-radius: 10px; font-size: 11px; }}"
        )
        top.addWidget(source_chip)
        layout.addLayout(top)

        if job.fit_reason:
            reason = QLabel(job.fit_reason)
            reason.setWordWrap(True)
            reason.setStyleSheet(
                f"QLabel {{ color: {config.COLOR_TEXT}; font-style: italic; "
                f"padding: 6px 10px; background: {config.COLOR_BG_HOVER}; border-radius: 4px; "
                f"border-left: 2px solid {_score_badge_color(job.fit_score)}; }}"
            )
            layout.addWidget(reason)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        open_btn = QPushButton("Open in browser")
        open_btn.clicked.connect(lambda: on_open(job))
        btn_row.addWidget(open_btn)

        eligibility = fire_mod.can_fire(job)
        fire_btn = QPushButton("🔥 Fire it")
        if eligibility.eligible:
            fire_btn.setStyleSheet(
                f"QPushButton {{ background: {config.COLOR_ACCENT}; color: white; "
                f"padding: 6px 12px; border-radius: 4px; font-weight: 700; }}"
                f"QPushButton:hover {{ background: {config.COLOR_ACCENT_HOVER}; }}"
            )
            fire_btn.setToolTip(
                f"Auto-fill and submit on {eligibility.ats_name}. "
                "Daily cap + whitelist enforced."
            )
        else:
            fire_btn.setEnabled(False)
            fire_btn.setToolTip(eligibility.reason)
            fire_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {config.COLOR_TEXT_FAINT}; "
                f"padding: 6px 12px; border-radius: 4px; "
                f"border: 1px solid {config.COLOR_BORDER_LIGHT}; }}"
            )
        fire_btn.clicked.connect(lambda: on_fire(job))
        btn_row.addWidget(fire_btn)

        applied_btn = QPushButton("Mark applied")
        applied_btn.setObjectName("PrimaryButton")
        applied_btn.clicked.connect(lambda: on_apply(job))
        btn_row.addWidget(applied_btn)
        skip_btn = QPushButton("Skip")
        skip_btn.clicked.connect(lambda: on_skip(job))
        btn_row.addWidget(skip_btn)
        btn_row.addStretch(1)
        del_btn = QPushButton("✕")
        del_btn.setFixedSize(30, 30)
        del_btn.setToolTip("Delete from queue")
        del_btn.setObjectName("GhostButton")
        del_btn.clicked.connect(lambda: on_delete(job))
        btn_row.addWidget(del_btn)
        layout.addLayout(btn_row)


# ============================================================================
# Searches tab
# ============================================================================


class _SearchesTab(QWidget):
    request_load_all = Signal()  # parent re-renders queue too when this fires

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)

        header = QHBoxLayout()
        title = _styled_text_label("Saved searches",
                                   color=config.COLOR_TEXT, point=15, bold=True)
        header.addWidget(title)
        header.addStretch(1)
        self.stop_btn = QPushButton("⏸ Stop scan")
        self.stop_btn.setToolTip("Cancel the in-progress scan or scoring run. "
                                  "Any results already saved are kept.")
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self._on_stop)
        header.addWidget(self.stop_btn)
        new_btn = QPushButton("+ New saved search")
        new_btn.setObjectName("PrimaryButton")
        new_btn.clicked.connect(self._on_new)
        header.addWidget(new_btn)
        outer.addLayout(header)

        self.status_banner = QLabel("Ready.")
        self.status_banner.setWordWrap(True)
        self.status_banner.setStyleSheet(
            f"QLabel {{ background: {config.COLOR_BG_HOVER}; "
            f"color: {config.COLOR_TEXT_DIM}; padding: 12px 16px; "
            f"border-left: 3px solid {config.COLOR_ACCENT}; border-radius: 4px; "
            f"font-size: 12px; }}"
        )
        outer.addWidget(self.status_banner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        self._cards_layout = QVBoxLayout(host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(14)
        self._cards_layout.addStretch(1)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        self._cards: list = []
        self._active_scan: QThread | None = None
        self._scan_worker: _ScanWorker | None = None
        self._active_score: QThread | None = None
        self._score_worker: _ScoreWorker | None = None
        self._scoring_search_id: int | None = None
        self.load()

    def load(self):
        for card in list(self._cards):
            self._cards_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()

        searches = svc.list_searches()
        if not searches:
            empty = QLabel(
                "No saved searches yet.\n\n"
                "Click <b>+ New saved search</b> to define what to look for."
            )
            empty.setTextFormat(Qt.RichText)
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; padding: 80px;")
            insert_at = max(0, self._cards_layout.count() - 1)
            self._cards_layout.insertWidget(insert_at, empty)
            self._cards.append(empty)
            return

        for s in searches:
            counts = queue_mod.count_by_status(s.id) if s.id is not None else {}
            queued_n = counts.get(queue_mod.STATUS_QUEUED, 0)
            new_n = counts.get(queue_mod.STATUS_NEW, 0)
            card = _SearchCard(
                s, queued_n, new_n,
                on_edit=self._on_edit,
                on_delete=self._on_delete,
                on_run_now=self._on_run_now,
            )
            insert_at = max(0, self._cards_layout.count() - 1)
            self._cards_layout.insertWidget(insert_at, card)
            self._cards.append(card)

    def _on_new(self):
        dlg = SavedSearchDialog(parent=self)
        if dlg.exec() and dlg.saved_id is not None:
            self.load()

    def _on_edit(self, search: svc.SavedSearch):
        dlg = SavedSearchDialog(search=search, parent=self)
        if dlg.exec():
            self.load()

    def _on_delete(self, search: svc.SavedSearch):
        confirm = QMessageBox.question(
            self, "Delete saved search",
            f"Delete '{search.name}'?\n\nAny queued matches from this search "
            "will also be removed.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return
        if search.id is not None:
            svc.delete_search(search.id)
        self.load()
        self.request_load_all.emit()

    def _on_run_now(self, search: svc.SavedSearch):
        if self._active_scan or self._active_score:
            QMessageBox.information(
                self, "Busy",
                "A scan or scoring run is already in progress. Wait for it to finish."
            )
            return
        card = self._card_for_search(search.id)
        if card is not None:
            card.run_btn.setEnabled(False)
            card.run_btn.setText("Scanning…")
        self.status_banner.setText(f"Scanning '{search.name}'…")
        self.stop_btn.setVisible(True)

        self._active_scan = QThread(self)
        worker = _ScanWorker(search)
        worker.moveToThread(self._active_scan)
        self._active_scan.started.connect(worker.run)
        worker.done.connect(self._on_scan_done)
        worker.done.connect(self._active_scan.quit)
        self._active_scan.finished.connect(self._active_scan.deleteLater)
        self._scan_worker = worker
        self._pending_search = search
        self._active_scan.start()

    def _on_scan_done(self, search_id: int, result):
        self._active_scan = None
        self._scan_worker = None
        search = getattr(self, "_pending_search", None)
        self._pending_search = None

        scan_summary = result.summary() if hasattr(result, "summary") else str(result)
        if getattr(result, "errors", None):
            err_block = "\n  • " + "\n  • ".join(result.errors)
            QMessageBox.warning(
                self, "Scan finished with errors",
                f"{scan_summary}\n\nErrors:{err_block}",
            )
        # If the scan picked up new rows, immediately kick off scoring.
        new_count = getattr(result, "new_count", 0)
        if new_count > 0 and search is not None:
            self.status_banner.setText(
                f"Scan: {scan_summary}. Scoring {new_count} new listing(s)…"
            )
            self._kick_off_scoring(search)
        else:
            card = self._card_for_search(search_id)
            if card is not None:
                card.run_btn.setEnabled(True)
                card.run_btn.setText("Run scan now")
            self.stop_btn.setVisible(False)
            self.stop_btn.setEnabled(True)
            self.stop_btn.setText("⏸ Stop scan")
            self.status_banner.setText(f"Scan complete: {scan_summary}")
            self.load()
            self.request_load_all.emit()

    def _kick_off_scoring(self, search: svc.SavedSearch):
        self._active_score = QThread(self)
        worker = _ScoreWorker(search)
        worker.moveToThread(self._active_score)
        self._active_score.started.connect(worker.run)
        worker.progress.connect(self._on_score_progress)
        worker.done.connect(self._on_score_done)
        worker.done.connect(self._active_score.quit)
        self._active_score.finished.connect(self._active_score.deleteLater)
        self._score_worker = worker
        self._scoring_search_id = search.id
        self._active_score.start()

    def _on_score_progress(self, done: int, total: int):
        if total:
            self.status_banner.setText(f"Scoring listings… {done}/{total}")

    def _on_score_done(self, search_id: int, result):
        self._active_score = None
        self._score_worker = None
        self._scoring_search_id = None
        card = self._card_for_search(search_id)
        if card is not None:
            card.run_btn.setEnabled(True)
            card.run_btn.setText("Run scan now")
        self.stop_btn.setVisible(False)
        summary = result.summary() if hasattr(result, "summary") else str(result)
        self.status_banner.setText(f"Done: {summary}")
        self.load()
        self.request_load_all.emit()

    def _on_stop(self):
        """Cancel whichever worker is running. Partial work is kept."""
        cancelled = False
        if self._scan_worker is not None:
            self._scan_worker.cancel()
            cancelled = True
        if self._score_worker is not None:
            self._score_worker.cancel()
            cancelled = True
        if cancelled:
            self.status_banner.setText("Cancelling… (waiting for the worker to wind down)")
            self.stop_btn.setEnabled(False)
            self.stop_btn.setText("⏸ Stopping…")
            # Re-enable the button visually after the worker actually finishes;
            # _on_scan_done / _on_score_done hide it.
            from PySide6.QtCore import QTimer
            QTimer.singleShot(3000, lambda: self.stop_btn.setEnabled(True))

    def _card_for_search(self, search_id: int):
        for c in self._cards:
            if isinstance(c, _SearchCard) and c.search.id == search_id:
                return c
        return None


# ============================================================================
# Queue tab
# ============================================================================


class _QueueTab(QWidget):
    fire_requested = Signal(object)  # emits a QueuedJob

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)

        header = QHBoxLayout()
        title = _styled_text_label("Queue",
                                   color=config.COLOR_TEXT, point=15, bold=True)
        header.addWidget(title)
        header.addSpacing(16)
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("All saved searches", None)
        self.filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        header.addWidget(self.filter_combo)
        header.addStretch(1)
        clear_btn = QPushButton("Clear processed")
        clear_btn.setToolTip("Remove applied / skipped / filtered rows from the database.")
        clear_btn.clicked.connect(self._on_clear_processed)
        header.addWidget(clear_btn)
        outer.addLayout(header)

        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet(
            f"color: {config.COLOR_TEXT_DIM}; font-size: 12px;"
        )
        outer.addWidget(self.summary_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        self._cards_layout = QVBoxLayout(host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(14)
        self._cards_layout.addStretch(1)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        self._cards: list = []
        self._search_name_by_id: dict[int, str] = {}
        self.load()

    def load(self):
        self._refresh_filter()
        for card in list(self._cards):
            self._cards_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()

        search_id = self.filter_combo.currentData()
        jobs = queue_mod.list_queued(search_id=search_id)
        counts = queue_mod.count_by_status(search_id=search_id)
        queued = counts.get(queue_mod.STATUS_QUEUED, 0)
        applied = counts.get(queue_mod.STATUS_APPLIED, 0)
        skipped = counts.get(queue_mod.STATUS_SKIPPED, 0)
        filtered = counts.get(queue_mod.STATUS_FILTERED, 0)
        errored = counts.get(queue_mod.STATUS_ERROR, 0)
        new = counts.get(queue_mod.STATUS_NEW, 0)
        self.summary_label.setText(
            f"{queued} queued · {new} unscored · {filtered} filtered · "
            f"{applied} applied · {skipped} skipped"
            + (f" · {errored} errors" if errored else "")
        )

        if not jobs:
            empty = QLabel(
                "Nothing in the queue.\n\nRun a saved search to populate it — "
                "matches above your fit-score threshold will land here."
            )
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; padding: 80px;")
            insert_at = max(0, self._cards_layout.count() - 1)
            self._cards_layout.insertWidget(insert_at, empty)
            self._cards.append(empty)
            return

        for job in jobs:
            search_name = self._search_name_by_id.get(
                job.saved_search_id, f"search #{job.saved_search_id}",
            )
            card = _QueueCard(
                job, search_name,
                on_apply=self._on_apply,
                on_skip=self._on_skip,
                on_open=self._on_open,
                on_delete=self._on_delete,
                on_fire=self._on_fire,
            )
            insert_at = max(0, self._cards_layout.count() - 1)
            self._cards_layout.insertWidget(insert_at, card)
            self._cards.append(card)

    def _refresh_filter(self):
        searches = svc.list_searches()
        self._search_name_by_id = {s.id: s.name for s in searches if s.id is not None}
        current = self.filter_combo.currentData()
        self.filter_combo.blockSignals(True)
        self.filter_combo.clear()
        self.filter_combo.addItem("All saved searches", None)
        for s in searches:
            if s.id is None:
                continue
            self.filter_combo.addItem(s.name, s.id)
        idx = self.filter_combo.findData(current)
        if idx >= 0:
            self.filter_combo.setCurrentIndex(idx)
        self.filter_combo.blockSignals(False)

    def _on_filter_changed(self, _idx: int):
        self.load()

    def _on_apply(self, job: queue_mod.QueuedJob):
        if job.source_url:
            QDesktopServices.openUrl(QUrl(job.source_url))
        queue_mod.mark_applied(job.id)
        # Also create a row in the applications table so it shows up in the pipeline.
        try:
            DB.execute(
                "INSERT INTO applications "
                "(company, role, source, listing_url, listing_text, autonomous_flag) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (
                    job.company or "(unknown)",
                    job.role or "(unknown)",
                    "autonomous_queue",
                    job.source_url,
                    job.listing_text,
                ),
            )
        except Exception:
            pass
        self.load()

    def _on_skip(self, job: queue_mod.QueuedJob):
        queue_mod.mark_skipped(job.id)
        self.load()

    def _on_open(self, job: queue_mod.QueuedJob):
        if job.source_url:
            QDesktopServices.openUrl(QUrl(job.source_url))

    def _on_fire(self, job: queue_mod.QueuedJob):
        # Re-check eligibility right before firing so daily-cap counts are fresh.
        eligibility = fire_mod.can_fire(job)
        if not eligibility.eligible:
            QMessageBox.warning(self, "Cannot fire", eligibility.reason)
            self.load()
            return
        confirm = QMessageBox.warning(
            self, "Fire mode — final confirmation",
            f"Auto-fill and submit this application to {eligibility.ats_name}?\n\n"
            f"  Company: {job.company}\n"
            f"  Role:    {job.role}\n"
            f"  Score:   {job.fit_score}\n\n"
            f"JobHunt will open the listing in the embedded browser, fill every "
            f"field it can, and click Submit. There's no undo.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return
        self.fire_requested.emit(job)

    def _on_delete(self, job: queue_mod.QueuedJob):
        queue_mod.delete_job(job.id)
        self.load()

    def _on_clear_processed(self):
        search_id = self.filter_combo.currentData()
        scope = "from all searches" if search_id is None else "from this search"
        confirm = QMessageBox.question(
            self, "Clear processed",
            f"Delete all applied / skipped / filtered queue rows {scope}?\n\n"
            "Queued (still actionable) and unscored rows are kept.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return
        n = queue_mod.clear_processed(search_id=search_id)
        QMessageBox.information(self, "Cleared", f"Removed {n} row(s).")
        self.load()


# ============================================================================
# Page
# ============================================================================


class AutonomousPage(QWidget):
    fire_requested = Signal(object)  # bubbled from queue tab → main_window → browser

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 30, 36, 30)
        outer.setSpacing(20)

        header = QHBoxLayout()
        title = QLabel("Autonomous Apply")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        outer.addLayout(header)

        intro = QLabel(
            "Define <b>saved searches</b> that scan job sources, score every match "
            "against your resume, and queue the strongest fits. <b>Queue mode</b> is "
            "on by default — you review each match. <b>Fire mode</b> auto-submits to "
            "whitelisted ATSes only (Greenhouse / Lever / Ashby / Workable), with a daily cap."
        )
        intro.setTextFormat(Qt.RichText)
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 13px;")
        outer.addWidget(intro)

        self.tabs = QTabWidget()
        self.searches_tab = _SearchesTab()
        self.queue_tab = _QueueTab()
        self.tabs.addTab(self.searches_tab, "Saved searches")
        self.tabs.addTab(self.queue_tab, "Queue")
        outer.addWidget(self.tabs, 1)

        # When the searches tab finishes a scan/score, refresh the queue tab too.
        self.searches_tab.request_load_all.connect(self.queue_tab.load)
        # Bubble Fire requests up so main_window can switch to Browser + dispatch.
        self.queue_tab.fire_requested.connect(self.fire_requested.emit)

    def refresh(self):
        self.searches_tab.load()
        self.queue_tab.load()

    def ai_context(self) -> dict:
        searches = svc.list_searches()
        counts = queue_mod.count_by_status()
        return {
            "page": "Autonomous Apply",
            "summary": (
                f"{len(searches)} saved search(es) · "
                f"{counts.get(queue_mod.STATUS_QUEUED, 0)} in queue"
            ),
            "data": {
                "saved_search_count": len(searches),
                "fire_mode_count": sum(1 for s in searches if s.mode == MODE_FIRE),
                "enabled_count": sum(1 for s in searches if s.enabled),
                "queue_counts": counts,
            },
            "rule_based_hints": [
                "Define a saved search with a few target companies + keywords.",
                "Link the search to a resume type so fit scoring has context.",
                "Set a minimum fit score (e.g. 70) to filter out low-quality matches.",
                "Review the Queue tab to see scored matches.",
            ],
        }
