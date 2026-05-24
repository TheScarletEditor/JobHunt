from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QStackedWidget, QStatusBar,
)

from ..mail.scheduler import ScanScheduler, set_instance
from .sidebar import Sidebar
from .widgets.ai_sidebar import AISidebar
from .widgets.dark_titlebar import apply_dark_title_bar
from .pages.dashboard import DashboardPage
from .pages.pipeline import PipelinePage
from .pages.resume import ResumePage
from .pages.cover_letter import CoverLetterPage
from .pages.browser import BrowserPage
from .pages.autonomous import AutonomousPage
from .pages.interviews import InterviewsPage
from .pages.reports import ReportsPage
from .pages.settings import SettingsPage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JobHunt")
        self.resize(1480, 860)
        self.setMinimumSize(1180, 700)

        root = QWidget()
        root.setObjectName("RootWindow")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar()
        self.stack = QStackedWidget()
        self.ai_sidebar = AISidebar()

        self.pages = {
            "dashboard": DashboardPage(),
            "pipeline": PipelinePage(),
            "resume": ResumePage(),
            "cover_letter": CoverLetterPage(),
            "browser": BrowserPage(),
            "autonomous": AutonomousPage(),
            "interviews": InterviewsPage(),
            "reports": ReportsPage(),
            "settings": SettingsPage(),
        }
        self._index_by_key = {}
        for i, (key, page) in enumerate(self.pages.items()):
            self.stack.addWidget(page)
            self._index_by_key[key] = i

        self.sidebar.nav_changed.connect(self._on_nav)
        self.sidebar.select("dashboard")

        self.pages["dashboard"].open_browser_requested.connect(
            lambda: self._on_nav("browser")
        )
        self.pages["dashboard"].open_autonomous_requested.connect(
            lambda: self._on_nav("autonomous")
        )
        self.pages["dashboard"].data_changed.connect(
            self.pages["pipeline"].refresh
        )
        # Autonomous → Fire mode: switch to embedded browser and dispatch.
        self.pages["autonomous"].fire_requested.connect(self._on_fire_requested)

        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.ai_sidebar)
        self.setCentralWidget(root)

        status = QStatusBar()
        status.showMessage("Ready")
        self.setStatusBar(status)

        apply_dark_title_bar(self)

        self.scheduler = ScanScheduler(self)
        self.scheduler.scan_started.connect(self._on_scheduled_scan_started)
        self.scheduler.scan_completed.connect(self._on_scheduled_scan_done)
        set_instance(self.scheduler)
        self.scheduler.start()

        # Autonomous-scan scheduler — runs saved searches on their cadence.
        from ..autonomous.scheduler import AutonomousScheduler
        self.autonomous_scheduler = AutonomousScheduler(self)
        self.autonomous_scheduler.scan_started.connect(self._on_autonomous_scan_started)
        self.autonomous_scheduler.scan_progress.connect(self._on_autonomous_scan_progress)
        self.autonomous_scheduler.scan_finished.connect(self._on_autonomous_scan_done)
        self.autonomous_scheduler.start()

        # Background update check — fires once a few seconds after launch.
        # No-op if `JOBHUNT_NO_UPDATE=1` is set, the network is down, or
        # there's no newer release.
        QTimer.singleShot(4000, self._check_for_update)

        self._on_nav("dashboard")

    def _check_for_update(self):
        """Run the update check on a background QThread so we don't block startup."""
        from ..updater import check_for_update
        from PySide6.QtCore import QObject, QThread, Signal as _Signal

        class _Worker(QObject):
            done = _Signal(object)

            def run(self):
                self.done.emit(check_for_update())

        self._update_thread = QThread(self)
        self._update_worker = _Worker()
        self._update_worker.moveToThread(self._update_thread)
        self._update_thread.started.connect(self._update_worker.run)
        self._update_worker.done.connect(self._on_update_check_done)
        self._update_worker.done.connect(self._update_thread.quit)
        self._update_thread.finished.connect(self._update_thread.deleteLater)
        self._update_thread.start()

    def _on_update_check_done(self, info):
        self._update_thread = None
        self._update_worker = None
        if info is None:
            return
        from .dialogs.update_available import UpdateAvailableDialog
        dlg = UpdateAvailableDialog(info, parent=self)
        dlg.exec()

    def _on_fire_requested(self, job):
        """Switch to the embedded browser and ask it to fire on this job."""
        self.sidebar.select("browser")
        self._on_nav("browser")
        browser = self.pages.get("browser")
        if browser is not None and hasattr(browser, "fire"):
            browser.fire(job)

    def _on_autonomous_scan_started(self, search_id: int, name: str):
        self.statusBar().showMessage(f"Auto-scan: '{name}' running…", 30000)

    def _on_autonomous_scan_progress(self, search_id: int, msg: str):
        self.statusBar().showMessage(f"Auto-scan: {msg}", 30000)

    def _on_autonomous_scan_done(self, search_id: int, payload: dict):
        name = payload.get("search_name", f"#{search_id}")
        bits = []
        if payload.get("scan"):
            bits.append(payload["scan"])
        if payload.get("score_summary"):
            bits.append(payload["score_summary"])
        msg = f"Auto-scan '{name}': " + (" · ".join(bits) or "no changes")
        self.statusBar().showMessage(msg, 15000)
        auto = self.pages.get("autonomous")
        if auto is not None and hasattr(auto, "refresh"):
            try:
                auto.refresh()
            except Exception:
                pass

    def _on_scheduled_scan_started(self):
        self.statusBar().showMessage("Auto-scan: fetching new email…", 30000)

    def _on_scheduled_scan_done(self, payload: dict):
        scans = payload.get("scans", []) if isinstance(payload, dict) else []
        classify = payload.get("classify", {}) if isinstance(payload, dict) else {}
        total_new = sum(r.get("new", 0) for r in scans)
        stage_updates = classify.get("stage_updates", 0)
        if total_new == 0 and stage_updates == 0:
            self.statusBar().showMessage("Auto-scan: no new email", 5000)
            return
        bits = [f"{total_new} new email(s)"]
        if classify.get("matched", 0) > 0:
            bits.append(f"{classify['matched']} matched")
        if stage_updates > 0:
            bits.append(f"{stage_updates} stage update(s)")
        self.statusBar().showMessage("Auto-scan: " + " · ".join(bits), 15000)
        for page in self.pages.values():
            if hasattr(page, "refresh"):
                try:
                    page.refresh()
                except Exception:
                    pass

    def _on_nav(self, key: str):
        idx = self._index_by_key.get(key)
        if idx is not None:
            self.stack.setCurrentIndex(idx)
            self.sidebar.select(key)
            page = self.pages.get(key)
            if hasattr(page, "refresh"):
                try:
                    page.refresh()
                except Exception:
                    pass
            context = None
            if page is not None and hasattr(page, "ai_context"):
                try:
                    context = page.ai_context()
                except Exception:
                    context = None
            if context is None:
                context = {
                    "page": key.replace("_", " ").title(),
                    "summary": "",
                    "data": {},
                    "rule_based_hints": [],
                }
            self.ai_sidebar.set_context(context)
