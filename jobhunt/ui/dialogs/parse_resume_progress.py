from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel

from ... import config
from ...documents import parser
from ...documents.model import ResumeContent
from ...llm import get_provider
from ..widgets.dark_titlebar import apply_dark_title_bar


class _ParseWorker(QObject):
    done = Signal(object, str, str)

    def __init__(self, raw_text: str):
        super().__init__()
        self._raw = raw_text

    def run(self):
        try:
            provider = get_provider()
            content = provider.parse_resume(self._raw)
            self.done.emit(content, provider.name, "")
        except Exception as e:
            try:
                content = parser.parse_text(self._raw)
                self.done.emit(content, "fallback", f"AI parse failed: {e}")
            except Exception as e2:
                self.done.emit(None, "", f"Could not parse: {e2}")


class ParseResumeDialog(QDialog):
    """Modal dialog that runs resume parsing on a background thread.
    Access `parsed_content`, `provider_name`, `error` after exec()."""

    def __init__(self, raw_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Parsing resume")
        self.setMinimumWidth(460)
        self.resize(480, 200)
        self.setModal(True)
        apply_dark_title_bar(self)

        self.parsed_content: ResumeContent | None = None
        self.provider_name = ""
        self.error = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel("Parsing resume…")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        provider = get_provider()
        if provider.name == "rule_based":
            msg_text = (
                "No AI key configured — using the heuristic parser. This is fast but may misread "
                "multi-column layouts. Add a Claude or OpenAI key in Settings → API Keys for much "
                "better accuracy."
            )
        else:
            msg_text = (
                f"Sending to {provider.name} for structured parsing. "
                "This usually takes 5-15 seconds for a typical resume."
            )
        msg = QLabel(msg_text)
        msg.setObjectName("SectionDescription")
        msg.setWordWrap(True)
        layout.addWidget(msg)

        layout.addStretch(1)

        self._thread = QThread(self)
        self._worker = _ParseWorker(raw_text)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_done(self, content, provider_name: str, error: str):
        self.parsed_content = content
        self.provider_name = provider_name
        self.error = error
        self.accept()

    def _cleanup(self):
        if self._worker is not None:
            try:
                self._worker.disconnect()
            except (RuntimeError, TypeError):
                pass
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(500)

    def reject(self):
        self._cleanup()
        super().reject()

    def closeEvent(self, event):
        self._cleanup()
        super().closeEvent(event)
