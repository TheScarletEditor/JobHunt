from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QThread, QObject
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFormLayout, QSpinBox, QCheckBox, QComboBox, QMessageBox,
    QDialogButtonBox, QAbstractSpinBox, QWidget,
)

from ... import config
from ...credentials import encrypt, decrypt
from ...db import DB
from ...mail.scanner import test_connection
from ...mail.oauth_microsoft import expires_at_from_now, extract_email_from_id_token
from ..widgets.dark_titlebar import apply_dark_title_bar


PROVIDER_PRESETS = [
    ("Custom", "", 993, True, "password", ""),
    ("Microsoft (Hotmail / Outlook / Office 365)", "outlook.office365.com", 993, True, "oauth2",
     "Microsoft accounts use OAuth2 sign-in (basic IMAP auth is being killed in 2025). "
     "Click 'Sign in with Microsoft' below to authorize in your browser. No password needed here."),
    ("Gmail", "imap.gmail.com", 993, True, "password",
     "Gmail requires an App Password (Google Account → Security → 2-Step Verification → App passwords). "
     "Your regular Google password will NOT work."),
    ("Yahoo", "imap.mail.yahoo.com", 993, True, "password",
     "Yahoo requires an App Password (Account Info → Account security → Generate app password)."),
    ("iCloud", "imap.mail.me.com", 993, True, "password",
     "iCloud requires an app-specific password (appleid.apple.com → App-Specific Passwords)."),
    ("Fastmail", "imap.fastmail.com", 993, True, "password",
     "Generate an app password under Settings → Privacy & Security → Integrations → App passwords."),
]


class _TestWorker(QObject):
    done = Signal(dict)

    def __init__(self, server: str, port: int, use_ssl: bool, username: str, password: str):
        super().__init__()
        self._args = (server, port, use_ssl, username, password)

    def run(self):
        self.done.emit(test_connection(*self._args))


class IMAPAccountDialog(QDialog):
    def __init__(self, account_id: int | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit IMAP account" if account_id else "New IMAP account")
        self.setMinimumWidth(640)
        self.setModal(True)
        apply_dark_title_bar(self)

        self.account_id = account_id
        self._thread: QThread | None = None
        self._worker: _TestWorker | None = None

        self._auth_type: str = "password"
        self._pending_oauth_token: dict | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 22, 22, 22)
        outer.setSpacing(14)

        title = QLabel("Edit IMAP account" if account_id else "New IMAP account")
        title.setObjectName("PageTitle")
        outer.addWidget(title)

        preset_row = QHBoxLayout()
        preset_label = QLabel("Provider")
        preset_label.setObjectName("FormLabel")
        self.preset_combo = QComboBox()
        for name, *_ in PROVIDER_PRESETS:
            self.preset_combo.addItem(name)
        self.preset_combo.currentIndexChanged.connect(self._on_preset)
        preset_row.addWidget(preset_label)
        preset_row.addSpacing(8)
        preset_row.addWidget(self.preset_combo, 1)
        outer.addLayout(preset_row)

        self.preset_hint = QLabel("")
        self.preset_hint.setStyleSheet(f"color: {config.COLOR_TEXT_DIM};")
        self.preset_hint.setWordWrap(True)
        self.preset_hint.setMinimumHeight(40)
        outer.addWidget(self.preset_hint)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(14)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.display_name = QLineEdit()
        self.display_name.setPlaceholderText("Optional label, e.g. 'Personal Gmail'")
        self.server = QLineEdit()
        self.server.setPlaceholderText("imap.example.com")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(993)
        self.port.setFrame(False)
        self.port.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.port.setAlignment(Qt.AlignLeft)
        self.use_ssl = QCheckBox("Use SSL/TLS (recommended)")
        self.use_ssl.setChecked(True)
        self.username = QLineEdit()
        self.username.setPlaceholderText("you@example.com")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("App password (not your regular email password)")
        self.oauth_btn = QPushButton("Sign in with Microsoft")
        self.oauth_btn.setObjectName("PrimaryButton")
        self.oauth_btn.clicked.connect(self._on_oauth_signin)
        self.oauth_status = QLabel("Not signed in")
        self.oauth_status.setStyleSheet(f"color: {config.COLOR_TEXT_DIM};")
        self.folder = QLineEdit()
        self.folder.setText("INBOX")
        self.folder.setPlaceholderText("INBOX")
        self.enabled = QCheckBox("Scan this account")
        self.enabled.setChecked(True)

        def lbl(text: str) -> QLabel:
            label_widget = QLabel(text)
            label_widget.setObjectName("FormLabel")
            return label_widget

        form.addRow(lbl("Display name"), self.display_name)
        form.addRow(lbl("Server"), self.server)
        form.addRow(lbl("Port"), self.port)
        form.addRow(QWidget(), self.use_ssl)
        form.addRow(lbl("Username"), self.username)
        self._password_label = lbl("Password")
        form.addRow(self._password_label, self.password)
        oauth_row = QHBoxLayout()
        oauth_row.setContentsMargins(0, 0, 0, 0)
        oauth_row.addWidget(self.oauth_btn)
        oauth_row.addWidget(self.oauth_status, 1)
        self._oauth_wrap = QWidget()
        self._oauth_wrap.setLayout(oauth_row)
        self._oauth_label = lbl("Microsoft")
        form.addRow(self._oauth_label, self._oauth_wrap)
        form.addRow(lbl("Folder"), self.folder)
        form.addRow(QWidget(), self.enabled)
        outer.addLayout(form)

        self._set_auth_mode("password")

        test_row = QHBoxLayout()
        self.test_status = QLabel("")
        self.test_status.setStyleSheet(f"color: {config.COLOR_TEXT_DIM};")
        self.test_status.setWordWrap(True)
        test_row.addWidget(self.test_status, 1)
        self.test_btn = QPushButton("Test connection")
        self.test_btn.clicked.connect(self._on_test)
        test_row.addWidget(self.test_btn)
        outer.addLayout(test_row)

        outer.addStretch(1)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        save_btn = btns.button(QDialogButtonBox.Save)
        save_btn.setObjectName("PrimaryButton")
        save_btn.setText("Save account")
        btns.accepted.connect(self._on_save)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)

        if account_id:
            self._load()
        else:
            self._on_preset(0)

    def _on_preset(self, idx: int):
        if idx < 0 or idx >= len(PROVIDER_PRESETS):
            return
        name, server, port, use_ssl, auth_type, hint = PROVIDER_PRESETS[idx]
        self.preset_hint.setText(hint)
        self._set_auth_mode(auth_type)
        if name == "Custom":
            return
        if server:
            self.server.setText(server)
        if port:
            self.port.setValue(port)
        self.use_ssl.setChecked(use_ssl)

    def _set_auth_mode(self, mode: str):
        self._auth_type = mode
        is_oauth = mode == "oauth2"
        self._password_label.setVisible(not is_oauth)
        self.password.setVisible(not is_oauth)
        self._oauth_label.setVisible(is_oauth)
        self._oauth_wrap.setVisible(is_oauth)
        self.test_btn.setEnabled(not is_oauth) if hasattr(self, "test_btn") else None

    def _on_oauth_signin(self):
        from .microsoft_signin import MicrosoftSignInDialog
        dlg = MicrosoftSignInDialog(self)
        if dlg.exec() and dlg.token_data:
            self._pending_oauth_token = dlg.token_data
            email = extract_email_from_id_token(dlg.token_data.get("id_token", "")) or ""
            if email and not self.username.text().strip():
                self.username.setText(email)
            display = email or self.username.text().strip() or "your Microsoft account"
            self.oauth_status.setText(f"✓ Signed in as {display}")
            self.oauth_status.setStyleSheet(f"color: {config.COLOR_ACCENT};")

    def _load(self):
        row = DB.query_one(
            """SELECT display_name, server, port, username, encrypted_password,
                      folder_filter, use_ssl, enabled, auth_type
               FROM imap_accounts WHERE id = ?""",
            (self.account_id,),
        )
        if not row:
            return
        self.display_name.setText(row["display_name"] or "")
        self.server.setText(row["server"] or "")
        self.port.setValue(row["port"] or 993)
        self.username.setText(row["username"] or "")
        self.folder.setText(row["folder_filter"] or "INBOX")
        self.use_ssl.setChecked(
            bool(row["use_ssl"]) if row["use_ssl"] is not None else True
        )
        self.enabled.setChecked(bool(row["enabled"]))

        existing_auth = row["auth_type"] or "password"
        self._set_auth_mode(existing_auth)
        if existing_auth == "password" and row["encrypted_password"]:
            try:
                self.password.setText(decrypt(row["encrypted_password"]))
            except Exception:
                pass
        elif existing_auth == "oauth2":
            self.oauth_status.setText(f"✓ Signed in as {row['username']}")
            self.oauth_status.setStyleSheet(f"color: {config.COLOR_ACCENT};")

    def _on_test(self):
        if not self.server.text().strip() or not self.username.text().strip() or not self.password.text():
            self.test_status.setText("Fill in server, username, and password first.")
            self.test_status.setStyleSheet(f"color: {config.COLOR_ACCENT};")
            return
        if self._thread and self._thread.isRunning():
            return
        self.test_btn.setEnabled(False)
        self.test_btn.setText("Testing…")
        self.test_status.setText("Connecting…")
        self.test_status.setStyleSheet(f"color: {config.COLOR_TEXT_DIM};")

        self._thread = QThread(self)
        self._worker = _TestWorker(
            self.server.text().strip(),
            self.port.value(),
            self.use_ssl.isChecked(),
            self.username.text().strip(),
            self.password.text(),
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_test_done)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def closeEvent(self, event):
        self._cleanup_worker()
        super().closeEvent(event)

    def _on_test_done(self, result: dict):
        self.test_btn.setEnabled(True)
        self.test_btn.setText("Test connection")
        self._thread = None
        self._worker = None
        if result["ok"]:
            count = len(result["folders"])
            self.test_status.setText(f"✓ Connected. Found {count} folder(s).")
            self.test_status.setStyleSheet(f"color: {config.COLOR_ACCENT};")
        else:
            self.test_status.setText(f"✗ {result['error']}")
            self.test_status.setStyleSheet(f"color: {config.COLOR_ACCENT};")

    def _cleanup_worker(self):
        """Disconnect worker signals and ask its thread to stop. Safe to call
        multiple times. Disconnect FIRST so any in-flight emit() is a no-op."""
        if self._worker is not None:
            try:
                self._worker.disconnect()
            except (RuntimeError, TypeError):
                pass
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(500)

    def reject(self):
        self._cleanup_worker()
        super().reject()

    def _on_save(self):
        self._cleanup_worker()

        if not self.server.text().strip():
            QMessageBox.warning(self, "Server required", "Enter the IMAP server hostname.")
            return
        if not self.username.text().strip():
            QMessageBox.warning(self, "Username required", "Enter your email username.")
            return

        is_oauth = self._auth_type == "oauth2"

        if is_oauth and not self.account_id and not self._pending_oauth_token:
            QMessageBox.warning(
                self, "Sign in required",
                "Click 'Sign in with Microsoft' and complete the browser sign-in first.",
            )
            return
        if not is_oauth and not self.password.text() and not self.account_id:
            QMessageBox.warning(
                self, "Password required",
                "Enter your password. Gmail, Yahoo, and iCloud require an App Password — "
                "not your normal account password.",
            )
            return

        common = (
            self.display_name.text().strip() or None,
            self.server.text().strip(),
            self.port.value(),
            self.username.text().strip(),
            self.folder.text().strip() or "INBOX",
            1 if self.use_ssl.isChecked() else 0,
            1 if self.enabled.isChecked() else 0,
            "oauth2" if is_oauth else "password",
        )

        encrypted_pw = encrypt(self.password.text()) if (not is_oauth and self.password.text()) else None
        oauth_access_enc = None
        oauth_refresh_enc = None
        oauth_expires = None
        if is_oauth and self._pending_oauth_token:
            tok = self._pending_oauth_token
            if tok.get("access_token"):
                oauth_access_enc = encrypt(tok["access_token"])
            if tok.get("refresh_token"):
                oauth_refresh_enc = encrypt(tok["refresh_token"])
            oauth_expires = expires_at_from_now(tok.get("expires_in", 3600))

        if self.account_id:
            sets = [
                "display_name = ?", "server = ?", "port = ?", "username = ?",
                "folder_filter = ?", "use_ssl = ?", "enabled = ?", "auth_type = ?",
            ]
            values: list = list(common)
            if encrypted_pw is not None:
                sets.append("encrypted_password = ?")
                values.append(encrypted_pw)
            if oauth_access_enc is not None:
                sets.append("oauth_access_token = ?")
                values.append(oauth_access_enc)
            if oauth_refresh_enc is not None:
                sets.append("oauth_refresh_token = ?")
                values.append(oauth_refresh_enc)
            if oauth_expires is not None:
                sets.append("oauth_expires_at = ?")
                values.append(oauth_expires)
            values.append(self.account_id)
            DB.execute(
                f"UPDATE imap_accounts SET {', '.join(sets)} WHERE id = ?",
                tuple(values),
            )
            DB.log_audit("imap_account_updated", {"id": self.account_id, "auth_type": common[7]})
        else:
            DB.execute(
                """INSERT INTO imap_accounts
                   (display_name, server, port, username, folder_filter,
                    use_ssl, enabled, auth_type,
                    encrypted_password, oauth_access_token, oauth_refresh_token, oauth_expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (*common, encrypted_pw, oauth_access_enc, oauth_refresh_enc, oauth_expires),
            )
            DB.log_audit("imap_account_added", {
                "username": self.username.text().strip(),
                "auth_type": common[7],
            })

        self.accept()
