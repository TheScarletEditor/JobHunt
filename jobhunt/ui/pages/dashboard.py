from datetime import datetime, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)

from ... import config
from ...db import DB
from ..widgets.pipeline_funnel import PipelineFunnel
from ..widgets.stats_strip import StatsStrip
from ..widgets.activity_feed import ActivityFeed
from ..widgets.effects import apply_card_shadow
from ..dialogs.add_application import AddApplicationDialog


class DashboardPage(QWidget):
    open_browser_requested = Signal()
    open_autonomous_requested = Signal()
    data_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 30, 36, 30)
        layout.setSpacing(22)

        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel("Dashboard")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)

        add_btn = QPushButton("+ Add application")
        add_btn.setObjectName("PrimaryButton")
        add_btn.clicked.connect(self._on_add_application)

        browse_btn = QPushButton("Open job boards")
        browse_btn.clicked.connect(self.open_browser_requested.emit)

        scan_btn = QPushButton("Run autonomous scan")
        scan_btn.setToolTip("Open the Autonomous Apply page to trigger a scan")
        scan_btn.clicked.connect(self.open_autonomous_requested.emit)

        header.addWidget(browse_btn)
        header.addWidget(scan_btn)
        header.addWidget(add_btn)
        layout.addLayout(header)

        self.stats = StatsStrip()
        layout.addWidget(self.stats)

        body = QHBoxLayout()
        body.setSpacing(16)

        funnel_card = QFrame()
        funnel_card.setObjectName("Card")
        fc_layout = QVBoxLayout(funnel_card)
        fc_layout.setContentsMargins(24, 20, 24, 22)
        fc_layout.setSpacing(12)
        fc_title = QLabel("Pipeline")
        fc_title.setObjectName("SectionTitle")
        fc_layout.addWidget(fc_title)
        self.funnel = PipelineFunnel()
        fc_layout.addWidget(self.funnel, 1)
        apply_card_shadow(funnel_card)
        body.addWidget(funnel_card, 3)

        self.activity = ActivityFeed()
        body.addWidget(self.activity, 2)

        layout.addLayout(body, 1)

        auto_card = QFrame()
        auto_card.setObjectName("Card")
        auto_layout = QHBoxLayout(auto_card)
        auto_layout.setContentsMargins(22, 18, 22, 18)
        auto_layout.setSpacing(14)
        status_box = QVBoxLayout()
        status_box.setSpacing(4)
        status_label = QLabel("Autonomous apply")
        status_label.setObjectName("SectionTitle")
        status_box.addWidget(status_label)
        self.auto_status = QLabel("…")
        self.auto_status.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 13px;")
        status_box.addWidget(self.auto_status)
        auto_layout.addLayout(status_box)
        auto_layout.addStretch(1)
        apply_card_shadow(auto_card)
        layout.addWidget(auto_card)

        self.refresh()

    def _on_add_application(self):
        dlg = AddApplicationDialog(parent=self)
        if dlg.exec():
            self.refresh()
            self.data_changed.emit()

    def ai_context(self) -> dict:
        stages = DB.query(
            """SELECT s.name,
                      (SELECT COUNT(*) FROM applications a WHERE a.current_stage_id = s.id) AS count
               FROM pipeline_stages s ORDER BY s.sort_order"""
        )
        total = DB.query_one("SELECT COUNT(*) AS n FROM applications") or {"n": 0}
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        recent = DB.query_one(
            "SELECT COUNT(*) AS n FROM applications WHERE date_applied >= ?",
            (week_ago,),
        ) or {"n": 0}
        stage_counts = {r["name"]: r["count"] for r in stages}
        hints: list[str] = []
        if total["n"] == 0:
            hints.append("Click '+ Add application' to log your first job application.")
        if recent["n"] == 0:
            hints.append("No applications this week — set a small daily target (e.g. 3/day).")
        if stage_counts.get("Interview", 0) == 0 and total["n"] > 5:
            hints.append("You've applied to several roles but no interviews yet — consider tightening resume keywords to the job listing.")
        if total["n"] >= 10:
            hints.append("Review your response rate by source under Reports to see which boards convert best.")
        return {
            "page": "Dashboard",
            "summary": f"{total['n']} total applications · {recent['n']} this week",
            "data": {"stage_counts": stage_counts, "total": total["n"], "this_week": recent["n"]},
            "rule_based_hints": hints,
        }

    def refresh(self):
        stages = DB.query(
            """SELECT s.id, s.name, s.color,
                      (SELECT COUNT(*) FROM applications a WHERE a.current_stage_id = s.id) AS count
               FROM pipeline_stages s
               ORDER BY s.sort_order"""
        )
        self.funnel.set_data([
            {"name": r["name"], "count": r["count"], "color": r["color"]} for r in stages
        ])

        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        wk = DB.query_one(
            "SELECT COUNT(*) AS n FROM applications WHERE date_applied >= ?",
            (week_ago,),
        )
        self.stats.this_week.set_value(str(wk["n"] if wk else 0))

        total = DB.query_one("SELECT COUNT(*) AS n FROM applications")
        total_n = total["n"] if total else 0

        # Autonomous status: counts of enabled saved searches + queued jobs
        ss_n = DB.query_one(
            "SELECT COUNT(*) AS n FROM saved_searches WHERE enabled = 1"
        )
        fire_n = DB.query_one(
            "SELECT COUNT(*) AS n FROM saved_searches WHERE enabled = 1 AND mode = 'fire'"
        )
        queued_n = DB.query_one(
            "SELECT COUNT(*) AS n FROM job_queue WHERE status = 'queued'"
        )
        ss_count = ss_n["n"] if ss_n else 0
        fire_count = fire_n["n"] if fire_n else 0
        queued_count = queued_n["n"] if queued_n else 0
        if ss_count == 0:
            self.auto_status.setText("OFF  ·  no saved searches yet")
        else:
            bits = [f"{ss_count} saved search" + ("es" if ss_count != 1 else "")]
            if fire_count:
                bits.append(f"{fire_count} in Fire mode")
            if queued_count:
                bits.append(f"{queued_count} queued")
            self.auto_status.setText("ON  ·  " + " · ".join(bits))
        if total_n == 0:
            self.stats.response_rate.set_value("—")
        else:
            beyond = DB.query_one(
                """SELECT COUNT(*) AS n FROM applications a
                   JOIN pipeline_stages s ON s.id = a.current_stage_id
                   WHERE s.name NOT IN ('Applied','Withdrawn')"""
            )
            beyond_n = beyond["n"] if beyond else 0
            self.stats.response_rate.set_value(f"{round(100 * beyond_n / total_n)}%")

        active = DB.query_one(
            """SELECT COUNT(*) AS n FROM applications a
               LEFT JOIN pipeline_stages s ON s.id = a.current_stage_id
               WHERE s.name NOT IN ('Offer','Rejected','Withdrawn') OR s.name IS NULL"""
        )
        self.stats.active.set_value(str(active["n"] if active else 0))

        next_iv = DB.query_one(
            """SELECT interview_datetime FROM interviews
               WHERE interview_datetime >= datetime('now')
               ORDER BY interview_datetime ASC LIMIT 1"""
        )
        if next_iv and next_iv["interview_datetime"]:
            self.stats.next_interview.set_value(next_iv["interview_datetime"][:16])
        else:
            self.stats.next_interview.set_value("None scheduled")

        recent = DB.query(
            "SELECT action_type, timestamp, details_json FROM audit_log "
            "ORDER BY timestamp DESC LIMIT 10"
        )
        entries = []
        for r in recent:
            entries.append({
                "timestamp": r["timestamp"][:16] if r["timestamp"] else "",
                "text": r["action_type"].replace("_", " "),
            })
        self.activity.set_entries(entries)
