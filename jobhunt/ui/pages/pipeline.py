from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QHBoxLayout, QPushButton,
)

from ...db import DB
from ..dialogs.add_application import AddApplicationDialog


class PipelinePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("Pipeline")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        add_btn = QPushButton("+ Add application")
        add_btn.setObjectName("PrimaryButton")
        add_btn.clicked.connect(self._on_add)
        header.addWidget(add_btn)
        layout.addLayout(header)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Company", "Role", "Stage", "Source", "Applied", "Fit", "Notes"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(self._on_row_open)
        layout.addWidget(self.table, 1)

        self.refresh()

    def _on_add(self):
        dlg = AddApplicationDialog(parent=self)
        if dlg.exec():
            self.refresh()

    def _on_row_open(self, row: int, _column: int):
        item = self.table.item(row, 0)
        if not item:
            return
        application_id = item.data(Qt.UserRole)
        if application_id is None:
            return
        from ..dialogs.application_detail import ApplicationDetailDialog
        dlg = ApplicationDetailDialog(application_id, self)
        dlg.exec()
        self.refresh()

    def ai_context(self) -> dict:
        rows = DB.query(
            """SELECT a.company, a.role, s.name AS stage_name, a.date_applied
               FROM applications a
               LEFT JOIN pipeline_stages s ON s.id = a.current_stage_id
               ORDER BY a.date_applied DESC, a.id DESC LIMIT 30"""
        )
        stale_screening = DB.query_one(
            """SELECT COUNT(*) AS n FROM applications a
               JOIN pipeline_stages s ON s.id = a.current_stage_id
               WHERE s.name = 'Screening' AND a.date_applied <= date('now', '-14 days')"""
        )
        hints: list[str] = []
        if not rows:
            hints.append("Add your first application via the '+ Add application' button.")
        if stale_screening and stale_screening["n"] > 0:
            hints.append(f"{stale_screening['n']} application(s) have been in Screening for 14+ days — consider following up.")
        return {
            "page": "Pipeline",
            "summary": f"{len(rows)} applications visible",
            "data": {"recent": [dict(r) for r in rows[:15]]},
            "rule_based_hints": hints,
        }

    def refresh(self):
        rows = DB.query(
            """SELECT a.id, a.company, a.role, s.name AS stage_name,
                      a.source, a.date_applied, a.fit_score, a.notes
               FROM applications a
               LEFT JOIN pipeline_stages s ON s.id = a.current_stage_id
               ORDER BY a.date_applied DESC, a.id DESC"""
        )
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            cells = [
                r["company"] or "",
                r["role"] or "",
                r["stage_name"] or "",
                r["source"] or "",
                r["date_applied"] or "",
                str(r["fit_score"]) if r["fit_score"] is not None else "",
                (r["notes"] or "").split("\n")[0][:80],
            ]
            for col, val in enumerate(cells):
                item = QTableWidgetItem(val)
                if col == 0:
                    item.setData(Qt.UserRole, r["id"])
                if col == 5:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, col, item)
