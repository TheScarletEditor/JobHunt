"""Verify the IMAP client's parsing + connection flow with a mocked server.
Does not connect to any real email account.
"""
from __future__ import annotations

import email
import email.policy
import imaplib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobhunt.mail.imap_client import (
    IMAPClient, IMAPError,
    _decode_header_value, _strip_html, _extract_body,
)


SAMPLE_MULTIPART = b"""From: =?utf-8?B?U3RyaXBlIFJlY3J1aXRpbmc=?= <recruiter@stripe.com>
To: candidate@example.com
Subject: =?utf-8?B?QXBwbGljYXRpb24gcmVjZWl2ZWQ=?= for Senior Engineer
Message-ID: <abc123@stripe.com>
Date: Mon, 1 Jan 2024 12:00:00 +0000
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="BOUNDARY42"

--BOUNDARY42
Content-Type: text/plain; charset=utf-8

Hi candidate,

Thanks for applying to Stripe! We received your application for the
Senior Engineer role and will review within 5 business days.

Best,
The Stripe team

--BOUNDARY42
Content-Type: text/html; charset=utf-8

<html><body><p>Hi candidate,</p><p>Thanks for applying!</p></body></html>

--BOUNDARY42--
"""


def _ok(*items):
    return ("OK", list(items))


def test_decode_header():
    assert _decode_header_value("Simple subject") == "Simple subject"
    assert _decode_header_value("=?utf-8?B?VGVzdCBlbWFpbA==?=") == "Test email"
    assert _decode_header_value("") == ""
    assert _decode_header_value(None) == ""
    print("  PASS  _decode_header_value")


def test_strip_html():
    out = _strip_html("<p>Hello <b>world</b>! <a href='x'>link</a></p>")
    assert "Hello" in out and "world" in out and "link" in out
    assert "<" not in out and ">" not in out

    out = _strip_html("<script>alert('x')</script><p>Hi</p>")
    assert "alert" not in out and "Hi" in out

    out = _strip_html("Hello &amp; world &lt;tag&gt;")
    assert "Hello & world <tag>" in out
    print("  PASS  _strip_html")


def test_extract_body_plain():
    raw = b"""From: x@y.com
Subject: t
Content-Type: text/plain; charset=utf-8

Line one.
Line two."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    body = _extract_body(msg)
    assert "Line one." in body and "Line two." in body
    print("  PASS  _extract_body (plain)")


def test_extract_body_multipart_prefers_plain():
    msg = email.message_from_bytes(SAMPLE_MULTIPART, policy=email.policy.default)
    body = _extract_body(msg)
    assert "Thanks for applying" in body
    assert "<html>" not in body
    assert "<p>" not in body
    print("  PASS  _extract_body (multipart prefers plain)")


def test_extract_body_html_only():
    raw = b"""From: x@y.com
Subject: t
Content-Type: text/html; charset=utf-8

<html><body><p>Hello <b>bold</b></p></body></html>"""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    body = _extract_body(msg)
    assert "Hello" in body and "bold" in body
    assert "<p>" not in body
    print("  PASS  _extract_body (html only)")


def test_connect_success_and_folder_list():
    mock = MagicMock()
    mock.login.return_value = _ok(b"login OK")
    mock.list.return_value = _ok(
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\HasNoChildren) "/" "Sent"',
        b'(\\HasNoChildren) "/" "[Gmail]/Trash"',
    )
    mock.logout.return_value = _ok(b"bye")

    with patch("imaplib.IMAP4_SSL", return_value=mock):
        client = IMAPClient("imap.example.com", 993, use_ssl=True)
        client.connect("user@example.com", "pw")
        folders = client.list_folders()
        client.disconnect()

    assert folders == ["INBOX", "Sent", "[Gmail]/Trash"], f"got: {folders}"
    print("  PASS  connect + list_folders")


def test_fetch_new_end_to_end():
    mock = MagicMock()
    mock.login.return_value = _ok(b"login OK")
    mock.select.return_value = _ok(b"INBOX")
    mock.logout.return_value = _ok(b"bye")

    def uid_side_effect(*args, **_kwargs):
        cmd = args[0]
        if cmd == "SEARCH":
            criteria = args[2] if len(args) > 2 else "ALL"
            if criteria == "ALL":
                return _ok(b"42 43 44")
            if criteria == "UID 44:*":
                return _ok(b"44")
            return _ok(b"")
        if cmd == "FETCH":
            uid_str = args[1].decode() if isinstance(args[1], bytes) else str(args[1])
            return ("OK", [(f"{uid_str} (RFC822 {{0}}".encode(), SAMPLE_MULTIPART)])
        return ("NO", [])

    mock.uid.side_effect = uid_side_effect

    with patch("imaplib.IMAP4_SSL", return_value=mock):
        client = IMAPClient("imap.example.com", 993, use_ssl=True)
        client.connect("user@example.com", "pw")
        emails = client.fetch_new("INBOX", since_uid=0)
        client.disconnect()

    assert len(emails) == 3, f"expected 3 emails, got {len(emails)}"
    em = emails[0]
    assert em.uid == 42
    assert em.message_id == "abc123@stripe.com", f"got: {em.message_id}"
    assert "Stripe Recruiting" in em.sender, f"got sender: {em.sender}"
    assert "Application received" in em.subject, f"got subject: {em.subject}"
    assert "Thanks for applying" in em.body
    print(f"  PASS  fetch_new end-to-end (3 emails parsed)")


def test_fetch_new_since_uid_filter():
    mock = MagicMock()
    mock.login.return_value = _ok(b"login OK")
    mock.select.return_value = _ok(b"INBOX")
    mock.logout.return_value = _ok(b"bye")

    def uid_side_effect(*args, **_kwargs):
        cmd = args[0]
        if cmd == "SEARCH":
            criteria = args[2] if len(args) > 2 else "ALL"
            if "UID 44:*" in criteria:
                return _ok(b"44")
            return _ok(b"42 43 44")
        if cmd == "FETCH":
            return ("OK", [(b"44 (RFC822 {0}", SAMPLE_MULTIPART)])
        return ("NO", [])

    mock.uid.side_effect = uid_side_effect

    with patch("imaplib.IMAP4_SSL", return_value=mock):
        client = IMAPClient("imap.example.com", 993, use_ssl=True)
        client.connect("user@example.com", "pw")
        emails = client.fetch_new("INBOX", since_uid=43)
        client.disconnect()

    assert len(emails) == 1, f"expected 1 email, got {len(emails)}"
    assert emails[0].uid == 44
    print("  PASS  since_uid filter (only newer UIDs returned)")


def test_auth_error_raises_imaperror():
    mock = MagicMock()
    mock.login.side_effect = imaplib.IMAP4.error("AUTHENTICATIONFAILED bad credentials")

    with patch("imaplib.IMAP4_SSL", return_value=mock):
        client = IMAPClient("imap.example.com", 993, use_ssl=True)
        raised = False
        try:
            client.connect("user@example.com", "wrong-password")
        except IMAPError as e:
            raised = True
            assert "Authentication failed" in str(e), f"got: {e}"
        assert raised, "Expected IMAPError on auth failure"
    print("  PASS  auth failure raises IMAPError")


def test_connection_error_raises_imaperror():
    import socket
    with patch("imaplib.IMAP4_SSL", side_effect=socket.gaierror("Name resolution failed")):
        client = IMAPClient("nonexistent.example", 993, use_ssl=True)
        raised = False
        try:
            client.connect("user", "pw")
        except IMAPError as e:
            raised = True
            assert "Connection error" in str(e)
        assert raised
    print("  PASS  network failure raises IMAPError")


def main() -> int:
    print("IMAP client tests (no real server):\n")
    test_decode_header()
    test_strip_html()
    test_extract_body_plain()
    test_extract_body_multipart_prefers_plain()
    test_extract_body_html_only()
    test_connect_success_and_folder_list()
    test_fetch_new_end_to_end()
    test_fetch_new_since_uid_filter()
    test_auth_error_raises_imaperror()
    test_connection_error_raises_imaperror()
    print("\nAll IMAP client tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
