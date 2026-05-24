from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from datetime import datetime, timezone

from .. import config
from ..credentials import decrypt, encrypt
from ..db import DB
from .imap_client import IMAPClient, IMAPError
from .graph_client import GraphMailClient, GraphError
from .oauth_microsoft import (
    OAuthError, refresh_access_token, is_token_expired, expires_at_from_now,
)


def get_account(account_id: int) -> Optional[dict]:
    row = DB.query_one(
        """SELECT id, display_name, server, port, username, encrypted_password,
                  folder_filter, last_uid, use_ssl, enabled, last_scan_at,
                  auth_type, oauth_access_token, oauth_refresh_token, oauth_expires_at
           FROM imap_accounts WHERE id = ?""",
        (account_id,),
    )
    return dict(row) if row else None


def list_accounts(enabled_only: bool = False) -> list[dict]:
    sql = (
        "SELECT id, display_name, server, port, username, folder_filter, "
        "last_uid, use_ssl, enabled, last_scan_at, auth_type FROM imap_accounts"
    )
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY id"
    return [dict(r) for r in DB.query(sql)]


def _ensure_fresh_oauth_token(account: dict) -> str:
    """Return a usable access token for an OAuth account, refreshing if needed."""
    if not account.get("oauth_refresh_token"):
        raise OAuthError("No refresh token stored. Re-sign in to Microsoft.")

    if not is_token_expired(account.get("oauth_expires_at")):
        try:
            return decrypt(account["oauth_access_token"])
        except Exception:
            pass

    refresh_token = decrypt(account["oauth_refresh_token"])
    result = refresh_access_token(refresh_token, client_id=config.MICROSOFT_CLIENT_ID)
    new_access = result["access_token"]
    new_refresh = result.get("refresh_token", refresh_token)
    expires_at = expires_at_from_now(result.get("expires_in", 3600))

    DB.execute(
        """UPDATE imap_accounts SET
           oauth_access_token = ?, oauth_refresh_token = ?, oauth_expires_at = ?
           WHERE id = ?""",
        (encrypt(new_access), encrypt(new_refresh), expires_at, account["id"]),
    )
    return new_access


def test_connection(server: str, port: int, use_ssl: bool,
                    username: str, password: str) -> dict:
    client = IMAPClient(server, port, use_ssl=use_ssl, timeout=15)
    try:
        client.connect(username, password)
        folders = client.list_folders()
        return {"ok": True, "folders": folders, "error": None}
    except IMAPError as e:
        return {"ok": False, "folders": [], "error": str(e)}
    except Exception as e:
        return {"ok": False, "folders": [], "error": f"Unexpected: {e}"}
    finally:
        client.disconnect()


def _scan_via_graph(account: dict) -> dict:
    account_id = account["id"]
    try:
        access_token = _ensure_fresh_oauth_token(account)
    except OAuthError as e:
        DB.log_audit("email_scan", {"account_id": account_id, "new": 0,
                                    "error": f"OAuth refresh failed: {e}"})
        return {"account_id": account_id, "new": 0,
                "error": f"OAuth refresh failed: {e}"}

    client = GraphMailClient(access_token)
    since_iso = account.get("last_scan_at")
    new_count = 0
    error: Optional[str] = None
    try:
        messages = client.fetch_recent_messages(since_iso=since_iso, max_messages=200)
        for m in messages:
            if m.message_id:
                exists = DB.query_one(
                    "SELECT id FROM emails WHERE message_id = ? AND account_id = ?",
                    (m.message_id, account_id),
                )
                if exists:
                    continue
            DB.execute(
                """INSERT INTO emails
                   (account_id, message_id, subject, sender, raw_body,
                    received_at, processed_flag)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (account_id, m.message_id, m.subject, m.sender,
                 m.body, m.received_at),
            )
            new_count += 1
        DB.execute(
            "UPDATE imap_accounts SET last_scan_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"),
             account_id),
        )
    except GraphError as e:
        error = str(e)
    except Exception as e:
        error = f"Unexpected: {e}"

    DB.log_audit("email_scan", {"account_id": account_id, "new": new_count,
                                "error": error, "backend": "graph"})
    return {"account_id": account_id, "new": new_count, "error": error}


def scan_account(account_id: int) -> dict:
    account = get_account(account_id)
    if not account:
        return {"account_id": account_id, "new": 0, "error": "Unknown account"}

    auth_type = account.get("auth_type") or "password"
    if auth_type == "oauth2":
        return _scan_via_graph(account)

    folder = account["folder_filter"] or "INBOX"
    last_uid = account["last_uid"] or 0
    use_ssl = bool(account["use_ssl"]) if account["use_ssl"] is not None else True

    client = IMAPClient(
        account["server"],
        account["port"] or 993,
        use_ssl=use_ssl,
    )
    new_count = 0
    error: Optional[str] = None
    max_seen_uid = last_uid
    try:
        if not account["encrypted_password"]:
            return {"account_id": account_id, "new": 0,
                    "error": "No password stored"}
        try:
            password = decrypt(account["encrypted_password"])
        except Exception as e:
            return {"account_id": account_id, "new": 0,
                    "error": f"Could not decrypt password: {e}"}
        client.connect(account["username"], password)
        emails = client.fetch_new(
            folder=folder, since_uid=last_uid, max_messages=200,
        )
        for em in emails:
            if em.uid > max_seen_uid:
                max_seen_uid = em.uid
            if em.message_id:
                exists = DB.query_one(
                    "SELECT id FROM emails WHERE message_id = ? AND account_id = ?",
                    (em.message_id, account_id),
                )
                if exists:
                    continue
            DB.execute(
                """INSERT INTO emails
                   (account_id, message_id, subject, sender, raw_body,
                    received_at, processed_flag)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (account_id, em.message_id, em.subject, em.sender,
                 em.body, em.received_at),
            )
            new_count += 1

        DB.execute(
            "UPDATE imap_accounts SET last_uid = ?, last_scan_at = ? WHERE id = ?",
            (max_seen_uid, datetime.now().isoformat(timespec="seconds"), account_id),
        )
    except IMAPError as e:
        error = str(e)
    except Exception as e:
        error = f"Unexpected: {e}"
    finally:
        client.disconnect()

    DB.log_audit("email_scan", {
        "account_id": account_id, "new": new_count, "error": error,
    })
    return {"account_id": account_id, "new": new_count, "error": error}


def scan_all(on_progress: Optional[Callable[[dict], None]] = None) -> list[dict]:
    accounts = list_accounts(enabled_only=True)
    results: list[dict] = []
    for acc in accounts:
        result = scan_account(acc["id"])
        results.append(result)
        if on_progress:
            on_progress(result)
    return results
