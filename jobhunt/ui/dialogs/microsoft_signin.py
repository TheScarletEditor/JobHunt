from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt, Signal, QThread, QObject
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)

from ... import config
from ...mail.oauth_microsoft import OAuthError, run_auth_code_flow
from ..widgets.dark_titlebar import apply_dark_title_bar


class _SignInWorker(QObject):
    auth_url_ready = Signal(str)
    sign_in_complete = Signal(dict)
    sign_in_failed = Signal(str)

    def __init__(self, client_id: str):
        super().__init__()
        self._client_id = client_id
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            token = run_auth_code_flow(
                self._client_id,
                on_ready=lambda url: self.auth_url_ready.emit(url),
                is_cancelled=lambda: self._cancelled,
                timeout=300,
            )
            self.sign_in_complete.emit(token)
        except OAuthError as e:
            self.sign_in_failed.emit(str(e))
        except Exception as e:
            self.sign_in_failed.emit(f"Unexpected: {e}")


class MicrosoftSignInDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sign in with Microsoft")
        self.setMinimumWidth(560)
        self.resize(600, 360)
        self.setModal(True)
        apply_dark_title_bar(self)

        self.token_data: dict | None = None
        self._auth_url: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 22)
        outer.setSpacing(16)

        title = QLabel("Sign in with Microsoft")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        self.intro = QLabel("Preparing sign-in… your browser will open shortly.")
        self.intro.setObjectName("SectionDescription")
        self.intro.setWordWrap(True)
        outer.addWidget(self.intro)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {config.COLOR_TEXT_DIM};")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        outer.addStretch(1)

        footer = QHBoxLayout()
        self.reopen_btn = QPushButton("Reopen browser")
        self.reopen_btn.setEnabled(False)
        self.reopen_btn.clicked.connect(self._reopen)
        footer.addWidget(self.reopen_btn)
        footer.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel)
        footer.addWidget(self.cancel_btn)
        outer.addLayout(footer)

        self._thread = QThread(self)
        self._worker = _SignInWorker(config.MICROSOFT_CLIENT_ID)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.auth_url_ready.connect(self._on_url_ready)
        self._worker.sign_in_complete.connect(self._on_complete)
        self._worker.sign_in_failed.connect(self._on_failed)
        self._worker.sign_in_complete.connect(self._thread.quit)
        self._worker.sign_in_failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_url_ready(self, url: str):
        self._auth_url = url
        self.reopen_btn.setEnabled(True)
        self.intro.setText(
            "Your browser should be opening Microsoft's sign-in page. "
            "Sign in, click Accept on the consent screen, and you'll be returned here automatically."
        )
        self.status_label.setText("Waiting for browser sign-in…")
        try:
            webbrowser.open(url)
        except Exception:
            pass

    def _reopen(self):
        if self._auth_url:
            try:
                webbrowser.open(self._auth_url)
            except Exception:
                pass

    def _on_complete(self, token: dict):
        self.token_data = token
        self.status_label.setStyleSheet(f"color: {config.COLOR_ACCENT};")
        self.status_label.setText("✓ Signed in successfully.")
        self.accept()

    def _on_failed(self, err: str):
        self.status_label.setStyleSheet(f"color: {config.COLOR_ACCENT};")
        self.status_label.setText(f"✗ {err}")
        self.cancel_btn.setText("Close")
        self.reopen_btn.setEnabled(False)

    def _cleanup_worker(self):
        """Disconnect worker signals + cancel + quit thread. Order matters:
        disconnect FIRST so a late emit() doesn't reach a destroyed slot."""
        if self._worker is not None:
            try:
                self._worker.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                self._worker.cancel()
            except Exception:
                pass
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)

    def reject(self):
        self._cleanup_worker()
        super().reject()

    def _cancel(self):
        self.reject()

    def closeEvent(self, event):
        self._cleanup_worker()
        super().closeEvent(event)
