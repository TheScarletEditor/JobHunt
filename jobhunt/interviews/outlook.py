"""Push an interview to Microsoft Outlook via the existing Graph OAuth.

Reuses the OAuth account stored in imap_accounts (`auth_type = 'oauth_msft'`).
Stores the resulting event ID on the interview row so updates / deletes can
target the same event.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import requests

from ..db import DB
from ..mail.scanner import _ensure_fresh_oauth_token


log = logging.getLogger(__name__)


GRAPH_BASE = "https://graph.microsoft.com/v1.0"
REQUEST_TIMEOUT = 15


class OutlookPushError(Exception):
    """Raised when we can't reach Graph, or it rejects the payload."""


def find_oauth_account() -> dict | None:
    """Return the first enabled Microsoft OAuth account, or None if there isn't one."""
    row = DB.query_one(
        """SELECT id, display_name, server, port, username, encrypted_password,
                  folder_filter, last_uid, use_ssl, enabled, last_scan_at,
                  auth_type, oauth_access_token, oauth_refresh_token, oauth_expires_at
           FROM imap_accounts
           WHERE enabled = 1 AND auth_type = 'oauth_msft'
           ORDER BY id LIMIT 1"""
    )
    return dict(row) if row else None


def push_event(interview) -> str:
    """Create (or update if outlook_event_id already set) a calendar event for
    this interview. Returns the event ID."""
    account = find_oauth_account()
    if account is None:
        raise OutlookPushError(
            "No Microsoft OAuth account configured. Add one in Settings → IMAP first."
        )

    try:
        token = _ensure_fresh_oauth_token(account)
    except Exception as e:
        raise OutlookPushError(f"Couldn't refresh access token: {e}") from e

    payload = _build_event_payload(interview)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    if interview.outlook_event_id:
        # Update existing event in place
        url = f"{GRAPH_BASE}/me/events/{interview.outlook_event_id}"
        resp = requests.patch(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code in (404, 410):
            # Event was deleted on Outlook side — fall through to create-new
            log.info("Outlook event %s no longer exists; creating fresh.",
                     interview.outlook_event_id)
        else:
            _raise_for_graph(resp)
            data = resp.json()
            event_id = data.get("id") or interview.outlook_event_id
            _persist_event_id(interview.id, event_id)
            return event_id

    # Create
    url = f"{GRAPH_BASE}/me/events"
    resp = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    _raise_for_graph(resp)
    data = resp.json()
    event_id = data.get("id")
    if not event_id:
        raise OutlookPushError(f"Graph returned no event id: {data}")
    _persist_event_id(interview.id, event_id)
    return event_id


def delete_event(interview) -> None:
    """Delete the Outlook event linked to this interview, if any."""
    if not interview.outlook_event_id:
        return
    account = find_oauth_account()
    if account is None:
        raise OutlookPushError("No Microsoft account configured.")
    try:
        token = _ensure_fresh_oauth_token(account)
    except Exception as e:
        raise OutlookPushError(f"Couldn't refresh access token: {e}") from e
    url = f"{GRAPH_BASE}/me/events/{interview.outlook_event_id}"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.delete(url, headers=headers, timeout=REQUEST_TIMEOUT)
    # 204 No Content on success; 404 means already gone, which is fine.
    if resp.status_code not in (204, 404):
        _raise_for_graph(resp)
    DB.execute(
        "UPDATE interviews SET outlook_event_id = NULL WHERE id = ?",
        (interview.id,),
    )


# ============================================================================
# Helpers
# ============================================================================


def _build_event_payload(interview) -> dict:
    start_dt = _parse_iso_naive(interview.interview_datetime)
    if start_dt is None:
        # Default: now + 1h, rounded to next hour
        start_dt = (datetime.now() + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    duration = timedelta(minutes=int(interview.duration_minutes or 60))
    end_dt = start_dt + duration

    subject_bits = ["Interview"]
    if interview.company:
        subject_bits.append(interview.company)
    if interview.role:
        subject_bits.append(interview.role)
    subject = " · ".join(subject_bits)
    if interview.round_type:
        subject = f"{subject} ({interview.round_type})"

    body_parts: list[str] = []
    if interview.role and interview.company:
        body_parts.append(f"Role: {interview.role} at {interview.company}")
    if interview.round_type:
        body_parts.append(f"Round: {interview.round_type}")
    if interview.meeting_url:
        body_parts.append(f"Meeting URL: {interview.meeting_url}")
    if interview.prep_notes:
        body_parts.append("")
        body_parts.append("=== Prep notes ===")
        body_parts.append(interview.prep_notes)
    body_text = "\n".join(body_parts) or "Interview scheduled via JobHunt."

    payload: dict = {
        "subject": subject,
        "body": {"contentType": "text", "content": body_text},
        "start": {
            "dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "UTC",
        },
        "end": {
            "dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "UTC",
        },
        "reminderMinutesBeforeStart": 15,
    }
    if interview.location:
        payload["location"] = {"displayName": interview.location}

    attendees = []
    for a in (interview.attendees or []):
        if a.email:
            attendees.append({
                "emailAddress": {
                    "address": a.email,
                    "name": a.name or a.email,
                },
                "type": "required",
            })
    if attendees:
        payload["attendees"] = attendees

    return payload


def _parse_iso_naive(text: str | None) -> datetime | None:
    if not text:
        return None
    s = text.strip().replace("T", " ").rstrip("Z").strip()
    if len(s) > 19 and (s[19] == "+" or s[19] == "-"):
        s = s[:19]
    try:
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _persist_event_id(interview_id: int | None, event_id: str) -> None:
    if interview_id is None:
        return
    DB.execute(
        "UPDATE interviews SET outlook_event_id = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (event_id, interview_id),
    )
    DB.log_audit("interview_pushed_to_outlook", {
        "interview_id": interview_id, "event_id": event_id,
    })


def _raise_for_graph(resp: requests.Response) -> None:
    if 200 <= resp.status_code < 300:
        return
    try:
        body = resp.json()
        err = body.get("error", {}) or {}
        msg = err.get("message") or str(body)[:300]
        code = err.get("code") or ""
    except Exception:
        msg = resp.text[:300] if resp.text else f"HTTP {resp.status_code}"
        code = ""

    # 403 + a scope/auth code → tokens are missing Calendars.ReadWrite. This
    # happens for users who signed in before the calendar scope was added.
    if resp.status_code in (401, 403) and any(
        s in (code + msg).lower()
        for s in ("scope", "permission", "calendars", "invalidauthenticationtoken",
                  "accessdenied", "authorization", "consent")
    ):
        raise OutlookPushError(
            "Microsoft hasn't authorized JobHunt to write to your calendar yet. "
            "Open Settings → Calendar and click 'Re-authorize Microsoft' to grant "
            "the Calendars.ReadWrite permission, then try again."
        )
    raise OutlookPushError(f"Graph error {resp.status_code}: {msg}")
