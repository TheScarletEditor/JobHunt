from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QInputDialog,
    QMessageBox, QFileDialog, QTabWidget, QFrame, QLineEdit, QMenu,
    QPlainTextEdit, QStackedWidget, QScrollArea, QSizePolicy, QToolButton,
)

from ... import config
from ...db import DB
from ...documents import parser, versions as ver
from ...documents.model import ResumeContent
from ..dialogs.parse_resume_progress import ParseResumeDialog
from ..widgets.resume_editor import ResumeEditor


class _SynonymGroupRow(QFrame):
    """One synonym group: comma-separated terms input + remove button."""
    remove_clicked = Signal(object)

    def __init__(self, group_id: int | None = None, terms: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.group_id = group_id

        self.setObjectName("GroupRow")
        self.setStyleSheet(
            f"#GroupRow {{ background: {config.COLOR_BG_RAISED}; border-radius: 6px; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        self.terms_input = QLineEdit(", ".join(terms or []))
        self.terms_input.setPlaceholderText(
            "Comma-separated interchangeable terms — e.g. React, React.js, ReactJS"
        )
        tf = self.terms_input.font()
        tf.setPointSize(12)
        self.terms_input.setFont(tf)
        self.terms_input.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none; "
            f"color: {config.COLOR_TEXT}; padding: 6px 4px; }}"
            f"QLineEdit:focus {{ border-bottom: 1px solid {config.COLOR_ACCENT}; "
            f"padding-bottom: 5px; }}"
        )
        layout.addWidget(self.terms_input, 1)

        rm = QPushButton("✕")
        rm.setFixedSize(30, 30)
        rm.setObjectName("GhostButton")
        rm.setToolTip("Remove group")
        rm.clicked.connect(lambda: self.remove_clicked.emit(self))
        layout.addWidget(rm)

    @property
    def terms(self) -> list[str]:
        return [t.strip() for t in self.terms_input.text().split(",") if t.strip()]


class _SynonymsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        title = QLabel("Synonym groups")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        info = QLabel(
            "Each row is one group of interchangeable terms. When you tailor a resume "
            "against a job listing, the AI is allowed to swap among the terms in a group "
            "if the listing uses one of them. Need at least 2 terms per group."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {config.COLOR_TEXT_DIM};")
        layout.addWidget(info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumHeight(360)
        host = QWidget()
        self._rows_layout = QVBoxLayout(host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(8)
        self._rows_layout.addStretch(1)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)

        btns = QHBoxLayout()
        add_btn = QPushButton("+ Add group")
        add_btn.clicked.connect(self._add_blank_group)
        btns.addWidget(add_btn)
        btns.addStretch(1)
        save_btn = QPushButton("Save groups")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._save)
        btns.addWidget(save_btn)
        layout.addLayout(btns)

        self._rows: list[_SynonymGroupRow] = []
        self._load()

    def _load(self):
        for row in list(self._rows):
            self._rows_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()
        records = DB.query("SELECT id, terms_json FROM synonym_groups ORDER BY id")
        for r in records:
            try:
                terms = json.loads(r["terms_json"])
            except Exception:
                terms = []
            if not isinstance(terms, list):
                terms = []
            self._append_row(_SynonymGroupRow(r["id"], [str(t) for t in terms]))

    def _append_row(self, row: _SynonymGroupRow):
        row.remove_clicked.connect(self._on_remove)
        insert_at = max(0, self._rows_layout.count() - 1)
        self._rows_layout.insertWidget(insert_at, row)
        self._rows.append(row)

    def _add_blank_group(self):
        self._append_row(_SynonymGroupRow(None, []))
        self._rows[-1].terms_input.setFocus()

    def _on_remove(self, row: _SynonymGroupRow):
        if row not in self._rows:
            return
        self._rows.remove(row)
        self._rows_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()

    def _save(self):
        existing_ids = {r["id"] for r in DB.query("SELECT id FROM synonym_groups")}
        kept_ids: set[int] = set()
        skipped = 0
        for row in self._rows:
            terms = row.terms
            if len(terms) < 2:
                skipped += 1
                continue
            terms_json = json.dumps(terms)
            if row.group_id is None:
                new_id = DB.execute(
                    "INSERT INTO synonym_groups (terms_json) VALUES (?)", (terms_json,)
                )
                row.group_id = new_id
            else:
                DB.execute(
                    "UPDATE synonym_groups SET terms_json = ? WHERE id = ?",
                    (terms_json, row.group_id),
                )
                kept_ids.add(row.group_id)
        for stale in existing_ids - kept_ids:
            DB.execute("DELETE FROM synonym_groups WHERE id = ?", (stale,))
        DB.log_audit("synonym_groups_updated")
        msg = "Synonym groups saved."
        if skipped:
            msg += f"\n\n{skipped} row(s) skipped — each group needs at least 2 terms."
        QMessageBox.information(self, "Saved", msg)
        self._load()


# ============================================================================
# Resume page — list-first landing, editor on selection
# ============================================================================


class ResumePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.tabs = QTabWidget()
        self.resumes_widget = _ResumesTabWidget()
        self.tabs.addTab(self.resumes_widget, "Resumes")
        self.tabs.addTab(_SynonymsTab(), "Synonym groups")
        outer.addWidget(self.tabs)

    def refresh(self):
        self.resumes_widget.refresh()

    def ai_context(self) -> dict:
        # Synonym-groups tab — short context, focus on the data the user sees.
        if self.tabs.currentIndex() == 1:
            group_count = DB.query_one(
                "SELECT COUNT(*) AS n FROM synonym_groups"
            ) or {"n": 0}
            return {
                "page": "Resume → Synonym groups",
                "summary": f"{group_count['n']} synonym group(s) defined",
                "data": {"synonym_group_count": group_count["n"]},
                "rule_based_hints": [
                    "Add a synonym group like ['React','React.js','ReactJS'] so AI tailoring "
                    "can swap among them when a listing uses any one.",
                    "Group action verbs ['led','spearheaded','drove','directed'] for swap-friendly bullets.",
                    "Each group needs at least 2 terms.",
                ],
            }
        # Resumes tab — delegate so we get list-vs-editor context.
        return self.resumes_widget.ai_context()


class _ResumesTabWidget(QWidget):
    """The 'Resumes' tab body: a QStackedWidget switching between the list of
    resume types/versions and a single-resume editor view."""

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack)

        self.current_type_id: int | None = None
        self.current_version_id: int | None = None

        self.list_view = self._build_list_view()
        self.editor_view = self._build_editor_view()
        self.stack.addWidget(self.list_view)
        self.stack.addWidget(self.editor_view)
        self.stack.setCurrentIndex(0)

        self._refresh_list()

    def refresh(self):
        if self.stack.currentIndex() == 0:
            self._refresh_list()

    def ai_context(self) -> dict:
        # In list view — show counts and prompt for next step.
        if self.stack.currentIndex() == 0:
            types = ver.list_resume_types()
            total_versions = DB.query_one(
                "SELECT COUNT(*) AS n FROM resume_versions"
            ) or {"n": 0}
            hints = [
                "Click 'Import resume…' to load an existing .docx/.pdf/.txt so the AI parser can extract sections.",
                "Use resume types (Engineering, Management, Operations…) to keep tailored variants organized.",
            ]
            if not types:
                hints.insert(0, "No resumes yet — import one to unlock AI tailoring and fit scoring.")
            return {
                "page": "Resume → list of resumes",
                "summary": (
                    f"{len(types)} type(s) · {total_versions['n']} version(s) total"
                ),
                "data": {
                    "type_count": len(types),
                    "version_count": total_versions["n"],
                    "type_names": [t["name"] for t in types],
                },
                "rule_based_hints": hints,
            }

        # In editor view — give the AI the actual resume so it can advise on it.
        try:
            content = self.editor.dump()
        except Exception:
            content = None
        title = self.editor_title.text() if hasattr(self, "editor_title") else "Resume"
        target_text = ""
        try:
            target_text = self.target_job.toPlainText().strip()
        except Exception:
            pass

        data: dict = {"resume_label": title}
        if content is not None:
            data["resume_name"] = content.name
            data["summary_preview"] = (content.summary or "")[:600]
            data["section_overview"] = [
                {
                    "title": s.title,
                    "item_count": len(s.items),
                    "first_item_header": s.items[0].header if s.items else "",
                    "first_item_bullets": (s.items[0].bullets[:3]
                                           if s.items and s.items[0].bullets else []),
                }
                for s in content.sections[:8]
            ]
        data["target_job_listing"] = target_text[:1500] if target_text else ""

        hints = [
            "Click 'Tailor with AI' with a listing pasted to swap synonyms and reorder bullets.",
            "Click any section in the right-side preview to edit it on the left.",
            "Use the B / I / Bullet toolbar above each editor for inline formatting.",
        ]
        if target_text:
            hints.insert(0, "Use 'Sort by relevance' on each item to surface listing-matching bullets first.")
        else:
            hints.insert(0, "Paste a job listing into 'Target job listing' to enable per-bullet 'Sort by relevance'.")

        return {
            "page": f"Resume Editor — {title}",
            "summary": (
                f"Editing '{title}'"
                + (f" with target listing pasted ({len(target_text)} chars)" if target_text else "")
            ),
            "data": data,
            "rule_based_hints": hints,
        }

    # ------------------------------------------------------------------ list view

    def _build_list_view(self) -> QWidget:
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(36, 30, 36, 30)
        outer.setSpacing(20)

        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel("Resumes")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        new_type_btn = QPushButton("+ New type")
        new_type_btn.setToolTip("Create a new resume category (e.g. Engineering, Management)")
        new_type_btn.clicked.connect(self._on_new_type)
        header.addWidget(new_type_btn)
        import_btn = QPushButton("Import resume…")
        import_btn.setObjectName("PrimaryButton")
        import_btn.setToolTip("Import a .docx, .pdf, or .txt resume and have AI parse its sections")
        import_btn.clicked.connect(self._on_import)
        header.addWidget(import_btn)
        outer.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll, 1)

        self.list_content = QWidget()
        self.list_content_layout = QVBoxLayout(self.list_content)
        self.list_content_layout.setContentsMargins(0, 0, 0, 0)
        self.list_content_layout.setSpacing(18)
        scroll.setWidget(self.list_content)

        return widget

    def _refresh_list(self):
        while self.list_content_layout.count() > 0:
            item = self.list_content_layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()

        types = ver.list_resume_types()
        if not types:
            empty = QLabel(
                "No resumes yet.\n\n"
                "Click <b>Import resume…</b> to load an existing .docx/.pdf/.txt, "
                "or <b>+ New type</b> to start a category from scratch."
            )
            empty.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; padding: 80px;")
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            empty.setTextFormat(Qt.RichText)
            self.list_content_layout.addWidget(empty)
        else:
            for t in types:
                section = self._make_type_section(t)
                self.list_content_layout.addWidget(section)

        self.list_content_layout.addStretch(1)

    def _make_type_section(self, type_row) -> QWidget:
        type_id = type_row["id"]
        type_name = type_row["name"]

        section = QFrame()
        section.setObjectName("Card")
        slay = QVBoxLayout(section)
        slay.setContentsMargins(24, 20, 24, 20)
        slay.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(8)
        name_label = QLabel(type_name)
        name_label.setStyleSheet(
            f"color: {config.COLOR_TEXT}; font-size: 18px; font-weight: 700;"
        )
        head.addWidget(name_label)
        head.addStretch(1)
        rename_btn = QPushButton("Rename")
        rename_btn.clicked.connect(lambda _c=False, t=type_id: self._on_rename_type(t))
        head.addWidget(rename_btn)
        new_ver_btn = QPushButton("+ Blank version")
        new_ver_btn.setToolTip("Open the editor with a blank resume to fill in manually")
        new_ver_btn.clicked.connect(lambda _c=False, t=type_id: self._on_new_blank_version(t))
        head.addWidget(new_ver_btn)
        delete_btn = QPushButton("Delete type")
        delete_btn.setStyleSheet(f"color: {config.COLOR_ACCENT};")
        delete_btn.clicked.connect(lambda _c=False, t=type_id: self._on_delete_type(t))
        head.addWidget(delete_btn)
        slay.addLayout(head)

        versions = ver.list_versions(type_id)
        if not versions:
            empty = QLabel("No versions yet — click '+ Blank version' or use 'Import resume…'.")
            empty.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; padding: 8px 0;")
            slay.addWidget(empty)
        else:
            for v in versions:
                card = self._make_version_card(type_id, v)
                slay.addWidget(card)

        return section

    def _make_version_card(self, type_id, version) -> QWidget:
        card = QFrame()
        card.setObjectName("SubCard")
        card.setCursor(Qt.PointingHandCursor)
        cl = QHBoxLayout(card)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(14)

        vnum = QLabel(f"v{version['version_number']}")
        vnum.setStyleSheet(
            f"color: {config.COLOR_ACCENT}; font-size: 18px; font-weight: 700; "
            f"min-width: 44px;"
        )
        vnum.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        cl.addWidget(vnum)

        mid = QVBoxLayout()
        mid.setSpacing(2)
        label_text = version.get("label") or "(no label)"
        label_lbl = QLabel(label_text)
        label_lbl.setStyleSheet(f"color: {config.COLOR_TEXT}; font-size: 14px;")
        mid.addWidget(label_lbl)
        meta_bits: list[str] = []
        if version.get("created_at"):
            meta_bits.append(version["created_at"][:10])
        if version.get("source_format"):
            meta_bits.append(version["source_format"])
        meta = QLabel(" · ".join(meta_bits) or "—")
        meta.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 12px;")
        mid.addWidget(meta)
        mid_wrap = QWidget()
        mid_wrap.setLayout(mid)
        mid_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        cl.addWidget(mid_wrap, 1)

        open_btn = QPushButton("Open")
        open_btn.clicked.connect(
            lambda _c=False, t=type_id, vid=version["id"]: self._open_version(t, vid)
        )
        cl.addWidget(open_btn)
        del_btn = QPushButton("Delete")
        del_btn.setStyleSheet(f"color: {config.COLOR_ACCENT};")
        del_btn.clicked.connect(
            lambda _c=False, vid=version["id"]: self._on_delete_version(vid)
        )
        cl.addWidget(del_btn)

        # Whole card clickable
        def _click(_event, t=type_id, vid=version["id"]):
            self._open_version(t, vid)
        card.mousePressEvent = _click

        return card

    # ------------------------------------------------------------------ editor view

    def _build_editor_view(self) -> QWidget:
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(10)
        back_btn = QPushButton("← All resumes")
        back_btn.setObjectName("GhostButton")
        back_btn.clicked.connect(self._go_to_list)
        header.addWidget(back_btn)
        header.addSpacing(12)
        self.editor_title = QLabel("Resume")
        self.editor_title.setObjectName("PageTitle")
        header.addWidget(self.editor_title)
        header.addStretch(1)

        tailor_btn = QPushButton("Tailor with AI")
        tailor_btn.setToolTip(
            "Paste a job listing or URL; tailor this resume to it (limited to your synonym groups)"
        )
        tailor_btn.clicked.connect(self._on_tailor)
        header.addWidget(tailor_btn)
        self.save_btn = QPushButton("Save as new version")
        self.save_btn.setObjectName("PrimaryButton")
        self.save_btn.clicked.connect(self._on_save_version)
        header.addWidget(self.save_btn)
        # Export button with format dropdown — explicit choice instead of
        # hiding format selection inside the save dialog's filter combo.
        export_btn = QToolButton()
        export_btn.setText("Export ▾")
        export_btn.setToolTip("Export current editor contents")
        export_btn.setPopupMode(QToolButton.InstantPopup)
        export_btn.setObjectName("GhostButton")
        export_menu = QMenu(export_btn)
        act_docx = QAction("Export as Word (.docx)", export_menu)
        act_docx.triggered.connect(lambda: self._on_export("docx"))
        export_menu.addAction(act_docx)
        act_pdf = QAction("Export as PDF (.pdf)", export_menu)
        act_pdf.triggered.connect(lambda: self._on_export("pdf"))
        export_menu.addAction(act_pdf)
        export_btn.setMenu(export_menu)
        header.addWidget(export_btn)
        outer.addLayout(header)

        target_card = QFrame()
        target_card.setObjectName("Card")
        target_layout = QVBoxLayout(target_card)
        target_layout.setContentsMargins(18, 12, 18, 14)
        target_layout.setSpacing(6)
        target_label = QLabel("Target job listing — paste here to enable 'Sort by relevance' on items")
        target_label.setObjectName("SectionTitle")
        target_layout.addWidget(target_label)
        self.target_job = QPlainTextEdit()
        self.target_job.setPlaceholderText(
            "Optional. Paste a job description here, then use 'Sort by relevance' on any item "
            "to reorder bullets by keyword overlap."
        )
        self.target_job.setFixedHeight(80)
        self.target_job.textChanged.connect(self._on_target_changed)
        target_layout.addWidget(self.target_job)
        outer.addWidget(target_card)

        self.editor = ResumeEditor()
        outer.addWidget(self.editor, 1)

        return widget

    # ------------------------------------------------------------------ navigation

    def _open_version(self, type_id: int, version_id: int):
        loaded = ver.get_version(version_id)
        if not loaded:
            QMessageBox.warning(self, "Not found", "That resume version no longer exists.")
            self._refresh_list()
            return
        content, meta = loaded
        type_row = DB.query_one("SELECT name FROM resume_types WHERE id = ?", (type_id,))
        type_name = type_row["name"] if type_row else "Resume"
        label = meta.get("label") or f"v{meta.get('version_number', '?')}"
        self.editor_title.setText(f"{type_name}  ·  {label}")
        self.current_type_id = type_id
        self.current_version_id = version_id
        self.editor.load(content)
        self.target_job.clear()
        self.stack.setCurrentIndex(1)

    def _go_to_list(self):
        self.current_type_id = None
        self.current_version_id = None
        self.target_job.clear()
        self._refresh_list()
        self.stack.setCurrentIndex(0)

    # ------------------------------------------------------------------ list-level actions

    def _on_new_type(self):
        name, ok = QInputDialog.getText(
            self, "New resume type", "Name (e.g. 'Engineering Resume'):",
        )
        if not ok or not name.strip():
            return
        existing = DB.query_one("SELECT id FROM resume_types WHERE name = ?", (name.strip(),))
        if existing:
            QMessageBox.warning(self, "Already exists",
                                f"A resume type named '{name.strip()}' already exists.")
            return
        new_id = ver.create_resume_type(name.strip())
        DB.log_audit("resume_type_created", {"name": name.strip()})
        self._refresh_list()
        # Auto-enter blank editor for the new type
        self._on_new_blank_version(new_id)

    def _on_rename_type(self, type_id: int):
        row = DB.query_one("SELECT name FROM resume_types WHERE id = ?", (type_id,))
        if not row:
            return
        new_name, ok = QInputDialog.getText(
            self, "Rename resume type", "New name:", text=row["name"],
        )
        if not ok or not new_name.strip() or new_name.strip() == row["name"]:
            return
        ver.rename_resume_type(type_id, new_name.strip())
        DB.log_audit("resume_type_renamed", {"id": type_id, "new": new_name.strip()})
        self._refresh_list()

    def _on_delete_type(self, type_id: int):
        row = DB.query_one("SELECT name FROM resume_types WHERE id = ?", (type_id,))
        if not row:
            return
        confirm = QMessageBox.question(
            self, "Delete resume type",
            f"Delete '{row['name']}' and all its versions?\n\n"
            "Applications that point at one of its versions will keep working "
            "(they get unlinked).",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return
        ver.delete_resume_type(type_id)
        DB.log_audit("resume_type_deleted", {"id": type_id, "name": row["name"]})
        self._refresh_list()

    def _on_delete_version(self, version_id: int):
        confirm = QMessageBox.question(
            self, "Delete version",
            "Delete this resume version permanently?",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return
        ver.delete_version(version_id)
        DB.log_audit("resume_version_deleted", {"id": version_id})
        self._refresh_list()

    def _on_new_blank_version(self, type_id: int):
        self.current_type_id = type_id
        self.current_version_id = None
        type_row = DB.query_one("SELECT name FROM resume_types WHERE id = ?", (type_id,))
        type_name = type_row["name"] if type_row else "Resume"
        self.editor_title.setText(f"{type_name}  ·  new draft (unsaved)")
        self.editor.load(ResumeContent())
        self.target_job.clear()
        self.stack.setCurrentIndex(1)

    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import resume",
            filter="Resumes (*.docx *.pdf *.txt);;Word (*.docx);;PDF (*.pdf);;Text (*.txt);;All files (*.*)",
        )
        if not path:
            return

        raw_text = parser.extract_raw_text(Path(path))
        if not raw_text.strip():
            QMessageBox.warning(
                self, "Empty file",
                f"Couldn't extract any text from {Path(path).name}. "
                "If it's a scanned PDF, JobHunt can't read it without OCR.",
            )
            return

        progress = ParseResumeDialog(raw_text, parent=self)
        if not progress.exec():
            return
        content = progress.parsed_content
        if content is None:
            QMessageBox.warning(
                self, "Parse failed",
                f"Could not parse {Path(path).name}:\n{progress.error}",
            )
            return

        types = ver.list_resume_types()
        if types:
            choices = [t["name"] for t in types] + ["+ Create new type…"]
            choice, ok = QInputDialog.getItem(
                self, "Which resume type?",
                "Save the imported resume under which type?",
                choices, 0, False,
            )
            if not ok:
                return
            if choice == "+ Create new type…":
                type_id = self._prompt_new_type(default_name=Path(path).stem)
                if type_id is None:
                    return
            else:
                type_id = next(t["id"] for t in types if t["name"] == choice)
        else:
            type_id = self._prompt_new_type(default_name=Path(path).stem)
            if type_id is None:
                return

        new_version_id = ver.save_version(
            type_id, content,
            label=f"imported from {Path(path).name}",
            source_format="imported",
        )
        DB.log_audit("resume_imported", {"path": path, "type_id": type_id})
        self._refresh_list()
        self._open_version(type_id, new_version_id)

    def _prompt_new_type(self, default_name: str = "Resume") -> int | None:
        suggested = default_name.replace("_", " ").replace("-", " ").strip().title() or "Resume"
        name, ok = QInputDialog.getText(
            self, "Name this resume type", "Type name:",
            text=suggested,
        )
        if not ok or not name.strip():
            return None
        existing = DB.query_one("SELECT id FROM resume_types WHERE name = ?", (name.strip(),))
        if existing:
            return existing["id"]
        return ver.create_resume_type(name.strip())

    # ------------------------------------------------------------------ editor-level actions

    def _on_save_version(self):
        if self.current_type_id is None:
            QMessageBox.information(self, "No type", "Open a resume type first.")
            return
        content = self.editor.dump()
        if not content.name and not content.sections:
            QMessageBox.warning(self, "Empty", "Nothing to save — the editor is empty.")
            return
        label, ok = QInputDialog.getText(
            self, "Save version",
            "Optional label (e.g. 'after-stripe-tailor'). Leave blank for none.",
        )
        if not ok:
            return
        label = label.strip() or None
        new_id = ver.save_version(self.current_type_id, content, label=label)
        self.current_version_id = new_id
        type_row = DB.query_one("SELECT name FROM resume_types WHERE id = ?", (self.current_type_id,))
        type_name = type_row["name"] if type_row else ""
        next_version = DB.query_one(
            "SELECT version_number FROM resume_versions WHERE id = ?", (new_id,),
        )
        v_num = next_version["version_number"] if next_version else "?"
        self.editor_title.setText(
            f"{type_name}  ·  v{v_num}" + (f"  ·  {label}" if label else "")
        )
        QMessageBox.information(
            self, "Saved",
            "Saved a new version. JobHunt retains the 5 most-recent versions per type — "
            "older ones are pruned automatically.",
        )

    def _on_export(self, fmt: str = "docx"):
        """Export the current editor contents.

        Format is chosen by the dropdown menu item — the save dialog is
        locked to that single extension. Previously the format was inferred
        from the user's filter pick in the save dialog, which most users
        missed; this version puts the choice up-front."""
        fmt = fmt.lower()
        if fmt not in ("docx", "pdf"):
            fmt = "docx"
        if self.current_type_id is None:
            QMessageBox.information(self, "No type", "Open a resume type first.")
            return
        try:
            content = self.editor.dump()
        except Exception as e:
            QMessageBox.warning(self, "Export error", f"Couldn't read editor state: {e}")
            return
        if not content.sections and not content.name:
            QMessageBox.warning(self, "Empty", "Nothing to export — the editor is empty.")
            return

        type_row = DB.query_one("SELECT name FROM resume_types WHERE id = ?", (self.current_type_id,))
        type_name = (type_row["name"] if type_row else "resume").replace(" ", "_") or "resume"
        title = "Export resume as PDF" if fmt == "pdf" else "Export resume as Word"
        file_filter = "PDF Document (*.pdf)" if fmt == "pdf" else "Word Document (*.docx)"
        path, _ = QFileDialog.getSaveFileName(
            self, title, f"{type_name}.{fmt}", file_filter,
        )
        if not path:
            return
        if not path.lower().endswith(f".{fmt}"):
            path += f".{fmt}"

        try:
            from ...documents.export import export_resume_docx, export_resume_pdf
            if fmt == "pdf":
                export_resume_pdf(content, path)
            else:
                export_resume_docx(content, path)
        except Exception as e:
            QMessageBox.warning(self, "Export error", f"Couldn't export:\n{e}")
            return
        DB.log_audit("resume_exported", {"path": path, "format": fmt})
        QMessageBox.information(self, "Exported", f"Saved to:\n{path}")

    def _on_target_changed(self):
        text = self.target_job.toPlainText()
        toks = {t.strip(".,;:()[]{}!?\"'").lower() for t in text.split() if len(t) > 2}
        self.editor.set_target_keywords(toks)
        self.editor.set_target_listing(text)

    def _on_tailor(self):
        if self.current_type_id is None:
            QMessageBox.information(self, "No type", "Open a resume type first.")
            return
        try:
            current = self.editor.dump()
        except Exception as e:
            QMessageBox.warning(self, "Editor error", f"Couldn't read current editor state: {e}")
            return
        if not current.sections:
            QMessageBox.information(self, "Empty resume", "Nothing to tailor yet.")
            return
        from ..dialogs.tailor_resume import TailorResumeDialog
        dlg = TailorResumeDialog(current, self.current_type_id, self)
        if dlg.exec() and dlg.saved_version_id is not None:
            self._open_version(self.current_type_id, dlg.saved_version_id)
