"""Modal that appears when the auto-updater finds a newer release."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QObject, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QTextBrowser, QVBoxLayout,
)

from ... import config
from ...__version__ import __version__
from ...updater import UpdateInfo, download_installer, launch_installer
from ..widgets.dark_titlebar import apply_dark_title_bar


log = logging.getLogger(__name__)


class _DownloadWorker(QObject):
    progress = Signal(int, int)   # (done, total)
    finished = Signal(str, str)   # (path, error)

    def __init__(self, info: UpdateInfo):
        super().__init__()
        self._info = info

    def run(self):
        try:
            path = download_installer(
                self._info,
                progress_cb=lambda d, t: self.progress.emit(d, t),
            )
            self.finished.emit(path, "")
        except Exception as e:
            log.exception("Download failed")
            self.finished.emit("", f"{type(e).__name__}: {e}")


class UpdateAvailableDialog(QDialog):
    def __init__(self, info: UpdateInfo, parent=None):
        super().__init__(parent)
        self._info = info
        self.setWindowTitle("JobHunt — update available")
        self.setMinimumWidth(560)
        self.setModal(True)
        apply_dark_title_bar(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 22, 22, 22)
        outer.setSpacing(14)

        title = QLabel(f"JobHunt {info.version} is available")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        subtitle = QLabel(f"You're on v{__version__}. Update now to get the latest features and fixes.")
        subtitle.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 13px;")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        if info.notes:
            notes_label = QLabel("Release notes:")
            notes_label.setStyleSheet(
                f"color: {config.COLOR_ACCENT}; font-size: 12px; font-weight: 700; "
                f"padding-top: 6px;"
            )
            outer.addWidget(notes_label)
            self.notes = QTextBrowser()
            self.notes.setReadOnly(True)
            self.notes.setOpenExternalLinks(True)
            self.notes.setMarkdown(info.notes)
            self.notes.setMaximumHeight(220)
            self.notes.setStyleSheet(
                f"QTextBrowser {{ background: {config.COLOR_BG_HOVER}; "
                f"color: {config.COLOR_TEXT}; border: none; border-radius: 6px; "
                f"padding: 10px; font-size: 12px; }}"
            )
            outer.addWidget(self.notes)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate until we know the size
        self.progress.setVisible(False)
        outer.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {config.COLOR_TEXT_DIM}; font-size: 12px;")
        self.status.setVisible(False)
        outer.addWidget(self.status)

        btns = QHBoxLayout()
        view_btn = QPushButton("View on GitHub")
        view_btn.setObjectName("GhostButton")
        view_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(info.release_url)) if info.release_url else None
        )
        btns.addWidget(view_btn)
        btns.addStretch(1)
        self.skip_btn = QPushButton("Skip for now")
        self.skip_btn.clicked.connect(self.reject)
        btns.addWidget(self.skip_btn)
        self.update_btn = QPushButton("Download & install")
        self.update_btn.setObjectName("PrimaryButton")
        self.update_btn.clicked.connect(self._on_update)
        btns.addWidget(self.update_btn)
        outer.addLayout(btns)

        self._thread: QThread | None = None
        self._worker: _DownloadWorker | None = None

    def _on_update(self):
        self.update_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.update_btn.setText("Downloading…")
        self.progress.setVisible(True)
        self.status.setVisible(True)
        self.status.setText("Starting download…")

        self._thread = QThread(self)
        self._worker = _DownloadWorker(self._info)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_progress(self, done: int, total: int):
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            mb_done = done / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            self.status.setText(f"Downloading… {mb_done:.1f} / {mb_total:.1f} MB")
        else:
            mb_done = done / (1024 * 1024)
            self.status.setText(f"Downloading… {mb_done:.1f} MB")

    def _on_finished(self, path: str, error: str):
        if error:
            QMessageBox.warning(
                self, "Download failed",
                f"Couldn't download the update:\n\n{error}\n\n"
                "You can grab the installer manually from GitHub if you'd like."
            )
            self.update_btn.setEnabled(True)
            self.update_btn.setText("Try again")
            self.skip_btn.setEnabled(True)
            self.progress.setVisible(False)
            self.status.setVisible(False)
            return

        self.status.setText("Download complete. Launching installer…")
        try:
            launch_installer(path, silent=True)
        except Exception as e:
            QMessageBox.warning(
                self, "Launch failed",
                f"Downloaded successfully but couldn't auto-launch the installer:\n\n{e}\n\n"
                f"Run it manually from:\n{path}"
            )
            return

        QMessageBox.information(
            self, "Updating",
            "The installer is running in the background. JobHunt will close and "
            "the new version will start automatically once installation completes."
        )
        # Close the running app so the installer can overwrite the .exe.
        QApplication.quit()
