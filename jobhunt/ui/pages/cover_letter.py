from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QTextEdit, QFrame, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QDialog, QFormLayout, QLineEdit, QPlainTextEdit,
    QDialogButtonBox, QStackedWidget, QScrollArea, QInputDialog, QSizePolicy,
    QSplitter, QTextBrowser, QToolButton, QMenu, QFileDialog,
)

from ... import config
from ...db import DB
from ..dialogs.generate_cover_letter import GenerateCoverLetterDialog
from ..widgets.dark_titlebar import apply_dark_title_bar
from ..widgets.growing_text import GrowingTextEdit


class _StoryDialog(QDialog):
    def __init__(self, story: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit story" if story else "New story")
        self.setMinimumWidth(560)
        self.setModal(True)
        apply_dark_title_bar(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 22, 22, 22)
        outer.setSpacing(14)

        title = QLabel("Edit story" if story else "New story")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(14)

        self.theme = QLineEdit()
        self.theme.setPlaceholderText("e.g. leadership, technical depth")
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Short title (e.g. 'Scaled checkout from 5 to 50 engineers')")
        self.body = GrowingTextEdit(min_lines=8)
        self.body.setPlaceholderText(
            "The full anecdote / paragraph. The AI will pull from this when "
            "generating cover letters where it's relevant."
        )

        theme_label = QLabel("Theme tag")
        theme_label.setObjectName("FormLabel")
        title_label = QLabel("Title")
        title_label.setObjectName("FormLabel")
        body_label = QLabel("Body")
        body_label.setObjectName("FormLabel")

        form.addRow(theme_label, self.theme)
        form.addRow(title_label, self.title_input)
        form.addRow(body_label, self.body)
        outer.addLayout(form)

        if story:
            self.theme.setText(story.get("theme_tag") or "")
            self.title_input.setText(story.get("title") or "")
            self.body.setPlainText(story.get("body") or "")

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        save_btn = btns.button(QDialogButtonBox.Save)
        save_btn.setObjectName("PrimaryButton")
        save_btn.setText("Save story")
        outer.addWidget(btns)

    def data(self) -> dict:
        return {
            "theme_tag": self.theme.text().strip() or None,
            "title": self.title_input.text().strip() or None,
            "body": self.body.toPlainText().strip(),
        }


class _StoryBankTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        section = QLabel("Story bank")
        section.setObjectName("SectionTitle")
        outer.addWidget(section)

        info = QLabel(
            "Reusable paragraphs and anecdotes. The AI generator picks from these "
            "when drafting a cover letter, choosing items whose theme tag fits the job."
        )
        info.setObjectName("SectionDescription")
        info.setWordWrap(True)
        outer.addWidget(info)

        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setSpacing(12)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Theme", "Title", "Body preview"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setMinimumHeight(280)
        self.table.itemDoubleClicked.connect(lambda *_: self._edit())
        cl.addWidget(self.table)

        btns = QHBoxLayout()
        add_btn = QPushButton("+ Add story")
        add_btn.clicked.connect(self._add)
        edit_btn = QPushButton("Edit selected")
        edit_btn.clicked.connect(self._edit)
        delete_btn = QPushButton("Delete selected")
        delete_btn.clicked.connect(self._delete)
        btns.addWidget(add_btn)
        btns.addWidget(edit_btn)
        btns.addWidget(delete_btn)
        btns.addStretch(1)
        cl.addLayout(btns)

        outer.addWidget(card)
        outer.addStretch(1)
        self._load()

    def _load(self):
        rows = DB.query("SELECT id, theme_tag, title, body FROM story_bank ORDER BY id DESC")
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            theme_item = QTableWidgetItem(r["theme_tag"] or "")
            theme_item.setData(Qt.UserRole, r["id"])
            title_item = QTableWidgetItem(r["title"] or "(untitled)")
            body_preview = (r["body"] or "").replace("\n", " ")
            if len(body_preview) > 110:
                body_preview = body_preview[:110] + "…"
            body_item = QTableWidgetItem(body_preview)
            self.table.setItem(i, 0, theme_item)
            self.table.setItem(i, 1, title_item)
            self.table.setItem(i, 2, body_item)

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _add(self):
        dlg = _StoryDialog(parent=self)
        if dlg.exec():
            data = dlg.data()
            if not data["body"]:
                QMessageBox.warning(self, "Empty", "A story needs at least a body.")
                return
            DB.execute(
                "INSERT INTO story_bank (theme_tag, title, body) VALUES (?, ?, ?)",
                (data["theme_tag"], data["title"], data["body"]),
            )
            DB.log_audit("story_added")
            self._load()

    def _edit(self):
        sid = self._selected_id()
        if sid is None:
            return
        row = DB.query_one("SELECT theme_tag, title, body FROM story_bank WHERE id = ?", (sid,))
        if not row:
            return
        dlg = _StoryDialog(story=dict(row), parent=self)
        if dlg.exec():
            data = dlg.data()
            if not data["body"]:
                QMessageBox.warning(self, "Empty", "A story needs at least a body.")
                return
            DB.execute(
                "UPDATE story_bank SET theme_tag = ?, title = ?, body = ? WHERE id = ?",
                (data["theme_tag"], data["title"], data["body"], sid),
            )
            DB.log_audit("story_updated", {"id": sid})
            self._load()

    def _delete(self):
        sid = self._selected_id()
        if sid is None:
            return
        confirm = QMessageBox.question(
            self, "Delete story",
            "Delete this story permanently?",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return
        DB.execute("DELETE FROM story_bank WHERE id = ?", (sid,))
        DB.log_audit("story_deleted", {"id": sid})
        self._load()


class _LettersTabWidget(QWidget):
    """The 'Cover Letters' tab body: list of saved letters, click to enter editor."""

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack)

        self.current_application_id: int | None = None

        self.list_view = self._build_list_view()
        self.editor_view = self._build_editor_view()
        self.stack.addWidget(self.list_view)
        self.stack.addWidget(self.editor_view)
        self.stack.setCurrentIndex(0)

        self._refresh_list()

    def refresh(self):
        if self.stack.currentIndex() == 0:
            self._refresh_list()

    # ------------------------------------------------------------------ list view

    def _build_list_view(self) -> QWidget:
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(36, 30, 36, 30)
        outer.setSpacing(20)

        header = QHBoxLayout()
        title = QLabel("Cover Letters")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        new_btn = QPushButton("+ New letter")
        new_btn.setObjectName("PrimaryButton")
        new_btn.setToolTip("Pick an application and draft a cover letter for it")
        new_btn.clicked.connect(self._on_new_letter)
        header.addWidget(new_btn)
        outer.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll, 1)

        self.list_content = QWidget()
        self.list_content_layout = QVBoxLayout(self.list_content)
        self.list_content_layout.setContentsMargins(0, 0, 0, 0)
        self.list_content_layout.setSpacing(14)
        scroll.setWidget(self.list_content)

        return widget

    def _refresh_list(self):
        while self.list_content_layout.count() > 0:
            item = self.list_content_layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()

        rows = DB.query(
            """SELECT cl.id AS letter_id, cl.application_id, cl.content,
                      cl.created_at, a.company, a.role, a.date_applied
               FROM cover_letters cl
               LEFT JOIN applications a ON a.id = cl.application_id
               ORDER BY cl.created_at DESC, cl.id DESC"""
        )

        if not rows:
            app_count = DB.query_one("SELECT COUNT(*) AS n FROM applications") or {"n": 0}
            if app_count["n"] == 0:
                msg = (
                    "No cover letters yet.\n\n"
                    "Add an application via the Pipeline page first,\n"
                    "then come back here and click '+ New letter'."
                )
            else:
                msg = (
                    "No cover letters yet.\n\n"
                    "Click <b>+ New letter</b> to draft one for an existing application."
                )
            empty = QLabel(msg)
            empty.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; padding: 80px;")
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            empty.setTextFormat(Qt.RichText)
            self.list_content_layout.addWidget(empty)
        else:
            for r in rows:
                card = self._make_letter_card(dict(r))
                self.list_content_layout.addWidget(card)

        self.list_content_layout.addStretch(1)

    def _make_letter_card(self, row: dict) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        card.setCursor(Qt.PointingHandCursor)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(22, 16, 22, 16)
        cl.setSpacing(6)

        top = QHBoxLayout()
        company = row.get("company") or "(no linked application)"
        role = row.get("role") or ""
        head_text = company if not role else f"{company} — {role}"
        head_label = QLabel(head_text)
        head_label.setStyleSheet(
            f"color: {config.COLOR_TEXT}; font-size: 16px; font-weight: 700;"
        )
        top.addWidget(head_label)
        top.addStretch(1)
        date_text = (row.get("created_at") or "")[:10]
        if date_text:
            date_label = QLabel(date_text)
            date_label.setStyleSheet(f"color: {config.COLOR_TEXT_DIM};")
            top.addWidget(date_label)
        cl.addLayout(top)

        preview_text = (row.get("content") or "").replace("\n", " ").strip()
        if len(preview_text) > 200:
            preview_text = preview_text[:200] + "…"
        preview = QLabel(preview_text or "(empty)")
        preview.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 13px;")
        preview.setWordWrap(True)
        cl.addWidget(preview)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)
        open_btn = QPushButton("Open")
        open_btn.clicked.connect(
            lambda _c=False, aid=row.get("application_id"): self._open_letter(aid)
        )
        btn_row.addWidget(open_btn)
        del_btn = QPushButton("Delete")
        del_btn.setStyleSheet(f"color: {config.COLOR_ACCENT};")
        del_btn.clicked.connect(
            lambda _c=False, lid=row.get("letter_id"): self._on_delete_letter(lid)
        )
        btn_row.addWidget(del_btn)
        cl.addLayout(btn_row)

        def _click(_event, aid=row.get("application_id")):
            self._open_letter(aid)
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
        back_btn = QPushButton("← All letters")
        back_btn.setObjectName("GhostButton")
        back_btn.clicked.connect(self._go_to_list)
        header.addWidget(back_btn)
        header.addSpacing(12)
        self.editor_title = QLabel("Cover Letter")
        self.editor_title.setObjectName("PageTitle")
        header.addWidget(self.editor_title)
        header.addStretch(1)
        gen_btn = QPushButton("Generate with AI")
        gen_btn.setToolTip(
            "Assemble a draft from your story bank, tailored to a job listing you paste"
        )
        gen_btn.clicked.connect(self._on_generate)
        header.addWidget(gen_btn)
        self.save_btn = QPushButton("Save letter")
        self.save_btn.setObjectName("PrimaryButton")
        self.save_btn.clicked.connect(self._on_save)
        header.addWidget(self.save_btn)
        export_btn = QToolButton()
        export_btn.setText("Export ▾")
        export_btn.setToolTip("Export this cover letter")
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

        splitter = QSplitter(Qt.Horizontal)

        editor_card = QFrame()
        editor_card.setObjectName("Card")
        ec = QVBoxLayout(editor_card)
        ec.setContentsMargins(20, 16, 20, 16)
        ec.setSpacing(10)
        self.editor = QTextEdit()
        self.editor.setPlaceholderText(
            "Write your cover letter here, or click 'Generate with AI' to assemble a draft "
            "from your story bank."
        )
        self.editor.setAcceptRichText(False)
        self.editor.textChanged.connect(self._schedule_preview)
        ec.addWidget(self.editor, 1)
        splitter.addWidget(editor_card)

        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(True)
        self.preview.setStyleSheet(
            "QTextBrowser { background-color: #ffffff; color: #1a1a1a; "
            "border: none; padding: 0; }"
        )
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([640, 460])
        outer.addWidget(splitter, 1)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(350)
        self._preview_timer.timeout.connect(self._update_preview)

        return widget

    def _schedule_preview(self):
        self._preview_timer.start()

    def _update_preview(self):
        profile_row = DB.query_one("SELECT * FROM profile WHERE id = 1")
        profile = dict(profile_row) if profile_row else {}
        company = ""
        role = ""
        if self.current_application_id is not None:
            row = DB.query_one(
                "SELECT company, role FROM applications WHERE id = ?",
                (self.current_application_id,),
            )
            if row:
                company = row["company"] or ""
                role = row["role"] or ""
        html = _render_cover_letter_html(
            self.editor.toPlainText(), profile, company, role,
        )
        self.preview.setHtml(html)

    # ------------------------------------------------------------------ navigation

    def _open_letter(self, application_id):
        if application_id is None:
            QMessageBox.information(
                self, "Unlinked letter",
                "This cover letter isn't linked to an application anymore. "
                "Use Copy from the export menu if you want to keep its text.",
            )
            return
        self.current_application_id = application_id
        app = DB.query_one(
            "SELECT company, role FROM applications WHERE id = ?",
            (application_id,),
        )
        if app:
            title = f"{app['company']} — {app['role']}"
        else:
            title = "(application deleted)"
        self.editor_title.setText(title)
        row = DB.query_one(
            "SELECT content FROM cover_letters WHERE application_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (application_id,),
        )
        self.editor.setPlainText(row["content"] if row and row["content"] else "")
        self._update_preview()
        self.stack.setCurrentIndex(1)

    def _go_to_list(self):
        self.current_application_id = None
        self._refresh_list()
        self.stack.setCurrentIndex(0)

    # ------------------------------------------------------------------ list-level actions

    def _on_new_letter(self):
        rows = DB.query(
            """SELECT id, company, role, date_applied
               FROM applications
               ORDER BY date_applied DESC, id DESC"""
        )
        if not rows:
            QMessageBox.information(
                self, "No applications",
                "Add an application via the Pipeline page first.",
            )
            return
        items = [f"{r['company']} — {r['role']}"
                 + (f"  ({r['date_applied']})" if r["date_applied"] else "")
                 for r in rows]
        choice, ok = QInputDialog.getItem(
            self, "New cover letter",
            "Which application is this letter for?",
            items, 0, False,
        )
        if not ok:
            return
        idx = items.index(choice)
        app_id = rows[idx]["id"]
        # Open editor for that application (will load existing letter if any)
        self._open_letter(app_id)

    def _on_delete_letter(self, letter_id):
        confirm = QMessageBox.question(
            self, "Delete cover letter",
            "Delete this cover letter permanently?",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return
        DB.execute("DELETE FROM cover_letters WHERE id = ?", (letter_id,))
        DB.log_audit("cover_letter_deleted", {"id": letter_id})
        self._refresh_list()

    # ------------------------------------------------------------------ editor-level actions

    def _on_generate(self):
        dlg = GenerateCoverLetterDialog(self)
        if dlg.exec() and dlg.generated_letter:
            self.editor.setPlainText(dlg.generated_letter)

    def _on_save(self):
        if self.current_application_id is None:
            QMessageBox.information(
                self, "Pick an application",
                "Open a letter from the list, or click '+ New letter'.",
            )
            return
        content = self.editor.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "Empty", "Nothing to save — the editor is empty.")
            return
        DB.execute(
            "DELETE FROM cover_letters WHERE application_id = ?",
            (self.current_application_id,),
        )
        new_id = DB.execute(
            "INSERT INTO cover_letters (application_id, content) VALUES (?, ?)",
            (self.current_application_id, content),
        )
        DB.execute(
            "UPDATE applications SET cover_letter_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_id, self.current_application_id),
        )
        DB.log_audit("cover_letter_saved", {"application_id": self.current_application_id})
        QMessageBox.information(self, "Saved", "Cover letter saved.")

    def _on_export(self, fmt: str = "docx"):
        """Export the current cover letter. Format chosen explicitly via the
        dropdown menu — the save dialog stays locked to that single extension."""
        fmt = fmt.lower()
        if fmt not in ("docx", "pdf"):
            fmt = "docx"
        content = self.editor.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "Empty", "Nothing to export — the editor is empty.")
            return

        app_label = "cover_letter"
        if self.current_application_id is not None:
            row = DB.query_one(
                "SELECT company, role FROM applications WHERE id = ?",
                (self.current_application_id,),
            )
            if row:
                app_label = f"{row['company']}_{row['role']}".replace(" ", "_")

        title = "Export cover letter as PDF" if fmt == "pdf" else "Export cover letter as Word"
        file_filter = "PDF Document (*.pdf)" if fmt == "pdf" else "Word Document (*.docx)"
        path, _ = QFileDialog.getSaveFileName(
            self, title, f"cover_letter_{app_label}.{fmt}", file_filter,
        )
        if not path:
            return
        if not path.lower().endswith(f".{fmt}"):
            path += f".{fmt}"

        profile_row = DB.query_one("SELECT * FROM profile WHERE id = 1")
        profile = dict(profile_row) if profile_row else {}

        try:
            from ...documents.export import export_cover_letter_docx, export_cover_letter_pdf
            if fmt == "pdf":
                export_cover_letter_pdf(content, path, profile)
            else:
                export_cover_letter_docx(content, path, profile)
        except Exception as e:
            QMessageBox.warning(self, "Export error", f"Couldn't export:\n{e}")
            return
        DB.log_audit("cover_letter_exported", {"path": path, "format": fmt})
        QMessageBox.information(self, "Exported", f"Saved to:\n{path}")


def _esc_html(text: str) -> str:
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _render_cover_letter_html(text: str, profile: dict, company: str = "", role: str = "") -> str:
    paragraphs = [p.strip() for p in (text or "").split("\n\n") if p.strip()]
    body = "".join(
        f"<p style='margin: 0 0 12px 0;'>{_esc_html(p)}</p>" for p in paragraphs
    ) or "<p style='color:#888'>(Empty letter — type or click 'Generate with AI'.)</p>"

    name = _esc_html(
        (profile.get("preferred_name") or "").strip()
        or (profile.get("legal_name") or "").strip()
    )
    email = _esc_html((profile.get("email") or "").strip())
    phone = _esc_html((profile.get("phone") or "").strip())
    linkedin = _esc_html((profile.get("linkedin_url") or "").strip())
    contact_bits = " &nbsp;·&nbsp; ".join(b for b in (email, phone, linkedin) if b)

    header_html = ""
    if name:
        header_html = (
            f"<div style='font-weight:700; font-size:15px; color:#111;'>{name}</div>"
        )
        if contact_bits:
            header_html += (
                f"<div style='color:#555; font-size:11px; margin-bottom:22px;'>"
                f"{contact_bits}</div>"
            )

    addressee = ""
    if company:
        target = f"{_esc_html(company)}" + (f" — {_esc_html(role)}" if role else "")
        addressee = (
            f"<div style='color:#444; font-size:11px; margin-bottom:18px;'>"
            f"To: {target}</div>"
        )

    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<style>
  body {{ font-family: 'Calibri', 'Segoe UI', sans-serif; font-size: 12px;
          color: #1a1a1a; padding: 28px 36px; line-height: 1.55; }}
  p {{ margin: 0 0 12px 0; }}
</style></head><body>
{header_html}
{addressee}
{body}
</body></html>"""


class CoverLetterPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        title = QLabel("Cover Letter Studio")
        title.setVisible(False)
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setUsesScrollButtons(False)
        self.letters_tab = _LettersTabWidget()
        self.story_tab = _StoryBankTab()
        self.tabs.addTab(self.letters_tab, "Cover Letters")
        self.tabs.addTab(self.story_tab, "Story Bank")
        outer.addWidget(self.tabs, 1)

    def refresh(self):
        self.letters_tab.refresh()

    def ai_context(self) -> dict:
        app_count = DB.query_one("SELECT COUNT(*) AS n FROM applications") or {"n": 0}
        story_count = DB.query_one("SELECT COUNT(*) AS n FROM story_bank") or {"n": 0}
        cover_count = DB.query_one("SELECT COUNT(*) AS n FROM cover_letters") or {"n": 0}
        hints: list[str] = []
        if story_count["n"] == 0:
            hints.append("Add 3-5 stories to the Story Bank so the AI has material to draw from.")
        if app_count["n"] == 0:
            hints.append("Add an application via Pipeline before drafting a cover letter against it.")
        if app_count["n"] > 0 and cover_count["n"] == 0:
            hints.append("Generate a letter for one application to see how the story bank pulls in.")
        hints.append("Group stories by theme tag so the AI can pick the right anecdote for each job.")
        return {
            "page": "Cover Letter Studio",
            "summary": (
                f"{app_count['n']} application(s) · {story_count['n']} stories · "
                f"{cover_count['n']} saved letter(s)"
            ),
            "data": {
                "application_count": app_count["n"],
                "story_count": story_count["n"],
                "saved_letter_count": cover_count["n"],
            },
            "rule_based_hints": hints,
        }
