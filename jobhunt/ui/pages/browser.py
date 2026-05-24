from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QFrame, QMessageBox, QInputDialog, QStyle,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import (
        QWebEnginePage, QWebEngineProfile, QWebEngineSettings,
    )
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False


CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


if HAS_WEBENGINE:
    class _JobHuntPage(QWebEnginePage):
        """Custom page that:
        - handles target='_blank' / window.open() by loading the new URL in
          the same view, so job-listing clicks actually navigate;
        - intercepts file pickers so JobHunt can feed pre-exported resume /
          cover letter files into ATS forms during auto-fill.
        """

        def __init__(self, profile, parent):
            super().__init__(profile, parent)
            self._pending_files: list[str] = []

        def set_pending_files(self, paths: list[str]):
            """Queue file paths that will be returned from chooseFiles in order,
            one per call. Each programmatic click on a file input pops one."""
            self._pending_files = [p for p in paths if p]

        def chooseFiles(self, mode, old_files, accepted_mime_types):
            if self._pending_files:
                path = self._pending_files.pop(0)
                return [path]
            return super().chooseFiles(mode, old_files, accepted_mime_types)

        def createWindow(self, _window_type):
            return self


AUTOFILL_TEXT_JS = r"""
(function(profile) {
    'use strict';

    function setReactValue(el, value) {
        if (value === null || value === undefined) return;
        const proto = (el.tagName === 'TEXTAREA')
            ? window.HTMLTextAreaElement.prototype
            : window.HTMLInputElement.prototype;
        const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
        const setter = descriptor && descriptor.set;
        if (setter) {
            setter.call(el, String(value));
        } else {
            el.value = String(value);
        }
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('blur', { bubbles: true }));
    }

    function ariaText(el) {
        let txt = '';
        if (el.getAttribute('aria-label')) {
            txt += ' ' + el.getAttribute('aria-label');
        }
        const ariaBy = el.getAttribute('aria-labelledby');
        if (ariaBy) {
            ariaBy.split(/\s+/).forEach(id => {
                const node = document.getElementById(id);
                if (node) txt += ' ' + (node.textContent || '');
            });
        }
        return txt;
    }

    function labelText(el) {
        let txt = '';
        if (el.labels && el.labels.length > 0) {
            txt += Array.from(el.labels).map(l => l.textContent || '').join(' ');
        }
        let parent = el.parentElement;
        let depth = 0;
        while (parent && depth < 4 && parent !== document.body) {
            if (parent.tagName === 'LABEL') {
                txt += ' ' + (parent.textContent || '');
                break;
            }
            parent = parent.parentElement;
            depth++;
        }
        return txt;
    }

    function matchField(el) {
        const name = (el.name || el.id || '').toLowerCase();
        const placeholder = (el.placeholder || '').toLowerCase();
        const aria = ariaText(el).toLowerCase();
        const lbl = labelText(el).toLowerCase();
        const all = name + ' ' + placeholder + ' ' + aria + ' ' + lbl;

        if (/\b(first[\s_-]*name|fname|given[\s_-]*name)\b/.test(all)) return profile.first_name;
        if (/\b(last[\s_-]*name|lname|surname|family[\s_-]*name)\b/.test(all)) return profile.last_name;
        if (/\b(full[\s_-]*name|your[\s_-]*name|legal[\s_-]*name)\b/.test(all)) return profile.legal_name;
        if (all.trim() === 'name' || / name(?!.)/.test(all)) return profile.legal_name;
        if (all.includes('preferred name') || all.includes('nickname')) return profile.preferred_name || profile.first_name;
        if (all.includes('email')) return profile.email;
        if (/\b(phone|mobile|cell|telephone)\b/.test(all)) return profile.phone;
        if (all.includes('linkedin')) return profile.linkedin_url;
        if (all.includes('github')) return profile.github_url;
        if (/(portfolio|personal\s*site|personal\s*website|website|homepage)/.test(all)) return profile.portfolio_url;
        if (/(address|city|location|where.*based|current\s*location)/.test(all)) return profile.address;
        if (/(work\s*auth|eligible\s*to\s*work|authorized\s*to\s*work|sponsor)/.test(all)) return profile.work_auth;
        if (/(citizen|nationality)/.test(all)) return profile.citizenship;
        return null;
    }

    let filled = 0;
    let skipped = 0;
    const inputs = document.querySelectorAll('input, textarea');
    for (const el of inputs) {
        if (el.disabled || el.readOnly) continue;
        const type = (el.type || '').toLowerCase();
        if (['hidden','file','checkbox','radio','submit','button','reset','image'].indexOf(type) >= 0) continue;
        if (el.value && el.value.trim().length > 0) { skipped++; continue; }
        const value = matchField(el);
        if (value) {
            setReactValue(el, value);
            filled++;
        }
    }
    return { filled: filled, skipped: skipped };
})(__PROFILE__);
"""

AUTOFILL_FILES_JS = r"""
(function() {
    'use strict';
    function labelText(el) {
        let txt = '';
        if (el.labels && el.labels.length > 0) {
            txt += Array.from(el.labels).map(l => l.textContent || '').join(' ');
        }
        if (el.getAttribute('aria-label')) txt += ' ' + el.getAttribute('aria-label');
        let parent = el.parentElement, depth = 0;
        while (parent && depth < 4 && parent !== document.body) {
            if (parent.tagName === 'LABEL') { txt += ' ' + (parent.textContent || ''); break; }
            parent = parent.parentElement;
            depth++;
        }
        return (txt + ' ' + (el.name || '') + ' ' + (el.id || '')).toLowerCase();
    }
    const inputs = Array.from(document.querySelectorAll('input[type="file"]'));
    const visible = inputs.filter(el => !el.disabled);
    let resumeInput = null, coverInput = null;
    for (const el of visible) {
        const t = labelText(el);
        if (!resumeInput && /(resume|cv\b|curriculum)/.test(t)) resumeInput = el;
        else if (!coverInput && /(cover\s*letter|cover-letter|coverletter)/.test(t)) coverInput = el;
    }
    const queue = [];
    if (resumeInput && __HAS_RESUME__) queue.push(resumeInput);
    if (coverInput && __HAS_COVER__) queue.push(coverInput);
    queue.forEach(el => el.click());
    return { uploaded_resume: !!resumeInput && __HAS_RESUME__, uploaded_cover: !!coverInput && __HAS_COVER__ };
})();
"""

from ... import config
from ...db import DB


HOME_PAGE = "https://www.google.com/search?q=jobs"


class BrowserPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        if not HAS_WEBENGINE:
            self._build_fallback()
            return

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(14)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_label = QLabel("Job Search")
        title_label.setObjectName("PageTitle")
        title_row.addWidget(title_label)
        title_row.addStretch(1)

        tailor_btn = QPushButton("Tailor resume from page")
        tailor_btn.setToolTip(
            "Extract this page's text and run ATS-optimized resume tailoring against it"
        )
        tailor_btn.clicked.connect(self._on_tailor_from_page)
        title_row.addWidget(tailor_btn)

        cover_btn = QPushButton("Draft cover letter from page")
        cover_btn.setToolTip(
            "Generate a cover letter using this page's job description, your profile, "
            "and your story bank"
        )
        cover_btn.clicked.connect(self._on_cover_letter_from_page)
        title_row.addWidget(cover_btn)

        autofill_btn = QPushButton("Auto-fill ATS form")
        autofill_btn.setToolTip(
            "Fill text fields from your profile and upload your most recent tailored "
            "resume + cover letter into the form"
        )
        autofill_btn.clicked.connect(self._on_autofill)
        title_row.addWidget(autofill_btn)

        save_btn = QPushButton("Save to pipeline")
        save_btn.setObjectName("PrimaryButton")
        save_btn.setToolTip(
            "Capture the current URL and page title as a new application in your pipeline"
        )
        save_btn.clicked.connect(self._on_save_current)
        title_row.addWidget(save_btn)
        outer.addLayout(title_row)

        body = QHBoxLayout()
        body.setSpacing(14)

        # Left rail — job board shortcuts
        rail_card = QFrame()
        rail_card.setObjectName("Card")
        rail_card.setFixedWidth(280)
        rail_layout = QVBoxLayout(rail_card)
        rail_layout.setContentsMargins(16, 14, 16, 14)
        rail_layout.setSpacing(10)

        rail_title = QLabel("Job boards")
        rail_title.setObjectName("SectionTitle")
        rail_layout.addWidget(rail_title)

        self.boards = QListWidget()
        self.boards.setFrameShape(QFrame.NoFrame)
        self.boards.itemActivated.connect(self._on_board_clicked)
        self.boards.itemClicked.connect(self._on_board_clicked)
        rail_layout.addWidget(self.boards, 1)

        rail_buttons = QHBoxLayout()
        add_btn = QPushButton("+ Add")
        add_btn.clicked.connect(self._on_add_board)
        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(self._on_edit_board)
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self._on_delete_board)
        rail_buttons.addWidget(add_btn)
        rail_buttons.addWidget(edit_btn)
        rail_buttons.addWidget(del_btn)
        rail_layout.addLayout(rail_buttons)

        body.addWidget(rail_card)

        # Right — browser
        browser_card = QFrame()
        browser_card.setObjectName("Card")
        bc_layout = QVBoxLayout(browser_card)
        bc_layout.setContentsMargins(12, 12, 12, 12)
        bc_layout.setSpacing(10)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)
        style = self.style()
        self.back_btn = QPushButton()
        self.back_btn.setIcon(style.standardIcon(QStyle.SP_ArrowBack))
        self.back_btn.setFixedWidth(36)
        self.back_btn.setToolTip("Back")
        self.fwd_btn = QPushButton()
        self.fwd_btn.setIcon(style.standardIcon(QStyle.SP_ArrowForward))
        self.fwd_btn.setFixedWidth(36)
        self.fwd_btn.setToolTip("Forward")
        self.reload_btn = QPushButton()
        self.reload_btn.setIcon(style.standardIcon(QStyle.SP_BrowserReload))
        self.reload_btn.setFixedWidth(36)
        self.reload_btn.setToolTip("Reload")
        self.address = QLineEdit()
        self.address.setPlaceholderText("Type a URL or paste a job listing link — Enter to go")
        self.address.returnPressed.connect(self._on_address_enter)
        self.go_btn = QPushButton("Go")
        nav_row.addWidget(self.back_btn)
        nav_row.addWidget(self.fwd_btn)
        nav_row.addWidget(self.reload_btn)
        nav_row.addWidget(self.address, 1)
        nav_row.addWidget(self.go_btn)
        bc_layout.addLayout(nav_row)

        self.view = QWebEngineView()
        profile = QWebEngineProfile.defaultProfile()
        profile.setHttpUserAgent(CHROME_UA)
        custom_page = _JobHuntPage(profile, self.view)
        self.view.setPage(custom_page)
        s = self.view.settings()
        s.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        s.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, True)
        s.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
        s.setAttribute(QWebEngineSettings.PluginsEnabled, True)
        s.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True)
        s.setAttribute(QWebEngineSettings.ScrollAnimatorEnabled, True)
        self.view.urlChanged.connect(self._on_url_changed)
        self.view.titleChanged.connect(self._on_title_changed)
        bc_layout.addWidget(self.view, 1)

        self.status_label = QLabel("Ready.")
        self.status_label.setStyleSheet(f"color: {config.COLOR_TEXT_DIM};")
        bc_layout.addWidget(self.status_label)

        body.addWidget(browser_card, 1)
        outer.addLayout(body, 1)

        self.back_btn.clicked.connect(self.view.back)
        self.fwd_btn.clicked.connect(self.view.forward)
        self.reload_btn.clicked.connect(self.view.reload)
        self.go_btn.clicked.connect(self._on_address_enter)

        QShortcut(QKeySequence("Ctrl+L"), self, activated=self._focus_address)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.view.reload)

        self._load_boards()
        self.view.load(QUrl(HOME_PAGE))

    # ---- Fallback when QtWebEngineWidgets unavailable ----
    def _build_fallback(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        title = QLabel("Job Search")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        msg = QLabel(
            "Embedded browser requires QtWebEngine, which isn't installed.\n\n"
            "Run:  .venv\\Scripts\\python.exe -m pip install PySide6-WebEngine\n\n"
            "Then reload JobHunt."
        )
        msg.setAlignment(Qt.AlignCenter)
        msg.setWordWrap(True)
        msg.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 14px;")
        layout.addStretch(1)
        layout.addWidget(msg)
        layout.addStretch(1)

    # ---- Job board rail ----
    def _seed_boards_if_empty(self):
        existing = DB.query_one("SELECT COUNT(*) AS n FROM settings_kv WHERE key = 'job_boards_seeded'")
        if existing and existing["n"] > 0:
            return
        for name, url in config.DEFAULT_JOB_BOARDS:
            DB.execute(
                "INSERT INTO settings_kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO NOTHING",
                (f"job_board:{name}", url),
            )
        DB.set_setting("job_boards_seeded", "1")

    def _all_boards(self) -> list[tuple[str, str]]:
        self._seed_boards_if_empty()
        rows = DB.query(
            "SELECT key, value FROM settings_kv WHERE key LIKE 'job_board:%' ORDER BY key"
        )
        return [(r["key"].split(":", 1)[1], r["value"]) for r in rows]

    def _load_boards(self):
        self.boards.clear()
        for name, url in self._all_boards():
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, url)
            item.setToolTip(url)
            self.boards.addItem(item)

    def _on_board_clicked(self, item: QListWidgetItem):
        url = item.data(Qt.UserRole)
        if url:
            self._navigate(url)

    def _on_add_board(self):
        name, ok = QInputDialog.getText(self, "Add job board", "Name (e.g. 'Anthropic Careers'):")
        if not ok or not name.strip():
            return
        url, ok = QInputDialog.getText(self, "Add job board", "URL:", text="https://")
        if not ok or not url.strip():
            return
        DB.execute(
            "INSERT INTO settings_kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"job_board:{name.strip()}", url.strip()),
        )
        DB.log_audit("job_board_added", {"name": name.strip(), "url": url.strip()})
        self._load_boards()

    def _on_edit_board(self):
        item = self.boards.currentItem()
        if not item:
            return
        old_name = item.text()
        new_name, ok = QInputDialog.getText(self, "Edit job board", "Name:", text=old_name)
        if not ok or not new_name.strip():
            return
        new_url, ok = QInputDialog.getText(
            self, "Edit job board", "URL:", text=item.data(Qt.UserRole),
        )
        if not ok or not new_url.strip():
            return
        DB.execute("DELETE FROM settings_kv WHERE key = ?", (f"job_board:{old_name}",))
        DB.execute(
            "INSERT INTO settings_kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"job_board:{new_name.strip()}", new_url.strip()),
        )
        DB.log_audit("job_board_edited", {"old": old_name, "new": new_name.strip()})
        self._load_boards()

    def _on_delete_board(self):
        item = self.boards.currentItem()
        if not item:
            return
        confirm = QMessageBox.question(
            self, "Remove job board",
            f"Remove '{item.text()}' from your shortcuts?",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return
        DB.execute("DELETE FROM settings_kv WHERE key = ?", (f"job_board:{item.text()}",))
        DB.log_audit("job_board_deleted", {"name": item.text()})
        self._load_boards()

    # ---- Navigation ----
    def _normalize_url(self, raw: str) -> QUrl:
        text = raw.strip()
        if not text:
            return QUrl(HOME_PAGE)
        if "://" not in text:
            if " " in text or "." not in text.split("/", 1)[0]:
                text = f"https://www.google.com/search?q={text.replace(' ', '+')}"
            else:
                text = "https://" + text
        return QUrl(text)

    def _navigate(self, url: str):
        self.view.load(self._normalize_url(url))

    def _on_address_enter(self):
        self._navigate(self.address.text())

    def _focus_address(self):
        self.address.setFocus()
        self.address.selectAll()

    def _on_url_changed(self, url: QUrl):
        self.address.setText(url.toString())

    def _on_title_changed(self, title: str):
        self.status_label.setText(title or "")

    def _on_save_current(self):
        if not hasattr(self, "view"):
            return
        url = self.view.url().toString()
        title = self.view.title() or ""
        if not url or url.startswith("about:"):
            QMessageBox.information(
                self, "Nothing to save",
                "Navigate to a job listing page first.",
            )
            return

        company, ok = QInputDialog.getText(
            self, "Save to pipeline",
            "Company name:",
            text=self._guess_company_from_url(url),
        )
        if not ok or not company.strip():
            return
        role, ok = QInputDialog.getText(
            self, "Save to pipeline",
            "Role / position title:",
            text=title.split(" - ")[0] if " - " in title else title,
        )
        if not ok or not role.strip():
            return

        stage_row = DB.query_one(
            "SELECT id FROM pipeline_stages ORDER BY sort_order LIMIT 1"
        )
        stage_id = stage_row["id"] if stage_row else None

        DB.execute(
            """INSERT INTO applications
               (company, role, source, date_applied, current_stage_id, listing_url)
               VALUES (?, ?, ?, date('now'), ?, ?)""",
            (company.strip(), role.strip(), "Browser", stage_id, url),
        )
        DB.log_audit("application_saved_from_browser",
                     {"company": company.strip(), "role": role.strip(), "url": url})
        self.status_label.setText(f"✓ Saved '{company} — {role}' to pipeline.")

    @staticmethod
    def _guess_company_from_url(url: str) -> str:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        if not host:
            return ""
        for prefix in ("www.", "jobs.", "careers.", "boards.", "apply."):
            if host.startswith(prefix):
                host = host[len(prefix):]
                break
        parts = host.split(".")
        if not parts:
            return ""
        if parts[0] in ("greenhouse", "lever", "ashbyhq", "workable", "smartrecruiters"):
            path_parts = urlparse(url).path.strip("/").split("/")
            if path_parts:
                return path_parts[0].replace("-", " ").title()
        return parts[0].replace("-", " ").title()

    # ---- Page-aware actions (Tailor resume / Draft cover letter) ----

    def _extract_page_text(self, on_ready):
        """Async — fetches the rendered text of the current page and calls on_ready(text)."""
        if not hasattr(self, "view"):
            on_ready("")
            return
        page = self.view.page()
        if page is None:
            on_ready("")
            return
        page.toPlainText(lambda text: on_ready(text or ""))

    def _master_resume(self):
        """Return (resume_type_id, ResumeContent) for the user's most recently saved
        resume version, or None if the user hasn't imported one."""
        from ...documents.model import ResumeContent
        type_row = DB.query_one("SELECT id, name FROM resume_types ORDER BY id LIMIT 1")
        if not type_row:
            return None
        version_row = DB.query_one(
            """SELECT content_json FROM resume_versions
               WHERE resume_type_id = ?
               ORDER BY version_number DESC LIMIT 1""",
            (type_row["id"],),
        )
        if not version_row or not version_row["content_json"]:
            return None
        try:
            content = ResumeContent.from_json(version_row["content_json"])
        except Exception:
            return None
        return type_row["id"], content

    def _on_tailor_from_page(self):
        self._extract_page_text(self._do_tailor_from_page)

    def _do_tailor_from_page(self, page_text: str):
        page_text = (page_text or "").strip()
        if len(page_text) < 100:
            QMessageBox.information(
                self, "Page too short",
                "Couldn't pull enough job description text from this page. "
                "Make sure a job listing is fully loaded, then try again.",
            )
            return
        master = self._master_resume()
        if master is None:
            QMessageBox.information(
                self, "No resume yet",
                "Import or build a resume in the Resume page first, then come back.",
            )
            return
        type_id, content = master

        from ..dialogs.tailor_resume import TailorResumeDialog
        dlg = TailorResumeDialog(content, type_id, parent=self)
        dlg.source_input.setPlainText(page_text[:30000])
        dlg.exec()

    def _on_cover_letter_from_page(self):
        self._extract_page_text(self._do_cover_letter_from_page)

    def _do_cover_letter_from_page(self, page_text: str):
        page_text = (page_text or "").strip()
        if len(page_text) < 100:
            QMessageBox.information(
                self, "Page too short",
                "Couldn't pull enough job description text from this page. "
                "Make sure a job listing is fully loaded, then try again.",
            )
            return

        from ..dialogs.generate_cover_letter import GenerateCoverLetterDialog
        dlg = GenerateCoverLetterDialog(parent=self)
        dlg.source_input.setPlainText(page_text[:30000])
        if not dlg.exec() or not dlg.generated_letter:
            return

        self._save_generated_letter(dlg.generated_letter)

    def _save_generated_letter(self, letter_text: str):
        apps = DB.query(
            """SELECT id, company, role, date_applied
               FROM applications
               ORDER BY date_applied DESC, id DESC
               LIMIT 50"""
        )

        items: list[str] = []
        items.append("(Don't save — just show the letter)")
        items.append("Create new application for this listing…")
        for a in apps:
            label = f"{a['company']} — {a['role']}"
            if a["date_applied"]:
                label += f"  ({a['date_applied']})"
            items.append(label)

        choice, ok = QInputDialog.getItem(
            self, "Save cover letter",
            "Link this cover letter to which application?",
            items, 0, False,
        )
        if not ok:
            return

        if choice == items[0]:
            self._show_letter_dialog(letter_text)
            return

        if choice == items[1]:
            app_id = self._create_application_from_page()
            if app_id is None:
                return
        else:
            app_id = apps[items.index(choice) - 2]["id"]

        DB.execute("DELETE FROM cover_letters WHERE application_id = ?", (app_id,))
        new_id = DB.execute(
            "INSERT INTO cover_letters (application_id, content) VALUES (?, ?)",
            (app_id, letter_text),
        )
        DB.execute(
            """UPDATE applications SET cover_letter_id = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (new_id, app_id),
        )
        DB.log_audit("cover_letter_saved_from_browser", {"application_id": app_id})
        QMessageBox.information(self, "Saved", "Cover letter linked to the application.")

    def _create_application_from_page(self) -> int | None:
        url = self.view.url().toString() if hasattr(self, "view") else ""
        title = self.view.title() if hasattr(self, "view") else ""
        company, ok = QInputDialog.getText(
            self, "New application", "Company:",
            text=self._guess_company_from_url(url),
        )
        if not ok or not company.strip():
            return None
        role, ok = QInputDialog.getText(
            self, "New application", "Role:",
            text=(title.split(" - ")[0] if " - " in title else title),
        )
        if not ok or not role.strip():
            return None
        stage_row = DB.query_one(
            "SELECT id FROM pipeline_stages ORDER BY sort_order LIMIT 1"
        )
        new_id = DB.execute(
            """INSERT INTO applications
               (company, role, source, date_applied, current_stage_id, listing_url)
               VALUES (?, ?, ?, date('now'), ?, ?)""",
            (company.strip(), role.strip(), "Browser",
             stage_row["id"] if stage_row else None, url),
        )
        DB.log_audit("application_created_from_browser",
                     {"id": new_id, "company": company.strip(), "url": url})
        return new_id

    def _show_letter_dialog(self, letter_text: str):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QHBoxLayout
        from PySide6.QtGui import QGuiApplication
        from ..widgets.dark_titlebar import apply_dark_title_bar

        dlg = QDialog(self)
        dlg.setWindowTitle("Generated cover letter")
        dlg.resize(720, 560)
        apply_dark_title_bar(dlg)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)

        title = QLabel("Generated cover letter")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        edit = QTextEdit()
        edit.setPlainText(letter_text)
        edit.setReadOnly(False)
        layout.addWidget(edit, 1)

        btns = QHBoxLayout()
        copy_btn = QPushButton("Copy to clipboard")
        copy_btn.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(edit.toPlainText())
        )
        btns.addWidget(copy_btn)
        btns.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("PrimaryButton")
        close_btn.clicked.connect(dlg.accept)
        btns.addWidget(close_btn)
        layout.addLayout(btns)

        dlg.exec()

    # ---- ATS auto-fill ----

    def _on_autofill(self):
        if not hasattr(self, "view"):
            return
        url = self.view.url().toString()
        if not url or url.startswith("about:"):
            QMessageBox.information(
                self, "Nothing to fill",
                "Navigate to an application form first.",
            )
            return

        confirm = QMessageBox.question(
            self, "Auto-fill this form?",
            "JobHunt will fill text fields from your profile (Settings → Profile) "
            "and upload your most recent tailored resume and cover letter into the "
            "form's file inputs. Existing values won't be overwritten. "
            "You'll still review and click Submit yourself.\n\n"
            "Proceed?",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Yes,
        )
        if confirm != QMessageBox.Yes:
            return

        profile_row = DB.query_one("SELECT * FROM profile WHERE id = 1")
        if not profile_row:
            QMessageBox.information(
                self, "No profile",
                "Fill out Settings → Profile first.",
            )
            return
        profile = dict(profile_row)
        legal = (profile.get("legal_name") or "").strip()
        parts = legal.split()
        first_name = profile.get("preferred_name") or (parts[0] if parts else "")
        last_name = parts[-1] if len(parts) > 1 else ""
        profile_for_js = {
            "first_name": first_name or "",
            "last_name": last_name or "",
            "legal_name": legal or "",
            "preferred_name": profile.get("preferred_name") or "",
            "email": profile.get("email") or "",
            "phone": profile.get("phone") or "",
            "linkedin_url": profile.get("linkedin_url") or "",
            "github_url": profile.get("github_url") or "",
            "portfolio_url": profile.get("portfolio_url") or "",
            "address": profile.get("address") or "",
            "work_auth": profile.get("work_auth") or "",
            "citizenship": profile.get("citizenship") or "",
        }

        import json as _json
        js = AUTOFILL_TEXT_JS.replace("__PROFILE__", _json.dumps(profile_for_js))
        # PySide6 >= 6.6: the 2-arg form is (script, worldId). Pass world 0
        # explicitly so the third arg is recognized as the result callback.
        self.view.page().runJavaScript(js, 0, self._on_autofill_text_done)

    def _on_autofill_text_done(self, result):
        try:
            filled = int(result.get("filled", 0)) if isinstance(result, dict) else 0
        except Exception:
            filled = 0
        self.status_label.setText(f"Auto-fill: filled {filled} text field(s). Preparing file uploads…")
        self._queue_files_for_upload()

    def _queue_files_for_upload(self):
        resume_path = self._export_latest_resume_to_temp()
        cover_path = self._export_latest_cover_letter_to_temp()
        queue: list[str] = []
        if resume_path:
            queue.append(resume_path)
        if cover_path:
            queue.append(cover_path)

        if queue:
            self.view.page().set_pending_files(queue)

        import json as _json
        js = (AUTOFILL_FILES_JS
              .replace("__HAS_RESUME__", "true" if resume_path else "false")
              .replace("__HAS_COVER__", "true" if cover_path else "false"))
        self.view.page().runJavaScript(
            js, 0,
            lambda r: self._on_autofill_files_done(r, resume_path, cover_path),
        )

    # _on_autofill_files_done is defined further down in the Fire-mode block
    # so the post-autofill hook can also trigger the submit click.

    def _export_latest_resume_to_temp(self) -> str | None:
        master = self._master_resume()
        if master is None:
            return None
        _type_id, content = master
        try:
            from ...documents.export import export_resume_pdf
            import tempfile, os
            tmp_dir = os.path.join(tempfile.gettempdir(), "JobHunt")
            os.makedirs(tmp_dir, exist_ok=True)
            safe_name = (content.name or "resume").replace(" ", "_") or "resume"
            path = os.path.join(tmp_dir, f"{safe_name}_resume.pdf")
            export_resume_pdf(content, path)
            return path
        except Exception as e:
            self.status_label.setText(f"Could not export resume to PDF: {e}")
            return None

    def _export_latest_cover_letter_to_temp(self) -> str | None:
        row = DB.query_one(
            """SELECT cl.content, a.company
               FROM cover_letters cl
               LEFT JOIN applications a ON a.id = cl.application_id
               ORDER BY cl.id DESC LIMIT 1"""
        )
        if not row or not row["content"]:
            return None
        profile_row = DB.query_one("SELECT * FROM profile WHERE id = 1")
        profile = dict(profile_row) if profile_row else {}
        try:
            from ...documents.export import export_cover_letter_pdf
            import tempfile, os
            tmp_dir = os.path.join(tempfile.gettempdir(), "JobHunt")
            os.makedirs(tmp_dir, exist_ok=True)
            company = (row["company"] or "cover_letter").replace(" ", "_") or "cover_letter"
            path = os.path.join(tmp_dir, f"{company}_cover.pdf")
            export_cover_letter_pdf(row["content"], path, profile)
            return path
        except Exception as e:
            self.status_label.setText(f"Could not export cover letter to PDF: {e}")
            return None

    # ----------------------------------------------------------------- Fire mode

    SUBMIT_JS = r"""
    (function() {
        try {
            const labels = [
                "submit application", "submit my application", "submit",
                "apply now", "send application", "send my application",
                "complete application", "finish application"
            ];
            function textOf(el) {
                return (el.innerText || el.value || el.getAttribute('aria-label') || "").trim().toLowerCase();
            }
            const candidates = Array.from(document.querySelectorAll(
                'button, input[type="submit"], a[role="button"], div[role="button"]'
            )).filter(el => {
                if (el.disabled) return false;
                if (el.offsetParent === null) return false;  // not visible
                const txt = textOf(el);
                if (!txt) return false;
                return labels.some(l => txt.includes(l));
            });
            // Prefer the deepest match (closest to the form). If none, bail.
            if (!candidates.length) {
                return {clicked: false, reason: "no submit button found"};
            }
            candidates.sort((a, b) => {
                const aIsBtn = a.tagName === 'BUTTON' || a.type === 'submit' ? 1 : 0;
                const bIsBtn = b.tagName === 'BUTTON' || b.type === 'submit' ? 1 : 0;
                if (aIsBtn !== bIsBtn) return bIsBtn - aIsBtn;
                return textOf(a).length - textOf(b).length;
            });
            const btn = candidates[0];
            const label = textOf(btn);
            btn.scrollIntoView({block: "center"});
            btn.click();
            return {clicked: true, label: label};
        } catch (e) {
            return {clicked: false, reason: String(e)};
        }
    })();
    """

    def fire(self, job) -> None:
        """Auto-fill + auto-submit a queue job. Called by AutonomousPage after
        the user clicks Fire on a queued match. The whitelist + daily-cap
        checks must have already passed."""
        from ...autonomous import fire as fire_mod
        from ...autonomous import queue as queue_mod

        # Re-check eligibility — guards against a stale UI state.
        eligibility = fire_mod.can_fire(job)
        if not eligibility.eligible:
            QMessageBox.warning(self, "Cannot fire", eligibility.reason)
            return

        self._fire_job = job
        self._fire_ats = eligibility.ats_name
        self.status_label.setText(
            f"🔥 Firing on {eligibility.ats_name}: {job.company} — {job.role}…"
        )

        # Chain: navigate → loadFinished → autofill → wait → submit → done
        try:
            self.view.loadFinished.disconnect(self._on_fire_load_finished)
        except (TypeError, RuntimeError):
            pass
        self.view.loadFinished.connect(self._on_fire_load_finished)
        self.view.setUrl(QUrl(job.source_url))

    def _on_fire_load_finished(self, ok: bool):
        try:
            self.view.loadFinished.disconnect(self._on_fire_load_finished)
        except (TypeError, RuntimeError):
            pass
        if not ok:
            self._fire_fail("Page failed to load.")
            return
        # Give the page a moment for client-side renders to settle.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, self._fire_run_autofill)

    def _fire_run_autofill(self):
        # We replay the existing autofill path; it ends with a call to
        # _queue_files_for_upload which JS-runs the file-input clicks. We need
        # to know when THAT is done so we can submit. Use a one-shot hook.
        self._fire_pending_submit = True
        self._on_autofill()

    def _on_autofill_files_done(self, result, resume_path, cover_path):
        # Call the parent implementation first so the status label is set normally.
        try:
            super_impl = self.__class__.__bases__[0].__dict__.get("_on_autofill_files_done")
        except Exception:
            super_impl = None
        # The original is on this same class, not a parent — call it inline:
        if not isinstance(result, dict):
            result = {}
        bits = []
        if resume_path and result.get("uploaded_resume"):
            bits.append("resume")
        elif resume_path:
            bits.append("(resume ready but no matching file input found)")
        if cover_path and result.get("uploaded_cover"):
            bits.append("cover letter")
        elif cover_path:
            bits.append("(cover letter ready but no matching file input found)")
        if bits:
            self.status_label.setText("Auto-fill done · uploaded: " + ", ".join(bits))
        else:
            self.status_label.setText("Auto-fill done.")
        DB.log_audit("ats_autofill", {
            "url": self.view.url().toString(),
            "resume": bool(resume_path and result.get("uploaded_resume")),
            "cover": bool(cover_path and result.get("uploaded_cover")),
        })

        if getattr(self, "_fire_pending_submit", False):
            self._fire_pending_submit = False
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1200, self._fire_click_submit)

    def _fire_click_submit(self):
        self.status_label.setText("🔥 Clicking submit…")
        self.view.page().runJavaScript(self.SUBMIT_JS, 0, self._on_fire_submit_done)

    def _on_fire_submit_done(self, result):
        from ...autonomous import fire as fire_mod
        job = getattr(self, "_fire_job", None)
        ats = getattr(self, "_fire_ats", "unknown")
        self._fire_job = None
        self._fire_ats = None
        if job is None:
            return
        if not isinstance(result, dict):
            result = {}
        if not result.get("clicked"):
            self._fire_fail(result.get("reason") or "Submit button not found.")
            return
        fire_mod.mark_auto_submitted(job.id, ats_name=ats)
        self.status_label.setText(
            f"✓ Submitted to {ats}: {job.company} — {job.role} "
            f"(button: '{result.get('label', '?')}')"
        )

    def _fire_fail(self, reason: str):
        from ...autonomous import fire as fire_mod
        job = getattr(self, "_fire_job", None)
        self._fire_job = None
        self._fire_ats = None
        if job is not None:
            fire_mod.mark_fire_error(job.id, reason)
        self.status_label.setText(f"Fire failed: {reason}")

    def ai_context(self) -> dict:
        current_url = ""
        current_title = ""
        if hasattr(self, "view"):
            current_url = self.view.url().toString()
            current_title = self.view.title() or ""
        return {
            "page": "Job Search",
            "summary": f"Browsing: {current_title or current_url or '(home)'}",
            "data": {"url": current_url, "title": current_title},
            "rule_based_hints": [
                "Click 'Save current page to pipeline' on a job listing to track it.",
                "Use Ctrl+L to focus the address bar.",
                "Add custom job boards via the + Add button on the left rail.",
            ],
        }
