"""Dialog for creating / editing a saved search."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIntValidator, QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QPlainTextEdit, QFrame, QDialogButtonBox, QStackedWidget,
    QWidget, QMessageBox, QCheckBox, QGridLayout, QScrollArea, QApplication,
    QSizePolicy,
)

from ... import config
from ...autonomous.searches import (
    SavedSearch, SOURCE_COMPANY_ATS, SOURCE_ADZUNA, MODE_QUEUE, MODE_FIRE,
    SCHEDULE_OPTIONS, ATS_KINDS,
)
from ...documents import versions as resume_versions
from ..widgets.dark_titlebar import apply_dark_title_bar


def _label(text: str, *, color: str, point: int = 10, bold: bool = True) -> QLabel:
    lbl = QLabel(text)
    f = QFont("Segoe UI", point); f.setBold(bold)
    lbl.setFont(f)
    lbl.setStyleSheet(
        f"QLabel {{ color: {color}; background-color: transparent; padding: 0; margin: 0; }}"
    )
    lbl.setMinimumHeight(36)
    return lbl


class _CompanyATSCriteriaPanel(QWidget):
    """Editor for company_ats source criteria — companies, keywords, locations."""

    def __init__(self, criteria: dict | None = None, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(_label(
            "Companies (one per line, as 'ats:slug')",
            color=config.COLOR_FORM_LABEL,
        ))
        hint = QLabel(
            "Example: <code>greenhouse:stripe</code>, <code>lever:robinhood</code>, "
            "<code>ashby:linear</code>, <code>workable:gitlab</code>. "
            "Find the slug in the board URL."
        )
        hint.setTextFormat(Qt.RichText)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 11px;")
        layout.addWidget(hint)
        self.companies = QPlainTextEdit()
        self.companies.setPlaceholderText("greenhouse:stripe\nlever:robinhood\nashby:linear")
        self.companies.setFixedHeight(140)
        layout.addWidget(self.companies)

        layout.addWidget(_label("Title keywords (comma-separated, any match)",
                                color=config.COLOR_FORM_LABEL))
        self.keywords = QLineEdit()
        self.keywords.setPlaceholderText("backend, python, infrastructure")
        layout.addWidget(self.keywords)

        layout.addWidget(_label("Location keywords (comma-separated, optional)",
                                color=config.COLOR_FORM_LABEL))
        self.locations = QLineEdit()
        self.locations.setPlaceholderText("remote, us, new york")
        layout.addWidget(self.locations)

        if criteria:
            self.load(criteria)

    def load(self, criteria: dict):
        companies = criteria.get("companies") or []
        lines = []
        for c in companies:
            ats = (c.get("ats") or "").strip()
            slug = (c.get("slug") or "").strip()
            if ats and slug:
                lines.append(f"{ats}:{slug}")
        self.companies.setPlainText("\n".join(lines))
        self.keywords.setText(", ".join(criteria.get("keywords") or []))
        self.locations.setText(", ".join(criteria.get("location_keywords") or []))

    def dump(self) -> dict:
        companies: list[dict] = []
        for raw in self.companies.toPlainText().splitlines():
            line = raw.strip()
            if not line or ":" not in line:
                continue
            ats, _, slug = line.partition(":")
            ats = ats.strip().lower()
            slug = slug.strip()
            if ats in ATS_KINDS and slug:
                companies.append({"ats": ats, "slug": slug})
        keywords = [t.strip() for t in self.keywords.text().split(",") if t.strip()]
        locations = [t.strip() for t in self.locations.text().split(",") if t.strip()]
        return {
            "companies": companies,
            "keywords": keywords,
            "location_keywords": locations,
        }


class _AdzunaCriteriaPanel(QWidget):
    """Editor for Adzuna source criteria."""

    def __init__(self, criteria: dict | None = None, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(_label("Query (job title / keywords)", color=config.COLOR_FORM_LABEL))
        self.query = QLineEdit()
        self.query.setPlaceholderText("backend engineer python")
        layout.addWidget(self.query)

        layout.addWidget(_label("Country code", color=config.COLOR_FORM_LABEL))
        self.where = QComboBox()
        for code, name in (
            ("us", "United States"), ("gb", "United Kingdom"), ("ca", "Canada"),
            ("au", "Australia"), ("de", "Germany"), ("fr", "France"),
        ):
            self.where.addItem(f"{name} ({code})", code)
        layout.addWidget(self.where)

        layout.addWidget(_label("Max age (days)", color=config.COLOR_FORM_LABEL))
        self.max_age = QLineEdit()
        self.max_age.setValidator(QIntValidator(1, 365))
        self.max_age.setPlaceholderText("7")
        layout.addWidget(self.max_age)

        layout.addWidget(_label("Minimum salary (USD, optional)", color=config.COLOR_FORM_LABEL))
        self.salary_min = QLineEdit()
        self.salary_min.setValidator(QIntValidator(0, 10_000_000))
        self.salary_min.setPlaceholderText("100000")
        layout.addWidget(self.salary_min)

        note = QLabel(
            "Requires an Adzuna API key — add yours in <b>Settings → API Keys</b>."
        )
        note.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 11px; padding-top: 4px;")
        note.setTextFormat(Qt.RichText)
        layout.addWidget(note)

        if criteria:
            self.load(criteria)

    def load(self, criteria: dict):
        self.query.setText(criteria.get("query") or "")
        where_code = criteria.get("where") or "us"
        idx = self.where.findData(where_code)
        if idx >= 0:
            self.where.setCurrentIndex(idx)
        self.max_age.setText(str(criteria.get("max_age_days") or 7))
        if criteria.get("salary_min"):
            self.salary_min.setText(str(criteria["salary_min"]))

    def dump(self) -> dict:
        out = {
            "query": self.query.text().strip(),
            "where": self.where.currentData(),
            "max_age_days": int(self.max_age.text() or 7),
        }
        if self.salary_min.text().strip():
            try:
                out["salary_min"] = int(self.salary_min.text())
            except ValueError:
                pass
        return out


class SavedSearchDialog(QDialog):
    def __init__(self, search: SavedSearch | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit saved search" if search else "New saved search")
        self.setModal(True)
        apply_dark_title_bar(self)

        # Size the dialog to fit the user's screen — fixed dimensions used to
        # push the Save button below the bottom edge on shorter displays.
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.resize(min(760, int(geo.width() * 0.85)),
                        min(820, int(geo.height() * 0.85)))
        else:
            self.resize(760, 820)
        self.setMinimumWidth(560)
        self.setMinimumHeight(480)

        self._search = search or SavedSearch()
        self.saved_id: int | None = self._search.id

        # Outer layout: header (fixed) + scrollable body (expanding) + buttons (fixed)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 22, 22, 22)
        outer.setSpacing(14)

        title = QLabel("Edit saved search" if search else "New saved search")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        # --- Scrollable body ---
        body_scroll = QScrollArea()
        body_scroll.setWidgetResizable(True)
        body_scroll.setFrameShape(QFrame.NoFrame)
        body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body_host = QWidget()
        body_layout = QVBoxLayout(body_host)
        body_layout.setContentsMargins(0, 0, 12, 0)  # right pad for scrollbar
        body_layout.setSpacing(14)
        body_scroll.setWidget(body_host)
        outer.addWidget(body_scroll, 1)

        # --- Two-column grid for top-level fields ---
        grid = QGridLayout()
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(20)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 200)

        row = 0
        grid.addWidget(_label("Name", color=config.COLOR_FORM_LABEL), row, 0)
        self.name_input = QLineEdit(self._search.name)
        self.name_input.setPlaceholderText("e.g. 'Senior backend roles — Bay Area'")
        grid.addWidget(self.name_input, row, 1); row += 1

        grid.addWidget(_label("Source", color=config.COLOR_FORM_LABEL), row, 0)
        self.source_combo = QComboBox()
        self.source_combo.addItem("Company ATS boards (Greenhouse / Lever / Ashby / Workable)",
                                  SOURCE_COMPANY_ATS)
        self.source_combo.addItem("Adzuna keyword search", SOURCE_ADZUNA)
        grid.addWidget(self.source_combo, row, 1); row += 1

        grid.addWidget(_label("Resume to score against", color=config.COLOR_FORM_LABEL), row, 0)
        resume_cell = QVBoxLayout()
        resume_cell.setContentsMargins(0, 0, 0, 0)
        resume_cell.setSpacing(4)
        self.resume_combo = QComboBox()
        self._populate_resume_combo()
        resume_cell.addWidget(self.resume_combo)
        if self.resume_combo.count() <= 1:
            hint = QLabel(
                "No resumes found. Import or create one on the "
                "<b>Resume</b> page, then come back to link it here."
            )
            hint.setTextFormat(Qt.RichText)
            hint.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 11px;")
            hint.setWordWrap(True)
            resume_cell.addWidget(hint)
        grid.addLayout(resume_cell, row, 1); row += 1

        grid.addWidget(_label("Minimum fit score (0–100)", color=config.COLOR_FORM_LABEL), row, 0)
        self.threshold_input = QLineEdit(str(self._search.threshold))
        self.threshold_input.setValidator(QIntValidator(0, 100))
        grid.addWidget(self.threshold_input, row, 1); row += 1

        grid.addWidget(_label("Schedule", color=config.COLOR_FORM_LABEL), row, 0)
        self.schedule_combo = QComboBox()
        for value, label in SCHEDULE_OPTIONS:
            self.schedule_combo.addItem(label, value)
        grid.addWidget(self.schedule_combo, row, 1); row += 1

        grid.addWidget(_label("Mode", color=config.COLOR_FORM_LABEL), row, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Queue — review each match", MODE_QUEUE)
        self.mode_combo.addItem("Fire — auto-submit to trusted ATS", MODE_FIRE)
        grid.addWidget(self.mode_combo, row, 1); row += 1

        grid.addWidget(_label("Daily auto-submit cap (Fire mode)", color=config.COLOR_FORM_LABEL),
                       row, 0)
        self.cap_input = QLineEdit(str(self._search.daily_cap))
        self.cap_input.setValidator(QIntValidator(1, 999))
        grid.addWidget(self.cap_input, row, 1); row += 1

        self.enabled_check = QCheckBox("Enabled")
        self.enabled_check.setChecked(self._search.enabled)
        grid.addWidget(self.enabled_check, row, 1); row += 1

        body_layout.addLayout(grid)

        # --- Source-specific criteria panel (swaps based on source_combo) ---
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {config.COLOR_BORDER_LIGHT}; background: {config.COLOR_BORDER_LIGHT};")
        sep.setFixedHeight(1)
        body_layout.addWidget(sep)

        body_layout.addWidget(_label("Search criteria",
                                     color=config.COLOR_ACCENT, point=12, bold=True))

        self.criteria_stack = QStackedWidget()
        self.company_panel = _CompanyATSCriteriaPanel(self._search.criteria)
        self.adzuna_panel = _AdzunaCriteriaPanel(self._search.criteria)
        self.criteria_stack.addWidget(self.company_panel)
        self.criteria_stack.addWidget(self.adzuna_panel)
        body_layout.addWidget(self.criteria_stack)
        body_layout.addStretch(1)

        # Hook source combo to stack
        self.source_combo.currentIndexChanged.connect(self._sync_criteria_stack)
        # Initial source selection
        if self._search.source_type == SOURCE_ADZUNA:
            self.source_combo.setCurrentIndex(1)
        # Set schedule + mode from existing search
        sch_idx = self.schedule_combo.findData(self._search.schedule_cron)
        if sch_idx >= 0:
            self.schedule_combo.setCurrentIndex(sch_idx)
        mode_idx = self.mode_combo.findData(self._search.mode)
        if mode_idx >= 0:
            self.mode_combo.setCurrentIndex(mode_idx)
        self._sync_criteria_stack()

        # --- Buttons ---
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        save_btn = btns.button(QDialogButtonBox.Save)
        save_btn.setObjectName("PrimaryButton")
        save_btn.setText("Save search")
        btns.accepted.connect(self._on_save)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)

    def _populate_resume_combo(self):
        self.resume_combo.addItem("(None — use default fit scoring)", None)
        try:
            types = resume_versions.list_resume_types()
        except Exception:
            types = []
        for t in types:
            self.resume_combo.addItem(t["name"], t["id"])
        if self._search.resume_type_id is not None:
            idx = self.resume_combo.findData(self._search.resume_type_id)
            if idx >= 0:
                self.resume_combo.setCurrentIndex(idx)

    def _sync_criteria_stack(self):
        source = self.source_combo.currentData()
        idx = 0 if source == SOURCE_COMPANY_ATS else 1
        self.criteria_stack.setCurrentIndex(idx)

    def _on_save(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Name required", "Give the saved search a name.")
            return
        try:
            threshold = int(self.threshold_input.text() or 70)
            cap = int(self.cap_input.text() or 15)
        except ValueError:
            QMessageBox.warning(self, "Invalid number", "Score and cap must be integers.")
            return

        source_type = self.source_combo.currentData()
        criteria = (self.company_panel if source_type == SOURCE_COMPANY_ATS
                    else self.adzuna_panel).dump()

        # Basic validation per source
        if source_type == SOURCE_COMPANY_ATS:
            if not criteria.get("companies"):
                QMessageBox.warning(
                    self, "No companies",
                    "Add at least one company (format: 'greenhouse:stripe', one per line).",
                )
                return
            if not criteria.get("keywords"):
                QMessageBox.warning(
                    self, "No keywords",
                    "Add at least one title keyword so we know which jobs to surface.",
                )
                return
        else:  # Adzuna
            if not criteria.get("query"):
                QMessageBox.warning(self, "No query", "Enter a search query.")
                return

        from ...autonomous import searches as svc
        search = SavedSearch(
            id=self._search.id,
            name=name,
            source_type=source_type,
            criteria=criteria,
            resume_type_id=self.resume_combo.currentData(),
            threshold=max(0, min(100, threshold)),
            mode=self.mode_combo.currentData(),
            schedule_cron=self.schedule_combo.currentData(),
            daily_cap=max(1, cap),
            enabled=self.enabled_check.isChecked(),
        )
        try:
            if search.id is None:
                self.saved_id = svc.create_search(search)
            else:
                svc.update_search(search)
                self.saved_id = search.id
        except Exception as e:
            QMessageBox.warning(self, "Save error", f"Couldn't save: {e}")
            return
        self.accept()
