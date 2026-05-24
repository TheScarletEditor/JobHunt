from __future__ import annotations

import json
import re

from PySide6.QtCore import Qt, Signal, QTimer, QObject, QThread, QUrl, QPoint
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLineEdit, QPlainTextEdit,
    QLabel, QPushButton, QScrollArea, QSplitter, QTextBrowser, QComboBox,
)

from ... import config
from ...db import DB
from ...documents.model import (
    ResumeContent, ResumeSection, ResumeItem,
    SECTION_KIND_DETAIL as KIND_DETAIL,
    SECTION_KIND_LIST as KIND_LIST,
    SECTION_KIND_LINE as KIND_LINE,
    detect_section_kind as _detect_kind,
)
from .growing_text import GrowingTextEdit as _GrowingTextEdit


# ============================================================================
# Section-kind labels for the dropdown
# ============================================================================

KIND_LABELS = [
    ("Experience / projects (bullets)", KIND_DETAIL),
    ("Skills / tools (comma-separated)", KIND_LIST),
    ("Certifications / awards (lines)",  KIND_LINE),
]


# ============================================================================
# Markdown <-> rich-text helpers
#
# Bullets are stored in the resume JSON as plain strings with inline markdown:
# **bold**, *italic*, ***bold-italic***. The editor displays them as actual
# styled text. md_to_html() converts on load; qtextedit_to_md() converts back
# on save by walking the QTextEdit's QTextDocument and emitting markdown based
# on each fragment's character format.
# ============================================================================


def _md_to_html(text: str) -> str:
    if not text:
        return ""
    # Escape HTML
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Bold-italic ***x***
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", text)
    # Bold **x**
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # Italic *x* (avoid sticking to alphanumerics on either side)
    text = re.sub(r"(?<![*\w])\*([^*\n]+?)\*(?![*\w])", r"<i>\1</i>", text)
    return text


def _md_to_html_inline(text: str) -> str:
    """Same as md_to_html but doesn't escape — already-escaped or for preview."""
    if not text:
        return ""
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![*\w])\*([^*\n]+?)\*(?![*\w])", r"<i>\1</i>", text)
    return text


# ============================================================================
# Synonym group plumbing
# ============================================================================


def _load_synonym_groups() -> list[list[str]]:
    rows = DB.query("SELECT terms_json FROM synonym_groups")
    out: list[list[str]] = []
    for r in rows:
        try:
            terms = json.loads(r["terms_json"])
        except Exception:
            continue
        if isinstance(terms, list):
            cleaned = [str(t).strip() for t in terms if str(t).strip()]
            if len(cleaned) >= 2:
                out.append(cleaned)
    return out


def _apply_swaps(text: str, target_keywords: set[str]) -> str:
    if not text.strip() or not target_keywords:
        return text
    groups = _load_synonym_groups()
    if not groups:
        return text
    listing_lower = " ".join(target_keywords).lower()
    result = text
    for group in groups:
        target = next((t for t in group if t.lower() in listing_lower), None)
        if not target:
            continue
        for term in group:
            if term == target or not term:
                continue
            result = re.sub(re.escape(term), target, result, flags=re.IGNORECASE)
    return result


# ============================================================================
# Section reshape helpers (skills explode, certs collapse)
# ============================================================================


_CATEGORY_RX = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 &/+\-]{1,50}):\s*(.+)$")


def _explode_skills_section(section: ResumeSection) -> ResumeSection:
    from collections import OrderedDict
    groups: "OrderedDict[str, list[str]]" = OrderedDict()

    def _add(cat: str, skill: str):
        skill = skill.strip(" \t-•·")
        if not skill:
            return
        bucket = groups.setdefault(cat, [])
        if skill not in bucket:
            bucket.append(skill)

    for item in section.items:
        item_cat = (item.header or "").strip()
        if not item.bullets:
            if item_cat:
                groups.setdefault(item_cat, [])
            continue
        for raw in item.bullets:
            text = (raw or "").strip()
            if not text:
                continue
            cat = item_cat
            if not cat:
                m = _CATEGORY_RX.match(text)
                if m and ("," in m.group(2) or ";" in m.group(2)):
                    cat = m.group(1).strip()
                    text = m.group(2)
            for part in re.split(r"[,;|]", text):
                _add(cat, part)

    return ResumeSection(
        title=section.title,
        items=[ResumeItem(header=cat, subheader="", bullets=skills)
               for cat, skills in groups.items()],
    )


def _collapse_line_section(section: ResumeSection) -> ResumeSection:
    new_items: list[ResumeItem] = []
    for item in section.items:
        if item.bullets:
            for b in item.bullets:
                txt = b.strip()
                if txt:
                    new_items.append(ResumeItem(header=txt, subheader=item.subheader, bullets=[]))
            if item.header and not any(it.header == item.header for it in new_items):
                new_items.insert(0, ResumeItem(header=item.header, subheader=item.subheader, bullets=[]))
        else:
            if item.header or item.subheader:
                new_items.append(ResumeItem(
                    header=item.header.strip(), subheader=item.subheader.strip(), bullets=[],
                ))
    return new_items and ResumeSection(title=section.title, items=new_items) or ResumeSection(title=section.title, items=[])


# ============================================================================
# AI rewrite-suggestions popup
# ============================================================================


class _RewriteWorker(QObject):
    done = Signal(list, str)  # (suggestions, error)

    def __init__(self, bullet_md: str, resume: ResumeContent, listing: str):
        super().__init__()
        self._bullet = bullet_md
        self._resume = resume
        self._listing = listing

    def run(self):
        try:
            from ...llm import get_provider
            provider = get_provider()
            suggestions = provider.suggest_bullet_rewrites(
                self._bullet, self._resume, job_listing=self._listing,
            )
            self.done.emit(suggestions or [], "")
        except Exception as e:
            self.done.emit([], f"{type(e).__name__}: {e}")


class _RewritePopup(QFrame):
    """Floating panel showing 3 AI rewrite alternatives for one bullet."""
    accepted = Signal(str)

    def __init__(self, original_md: str, resume: ResumeContent, listing: str, parent=None):
        super().__init__(parent)
        self.setObjectName("RewritePopup")
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            f"#RewritePopup {{ background: {config.COLOR_BG_RAISED}; "
            f"border: 1px solid {config.COLOR_BORDER_LIGHT}; border-radius: 8px; }}"
        )
        self.setWindowFlags(Qt.Popup)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        head = QLabel("✨ AI suggestions")
        head.setStyleSheet(
            f"color: {config.COLOR_TEXT}; font-size: 13px; font-weight: 700;"
        )
        layout.addWidget(head)

        sub = QLabel(
            "Same facts, your voice. Click one to apply — you can keep editing afterwards."
        )
        sub.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 11px;")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        self._suggestions_layout = QVBoxLayout()
        self._suggestions_layout.setSpacing(6)
        layout.addLayout(self._suggestions_layout)

        self.status = QLabel("Thinking…")
        self.status.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 11px;")
        layout.addWidget(self.status)

        btns = QHBoxLayout()
        btns.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("GhostButton")
        close.clicked.connect(self.close)
        btns.addWidget(close)
        layout.addLayout(btns)

        self._thread: QThread | None = None
        self._worker: _RewriteWorker | None = None
        self._kick_off(original_md, resume, listing)

    def _kick_off(self, bullet_md: str, resume: ResumeContent, listing: str):
        self._thread = QThread(self)
        self._worker = _RewriteWorker(bullet_md, resume, listing)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_done(self, suggestions: list[str], err: str):
        if err:
            self.status.setText(f"Couldn't fetch suggestions: {err}")
            self.status.setStyleSheet(f"color: {config.COLOR_ACCENT}; font-size: 11px;")
            return
        if not suggestions:
            self.status.setText(
                "No suggestions available. Add an API key in Settings → API Keys, "
                "or paste a target job listing first."
            )
            self.status.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 11px;")
            return
        self.status.hide()
        for s in suggestions:
            self._suggestions_layout.addWidget(self._make_card(s))

    def _make_card(self, suggestion: str) -> QFrame:
        card = QFrame()
        card.setObjectName("SuggestionCard")
        card.setCursor(Qt.PointingHandCursor)
        card.setStyleSheet(
            f"#SuggestionCard {{ background: {config.COLOR_BG_HOVER}; "
            f"border: 1px solid {config.COLOR_BORDER_LIGHT}; border-radius: 6px; }}"
            f"#SuggestionCard:hover {{ border-color: {config.COLOR_ACCENT}; }}"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 10, 12, 10)
        label = QLabel(_md_to_html_inline(suggestion))
        label.setTextFormat(Qt.RichText)
        label.setStyleSheet(f"color: {config.COLOR_TEXT}; font-size: 12px;")
        label.setWordWrap(True)
        cl.addWidget(label)
        def _click(_event, s=suggestion):
            self.accepted.emit(s)
            self.close()
        card.mousePressEvent = _click
        return card


# ============================================================================
# Formatting toolbar — Bold / Italic / Bullet operating on a QPlainTextEdit
#
# We're in plain-text-with-markdown land, so "bold" just wraps the selection
# in **, italic in *, and the bullet button toggles a "- " prefix on each line
# in the current selection (or the line under the cursor). Ctrl+B / Ctrl+I /
# Ctrl+Shift+8 are wired up as keyboard shortcuts on the edit itself.
# ============================================================================


class _FormatToolbar(QWidget):
    def __init__(self, edit: QPlainTextEdit, *, include_bullet: bool = True, parent=None):
        super().__init__(parent)
        self._edit = edit

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(4)

        self._add_btn(
            layout, "B", "Bold (Ctrl+B) — wraps selected text in **",
            lambda: self._wrap("**", "**"), bold=True,
        )
        self._add_btn(
            layout, "I", "Italic (Ctrl+I) — wraps selected text in *",
            lambda: self._wrap("*", "*"), italic=True,
        )
        if include_bullet:
            self._add_btn(
                layout, "• Bullet", "Toggle bullet (Ctrl+Shift+8) on the current line",
                self._toggle_bullet,
            )
        layout.addStretch(1)

        # Keyboard shortcuts on the target edit.
        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Ctrl+B"), edit, activated=lambda: self._wrap("**", "**"))
        QShortcut(QKeySequence("Ctrl+I"), edit, activated=lambda: self._wrap("*", "*"))
        if include_bullet:
            QShortcut(QKeySequence("Ctrl+Shift+8"), edit, activated=self._toggle_bullet)

    def _add_btn(self, layout, label, tip, slot, *, bold=False, italic=False):
        btn = QPushButton(label)
        f = btn.font()
        if bold:
            f.setBold(True)
        if italic:
            f.setItalic(True)
        btn.setFont(f)
        btn.setObjectName("GhostButton")
        btn.setFixedHeight(28)
        btn.setMinimumWidth(36)
        btn.setToolTip(tip)
        btn.setFocusPolicy(Qt.NoFocus)  # don't steal focus from the edit
        btn.clicked.connect(slot)
        layout.addWidget(btn)

    def _wrap(self, prefix: str, suffix: str):
        cursor = self._edit.textCursor()
        if cursor.hasSelection():
            selected = cursor.selectedText()
            cursor.insertText(f"{prefix}{selected}{suffix}")
        else:
            pos = cursor.position()
            cursor.insertText(f"{prefix}{suffix}")
            cursor.setPosition(pos + len(prefix))
            self._edit.setTextCursor(cursor)
        self._edit.setFocus()

    def _toggle_bullet(self):
        doc = self._edit.document()
        cursor = self._edit.textCursor()

        # Collect blocks touched by the selection (or just the current block).
        if cursor.hasSelection():
            start = doc.findBlock(cursor.selectionStart())
            end = doc.findBlock(cursor.selectionEnd())
        else:
            start = end = cursor.block()

        blocks: list = []
        block = start
        while block.isValid():
            blocks.append(block)
            if block.blockNumber() >= end.blockNumber():
                break
            block = block.next()

        markers = ("- ", "* ", "• ")
        all_bulleted = all(b.text().lstrip().startswith(markers) for b in blocks if b.text().strip())

        cursor.beginEditBlock()
        try:
            for block in blocks:
                text = block.text()
                stripped = text.lstrip()
                indent = text[:len(text) - len(stripped)]
                if not stripped:
                    continue
                c = QTextCursor(block)
                c.movePosition(QTextCursor.StartOfBlock)
                c.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                if all_bulleted:
                    for m in markers:
                        if stripped.startswith(m):
                            c.insertText(indent + stripped[len(m):])
                            break
                else:
                    if not stripped.startswith(markers):
                        c.insertText(indent + "- " + stripped)
        finally:
            cursor.endEditBlock()
        self._edit.setFocus()


# ============================================================================
# Header panel (name + contact lines)
# ============================================================================


class _HeaderPanel(QWidget):
    content_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title = QLabel("Header")
        title.setStyleSheet(
            f"color: {config.COLOR_TEXT}; font-size: 18px; font-weight: 700;"
        )
        layout.addWidget(title)

        hint = QLabel("Your name and contact info. Shown at the top of every export.")
        hint.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 12px;")
        layout.addWidget(hint)

        self.name = QLineEdit()
        self.name.setPlaceholderText("Your full name")
        nf = self.name.font()
        nf.setPointSize(18)
        nf.setWeight(QFont.DemiBold)
        self.name.setFont(nf)
        self.name.textChanged.connect(lambda _t: self.content_changed.emit())
        layout.addWidget(self.name)

        cl_label = QLabel("Contact lines — one per line (email, phone, LinkedIn, GitHub, location)")
        cl_label.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 11px;")
        layout.addWidget(cl_label)

        self.contact = QPlainTextEdit()
        self.contact.setPlaceholderText(
            "you@example.com\n555-555-5555\nlinkedin.com/in/you\ngithub.com/you\nSeattle, WA"
        )
        self.contact.setFixedHeight(140)
        self.contact.setStyleSheet(
            "QPlainTextEdit { background: transparent; border: none; padding: 4px; "
            f"color: {config.COLOR_TEXT}; }}"
        )
        self.contact.textChanged.connect(self.content_changed.emit)
        layout.addWidget(self.contact)

        layout.addStretch(1)

    def load(self, name: str, contact: list[str]):
        self.name.blockSignals(True); self.contact.blockSignals(True)
        self.name.setText(name)
        self.contact.setPlainText("\n".join(contact or []))
        self.name.blockSignals(False); self.contact.blockSignals(False)

    def dump(self) -> tuple[str, list[str]]:
        contact_lines = [
            line.strip() for line in self.contact.toPlainText().splitlines() if line.strip()
        ]
        return self.name.text().strip(), contact_lines


# ============================================================================
# Summary panel (single rich text paragraph)
# ============================================================================


class _SummaryPanel(QWidget):
    content_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title = QLabel("Professional summary")
        title.setStyleSheet(
            f"color: {config.COLOR_TEXT}; font-size: 18px; font-weight: 700;"
        )
        layout.addWidget(title)

        hint = QLabel(
            "Free-form paragraph(s). Use the toolbar below to bold, italic, or bullet — "
            "or type **markdown** directly. The editor grows to fit your text."
        )
        hint.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 12px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.body = _GrowingTextEdit(min_lines=6)
        self.body.setPlaceholderText(
            "A short paragraph framing your background, focus, and what you're looking for."
        )
        self.body.textChanged.connect(self.content_changed.emit)
        layout.addWidget(_FormatToolbar(self.body, include_bullet=True))
        layout.addWidget(self.body)

        layout.addStretch(1)

    def load(self, summary: str):
        self.body.blockSignals(True)
        self.body.setPlainText(summary or "")
        self.body.blockSignals(False)

    def dump(self) -> str:
        return self.body.toPlainText().strip()


# ============================================================================
# Freeform section text <-> ResumeItem serialization
#
# Each body section is edited as one big text blob. We serialize ResumeItem
# lists to text on load and parse the text back to items on save. The format
# depends on the section kind.
# ============================================================================


_BULLET_LINE_RE = re.compile(r"^\s*[-*•·]\s+(.+)$")


def _items_to_text(section: ResumeSection, kind: str) -> str:
    """Render a section's items as a single editable text blob."""
    if kind == KIND_LIST:
        section = _explode_skills_section(section)
        lines: list[str] = []
        for item in section.items:
            cat = (item.header or "").strip()
            skills = ", ".join(b.strip() for b in item.bullets if b.strip())
            if cat and skills:
                lines.append(f"{cat}: {skills}")
            elif skills:
                lines.append(skills)
            elif cat:
                lines.append(f"{cat}:")
        return "\n".join(lines)

    if kind == KIND_LINE:
        section = _collapse_line_section(section)
        lines: list[str] = []
        for item in section.items:
            head = (item.header or "").strip()
            sub = (item.subheader or "").strip()
            if head and sub:
                lines.append(f"{head} · {sub}")
            elif head:
                lines.append(head)
            elif sub:
                lines.append(sub)
        return "\n".join(lines)

    # KIND_DETAIL: experience-style, items separated by blank line.
    blocks: list[str] = []
    for item in section.items:
        item_lines: list[str] = []
        if item.header:
            item_lines.append(item.header.strip())
        if item.subheader:
            item_lines.append(item.subheader.strip())
        for b in item.bullets:
            t = (b or "").strip()
            if t:
                item_lines.append(f"- {t}")
        if item_lines:
            blocks.append("\n".join(item_lines))
    return "\n\n".join(blocks)


def _text_to_items(text: str, kind: str) -> list[ResumeItem]:
    """Parse a section text blob back to a list of ResumeItems."""
    text = text or ""

    if kind == KIND_LIST:
        items: list[ResumeItem] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            cat = ""
            body = line
            m = _CATEGORY_RX.match(line)
            if m:
                cat = m.group(1).strip()
                body = m.group(2)
            bullets: list[str] = []
            for part in re.split(r"[,;|]", body):
                p = part.strip()
                if p and p not in bullets:
                    bullets.append(p)
            if cat or bullets:
                items.append(ResumeItem(header=cat, subheader="", bullets=bullets))
        return items

    if kind == KIND_LINE:
        items = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if " · " in line:
                head, sub = line.split(" · ", 1)
                items.append(ResumeItem(header=head.strip(), subheader=sub.strip(), bullets=[]))
            else:
                items.append(ResumeItem(header=line, subheader="", bullets=[]))
        return items

    # KIND_DETAIL: blank lines separate items.
    items = []
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.splitlines()]
        # Drop leading/trailing blank lines inside the block.
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            continue
        header = lines[0].strip()
        subheader = ""
        bullet_start = 1
        if len(lines) > 1 and not _BULLET_LINE_RE.match(lines[1]):
            subheader = lines[1].strip()
            bullet_start = 2
        bullets: list[str] = []
        for ln in lines[bullet_start:]:
            m = _BULLET_LINE_RE.match(ln)
            if m:
                bullets.append(m.group(1).strip())
            else:
                t = ln.strip()
                if t and bullets:
                    # Continuation of the previous bullet.
                    bullets[-1] = f"{bullets[-1]} {t}"
                elif t:
                    bullets.append(t)
        items.append(ResumeItem(header=header, subheader=subheader, bullets=bullets))
    return items


# ============================================================================
# Section panel — title + kind selector + one big growing text body
#
# Same shape as the Summary panel. No per-item editors, no per-bullet toolbars.
# Users type in a simple format: blank line separates items in Experience-style
# sections; bullets start with "- "; skills are comma-separated per category.
# ============================================================================


_KIND_HINTS = {
    KIND_DETAIL: (
        "One block per role / project, separated by a blank line. "
        "Line 1 = role · company · dates · location. "
        "Line 2 (optional) = location or extra context. "
        "Lines starting with '- ' = bullets. Use **bold** for emphasis."
    ),
    KIND_LIST: (
        "One line per category. Format: 'Category: skill1, skill2, skill3'. "
        "Drop the 'Category:' prefix for an uncategorized line."
    ),
    KIND_LINE: (
        "One entry per line. Use ' · ' (space-dot-space) to separate the entry "
        "from its detail — e.g. 'Prompt Engineering · Vanderbilt · 2024'."
    ),
}


class _SectionPanel(QWidget):
    content_changed = Signal()
    ai_requested    = Signal(str)  # emits the current bullet text under cursor

    def __init__(self, section: ResumeSection | None = None, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # --- Title row ---
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.title = QLineEdit()
        self.title.setPlaceholderText("Section title (e.g. Experience, Skills, Certifications)")
        tf = self.title.font()
        tf.setPointSize(18)
        tf.setWeight(QFont.Bold)
        self.title.setFont(tf)
        self.title.setStyleSheet(
            f"QLineEdit {{ background-color: transparent; border: none; "
            f"color: {config.COLOR_ACCENT}; padding: 2px 0; }}"
            f"QLineEdit:focus {{ border-bottom: 1px solid {config.COLOR_ACCENT}; padding-bottom: 1px; }}"
        )
        self.title.textChanged.connect(self._on_title_changed)
        title_row.addWidget(self.title, 1)

        self.kind_combo = QComboBox()
        for label, value in KIND_LABELS:
            self.kind_combo.addItem(label, value)
        self.kind_combo.setToolTip(
            "How this section should render. Auto-detected from the title; override here."
        )
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        title_row.addWidget(self.kind_combo)
        layout.addLayout(title_row)

        # --- Hint line ---
        self.hint = QLabel("")
        self.hint.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 12px;")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        # --- Body ---
        self.body = _GrowingTextEdit(min_lines=10)
        self.body.textChanged.connect(self._on_body_changed)

        # Toolbar row: formatting on the left, AI on the right.
        toolbar_row = QHBoxLayout()
        toolbar_row.setContentsMargins(0, 0, 0, 0)
        toolbar_row.setSpacing(8)
        self._toolbar = _FormatToolbar(self.body, include_bullet=True)
        toolbar_row.addWidget(self._toolbar, 1)
        self.ai_btn = QPushButton("✨ AI suggestions")
        self.ai_btn.setObjectName("GhostButton")
        self.ai_btn.setToolTip(
            "Suggest alternative phrasings for the bullet your cursor is sitting on. "
            "Preserves your facts and voice — you accept or reject each suggestion."
        )
        self.ai_btn.setFocusPolicy(Qt.NoFocus)
        self.ai_btn.clicked.connect(self._emit_ai_request)
        toolbar_row.addWidget(self.ai_btn)
        layout.addLayout(toolbar_row)

        layout.addWidget(self.body)

        self._kind = KIND_DETAIL
        if section:
            self.load(section)

    # ---------------------------------------------------------------- kind

    def _set_kind_combo(self, kind: str):
        for i, (_label, value) in enumerate(KIND_LABELS):
            if value == kind:
                self.kind_combo.blockSignals(True)
                self.kind_combo.setCurrentIndex(i)
                self.kind_combo.blockSignals(False)
                break

    def _on_title_changed(self, _text: str):
        # Kind is detected on load() only — silent flips while typing are too
        # surprising. Use the dropdown to override.
        self.content_changed.emit()

    def _on_kind_changed(self, _idx: int):
        new_kind = self.kind_combo.currentData()
        if new_kind == self._kind:
            return
        # Re-serialize current text under the new kind's format.
        current_items = _text_to_items(self.body.toPlainText(), self._kind)
        self._kind = new_kind
        text = _items_to_text(
            ResumeSection(title=self.title.text(), items=current_items),
            new_kind,
        )
        self.body.blockSignals(True)
        self.body.setPlainText(text)
        self.body.blockSignals(False)
        self._update_hint_and_placeholder()
        self.content_changed.emit()

    def _update_hint_and_placeholder(self):
        self.hint.setText(_KIND_HINTS.get(self._kind, ""))
        if self._kind == KIND_DETAIL:
            ph = (
                "Senior Engineer · Acme · 2022 — Present\n"
                "Remote\n"
                "- Led ...\n"
                "- Built ...\n"
                "\n"
                "Engineer · Other Co · 2020 — 2022\n"
                "- ...\n"
            )
        elif self._kind == KIND_LIST:
            ph = (
                "Tools: Salesforce, Jira, Confluence, Microsoft 365\n"
                "Languages: Python, SQL, JavaScript\n"
                "AI: Claude, ChatGPT, Prompt Engineering"
            )
        else:  # KIND_LINE
            ph = (
                "Prompt Engineering for ChatGPT · Vanderbilt · 2024\n"
                "Build Your Own Custom AI Assistants · Vanderbilt · 2024"
            )
        self.body.setPlaceholderText(ph)

    # ---------------------------------------------------------------- body

    def _on_body_changed(self):
        self.content_changed.emit()

    def _emit_ai_request(self):
        cursor = self.body.textCursor()
        block = cursor.block()
        line = block.text().strip()
        # Strip a leading bullet marker so we hand the LLM the bullet text only.
        m = _BULLET_LINE_RE.match(line)
        text = m.group(1).strip() if m else line
        if text:
            self.ai_requested.emit(text)

    def replace_cursor_line(self, new_text: str):
        """Replace the line under the cursor with new_text, preserving any
        leading bullet marker that was already there."""
        cursor = self.body.textCursor()
        block = cursor.block()
        original = block.text()
        m = _BULLET_LINE_RE.match(original)
        prefix = original[:m.start(1)] if m else ""
        cursor.setPosition(block.position())
        cursor.setPosition(block.position() + len(original), QTextCursor.KeepAnchor)
        cursor.insertText(prefix + new_text)

    # ---------------------------------------------------------------- load / dump

    def load(self, section: ResumeSection):
        self.title.blockSignals(True)
        self.title.setText(section.title or "")
        self.title.blockSignals(False)
        self._kind = _detect_kind(section.title)
        self._set_kind_combo(self._kind)
        self._update_hint_and_placeholder()
        text = _items_to_text(section, self._kind)
        self.body.blockSignals(True)
        self.body.setPlainText(text)
        self.body.blockSignals(False)

    def dump(self) -> ResumeSection:
        return ResumeSection(
            title=self.title.text().strip(),
            items=_text_to_items(self.body.toPlainText(), self._kind),
        )

# ============================================================================
# Outline strip — small clickable tabs at the top of the editor pane
# ============================================================================


class _OutlineStrip(QWidget):
    section_clicked    = Signal(str)   # emits a key like "header", "summary", "body/2"
    add_section_clicked = Signal()
    remove_section_clicked = Signal(int)
    move_section_clicked   = Signal(int, int)  # (from_idx, to_idx)

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFixedHeight(54)

        host = QWidget()
        self._row = QHBoxLayout(host)
        self._row.setContentsMargins(0, 6, 0, 6)
        self._row.setSpacing(6)
        self._row.addStretch(1)
        scroll.setWidget(host)
        outer.addWidget(scroll)

        self._buttons: dict[str, QPushButton] = {}
        self._active: str | None = None

    def rebuild(self, sections: list[ResumeSection]):
        for b in self._buttons.values():
            b.setParent(None)
            b.deleteLater()
        self._buttons.clear()
        # Remove the stretch + add buttons placeholder
        while self._row.count() > 0:
            it = self._row.takeAt(0)
            if it and it.widget():
                it.widget().setParent(None)

        for key, label in (("header", "Header"), ("summary", "Summary")):
            btn = self._make_tab(label, key)
            self._row.addWidget(btn)
            self._buttons[key] = btn

        for idx, sec in enumerate(sections):
            label = sec.title.strip() or f"Section {idx + 1}"
            key = f"body/{idx}"
            btn = self._make_tab(label, key)
            self._row.addWidget(btn)
            self._buttons[key] = btn

        add_btn = QPushButton("＋")
        add_btn.setObjectName("GhostButton")
        add_btn.setFixedHeight(30)
        add_btn.setToolTip("Add a new section")
        add_btn.clicked.connect(self.add_section_clicked.emit)
        self._row.addWidget(add_btn)
        self._row.addStretch(1)

        if self._active and self._active in self._buttons:
            self.set_active(self._active)
        elif self._buttons:
            self.set_active(next(iter(self._buttons)))

    def _make_tab(self, label: str, key: str) -> QPushButton:
        b = QPushButton(label)
        b.setFixedHeight(30)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(self._tab_qss(active=False))
        b.clicked.connect(lambda _c=False, k=key: self.section_clicked.emit(k))
        return b

    def _tab_qss(self, *, active: bool) -> str:
        if active:
            return (
                f"QPushButton {{ background: {config.COLOR_ACCENT}; "
                f"color: {config.COLOR_TEXT}; border: 1px solid {config.COLOR_ACCENT}; "
                f"border-radius: 14px; padding: 4px 14px; font-weight: 600; }}"
            )
        return (
            f"QPushButton {{ background: transparent; color: {config.COLOR_TEXT_DIM}; "
            f"border: 1px solid {config.COLOR_BORDER_LIGHT}; "
            f"border-radius: 14px; padding: 4px 14px; }}"
            f"QPushButton:hover {{ color: {config.COLOR_TEXT}; "
            f"border-color: {config.COLOR_TEXT_DIM}; }}"
        )

    def set_active(self, key: str):
        if key not in self._buttons:
            return
        if self._active and self._active in self._buttons:
            self._buttons[self._active].setStyleSheet(self._tab_qss(active=False))
        self._active = key
        self._buttons[key].setStyleSheet(self._tab_qss(active=True))


# ============================================================================
# Clickable preview pane
#
# Each section in the rendered HTML is wrapped in an <a href="section://KEY">
# anchor. We intercept anchorClicked to surface the key to the parent editor.
# ============================================================================


class _ClickablePreview(QTextBrowser):
    section_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setStyleSheet(
            "QTextBrowser { background-color: #ffffff; color: #1a1a1a; "
            "border: none; padding: 0; }"
        )
        self.anchorClicked.connect(self._on_anchor)

    def _on_anchor(self, url: QUrl):
        s = url.toString()
        if s.startswith("section://"):
            self.section_clicked.emit(s[len("section://"):])


# ============================================================================
# Main resume editor — click-to-edit layout
# ============================================================================


class ResumeEditor(QWidget):
    """Section-focused editor with live HTML preview.
    Click a section in the preview (or in the outline strip) to edit it.
    Bullets support inline bold/italic and AI rewrite suggestions."""

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # === Splitter: left = editor pane, right = preview ===
        splitter = QSplitter(Qt.Horizontal)
        outer.addWidget(splitter)

        # ----- Left pane -----
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(20, 16, 20, 16)
        ll.setSpacing(10)

        self.outline = _OutlineStrip()
        self.outline.section_clicked.connect(self._switch_to)
        self.outline.add_section_clicked.connect(self._add_blank_section)
        ll.addWidget(self.outline)

        edit_card = QFrame()
        edit_card.setObjectName("Card")
        ec = QVBoxLayout(edit_card)
        ec.setContentsMargins(20, 16, 20, 16)
        ec.setSpacing(10)

        # Action row for section-specific operations (remove section, etc.)
        self._section_actions = QHBoxLayout()
        self._section_actions.setSpacing(6)
        self._remove_section_btn = QPushButton("Remove section")
        self._remove_section_btn.setObjectName("GhostButton")
        self._remove_section_btn.clicked.connect(self._remove_active_section)
        self._move_up_section_btn = QPushButton("↑ Move section up")
        self._move_up_section_btn.setObjectName("GhostButton")
        self._move_up_section_btn.clicked.connect(lambda: self._move_active_section(-1))
        self._move_down_section_btn = QPushButton("Move section down ↓")
        self._move_down_section_btn.setObjectName("GhostButton")
        self._move_down_section_btn.clicked.connect(lambda: self._move_active_section(+1))
        self._section_actions.addWidget(self._move_up_section_btn)
        self._section_actions.addWidget(self._move_down_section_btn)
        self._section_actions.addStretch(1)
        self._section_actions.addWidget(self._remove_section_btn)
        ec.addLayout(self._section_actions)

        # Scroll area holding whichever panel is active
        self._panel_scroll = QScrollArea()
        self._panel_scroll.setWidgetResizable(True)
        self._panel_scroll.setFrameShape(QFrame.NoFrame)
        ec.addWidget(self._panel_scroll, 1)

        ll.addWidget(edit_card, 1)
        splitter.addWidget(left)

        # ----- Right pane (preview) -----
        self.preview = _ClickablePreview()
        self.preview.section_clicked.connect(self._switch_to)
        splitter.addWidget(self.preview)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([720, 480])

        # Pre-built section panels — header & summary are fixed; body panels are
        # created lazily per section index.
        self._header_panel = _HeaderPanel()
        self._summary_panel = _SummaryPanel()
        self._body_panels: dict[int, _SectionPanel] = {}

        self._header_panel.content_changed.connect(self._on_content_changed)
        self._summary_panel.content_changed.connect(self._on_content_changed)

        self._content = ResumeContent()
        self._active: str = "header"
        self._target_keywords: set[str] = set()
        self._target_listing_text: str = ""
        self._rewrite_popup: _RewritePopup | None = None

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(220)
        self._preview_timer.timeout.connect(self._update_preview)

    # ---------------------------------------------------------------- API

    def set_target_keywords(self, keywords: set[str]):
        self._target_keywords = keywords

    def set_target_listing(self, text: str):
        self._target_listing_text = text or ""

    def load(self, content: ResumeContent):
        self._content = ResumeContent.from_dict(content.to_dict())
        # Reset body panels — they're keyed by section index.
        for p in self._body_panels.values():
            p.setParent(None)
            p.deleteLater()
        self._body_panels.clear()
        self._header_panel.load(self._content.name, self._content.contact)
        self._summary_panel.load(self._content.summary)
        self.outline.rebuild(self._content.sections)
        self._switch_to("header")
        self._update_preview()

    def dump(self) -> ResumeContent:
        # Capture any in-flight panel state into self._content before returning.
        self._sync_active_panel_to_content()
        # Also re-dump any body panel we've ever opened — they hold their own state.
        for idx, panel in self._body_panels.items():
            if 0 <= idx < len(self._content.sections):
                self._content.sections[idx] = panel.dump()
        # Header & summary are always live.
        name, contact = self._header_panel.dump()
        self._content.name = name
        self._content.contact = contact
        self._content.summary = self._summary_panel.dump()
        return ResumeContent.from_dict(self._content.to_dict())

    # ---------------------------------------------------------------- panel switching

    def _switch_to(self, key: str):
        # Flush whatever's open into the in-memory content first.
        self._sync_active_panel_to_content()
        self._active = key
        self.outline.set_active(key)

        if key == "header":
            self._show_panel(self._header_panel)
            self._set_section_actions_visible(False)
        elif key == "summary":
            self._show_panel(self._summary_panel)
            self._set_section_actions_visible(False)
        elif key.startswith("body/"):
            try:
                idx = int(key.split("/", 1)[1])
            except (ValueError, IndexError):
                return
            if idx < 0 or idx >= len(self._content.sections):
                return
            panel = self._body_panels.get(idx)
            if panel is None:
                panel = _SectionPanel(self._content.sections[idx])
                panel.content_changed.connect(self._on_content_changed)
                panel.ai_requested.connect(self._on_ai_requested)
                self._body_panels[idx] = panel
            self._show_panel(panel)
            self._set_section_actions_visible(True, idx=idx)
        self._update_preview()

    def _show_panel(self, panel: QWidget):
        # QScrollArea takes ownership of the widget we pass to setWidget().
        current = self._panel_scroll.takeWidget()
        if current is not None and current is not panel:
            current.setParent(None)
        self._panel_scroll.setWidget(panel)
        panel.show()

    def _set_section_actions_visible(self, visible: bool, *, idx: int = -1):
        for w in (self._remove_section_btn, self._move_up_section_btn, self._move_down_section_btn):
            w.setVisible(visible)
        if visible:
            n = len(self._content.sections)
            self._move_up_section_btn.setEnabled(idx > 0)
            self._move_down_section_btn.setEnabled(0 <= idx < n - 1)

    # ---------------------------------------------------------------- mutations

    def _add_blank_section(self):
        self._sync_active_panel_to_content()
        self._content.sections.append(ResumeSection(title="New section", items=[]))
        new_idx = len(self._content.sections) - 1
        self.outline.rebuild(self._content.sections)
        self._switch_to(f"body/{new_idx}")

    def _remove_active_section(self):
        if not self._active.startswith("body/"):
            return
        try:
            idx = int(self._active.split("/", 1)[1])
        except (ValueError, IndexError):
            return
        if not (0 <= idx < len(self._content.sections)):
            return
        from PySide6.QtWidgets import QMessageBox
        confirm = QMessageBox.question(
            self, "Remove section",
            f"Remove the '{self._content.sections[idx].title or '(untitled)'}' section?",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return
        # Drop the panel + reindex
        panel = self._body_panels.pop(idx, None)
        if panel is not None:
            panel.setParent(None)
            panel.deleteLater()
        new_panels: dict[int, _SectionPanel] = {}
        for k, p in self._body_panels.items():
            if k < idx:
                new_panels[k] = p
            elif k > idx:
                new_panels[k - 1] = p
        self._body_panels = new_panels
        del self._content.sections[idx]
        self.outline.rebuild(self._content.sections)
        if self._content.sections:
            new_key = f"body/{min(idx, len(self._content.sections) - 1)}"
        else:
            new_key = "summary"
        self._switch_to(new_key)

    def _move_active_section(self, delta: int):
        if not self._active.startswith("body/"):
            return
        try:
            idx = int(self._active.split("/", 1)[1])
        except (ValueError, IndexError):
            return
        new_idx = idx + delta
        if not (0 <= new_idx < len(self._content.sections)):
            return
        self._sync_active_panel_to_content()
        # Move in content
        self._content.sections[idx], self._content.sections[new_idx] = (
            self._content.sections[new_idx], self._content.sections[idx],
        )
        # Swap panel keys
        p_a = self._body_panels.pop(idx, None)
        p_b = self._body_panels.pop(new_idx, None)
        if p_a is not None:
            self._body_panels[new_idx] = p_a
        if p_b is not None:
            self._body_panels[idx] = p_b
        self.outline.rebuild(self._content.sections)
        self._switch_to(f"body/{new_idx}")

    # ---------------------------------------------------------------- content sync

    def _sync_active_panel_to_content(self):
        if self._active == "header":
            name, contact = self._header_panel.dump()
            self._content.name = name
            self._content.contact = contact
        elif self._active == "summary":
            self._content.summary = self._summary_panel.dump()
        elif self._active.startswith("body/"):
            try:
                idx = int(self._active.split("/", 1)[1])
            except (ValueError, IndexError):
                return
            panel = self._body_panels.get(idx)
            if panel is not None and 0 <= idx < len(self._content.sections):
                self._content.sections[idx] = panel.dump()

    def _on_content_changed(self):
        self._sync_active_panel_to_content()
        # Also refresh outline if a section title changed.
        if self._active.startswith("body/"):
            self.outline.rebuild(self._content.sections)
            self.outline.set_active(self._active)
        self._preview_timer.start()

    # ---------------------------------------------------------------- preview

    def _update_preview(self):
        # Capture latest state.
        self._sync_active_panel_to_content()
        html = _render_resume_html(self._content, active=self._active)
        # Preserve scroll position so editing doesn't jump the preview to top.
        v = self.preview.verticalScrollBar().value()
        self.preview.setHtml(html)
        self.preview.verticalScrollBar().setValue(v)

    # ---------------------------------------------------------------- AI rewrites

    def _on_ai_requested(self, bullet_text: str):
        """Section panel emitted an AI-rewrite request for the bullet text under
        its cursor. Show the popup; on accept, replace the line in that panel."""
        if not bullet_text.strip():
            return
        # The section panel that emitted this is the active body panel.
        if not self._active.startswith("body/"):
            return
        try:
            idx = int(self._active.split("/", 1)[1])
        except (ValueError, IndexError):
            return
        panel = self._body_panels.get(idx)
        if panel is None:
            return

        swapped = _apply_swaps(bullet_text, self._target_keywords)
        if self._rewrite_popup is not None:
            self._rewrite_popup.close()
        snapshot = self.dump()

        popup = _RewritePopup(bullet_text, snapshot, self._target_listing_text, parent=self)
        if swapped and swapped != bullet_text:
            QTimer.singleShot(
                0,
                lambda s=swapped: popup._suggestions_layout.insertWidget(0, popup._make_card(s)),
            )
        def _apply(s: str, p=panel):
            p.replace_cursor_line(s)
            self._on_content_changed()
        popup.accepted.connect(_apply)

        try:
            global_pos = panel.ai_btn.mapToGlobal(QPoint(0, panel.ai_btn.height()))
            popup.move(global_pos)
        except Exception:
            pass
        popup.show()
        self._rewrite_popup = popup


# ============================================================================
# Preview HTML rendering
# ============================================================================


def _esc(text: str) -> str:
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _esc_md(text: str) -> str:
    """Escape HTML in plain text, then re-apply markdown bold/italic as HTML."""
    return _md_to_html(text or "")


# Background tint for the section the user is currently editing.
_ACTIVE_TINT = "#fff4e1"


def _section_wrapper(inner: str, key: str, *, is_active: bool) -> str:
    """Wrap a renderable region in an invisible anchor so clicks register, and
    highlight it lightly when active."""
    style = f"background:{_ACTIVE_TINT};" if is_active else ""
    return (
        f"<a href='section://{key}' style='text-decoration:none; color:inherit;'>"
        f"<div style='padding: 6px 8px; border-radius: 6px; {style} cursor:pointer;'>"
        f"{inner}"
        f"</div></a>"
    )


def _render_resume_html(content: ResumeContent, active: str | None = None) -> str:
    # --- Header block ---
    name_html = _esc(content.name) or "<span style='color:#888'>(Your name)</span>"
    contact_html = " &nbsp;·&nbsp; ".join(_esc(c) for c in content.contact if c)
    header_inner = (
        f"<h1 style='font-size:22px; margin: 0 0 4px 0; color:#111;'>{name_html}</h1>"
        f"<div style='color:#555; font-size:12px; margin-bottom:6px;'>{contact_html}</div>"
    )
    header_html = _section_wrapper(header_inner, "header", is_active=(active == "header"))

    # --- Summary block ---
    if content.summary:
        paras = [p.strip() for p in content.summary.split("\n\n") if p.strip()]
        summary_inner = "".join(
            f"<p style='margin: 4px 0;'>{_esc_md(p)}</p>" for p in paras
        )
    else:
        summary_inner = "<p style='margin: 4px 0; color:#aaa; font-style:italic;'>(No summary — click here to add one.)</p>"
    summary_html = _section_wrapper(summary_inner, "summary", is_active=(active == "summary"))

    # --- Body sections ---
    sections_html: list[str] = []
    for idx, section in enumerate(content.sections):
        kind = _detect_kind(section.title)
        title = _esc(section.title).upper() if section.title else "(UNTITLED)"

        items_html: list[str] = []
        if kind == KIND_LIST:
            for item in section.items:
                cat = _esc(item.header)
                chips = ", ".join(_esc(b) for b in item.bullets if b)
                if cat and chips:
                    items_html.append(
                        f"<div style='margin: 4px 0;'>"
                        f"<span style='font-weight:700'>{cat}:</span> {chips}</div>"
                    )
                elif chips:
                    items_html.append(f"<div style='margin: 4px 0;'>{chips}</div>")
                elif cat:
                    items_html.append(f"<div style='margin: 4px 0; font-weight:700'>{cat}</div>")
        elif kind == KIND_LINE:
            ul = []
            for item in section.items:
                head = _esc(item.header)
                sub = _esc(item.subheader)
                line = head
                if sub:
                    line += f" <span style='color:#666; font-style:italic'>· {sub}</span>"
                if line.strip():
                    ul.append(f"<li style='margin: 2px 0;'>{line}</li>")
            if ul:
                items_html.append(f"<ul style='margin: 4px 0 4px 20px; padding: 0;'>{''.join(ul)}</ul>")
        else:  # KIND_DETAIL
            for item in section.items:
                head = _esc(item.header)
                sub = _esc(item.subheader)
                hh = f"<div style='font-weight:700; margin-top:10px;'>{head}</div>" if head else ""
                sh = f"<div style='color:#555; font-style:italic; font-size:12px;'>{sub}</div>" if sub else ""
                bh = ""
                if item.bullets:
                    li = "".join(
                        f"<li style='margin: 2px 0;'>{_esc_md(b)}</li>" for b in item.bullets if b
                    )
                    bh = f"<ul style='margin: 4px 0 8px 22px; padding: 0;'>{li}</ul>"
                items_html.append(hh + sh + bh)

        inner = (
            f"<div style='font-weight:700; font-size:13px; color:#222;"
            f" border-bottom: 1px solid #999; padding-bottom: 2px; margin-bottom: 6px;'>"
            f"{title}</div>{''.join(items_html)}"
        )
        key = f"body/{idx}"
        sections_html.append(_section_wrapper(inner, key, is_active=(active == key)))

    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<style>
  body {{ font-family: 'Segoe UI', 'Calibri', sans-serif; font-size: 12px;
          color: #1a1a1a; padding: 22px 28px; line-height: 1.45; }}
  a {{ text-decoration: none; color: inherit; }}
</style></head><body>
{header_html}
{summary_html}
{''.join(sections_html)}
</body></html>"""
