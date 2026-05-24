from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QObject, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QFormLayout,
    QTabWidget, QFrame, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QFileDialog, QSpinBox, QColorDialog,
    QRadioButton, QButtonGroup, QInputDialog, QAbstractSpinBox,
    QCheckBox, QComboBox, QSizePolicy, QScrollArea, QGridLayout,
)

from ...documents import parser as doc_parser
from PySide6.QtGui import QColor, QIntValidator, QFont

from ...db import DB
from ... import config
from ...llm import keys as llm_keys
from ...documents import versions as resume_versions
from ..widgets.effects import apply_card_shadow


def _styled_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("FormLabel")
    return lbl


def _make_form() -> QFormLayout:
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.DontWrapRows)
    form.setHorizontalSpacing(18)
    form.setVerticalSpacing(14)
    return form


_EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")
_PHONE_RE = re.compile(r"^[+\d][\d\s().\-]{6,}\d$")


def _map_contact_to_profile(name: str, contact_lines: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    if name and name.strip():
        out["legal_name"] = name.strip()
    for raw in contact_lines:
        item = (raw or "").strip()
        if not item:
            continue
        lower = item.lower()
        m = _EMAIL_RE.search(item)
        if m and "email" not in out:
            out["email"] = m.group(0)
            continue
        if "linkedin.com" in lower or "linkedin/in/" in lower:
            if "linkedin_url" not in out:
                out["linkedin_url"] = item
            continue
        if "github.com" in lower:
            if "github_url" not in out:
                out["github_url"] = item
            continue
        if ("://" in lower or lower.startswith("www.")) and "portfolio_url" not in out:
            out["portfolio_url"] = item
            continue
        digits = sum(1 for c in item if c.isdigit())
        if digits >= 7 and _PHONE_RE.match(item) and "phone" not in out:
            out["phone"] = item
            continue
        if "address" not in out:
            out["address"] = item
    return out


def _section_header(title: str, description: str | None = None) -> QWidget:
    box = QWidget()
    box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    title_label = QLabel(title)
    title_label.setObjectName("SectionTitle")
    layout.addWidget(title_label)
    if description:
        desc = QLabel(description)
        desc.setObjectName("SectionDescription")
        desc.setWordWrap(True)
        desc.setMinimumWidth(0)
        desc.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.MinimumExpanding)
        layout.addWidget(desc)
    return box


def _tab_outer(widget: QWidget) -> QVBoxLayout:
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(28, 24, 28, 24)
    layout.setSpacing(18)
    return layout


def _card() -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("Card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(28, 24, 28, 24)
    layout.setSpacing(16)
    apply_card_shadow(card)
    return card, layout


class _ProfileTab(QWidget):
    SPEC = [
        ("legal_name", "Legal name"),
        ("preferred_name", "Preferred name"),
        ("email", "Email"),
        ("phone", "Phone"),
        ("address", "Address"),
        ("linkedin_url", "LinkedIn URL"),
        ("portfolio_url", "Portfolio URL"),
        ("github_url", "GitHub URL"),
        ("work_auth", "Work authorization"),
        ("citizenship", "Citizenship"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = _tab_outer(self)

        outer.addWidget(_section_header(
            "Profile",
            "Used to auto-fill ATS forms. Stored locally — never transmitted "
            "except to the application form you're filling out."
        ))

        card, card_layout = _card()
        form = _make_form()

        self.fields: dict[str, QLineEdit] = {}
        for key, label in self.SPEC:
            edit = QLineEdit()
            edit.setPlaceholderText(f"Your {label.lower()}…")
            self.fields[key] = edit
            form.addRow(_styled_label(label), edit)

        self.salary_min = QLineEdit()
        self.salary_min.setValidator(QIntValidator(0, 10_000_000))
        self.salary_min.setPlaceholderText("e.g. 120000 (USD)")
        form.addRow(_styled_label("Salary expectation"), self.salary_min)

        card_layout.addLayout(form)
        card_layout.addSpacing(12)

        save_row = QHBoxLayout()
        fill_btn = QPushButton("Fill from Resume…")
        fill_btn.setToolTip("Parse an existing resume file and auto-fill these profile fields")
        fill_btn.clicked.connect(self._on_fill_from_resume)
        save_row.addWidget(fill_btn)
        save_row.addStretch(1)
        save_btn = QPushButton("Save profile")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._save)
        save_row.addWidget(save_btn)
        card_layout.addLayout(save_row)

        outer.addWidget(card)
        outer.addStretch(1)
        self._load()

    def _on_fill_from_resume(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick a resume to fill your profile from",
            filter="Resumes (*.docx *.pdf *.txt);;Word (*.docx);;PDF (*.pdf);;Text (*.txt);;All files (*.*)",
        )
        if not path:
            return
        raw_text = doc_parser.extract_raw_text(Path(path))
        if not raw_text.strip():
            QMessageBox.warning(
                self, "Empty file",
                f"Couldn't extract any text from {Path(path).name}. "
                "If it's a scanned PDF, JobHunt can't read it without OCR.",
            )
            return

        from ..dialogs.parse_resume_progress import ParseResumeDialog
        progress = ParseResumeDialog(raw_text, parent=self)
        if not progress.exec():
            return
        content = progress.parsed_content
        if content is None:
            QMessageBox.warning(self, "Parse failed",
                                f"Could not parse {Path(path).name}:\n{progress.error}")
            return

        mapped = _map_contact_to_profile(content.name or "", content.contact or [])

        filled: list[str] = []
        for key, edit in self.fields.items():
            value = mapped.get(key)
            if value and not edit.text().strip():
                edit.setText(value)
                filled.append(key)

        if mapped.get("legal_name") and not self.fields["preferred_name"].text().strip():
            first = mapped["legal_name"].split()[0] if mapped["legal_name"] else ""
            if first:
                self.fields["preferred_name"].setText(first)
                filled.append("preferred_name")

        note = ""
        if progress.error:
            note = f"\n\n(Note: {progress.error})"
        elif progress.provider_name not in ("rule_based", "fallback"):
            note = f"\n\nParsed by {progress.provider_name}."

        if filled:
            QMessageBox.information(
                self, "Filled",
                f"Filled {len(filled)} field(s) from {Path(path).name}.{note}\n\n"
                "Review the values and click 'Save profile' to keep them.",
            )
        else:
            QMessageBox.information(
                self, "Nothing to fill",
                "All your profile fields already have values, or the resume didn't expose "
                "anything matchable (name, email, phone, links, address).",
            )

    def _load(self):
        row = DB.query_one("SELECT * FROM profile WHERE id = 1")
        if not row:
            return
        for key, edit in self.fields.items():
            edit.setText(row[key] or "")
        self.salary_min.setText(str(row["salary_min"]) if row["salary_min"] else "")

    @staticmethod
    def _parse_int(text: str) -> int | None:
        text = (text or "").strip()
        if not text:
            return None
        try:
            value = int(text)
            return value if value > 0 else None
        except ValueError:
            return None

    def _save(self):
        values = {k: (e.text().strip() or None) for k, e in self.fields.items()}
        values["salary_min"] = self._parse_int(self.salary_min.text())
        cols = ", ".join(f"{k} = ?" for k in values)
        DB.execute(f"UPDATE profile SET {cols} WHERE id = 1", tuple(values.values()))
        DB.log_audit("profile_updated")
        QMessageBox.information(self, "Saved", "Profile saved.")


# ============================================================================
# Demographics — voluntary self-disclosure used for ATS auto-fill
#
# Field options mirror what Greenhouse, Lever, Workday, and EEO-1 reporting
# commonly ask. "Prefer not to say" is the default for every dropdown.
# ============================================================================


_PREFER_NOT = "Prefer not to say"


_PRONOUN_OPTIONS = [
    _PREFER_NOT,
    "She/her",
    "He/him",
    "They/them",
    "She/they",
    "He/they",
    "Ze/zir",
    "Xe/xem",
]
_PRONOUN_CUSTOM_LABEL = "Custom…"

_GENDER_OPTIONS = [
    _PREFER_NOT,
    "Woman",
    "Man",
    "Non-binary",
    "Genderqueer / Gender fluid",
    "Agender",
    "Other / self-describe",
]

_TRANS_OPTIONS = [
    _PREFER_NOT, "No", "Yes",
]

_HISPANIC_OPTIONS = [
    _PREFER_NOT,
    "No, not Hispanic or Latino",
    "Yes, Hispanic or Latino",
]

_RACE_OPTIONS = [
    # EEO-1 categories, multi-select.
    "American Indian or Alaska Native",
    "Asian",
    "Black or African American",
    "Native Hawaiian or Other Pacific Islander",
    "White",
    "Two or more races",
]

_ORIENTATION_OPTIONS = [
    _PREFER_NOT,
    "Heterosexual / Straight",
    "Gay or Lesbian",
    "Bisexual",
    "Queer",
    "Asexual",
    "Pansexual",
    "Other / self-describe",
]

_VETERAN_OPTIONS = [
    _PREFER_NOT,
    "I am not a protected veteran",
    "I am a veteran",
    "I am a disabled veteran",
]

_DISABILITY_OPTIONS = [
    _PREFER_NOT,
    "No, I do not have a disability",
    "Yes, I have a disability (or previously had one)",
]

_SPONSORSHIP_OPTIONS = [
    _PREFER_NOT,
    "No — I am authorized to work without sponsorship",
    "Yes — I need sponsorship now",
    "I will need sponsorship in the future",
]


def _make_combo(options: list[str], *, editable: bool = False) -> QComboBox:
    combo = QComboBox()
    combo.addItems(options)
    if editable:
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
    return combo


class _DemographicsTab(QWidget):
    """Voluntary self-disclosure fields. Saved alongside the profile row."""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = _tab_outer(self)

        outer.addWidget(_section_header(
            "Demographics (optional)",
            "Voluntary self-disclosure for auto-filling application forms. Every "
            "field defaults to 'Prefer not to say' — answer only what you want. "
            "Stored locally and never transmitted except to the application form "
            "you choose to submit."
        ))

        # Build all field widgets up front.
        self.pronouns = _make_combo(_PRONOUN_OPTIONS + [_PRONOUN_CUSTOM_LABEL])
        self.pronouns.activated.connect(self._on_pronouns_activated)
        self._pronouns_custom_value: str | None = None
        self.dob = QLineEdit()
        self.dob.setPlaceholderText("YYYY-MM-DD (optional)")
        self.country_of_origin = QLineEdit()
        self.country_of_origin.setPlaceholderText("e.g. United States (optional)")
        self.gender_identity = _make_combo(_GENDER_OPTIONS)
        self.transgender_status = _make_combo(_TRANS_OPTIONS)
        self.hispanic_latino = _make_combo(_HISPANIC_OPTIONS)
        self.sexual_orientation = _make_combo(_ORIENTATION_OPTIONS)
        self.veteran_status = _make_combo(_VETERAN_OPTIONS)
        self.disability_status = _make_combo(_DISABILITY_OPTIONS)
        self.needs_sponsorship = _make_combo(_SPONSORSHIP_OPTIONS)

        # Race multi-select container — plain QWidget + vbox of checkboxes.
        # QFormLayout will size it from the natural sizeHint (sum of children).
        race_box = QWidget()
        race_vbox = QVBoxLayout(race_box)
        race_vbox.setContentsMargins(0, 0, 0, 0)
        race_vbox.setSpacing(4)
        self.race_checks: list[QCheckBox] = []
        for opt in _RACE_OPTIONS:
            cb = QCheckBox(opt)
            self.race_checks.append(cb)
            race_vbox.addWidget(cb)
        self.race_prefer_not = QCheckBox(_PREFER_NOT)
        self.race_checks.append(self.race_prefer_not)
        race_vbox.addWidget(self.race_prefer_not)
        self.race_prefer_not.toggled.connect(self._on_race_prefer_toggled)
        for cb in self.race_checks[:-1]:
            cb.toggled.connect(self._on_race_choice_toggled)

        # QGridLayout + inline-styleSheet labels — same pattern as the Saved
        # Search dialog (which has been rendering reliably). Inline stylesheet
        # with explicit QFont + min-height is what makes labels actually paint
        # in this context; the objectName-only `_styled_label` helper that
        # works in Profile's QFormLayout doesn't reliably render here.
        from PySide6.QtGui import QFont
        def _grid_label(text: str, *, color: str, point: int = 10, bold: bool = True) -> QLabel:
            lbl = QLabel(text)
            f = QFont("Segoe UI", point); f.setBold(bold)
            lbl.setFont(f)
            lbl.setStyleSheet(
                f"QLabel {{ color: {color}; background-color: transparent; "
                f"padding: 0; margin: 0; }}"
            )
            lbl.setMinimumHeight(36)
            return lbl

        card, card_layout = _card()
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 260)

        row = 0
        for group, entries in (
            ("Personal", [
                ("Pronouns",                       self.pronouns),
                ("Date of birth",                  self.dob),
                ("Country of origin",              self.country_of_origin),
            ]),
            ("Gender identity", [
                ("Gender identity",                self.gender_identity),
                ("Identify as transgender?",       self.transgender_status),
            ]),
            ("Race & ethnicity", [
                ("Hispanic or Latino?",            self.hispanic_latino),
                ("Race (select all that apply)",   race_box),
            ]),
            ("Sexual orientation", [
                ("Orientation",                    self.sexual_orientation),
            ]),
            ("Veteran & disability status", [
                ("Veteran status",                 self.veteran_status),
                ("Disability status",              self.disability_status),
            ]),
            ("Work authorization", [
                ("Sponsorship needed?",            self.needs_sponsorship),
            ]),
        ):
            # Group header spans both columns
            grid.addWidget(
                _grid_label(group, color=config.COLOR_ACCENT, point=12, bold=True),
                row, 0, 1, 2,
            )
            grid.setRowMinimumHeight(row, 56)
            row += 1
            for label_text, widget in entries:
                grid.addWidget(
                    _grid_label(label_text, color=config.COLOR_FORM_LABEL,
                                point=10, bold=True),
                    row, 0, Qt.AlignLeft | Qt.AlignVCenter,
                )
                grid.addWidget(widget, row, 1)
                grid.setRowMinimumHeight(row, 240 if widget is race_box else 50)
                row += 1

        card_layout.addLayout(grid)
        card_layout.addSpacing(20)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("Save demographics")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._save)
        save_row.addWidget(save_btn)
        card_layout.addLayout(save_row)

        outer.addWidget(card)
        outer.addStretch(1)
        self._load()

    def _group_header(self, text: str) -> QLabel:
        """Red group-header label, added as a spanning row in the QFormLayout.
        Styled by `QLabel#GroupHeader` in theme.py."""
        lbl = QLabel(text)
        lbl.setObjectName("GroupHeader")
        return lbl

    def _on_pronouns_activated(self, index: int):
        if self.pronouns.itemText(index) != _PRONOUN_CUSTOM_LABEL:
            return
        text, ok = QInputDialog.getText(
            self, "Custom pronouns",
            "Enter your pronouns:",
            text=self._pronouns_custom_value or "",
        )
        if not ok or not text.strip():
            # Revert to first option
            self.pronouns.setCurrentIndex(0)
            return
        self._set_custom_pronouns(text.strip())

    def _set_custom_pronouns(self, text: str):
        """Insert/replace a custom item just above 'Custom…' and select it."""
        self._pronouns_custom_value = text
        # Remove any prior custom entry (everything between the preset list and 'Custom…')
        preset_count = len(_PRONOUN_OPTIONS)
        while self.pronouns.count() > preset_count + 1:
            self.pronouns.removeItem(preset_count)
        # Insert the new custom entry just before 'Custom…'
        self.pronouns.insertItem(preset_count, text)
        self.pronouns.setCurrentIndex(preset_count)

    def _on_race_prefer_toggled(self, checked: bool):
        if not checked:
            return
        for cb in self.race_checks[:-1]:
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)

    def _on_race_choice_toggled(self, _checked: bool):
        if any(cb.isChecked() for cb in self.race_checks[:-1]):
            self.race_prefer_not.blockSignals(True)
            self.race_prefer_not.setChecked(False)
            self.race_prefer_not.blockSignals(False)

    def _load(self):
        row = DB.query_one("SELECT * FROM profile WHERE id = 1")
        if not row:
            return

        def _set_combo(combo: QComboBox, value: str | None):
            if value is None:
                combo.setCurrentIndex(0)
                if combo.isEditable():
                    combo.setEditText("")
                return
            idx = combo.findText(value)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            elif combo.isEditable():
                combo.setEditText(value)
            else:
                combo.setCurrentIndex(0)

        # Pronouns: match the stored value against the preset list; if it's
        # something custom we add it as a custom entry just above 'Custom…'.
        pronouns_value = row["pronouns"] if "pronouns" in row.keys() else None
        if pronouns_value:
            idx = self.pronouns.findText(pronouns_value)
            if idx >= 0:
                self.pronouns.setCurrentIndex(idx)
            else:
                self._set_custom_pronouns(pronouns_value)
        else:
            self.pronouns.setCurrentIndex(0)

        self.dob.setText(row["date_of_birth"] or "" if "date_of_birth" in row.keys() else "")
        self.country_of_origin.setText(
            row["country_of_origin"] or "" if "country_of_origin" in row.keys() else ""
        )

        _set_combo(self.gender_identity, row["eeo_gender"])
        _set_combo(self.transgender_status,
                   row["transgender_status"] if "transgender_status" in row.keys() else None)
        _set_combo(self.hispanic_latino,
                   row["hispanic_latino"] if "hispanic_latino" in row.keys() else None)
        _set_combo(self.sexual_orientation,
                   row["sexual_orientation"] if "sexual_orientation" in row.keys() else None)
        _set_combo(self.veteran_status, row["eeo_veteran"])
        _set_combo(self.disability_status, row["eeo_disability"])
        _set_combo(self.needs_sponsorship,
                   row["needs_sponsorship"] if "needs_sponsorship" in row.keys() else None)

        # Race multi-select: stored as JSON list in eeo_race
        raw = row["eeo_race"] or ""
        chosen: list[str] = []
        if raw:
            try:
                import json
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    chosen = [str(x) for x in parsed]
                else:
                    chosen = [raw]  # fall back to legacy single-string format
            except Exception:
                chosen = [raw]
        if _PREFER_NOT in chosen:
            self.race_prefer_not.setChecked(True)
        else:
            for cb in self.race_checks[:-1]:
                cb.setChecked(cb.text() in chosen)

    def _save(self):
        import json
        chosen_races: list[str] = []
        if self.race_prefer_not.isChecked():
            chosen_races = [_PREFER_NOT]
        else:
            chosen_races = [cb.text() for cb in self.race_checks[:-1] if cb.isChecked()]
        race_value = json.dumps(chosen_races) if chosen_races else None

        def _combo_value(combo: QComboBox) -> str | None:
            value = (combo.currentText() or "").strip()
            return value or None

        pronoun_text = (self.pronouns.currentText() or "").strip()
        # If user landed on the sentinel without choosing a custom value, save nothing.
        if pronoun_text == _PRONOUN_CUSTOM_LABEL:
            pronoun_text = ""
        values = {
            "pronouns":            pronoun_text or None,
            "date_of_birth":       self.dob.text().strip() or None,
            "country_of_origin":   self.country_of_origin.text().strip() or None,
            "eeo_gender":          _combo_value(self.gender_identity),
            "transgender_status":  _combo_value(self.transgender_status),
            "hispanic_latino":     _combo_value(self.hispanic_latino),
            "eeo_race":            race_value,
            "sexual_orientation":  _combo_value(self.sexual_orientation),
            "eeo_veteran":         _combo_value(self.veteran_status),
            "eeo_disability":      _combo_value(self.disability_status),
            "needs_sponsorship":   _combo_value(self.needs_sponsorship),
        }
        cols = ", ".join(f"{k} = ?" for k in values)
        DB.execute(f"UPDATE profile SET {cols} WHERE id = 1", tuple(values.values()))
        DB.log_audit("demographics_updated")
        QMessageBox.information(self, "Saved", "Demographics saved.")


class _ApiKeysTab(QWidget):
    PLACEHOLDER = "•" * 24

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = _tab_outer(self)

        outer.addWidget(_section_header(
            "AI provider keys",
            "Keys are encrypted with Windows DPAPI before being stored locally. "
            "Without any key, the app runs in rule-based fallback mode — usable "
            "but no AI-driven tailoring, generation, or recommendations."
        ))

        card, card_layout = _card()
        form = _make_form()

        self.claude_field = QLineEdit()
        self.claude_field.setEchoMode(QLineEdit.Password)
        self.claude_field.setPlaceholderText("sk-ant-…")
        self.claude_status = QLabel("")
        self.openai_field = QLineEdit()
        self.openai_field.setEchoMode(QLineEdit.Password)
        self.openai_field.setPlaceholderText("sk-…")
        self.openai_status = QLabel("")
        self.adzuna_id_field = QLineEdit()
        self.adzuna_id_field.setEchoMode(QLineEdit.Password)
        self.adzuna_id_field.setPlaceholderText("Adzuna app_id")
        self.adzuna_id_status = QLabel("")
        self.adzuna_key_field = QLineEdit()
        self.adzuna_key_field.setEchoMode(QLineEdit.Password)
        self.adzuna_key_field.setPlaceholderText("Adzuna app_key")
        self.adzuna_key_status = QLabel("")

        form.addRow(_styled_label("Claude API key"), self._field_with_status(self.claude_field, self.claude_status))
        form.addRow(_styled_label("OpenAI API key"), self._field_with_status(self.openai_field, self.openai_status))
        form.addRow(_styled_label("Adzuna app_id"), self._field_with_status(self.adzuna_id_field, self.adzuna_id_status))
        form.addRow(_styled_label("Adzuna app_key"), self._field_with_status(self.adzuna_key_field, self.adzuna_key_status))

        card_layout.addLayout(form)

        pref_row = QHBoxLayout()
        pref_label = _styled_label("Preferred provider:")
        self.pref_group = QButtonGroup(self)
        self.radio_claude = QRadioButton("Claude")
        self.radio_openai = QRadioButton("OpenAI")
        self.pref_group.addButton(self.radio_claude)
        self.pref_group.addButton(self.radio_openai)
        pref_row.addWidget(pref_label)
        pref_row.addSpacing(8)
        pref_row.addWidget(self.radio_claude)
        pref_row.addSpacing(20)
        pref_row.addWidget(self.radio_openai)
        pref_row.addStretch(1)
        card_layout.addLayout(pref_row)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("Save keys")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._save)
        save_row.addWidget(save_btn)
        card_layout.addLayout(save_row)

        outer.addWidget(card)
        outer.addStretch(1)
        self._load()

    def _field_with_status(self, field: QLineEdit, status: QLabel) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(field, 1)
        row.addWidget(status)
        wrapper = QWidget()
        wrapper.setLayout(row)
        return wrapper

    def _set_field_status(self, field: QLineEdit, status: QLabel, provider: str):
        if llm_keys.is_configured(provider):
            field.setText(self.PLACEHOLDER)
            status.setText("✓ Configured")
            status.setStyleSheet(
                f"QLabel {{ color: {config.COLOR_ACCENT}; font-weight: 600; }}"
            )
        else:
            status.setText("Not set")
            status.setStyleSheet(f"QLabel {{ color: {config.COLOR_TEXT_FAINT}; }}")

    def _load(self):
        self._set_field_status(self.claude_field, self.claude_status, "claude")
        self._set_field_status(self.openai_field, self.openai_status, "openai")
        self._set_field_status(self.adzuna_id_field, self.adzuna_id_status, "adzuna_app_id")
        self._set_field_status(self.adzuna_key_field, self.adzuna_key_status, "adzuna_app_key")
        pref = llm_keys.get_preference()
        if pref == "openai":
            self.radio_openai.setChecked(True)
        else:
            self.radio_claude.setChecked(True)

    def _persist_field(self, field: QLineEdit, provider: str):
        value = field.text()
        if value and value != self.PLACEHOLDER:
            llm_keys.store_key(provider, value.strip())
        elif not value:
            llm_keys.store_key(provider, None)

    def _save(self):
        self._persist_field(self.claude_field, "claude")
        self._persist_field(self.openai_field, "openai")
        self._persist_field(self.adzuna_id_field, "adzuna_app_id")
        self._persist_field(self.adzuna_key_field, "adzuna_app_key")
        llm_keys.set_preference("openai" if self.radio_openai.isChecked() else "claude")
        DB.log_audit("api_keys_updated")
        self._load()
        QMessageBox.information(self, "Saved", "API key settings saved.")


# ----------------------------------------------------------------------------
# Pipeline stages — vertical list of editable rows with a swatch color picker.
# ----------------------------------------------------------------------------

PIPELINE_STAGE_PRESETS = [
    ("Red",     "#e53935"),
    ("Orange",  "#fb8c00"),
    ("Yellow",  "#fdd835"),
    ("Green",   "#43a047"),
    ("Teal",    "#00897b"),
    ("Blue",    "#1e88e5"),
    ("Indigo",  "#5e35b1"),
    ("Purple",  "#8e24aa"),
    ("Pink",    "#d81b60"),
    ("Gray",    "#5b5b5b"),
]


class _ColorSwatchPopup(QFrame):
    """Floating panel with 10 preset color swatches plus a Custom... fallback
    that opens the full color wheel."""
    color_chosen = Signal(str)

    def __init__(self, current: str, parent=None):
        super().__init__(parent)
        self.setObjectName("ColorPopup")
        self.setFrameShape(QFrame.StyledPanel)
        self.setWindowFlags(Qt.Popup)
        self.setStyleSheet(
            f"#ColorPopup {{ background: {config.COLOR_BG_RAISED}; "
            f"border: 1px solid {config.COLOR_BORDER_LIGHT}; border-radius: 8px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("Pick a color")
        title.setStyleSheet(
            f"color: {config.COLOR_TEXT}; font-size: 12px; font-weight: 700;"
        )
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(6)
        for i, (name, hex_code) in enumerate(PIPELINE_STAGE_PRESETS):
            btn = QPushButton()
            btn.setFixedSize(32, 32)
            btn.setToolTip(f"{name}  ({hex_code})")
            btn.setCursor(Qt.PointingHandCursor)
            selected = current.lower() == hex_code.lower()
            border = config.COLOR_TEXT if selected else "transparent"
            btn.setStyleSheet(
                f"QPushButton {{ background: {hex_code}; "
                f"border: 2px solid {border}; border-radius: 16px; }}"
                f"QPushButton:hover {{ border: 2px solid {config.COLOR_TEXT}; }}"
            )
            btn.clicked.connect(lambda _c=False, h=hex_code: self._pick(h))
            grid.addWidget(btn, i // 5, i % 5)
        layout.addLayout(grid)

        custom = QPushButton("Custom color wheel…")
        custom.setObjectName("GhostButton")
        custom.clicked.connect(self._custom_pick)
        layout.addWidget(custom)

        self._current = current

    def _pick(self, hex_code: str):
        self.color_chosen.emit(hex_code)
        self.close()

    def _custom_pick(self):
        chosen = QColorDialog.getColor(QColor(self._current), self, "Pick a custom color")
        if chosen.isValid():
            self.color_chosen.emit(chosen.name())
        self.close()


class _StageRow(QFrame):
    """One pipeline stage: color swatch + name input + move/remove buttons."""
    move_up_clicked   = Signal(object)
    move_down_clicked = Signal(object)
    remove_clicked    = Signal(object)
    changed           = Signal()

    def __init__(self, stage_id: int | None = None, name: str = "",
                 color: str = "#5b5b5b", parent=None):
        super().__init__(parent)
        self.stage_id = stage_id
        self.color = color

        self.setObjectName("StageRow")
        self.setStyleSheet(
            f"#StageRow {{ background: {config.COLOR_BG_RAISED}; "
            f"border-radius: 6px; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        self.swatch = QPushButton()
        self.swatch.setFixedSize(32, 32)
        self.swatch.setCursor(Qt.PointingHandCursor)
        self.swatch.setToolTip("Click to pick a color")
        self.swatch.clicked.connect(self._open_picker)
        self._update_swatch()
        layout.addWidget(self.swatch)

        self.name_input = QLineEdit(name)
        self.name_input.setPlaceholderText("Stage name")
        nf = self.name_input.font()
        nf.setPointSize(12)
        self.name_input.setFont(nf)
        self.name_input.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none; "
            f"color: {config.COLOR_TEXT}; padding: 6px 4px; }}"
            f"QLineEdit:focus {{ border-bottom: 1px solid {config.COLOR_ACCENT}; "
            f"padding-bottom: 5px; }}"
        )
        self.name_input.textChanged.connect(lambda _t: self.changed.emit())
        layout.addWidget(self.name_input, 1)

        for sym, slot, tip in (
            ("↑", self.move_up_clicked,   "Move up"),
            ("↓", self.move_down_clicked, "Move down"),
            ("✕", self.remove_clicked,    "Remove stage"),
        ):
            b = QPushButton(sym)
            b.setFixedSize(30, 30)
            b.setObjectName("GhostButton")
            b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, s=slot: s.emit(self))
            layout.addWidget(b)

    def _update_swatch(self):
        self.swatch.setStyleSheet(
            f"QPushButton {{ background: {self.color}; "
            f"border: 2px solid {config.COLOR_BORDER_LIGHT}; border-radius: 16px; }}"
            f"QPushButton:hover {{ border: 2px solid {config.COLOR_TEXT}; }}"
        )

    def _open_picker(self):
        popup = _ColorSwatchPopup(self.color, self.window())
        popup.color_chosen.connect(self._set_color)
        # Anchor below the swatch button.
        pos = self.swatch.mapToGlobal(self.swatch.rect().bottomLeft())
        popup.adjustSize()
        popup.move(pos)
        popup.show()

    def _set_color(self, hex_code: str):
        self.color = hex_code
        self._update_swatch()
        self.changed.emit()

    @property
    def name_text(self) -> str:
        return self.name_input.text().strip()


class _StagesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        outer = _tab_outer(self)

        outer.addWidget(_section_header(
            "Pipeline stages",
            "Rename, reorder, and recolor the stages used across the dashboard "
            "funnel and the pipeline list. Click a color swatch to pick from 10 "
            "presets or open the full color wheel."
        ))

        card, card_layout = _card()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumHeight(380)
        host = QWidget()
        self._rows_layout = QVBoxLayout(host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(8)
        self._rows_layout.addStretch(1)
        scroll.setWidget(host)
        card_layout.addWidget(scroll)

        btns = QHBoxLayout()
        add_btn = QPushButton("+ Add stage")
        add_btn.clicked.connect(self._add_blank_stage)
        btns.addWidget(add_btn)
        btns.addStretch(1)
        save_btn = QPushButton("Save stages")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._save)
        btns.addWidget(save_btn)
        card_layout.addLayout(btns)

        outer.addWidget(card)
        outer.addStretch(1)

        self._rows: list[_StageRow] = []
        self._load()

    # ---------- rendering ----------

    def _load(self):
        for row in list(self._rows):
            self._rows_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()
        records = DB.query(
            "SELECT id, name, sort_order, color FROM pipeline_stages ORDER BY sort_order"
        )
        for r in records:
            self._append_row(_StageRow(r["id"], r["name"], r["color"] or "#5b5b5b"))

    def _append_row(self, row: _StageRow):
        row.move_up_clicked.connect(self._on_move_up)
        row.move_down_clicked.connect(self._on_move_down)
        row.remove_clicked.connect(self._on_remove)
        # Insert before the trailing stretch.
        insert_at = max(0, self._rows_layout.count() - 1)
        self._rows_layout.insertWidget(insert_at, row)
        self._rows.append(row)

    def _add_blank_stage(self):
        self._append_row(_StageRow(None, "", "#5b5b5b"))
        self._rows[-1].name_input.setFocus()

    # ---------- reorder / remove ----------

    def _on_move_up(self, row: _StageRow):
        if row not in self._rows:
            return
        i = self._rows.index(row)
        if i == 0:
            return
        self._rows[i], self._rows[i - 1] = self._rows[i - 1], self._rows[i]
        self._rows_layout.removeWidget(row)
        self._rows_layout.insertWidget(i - 1, row)

    def _on_move_down(self, row: _StageRow):
        if row not in self._rows:
            return
        i = self._rows.index(row)
        if i >= len(self._rows) - 1:
            return
        self._rows[i], self._rows[i + 1] = self._rows[i + 1], self._rows[i]
        self._rows_layout.removeWidget(row)
        self._rows_layout.insertWidget(i + 1, row)

    def _on_remove(self, row: _StageRow):
        if row.stage_id is not None:
            in_use = DB.query_one(
                "SELECT COUNT(*) AS n FROM applications WHERE current_stage_id = ?",
                (row.stage_id,),
            )
            if in_use and in_use["n"] > 0:
                QMessageBox.warning(
                    self, "In use",
                    "Cannot remove a stage that has applications assigned to it. "
                    "Move those applications to a different stage first."
                )
                return
        self._rows.remove(row)
        self._rows_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()

    # ---------- save ----------

    def _save(self):
        seen: set[str] = set()
        existing_ids = {r["id"] for r in DB.query("SELECT id FROM pipeline_stages")}
        kept: set[int] = set()
        for order_idx, row in enumerate(self._rows, start=1):
            name = row.name_text
            if not name:
                continue
            if name in seen:
                QMessageBox.warning(self, "Duplicate", f"Stage name '{name}' is duplicated.")
                return
            seen.add(name)
            color = row.color or "#5b5b5b"
            if row.stage_id is None:
                new_id = DB.execute(
                    "INSERT INTO pipeline_stages (name, sort_order, color) VALUES (?, ?, ?)",
                    (name, order_idx, color),
                )
                row.stage_id = new_id
            else:
                DB.execute(
                    "UPDATE pipeline_stages SET name = ?, sort_order = ?, color = ? WHERE id = ?",
                    (name, order_idx, color, row.stage_id),
                )
                kept.add(row.stage_id)
        for stale in existing_ids - kept:
            in_use = DB.query_one(
                "SELECT COUNT(*) AS n FROM applications WHERE current_stage_id = ?",
                (stale,),
            )
            if not in_use or in_use["n"] == 0:
                DB.execute("DELETE FROM pipeline_stages WHERE id = ?", (stale,))
        DB.log_audit("pipeline_stages_updated")
        self._load()
        QMessageBox.information(self, "Saved", "Pipeline stages saved.")


class _ResumeTypeRow(QFrame):
    """One resume type: inline-editable name + version count badge + delete."""
    remove_clicked = Signal(object)

    def __init__(self, type_id: int, name: str, version_count: int, parent=None):
        super().__init__(parent)
        self.type_id = type_id
        self.original_name = name
        self.version_count = version_count

        self.setObjectName("TypeRow")
        self.setStyleSheet(
            f"#TypeRow {{ background: {config.COLOR_BG_RAISED}; border-radius: 6px; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        self.name_input = QLineEdit(name)
        self.name_input.setPlaceholderText("Resume type name")
        nf = self.name_input.font()
        nf.setPointSize(12)
        self.name_input.setFont(nf)
        self.name_input.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none; "
            f"color: {config.COLOR_TEXT}; padding: 6px 4px; }}"
            f"QLineEdit:focus {{ border-bottom: 1px solid {config.COLOR_ACCENT}; "
            f"padding-bottom: 5px; }}"
        )
        layout.addWidget(self.name_input, 1)

        badge_text = f"{version_count} version" + ("s" if version_count != 1 else "")
        badge = QLabel(badge_text)
        badge.setStyleSheet(
            f"color: {config.COLOR_TEXT_DIM}; background: {config.COLOR_BG_HOVER}; "
            f"padding: 4px 10px; border-radius: 10px; font-size: 11px;"
        )
        layout.addWidget(badge)

        rm = QPushButton("Delete")
        rm.setObjectName("GhostButton")
        rm.setStyleSheet(
            f"QPushButton {{ color: {config.COLOR_ACCENT}; border: 1px solid {config.COLOR_BORDER_LIGHT}; "
            f"padding: 6px 12px; border-radius: 4px; background: transparent; }}"
            f"QPushButton:hover {{ background: {config.COLOR_ACCENT_SOFT}; }}"
        )
        rm.clicked.connect(lambda: self.remove_clicked.emit(self))
        layout.addWidget(rm)

    @property
    def name_text(self) -> str:
        return self.name_input.text().strip()


class _ResumeTypesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        outer = _tab_outer(self)

        outer.addWidget(_section_header(
            "Resume types",
            "Master list of resume categories. Each type retains its 5 most recent "
            "versions automatically. You can also create a new type on the fly from "
            "the Resume Editor toolbar."
        ))

        card, card_layout = _card()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumHeight(320)
        host = QWidget()
        self._rows_layout = QVBoxLayout(host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(8)
        self._rows_layout.addStretch(1)
        scroll.setWidget(host)
        card_layout.addWidget(scroll)

        btns = QHBoxLayout()
        add_btn = QPushButton("+ Add type")
        add_btn.clicked.connect(self._add_blank)
        btns.addWidget(add_btn)
        btns.addStretch(1)
        save_btn = QPushButton("Save renames")
        save_btn.setObjectName("PrimaryButton")
        save_btn.setToolTip("Save any inline name edits. Deletes apply immediately.")
        save_btn.clicked.connect(self._save_renames)
        btns.addWidget(save_btn)
        card_layout.addLayout(btns)

        outer.addWidget(card)
        outer.addStretch(1)

        self._rows: list[_ResumeTypeRow] = []
        self._load()

    def _load(self):
        for row in list(self._rows):
            self._rows_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()
        records = DB.query("""
            SELECT t.id, t.name,
                   (SELECT COUNT(*) FROM resume_versions v WHERE v.resume_type_id = t.id) AS version_count
            FROM resume_types t
            ORDER BY t.name
        """)
        for r in records:
            self._append_row(_ResumeTypeRow(r["id"], r["name"], r["version_count"]))

    def _append_row(self, row: _ResumeTypeRow):
        row.remove_clicked.connect(self._on_delete)
        insert_at = max(0, self._rows_layout.count() - 1)
        self._rows_layout.insertWidget(insert_at, row)
        self._rows.append(row)

    def _add_blank(self):
        name, ok = QInputDialog.getText(self, "New resume type", "Name (e.g. 'Engineering Resume'):")
        if not ok or not name.strip():
            return
        clean = name.strip()
        existing = DB.query_one("SELECT id FROM resume_types WHERE name = ?", (clean,))
        if existing:
            QMessageBox.warning(self, "Already exists", f"A resume type named '{clean}' already exists.")
            return
        resume_versions.create_resume_type(clean)
        DB.log_audit("resume_type_created", {"name": clean})
        self._load()

    def _on_delete(self, row: _ResumeTypeRow):
        if row.version_count > 0:
            confirm = QMessageBox.warning(
                self, "Delete with versions?",
                f"'{row.original_name}' has {row.version_count} saved version(s). "
                f"Deleting will permanently remove them too. Continue?",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
            )
            if confirm != QMessageBox.Yes:
                return
        resume_versions.delete_resume_type(row.type_id)
        DB.log_audit("resume_type_deleted", {"id": row.type_id, "name": row.original_name})
        self._load()

    def _save_renames(self):
        renamed = 0
        seen: set[str] = set()
        for row in self._rows:
            new_name = row.name_text
            if not new_name:
                QMessageBox.warning(self, "Empty name", "Resume type names can't be blank.")
                return
            if new_name in seen:
                QMessageBox.warning(self, "Duplicate", f"Resume type '{new_name}' is duplicated.")
                return
            seen.add(new_name)
            if new_name == row.original_name:
                continue
            clash = DB.query_one(
                "SELECT id FROM resume_types WHERE name = ? AND id != ?",
                (new_name, row.type_id),
            )
            if clash:
                QMessageBox.warning(
                    self, "Already exists",
                    f"A resume type named '{new_name}' already exists.",
                )
                return
            resume_versions.rename_resume_type(row.type_id, new_name)
            DB.log_audit("resume_type_renamed", {"id": row.type_id, "name": new_name})
            renamed += 1
        if renamed:
            QMessageBox.information(self, "Saved", f"Renamed {renamed} resume type(s).")
        else:
            QMessageBox.information(self, "No changes", "Nothing to rename.")
        self._load()


class _BackupTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        outer = _tab_outer(self)

        outer.addWidget(_section_header(
            "Backup & restore",
            f"Your local database lives at:  {config.DB_PATH}"
        ))

        card, card_layout = _card()
        info = QLabel(
            "Export creates a JSON snapshot of every table — safe to commit to a "
            "private Git repo or stash on a USB stick. Restore replaces current "
            "data with the contents of a snapshot (Phase 6)."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {config.COLOR_TEXT_DIM};")
        card_layout.addWidget(info)

        row = QHBoxLayout()
        export_btn = QPushButton("Export to JSON…")
        export_btn.clicked.connect(self._export)
        import_btn = QPushButton("Restore from JSON…")
        import_btn.clicked.connect(self._restore)
        row.addWidget(export_btn)
        row.addWidget(import_btn)
        row.addStretch(1)
        card_layout.addLayout(row)

        outer.addWidget(card)
        outer.addStretch(1)

    def _export(self):
        import json
        path, _ = QFileDialog.getSaveFileName(self, "Export to JSON", "jobhunt-backup.json", "JSON (*.json)")
        if not path:
            return
        tables = [r["name"] for r in DB.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        snapshot = {}
        for t in tables:
            rows = DB.query(f"SELECT * FROM {t}")
            snapshot[t] = [dict(r) for r in rows]
        for t in snapshot:
            for row in snapshot[t]:
                for k, v in list(row.items()):
                    if isinstance(v, bytes):
                        row[k] = {"__bytes__": v.hex()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, default=str)
        DB.log_audit("backup_exported", {"path": path})
        QMessageBox.information(self, "Exported", f"Backup saved to:\n{path}")

    def _restore(self):
        QMessageBox.information(
            self, "Restore",
            "Restore is implemented in Phase 6 with proper validation. "
            "For now, you can manually replace the database file:\n\n"
            f"{config.DB_PATH}"
        )


class _CalendarTab(QWidget):
    """Connect / disconnect Google Calendar and view the detected provider.
    Outlook is configured via the existing IMAP tab; this tab just reports its
    status so the user can see everything in one place."""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = _tab_outer(self)

        outer.addWidget(_section_header(
            "Calendar integration",
            "Push interview events to your calendar from any interview's detail "
            "dialog. JobHunt picks Google or Outlook based on your profile email; "
            "you can also switch providers by changing that email."
        ))

        # Provider summary card
        self.provider_card, plc = _card()
        outer.addWidget(self.provider_card)

        provider_title = QLabel("Detected provider")
        provider_title.setStyleSheet(
            f"QLabel {{ color: {config.COLOR_ACCENT}; font-size: 13px; "
            f"font-weight: 700; }}"
        )
        plc.addWidget(provider_title)
        self.provider_label = QLabel("…")
        self.provider_label.setStyleSheet(
            f"QLabel {{ color: {config.COLOR_TEXT}; font-size: 14px; padding: 4px 0; }}"
        )
        self.provider_label.setWordWrap(True)
        plc.addWidget(self.provider_label)
        self.provider_hint = QLabel("")
        self.provider_hint.setStyleSheet(
            f"QLabel {{ color: {config.COLOR_TEXT_DIM}; font-size: 12px; }}"
        )
        self.provider_hint.setWordWrap(True)
        plc.addWidget(self.provider_hint)

        # Google card
        self.google_card, gc = _card()
        outer.addWidget(self.google_card)
        gc_title = QLabel("Google Calendar")
        gc_title.setStyleSheet(
            f"QLabel {{ color: {config.COLOR_ACCENT}; font-size: 13px; "
            f"font-weight: 700; }}"
        )
        gc.addWidget(gc_title)
        self.google_status = QLabel("…")
        self.google_status.setWordWrap(True)
        self.google_status.setStyleSheet(
            f"QLabel {{ color: {config.COLOR_TEXT}; font-size: 13px; padding: 4px 0 8px 0; }}"
        )
        gc.addWidget(self.google_status)
        google_row = QHBoxLayout()
        self.google_connect_btn = QPushButton("Connect Google Calendar")
        self.google_connect_btn.setObjectName("PrimaryButton")
        self.google_connect_btn.clicked.connect(self._on_connect_google)
        google_row.addWidget(self.google_connect_btn)
        self.google_disconnect_btn = QPushButton("Disconnect")
        self.google_disconnect_btn.setStyleSheet(
            f"QPushButton {{ color: {config.COLOR_ACCENT}; border: 1px solid "
            f"{config.COLOR_BORDER_LIGHT}; padding: 8px 16px; border-radius: 4px; "
            f"background: transparent; }}"
            f"QPushButton:hover {{ background: {config.COLOR_ACCENT_SOFT}; }}"
        )
        self.google_disconnect_btn.clicked.connect(self._on_disconnect_google)
        google_row.addWidget(self.google_disconnect_btn)
        google_row.addStretch(1)
        gc.addLayout(google_row)
        self.google_setup_hint = QLabel("")
        self.google_setup_hint.setTextFormat(Qt.RichText)
        self.google_setup_hint.setOpenExternalLinks(True)
        self.google_setup_hint.setWordWrap(True)
        self.google_setup_hint.setStyleSheet(
            f"QLabel {{ color: {config.COLOR_TEXT_DIM}; font-size: 11px; "
            f"padding-top: 8px; }}"
        )
        gc.addWidget(self.google_setup_hint)

        # Outlook card
        outlook_card, oc = _card()
        outer.addWidget(outlook_card)
        oc_title = QLabel("Microsoft Outlook")
        oc_title.setStyleSheet(
            f"QLabel {{ color: {config.COLOR_ACCENT}; font-size: 13px; "
            f"font-weight: 700; }}"
        )
        oc.addWidget(oc_title)
        self.outlook_status = QLabel("…")
        self.outlook_status.setWordWrap(True)
        self.outlook_status.setStyleSheet(
            f"QLabel {{ color: {config.COLOR_TEXT}; font-size: 13px; padding: 4px 0 8px 0; }}"
        )
        oc.addWidget(self.outlook_status)
        outlook_btn_row = QHBoxLayout()
        self.outlook_reauth_btn = QPushButton("Re-authorize Microsoft")
        self.outlook_reauth_btn.setToolTip(
            "Sign in to Microsoft again to grant Calendars.ReadWrite permission. "
            "Required for Outlook calendar push if you signed in before May 2026."
        )
        self.outlook_reauth_btn.clicked.connect(self._on_reauth_outlook)
        outlook_btn_row.addWidget(self.outlook_reauth_btn)
        outlook_btn_row.addStretch(1)
        oc.addLayout(outlook_btn_row)

        outlook_hint = QLabel(
            "Outlook uses the Microsoft OAuth account configured in the "
            "<b>IMAP</b> tab. Sign in there first to enable Outlook calendar push. "
            "If you signed in before calendar support landed, click "
            "<b>Re-authorize Microsoft</b> to grant the new permission."
        )
        outlook_hint.setTextFormat(Qt.RichText)
        outlook_hint.setStyleSheet(
            f"QLabel {{ color: {config.COLOR_TEXT_DIM}; font-size: 11px; }}"
        )
        outlook_hint.setWordWrap(True)
        oc.addWidget(outlook_hint)

        outer.addStretch(1)
        self._refresh()

    # ------------------------------------------------------------------ render

    def _refresh(self):
        from ...interviews import calendar as cal_mod
        from ...interviews import google_calendar as gcal

        provider = cal_mod.detect_provider()
        row = DB.query_one("SELECT email FROM profile WHERE id = 1")
        profile_email = (row["email"] if row else "") or "(no email set)"
        if provider == cal_mod.PROVIDER_GOOGLE:
            self.provider_label.setText(
                f"Google Calendar — based on profile email <b>{profile_email}</b>"
            )
            self.provider_hint.setText(
                "Change your Profile email if you want to switch to Outlook."
            )
        else:
            self.provider_label.setText(
                f"Microsoft Outlook — based on profile email <b>{profile_email}</b>"
            )
            self.provider_hint.setText(
                "Gmail addresses (gmail.com / googlemail.com) auto-route to "
                "Google Calendar instead."
            )
        self.provider_label.setTextFormat(Qt.RichText)

        # Google card state
        from ... import config as cfg
        if not cfg.GOOGLE_CLIENT_ID:
            self.google_status.setText("⚠ Not configured.")
            self.google_setup_hint.setText(
                "Set <code>GOOGLE_CLIENT_ID</code> in <code>jobhunt/config.py</code>. "
                "Create a Desktop OAuth client at "
                "<a href='https://console.cloud.google.com/' "
                "style='color:#1e88e5'>console.cloud.google.com</a>, enable the "
                "Google Calendar API, and paste the client_id."
            )
            self.google_connect_btn.setEnabled(False)
            self.google_disconnect_btn.setVisible(False)
        elif gcal.is_connected():
            email = gcal.stored_email() or "(unknown)"
            self.google_status.setText(
                f"✓ Connected as <b>{email}</b>. Calendar event creation enabled."
            )
            self.google_status.setTextFormat(Qt.RichText)
            self.google_setup_hint.setText("")
            self.google_connect_btn.setText("Reconnect")
            self.google_connect_btn.setEnabled(True)
            self.google_disconnect_btn.setVisible(True)
        else:
            self.google_status.setText(
                "Not signed in yet. Click <b>Connect</b> to authorize JobHunt to "
                "create calendar events on your behalf."
            )
            self.google_status.setTextFormat(Qt.RichText)
            self.google_setup_hint.setText("")
            self.google_connect_btn.setText("Connect Google Calendar")
            self.google_connect_btn.setEnabled(True)
            self.google_disconnect_btn.setVisible(False)

        # Outlook card state
        from ...interviews import outlook as outlook_mod
        account = outlook_mod.find_oauth_account()
        if account is None:
            self.outlook_status.setText(
                "No Microsoft account linked. Outlook push will fail until one "
                "is configured."
            )
        else:
            self.outlook_status.setText(
                f"✓ Linked to <b>{account.get('username') or '(unknown)'}</b> "
                f"(auth type: {account.get('auth_type') or 'unknown'})."
            )
            self.outlook_status.setTextFormat(Qt.RichText)

    # ------------------------------------------------------------------ actions

    def _on_connect_google(self):
        from ... import config as cfg
        from ...interviews import google_calendar as gcal
        if not cfg.GOOGLE_CLIENT_ID:
            QMessageBox.warning(
                self, "Google Calendar not configured",
                "Set GOOGLE_CLIENT_ID in jobhunt/config.py first."
            )
            return
        self.google_connect_btn.setEnabled(False)
        self.google_connect_btn.setText("Waiting for sign-in…")
        try:
            result = gcal.run_auth_code_flow()
        except gcal.GoogleAuthError as e:
            QMessageBox.warning(self, "Sign-in failed", str(e))
            self._refresh()
            return
        email = result.get("email") or "(unknown email)"
        QMessageBox.information(
            self, "Connected",
            f"Signed in to Google Calendar as {email}. You can now push "
            "interview events from the Interviews page."
        )
        self._refresh()

    def _on_reauth_outlook(self):
        from ...interviews import outlook as outlook_mod
        account = outlook_mod.find_oauth_account()
        if account is None:
            QMessageBox.information(
                self, "No Microsoft account",
                "Add a Microsoft account in Settings → IMAP first. The IMAP setup "
                "flow now requests Calendars.ReadWrite alongside Mail.Read."
            )
            return
        from ..dialogs.microsoft_signin import MicrosoftSignInDialog
        dlg = MicrosoftSignInDialog(self)
        if not (dlg.exec() and dlg.token_data):
            return
        tok = dlg.token_data
        from ...credentials import encrypt
        from ...mail.oauth_microsoft import expires_at_from_now, extract_email_from_id_token
        from ...db import DB as _DB
        new_email = extract_email_from_id_token(tok.get("id_token", "")) or account.get("username")
        _DB.execute(
            """UPDATE imap_accounts
               SET oauth_access_token = ?, oauth_refresh_token = ?, oauth_expires_at = ?,
                   username = COALESCE(?, username)
               WHERE id = ?""",
            (
                encrypt(tok["access_token"]),
                encrypt(tok.get("refresh_token", "")),
                expires_at_from_now(tok.get("expires_in", 3600)),
                new_email if new_email else None,
                account["id"],
            ),
        )
        _DB.log_audit("microsoft_reauthorized", {
            "account_id": account["id"], "scopes": "Mail.Read Calendars.ReadWrite",
        })
        QMessageBox.information(
            self, "Re-authorized",
            "Microsoft tokens refreshed with Calendars.ReadWrite. Outlook calendar "
            "push should now work."
        )
        self._refresh()

    def _on_disconnect_google(self):
        confirm = QMessageBox.question(
            self, "Disconnect Google Calendar",
            "Revoke JobHunt's access to your Google Calendar?\n\n"
            "Already-created events stay in your calendar. You'll need to "
            "sign in again to push new events.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return
        from ...interviews import google_calendar as gcal
        gcal.disconnect()
        self._refresh()


class _DangerZoneTab(QWidget):
    """Destructive operations. Lives in its own tab so the button is hard to
    hit by accident."""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = _tab_outer(self)

        outer.addWidget(_section_header(
            "Reset all data",
            "Wipes your local JobHunt database and audit log — every application, "
            "resume version, cover letter, story, email account, synonym group, "
            "API key, and profile field. This cannot be undone."
        ))

        card, card_layout = _card()

        warn = QLabel(
            "<b style='color:" + config.COLOR_ACCENT + "'>This is permanent.</b> "
            "Use Backup → Export to JSON first if you want a copy before resetting. "
            "After the reset, JobHunt will close — relaunch it to start fresh."
        )
        warn.setWordWrap(True)
        warn.setTextFormat(Qt.RichText)
        warn.setStyleSheet(f"color: {config.COLOR_TEXT}; font-size: 13px; padding: 4px 0 12px 0;")
        card_layout.addWidget(warn)

        paths_label = QLabel(
            f"Database:   {config.DB_PATH}\n"
            f"Log file:   {config.LOG_PATH}"
        )
        paths_label.setStyleSheet(
            f"color: {config.COLOR_TEXT_DIM}; font-family: 'Cascadia Mono', 'Consolas', monospace; "
            f"font-size: 11px; padding: 6px 8px; "
            f"background: {config.COLOR_BG_HOVER}; border-radius: 4px;"
        )
        card_layout.addWidget(paths_label)

        card_layout.addSpacing(12)

        confirm_row = QHBoxLayout()
        confirm_label = QLabel("Type <code>DELETE</code> to enable the button:")
        confirm_label.setTextFormat(Qt.RichText)
        confirm_label.setStyleSheet(f"color: {config.COLOR_TEXT};")
        confirm_row.addWidget(confirm_label)
        self._confirm_input = QLineEdit()
        self._confirm_input.setMaximumWidth(160)
        self._confirm_input.textChanged.connect(self._on_confirm_changed)
        confirm_row.addWidget(self._confirm_input)
        confirm_row.addStretch(1)
        card_layout.addLayout(confirm_row)

        card_layout.addSpacing(8)

        self._reset_btn = QPushButton("Delete all JobHunt data")
        self._reset_btn.setObjectName("PrimaryButton")
        self._reset_btn.setStyleSheet(
            f"QPushButton {{ background: {config.COLOR_ACCENT}; color: white; "
            f"padding: 10px 20px; border-radius: 4px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {config.COLOR_ACCENT_HOVER}; }}"
            f"QPushButton:disabled {{ background: {config.COLOR_BG_HOVER}; "
            f"color: {config.COLOR_TEXT_FAINT}; }}"
        )
        self._reset_btn.setEnabled(False)
        self._reset_btn.clicked.connect(self._on_reset)
        card_layout.addWidget(self._reset_btn)

        outer.addWidget(card)
        outer.addStretch(1)

    def _on_confirm_changed(self, text: str):
        self._reset_btn.setEnabled(text.strip() == "DELETE")

    def _on_reset(self):
        confirm = QMessageBox.question(
            self, "Final confirmation",
            "This will delete EVERYTHING in your local JobHunt install:\n\n"
            "  • all applications, resumes, cover letters, stories\n"
            "  • all email accounts and scan history\n"
            "  • all API keys and OAuth tokens\n"
            "  • all profile and demographics fields\n\n"
            "The app will close. Continue?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return

        from pathlib import Path
        from PySide6.QtWidgets import QApplication

        errors: list[str] = []

        # Close the DB connection so the file isn't locked on Windows.
        try:
            DB.close()
        except Exception as e:
            errors.append(f"close DB: {e}")

        for target in (config.DB_PATH, config.LOG_PATH):
            p = Path(target)
            if not p.exists():
                continue
            try:
                p.unlink()
            except Exception as e:
                errors.append(f"{p.name}: {e}")

        if errors:
            QMessageBox.warning(
                self, "Reset partially completed",
                "Some files couldn't be removed:\n\n" + "\n".join(errors) +
                "\n\nClose JobHunt and delete them manually if needed.",
            )
            return

        QMessageBox.information(
            self, "Reset complete",
            "All JobHunt data has been deleted. The app will close now — "
            "relaunch it to start fresh.",
        )
        QApplication.quit()


class _ScanWorker(QObject):
    done = Signal(dict)

    def __init__(self, account_ids: list[int]):
        super().__init__()
        self._ids = account_ids

    def run(self):
        from ...mail.scanner import scan_account
        from ...mail.classifier import classify_pending
        scan_results = [scan_account(aid) for aid in self._ids]
        classify_stats = classify_pending(max_emails=50)
        self.done.emit({"scans": scan_results, "classify": classify_stats})


class _ImapTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        outer = _tab_outer(self)

        outer.addWidget(_section_header(
            "IMAP accounts",
            "Add IMAP credentials for any email provider. Passwords are encrypted via Windows DPAPI "
            "before storage. Gmail / Yahoo / iCloud require an App Password — not your normal "
            "account password."
        ))

        # Auto-scan settings
        autoscan_card, autoscan_layout = _card()
        autoscan_row = QHBoxLayout()
        autoscan_row.setSpacing(14)
        self.autoscan_check = QCheckBox("Scan inbox automatically")
        self.autoscan_check.setChecked(DB.get_setting("auto_scan_enabled", "0") == "1")
        self.autoscan_check.stateChanged.connect(self._on_autoscan_changed)
        autoscan_row.addWidget(self.autoscan_check)
        autoscan_row.addWidget(QLabel("every"))
        self.autoscan_interval = QComboBox()
        for label, mins in [("15 minutes", 15), ("30 minutes", 30),
                            ("1 hour", 60), ("2 hours", 120)]:
            self.autoscan_interval.addItem(label, mins)
        current_interval = int(DB.get_setting("auto_scan_interval_min", "30") or "30")
        idx = self.autoscan_interval.findData(current_interval)
        if idx >= 0:
            self.autoscan_interval.setCurrentIndex(idx)
        self.autoscan_interval.currentIndexChanged.connect(self._on_autoscan_changed)
        autoscan_row.addWidget(self.autoscan_interval)
        autoscan_row.addStretch(1)
        autoscan_layout.addLayout(autoscan_row)
        outer.addWidget(autoscan_card)

        card, card_layout = _card()

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Display name", "Server", "Username", "Folder", "Enabled"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setMinimumHeight(220)
        self.table.itemDoubleClicked.connect(lambda *_: self._edit())
        card_layout.addWidget(self.table)

        btns = QHBoxLayout()
        add_btn = QPushButton("+ Add account")
        add_btn.clicked.connect(self._add)
        edit_btn = QPushButton("Edit selected")
        edit_btn.clicked.connect(self._edit)
        delete_btn = QPushButton("Delete selected")
        delete_btn.clicked.connect(self._delete)
        self.scan_btn = QPushButton("Scan now")
        self.scan_btn.setObjectName("PrimaryButton")
        self.scan_btn.clicked.connect(self._scan)
        btns.addWidget(add_btn)
        btns.addWidget(edit_btn)
        btns.addWidget(delete_btn)
        btns.addStretch(1)
        btns.addWidget(self.scan_btn)
        card_layout.addLayout(btns)

        self.scan_status = QLabel("")
        self.scan_status.setStyleSheet(f"color: {config.COLOR_TEXT_DIM};")
        self.scan_status.setWordWrap(True)
        card_layout.addWidget(self.scan_status)

        outer.addWidget(card)
        outer.addStretch(1)

        self._scan_thread: QThread | None = None
        self._scan_worker: _ScanWorker | None = None
        self._load()

    def _load(self):
        from ...mail.scanner import list_accounts
        accounts = list_accounts()
        self.table.setRowCount(len(accounts))
        for i, a in enumerate(accounts):
            name_item = QTableWidgetItem(a.get("display_name") or "—")
            name_item.setData(Qt.UserRole, a["id"])
            self.table.setItem(i, 0, name_item)
            self.table.setItem(i, 1, QTableWidgetItem(f"{a['server']}:{a['port'] or 993}"))
            self.table.setItem(i, 2, QTableWidgetItem(a["username"]))
            self.table.setItem(i, 3, QTableWidgetItem(a["folder_filter"] or "INBOX"))
            self.table.setItem(i, 4, QTableWidgetItem("Yes" if a["enabled"] else "No"))
        last = "—"
        rows = DB.query("SELECT MAX(last_scan_at) AS last FROM imap_accounts WHERE last_scan_at IS NOT NULL")
        if rows and rows[0]["last"]:
            last = rows[0]["last"][:16].replace("T", " ")
        self.scan_status.setText(f"Last scan: {last}")
        self.scan_status.setStyleSheet(f"color: {config.COLOR_TEXT_DIM};")

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _add(self):
        from ..dialogs.imap_account import IMAPAccountDialog
        dlg = IMAPAccountDialog(parent=self)
        if dlg.exec():
            self._load()

    def _edit(self):
        from ..dialogs.imap_account import IMAPAccountDialog
        aid = self._selected_id()
        if aid is None:
            return
        dlg = IMAPAccountDialog(account_id=aid, parent=self)
        if dlg.exec():
            self._load()

    def _delete(self):
        aid = self._selected_id()
        if aid is None:
            return
        confirm = QMessageBox.question(
            self, "Delete account",
            "Delete this account and all its fetched emails?",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return
        DB.execute("DELETE FROM imap_accounts WHERE id = ?", (aid,))
        DB.log_audit("imap_account_deleted", {"id": aid})
        self._load()

    def _scan(self):
        from ...mail.scanner import list_accounts
        if self._scan_thread and self._scan_thread.isRunning():
            return
        accounts = list_accounts(enabled_only=True)
        if not accounts:
            self.scan_status.setText("No enabled accounts to scan.")
            self.scan_status.setStyleSheet(f"color: {config.COLOR_ACCENT};")
            return

        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Scanning…")
        self.scan_status.setText(f"Scanning {len(accounts)} account(s)…")
        self.scan_status.setStyleSheet(f"color: {config.COLOR_TEXT_DIM};")

        self._scan_thread = QThread(self)
        self._scan_worker = _ScanWorker([a["id"] for a in accounts])
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.done.connect(self._on_scan_done)
        self._scan_worker.done.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.start()

    def _on_autoscan_changed(self):
        enabled = "1" if self.autoscan_check.isChecked() else "0"
        interval = str(self.autoscan_interval.currentData() or 30)
        DB.set_setting("auto_scan_enabled", enabled)
        DB.set_setting("auto_scan_interval_min", interval)
        DB.log_audit("auto_scan_settings_changed",
                     {"enabled": enabled, "interval_min": interval})
        from ...mail.scheduler import get_instance
        sched = get_instance()
        if sched is not None:
            sched.restart()

    def _on_scan_done(self, payload: dict):
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("Scan now")
        self._scan_thread = None
        self._scan_worker = None

        scans = payload.get("scans", [])
        classify = payload.get("classify", {})

        total = sum(r.get("new", 0) for r in scans)
        errors = [r for r in scans if r.get("error")]

        classify_bits: list[str] = []
        if classify.get("classified", 0) > 0:
            classify_bits.append(f"{classify['classified']} classified")
        if classify.get("matched", 0) > 0:
            classify_bits.append(f"{classify['matched']} matched to applications")
        if classify.get("stage_updates", 0) > 0:
            classify_bits.append(f"{classify['stage_updates']} stage update(s)")
        if classify.get("interviews_detected", 0) > 0:
            classify_bits.append(f"{classify['interviews_detected']} interview(s) added")
        classify_summary = (" · " + " · ".join(classify_bits)) if classify_bits else ""

        if errors:
            err_summary = "; ".join(
                f"acct {r['account_id']}: {r['error']}" for r in errors[:3]
            )
            self.scan_status.setText(
                f"Fetched {total} new email(s){classify_summary}. "
                f"{len(errors)} account(s) failed — {err_summary}"
            )
            self.scan_status.setStyleSheet(f"color: {config.COLOR_ACCENT};")
        else:
            self.scan_status.setText(f"✓ Fetched {total} new email(s){classify_summary}.")
            self.scan_status.setStyleSheet(f"color: {config.COLOR_ACCENT};")
        self._load()


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title = QLabel("Settings")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        tabs = QTabWidget()
        tabs.tabBar().setExpanding(False)
        tabs.tabBar().setUsesScrollButtons(False)
        tabs.tabBar().setElideMode(Qt.ElideNone)
        tabs.addTab(_ProfileTab(), "Profile")
        tabs.addTab(_DemographicsTab(), "Demographics")
        tabs.addTab(_ApiKeysTab(), "API Keys")
        tabs.addTab(_StagesTab(), "Pipeline Stages")
        tabs.addTab(_ResumeTypesTab(), "Resume Types")
        tabs.addTab(_BackupTab(), "Backup")
        tabs.addTab(_ImapTab(), "IMAP")
        tabs.addTab(_CalendarTab(), "Calendar")
        tabs.addTab(_DangerZoneTab(), "Reset")
        layout.addWidget(tabs, 1)

    def ai_context(self) -> dict:
        configured = llm_keys.configured_providers()
        types = DB.query("SELECT name FROM resume_types")
        stages = DB.query("SELECT name FROM pipeline_stages")
        return {
            "page": "Settings",
            "summary": (
                f"{'AI configured' if configured else 'No AI key configured'} · "
                f"{len(types)} resume types · {len(stages)} pipeline stages"
            ),
            "data": {
                "ai_configured": configured,
                "resume_type_count": len(types),
                "stage_names": [s["name"] for s in stages],
            },
            "rule_based_hints": [
                "Set up at least one API key (Claude or OpenAI) under API Keys to unlock AI features.",
                "Fill in your Profile so ATS forms auto-fill correctly later in Phase 4.",
                "Add at least one Resume Type so you can import a resume and start tailoring.",
                "Export a JSON backup before making big changes — restore lands in Phase 6.",
            ],
        }
