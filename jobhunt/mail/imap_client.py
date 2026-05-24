from __future__ import annotations

import email
import email.policy
import imaplib
import re
import socket
from dataclasses import dataclass
from email.header import decode_header


class IMAPError(Exception):
    pass


@dataclass
class Email:
    uid: int
    message_id: str
    subject: str
    sender: str
    body: str
    received_at: str
    raw_size: int


def _decode_header_value(value: str) -> str:
    if not value:
        return ""
    try:
        decoded = decode_header(value)
    except Exception:
        return value
    parts: list[str] = []
    for raw, charset in decoded:
        if isinstance(raw, bytes):
            try:
                parts.append(raw.decode(charset or "utf-8", errors="replace"))
            except Exception:
                parts.append(raw.decode("utf-8", errors="replace"))
        else:
            parts.append(raw)
    return "".join(parts).strip()


def _strip_html(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ct == "text/plain" and "attachment" not in disp:
                return _safe_payload(part)
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html":
                html = _safe_payload(part)
                return _strip_html(html)
        return ""
    ct = msg.get_content_type()
    body = _safe_payload(msg)
    if ct == "text/html":
        return _strip_html(body)
    return body


def _safe_payload(part) -> str:
    try:
        return part.get_content()
    except Exception:
        pass
    payload = part.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except Exception:
            return payload.decode("utf-8", errors="replace")
    return str(payload or "")


class IMAPClient:
    def __init__(self, server: str, port: int = 993, use_ssl: bool = True, timeout: int = 20):
        self._server = server
        self._port = port
        self._use_ssl = use_ssl
        self._timeout = timeout
        self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.disconnect()
        return False

    def connect(self, username: str, password: str):
        try:
            if self._use_ssl:
                self._conn = imaplib.IMAP4_SSL(self._server, self._port, timeout=self._timeout)
            else:
                self._conn = imaplib.IMAP4(self._server, self._port, timeout=self._timeout)
            self._conn.login(username, password)
        except imaplib.IMAP4.error as e:
            self._conn = None
            raise IMAPError(f"Authentication failed: {e}")
        except (socket.gaierror, socket.timeout, ConnectionError, OSError) as e:
            self._conn = None
            raise IMAPError(f"Connection error: {e}")

    def connect_oauth2(self, username: str, access_token: str):
        try:
            if self._use_ssl:
                self._conn = imaplib.IMAP4_SSL(self._server, self._port, timeout=self._timeout)
            else:
                self._conn = imaplib.IMAP4(self._server, self._port, timeout=self._timeout)
            auth_string = f"user={username}\x01auth=Bearer {access_token}\x01\x01"
            self._conn.authenticate("XOAUTH2", lambda _x: auth_string.encode())
        except imaplib.IMAP4.error as e:
            self._conn = None
            raise IMAPError(f"OAuth2 authentication failed: {e}")
        except (socket.gaierror, socket.timeout, ConnectionError, OSError) as e:
            self._conn = None
            raise IMAPError(f"Connection error: {e}")

    def disconnect(self):
        if self._conn is not None:
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None

    def list_folders(self) -> list[str]:
        if not self._conn:
            raise IMAPError("Not connected")
        status, data = self._conn.list()
        if status != "OK" or not data:
            return []
        folders: list[str] = []
        for item in data:
            if not isinstance(item, bytes):
                continue
            try:
                s = item.decode("utf-8", errors="replace")
            except Exception:
                continue
            if '"/" ' in s:
                name = s.rsplit('"/" ', 1)[-1].strip().strip('"')
            else:
                parts = s.rsplit(" ", 1)
                name = parts[-1].strip().strip('"')
            if name:
                folders.append(name)
        return folders

    def fetch_new(self, folder: str = "INBOX", since_uid: int = 0,
                  max_messages: int = 200) -> list[Email]:
        if not self._conn:
            raise IMAPError("Not connected")
        status, _ = self._conn.select(folder, readonly=True)
        if status != "OK":
            raise IMAPError(f"Could not open folder: {folder}")

        search = f"UID {since_uid + 1}:*" if since_uid > 0 else "ALL"
        status, data = self._conn.uid("SEARCH", None, search)
        if status != "OK" or not data or not data[0]:
            return []

        uid_list = data[0].split()
        if not uid_list:
            return []
        uid_list = uid_list[-max_messages:]

        results: list[Email] = []
        for uid_bytes in uid_list:
            try:
                uid_int = int(uid_bytes)
            except (ValueError, TypeError):
                continue
            if uid_int <= since_uid:
                continue

            status, msg_data = self._conn.uid("FETCH", uid_bytes, "(RFC822)")
            if status != "OK" or not msg_data:
                continue

            raw = None
            for item in msg_data:
                if isinstance(item, tuple) and len(item) >= 2:
                    candidate = item[1]
                    if isinstance(candidate, bytes):
                        raw = candidate
                        break
            if not raw:
                continue

            try:
                msg = email.message_from_bytes(raw, policy=email.policy.default)
            except Exception:
                continue

            message_id = (msg.get("Message-ID") or "").strip("<>").strip()
            results.append(Email(
                uid=uid_int,
                message_id=message_id,
                subject=_decode_header_value(msg.get("Subject", "")),
                sender=_decode_header_value(msg.get("From", "")),
                body=_extract_body(msg),
                received_at=str(msg.get("Date", "")),
                raw_size=len(raw),
            ))
        return results
