"""Google Calendar push — OAuth (loopback + PKCE) + event create/update/delete.

Lives next to outlook.py; calendar.py dispatches to whichever provider matches
the user's profile email.

Tokens are stored encrypted via the existing api_keys / settings_kv tables —
no new schema. Refresh-token logic mirrors mail/scanner._ensure_fresh_oauth_token.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import secrets
import socket
import threading
import urllib.parse
import webbrowser
from datetime import datetime, timedelta, timezone

import requests

from .. import config
from ..db import DB
from ..llm import keys as llm_keys  # llm_keys.store_key handles DPAPI encryption


log = logging.getLogger(__name__)


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CAL_BASE = "https://www.googleapis.com/calendar/v3"
SCOPE = "openid email https://www.googleapis.com/auth/calendar.events"

REQUEST_TIMEOUT = 15


class GoogleAuthError(Exception):
    """Raised on any OAuth or Calendar API failure for Google."""


# ============================================================================
# Token storage (uses encrypted api_keys + plain settings_kv for metadata)
# ============================================================================


_ACCESS_KEY = "google_calendar_access_token"
_REFRESH_KEY = "google_calendar_refresh_token"
_EXPIRES_SETTING = "google_calendar_expires_at"
_EMAIL_SETTING = "google_calendar_email"


def stored_email() -> str | None:
    return DB.get_setting(_EMAIL_SETTING)


def is_connected() -> bool:
    return llm_keys.get_key(_REFRESH_KEY) is not None


def _save_tokens(token_response: dict, *, email: str | None = None) -> None:
    access = token_response.get("access_token")
    refresh = token_response.get("refresh_token")
    expires_in = int(token_response.get("expires_in") or 3600)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
    if access:
        llm_keys.store_key(_ACCESS_KEY, access)
    if refresh:
        llm_keys.store_key(_REFRESH_KEY, refresh)
    DB.set_setting(_EXPIRES_SETTING, expires_at)
    if email:
        DB.set_setting(_EMAIL_SETTING, email)


def disconnect() -> None:
    llm_keys.store_key(_ACCESS_KEY, None)
    llm_keys.store_key(_REFRESH_KEY, None)
    DB.set_setting(_EXPIRES_SETTING, "")
    DB.set_setting(_EMAIL_SETTING, "")
    DB.log_audit("google_calendar_disconnected")


def _fresh_access_token() -> str:
    if not config.GOOGLE_CLIENT_ID:
        raise GoogleAuthError(
            "Google OAuth not configured. Set GOOGLE_CLIENT_ID in jobhunt/config.py — "
            "create a Desktop OAuth client at https://console.cloud.google.com/."
        )
    expires_at_text = DB.get_setting(_EXPIRES_SETTING)
    expires_at = _parse_iso(expires_at_text)
    if expires_at and expires_at > datetime.now(timezone.utc) + timedelta(seconds=120):
        existing = llm_keys.get_key(_ACCESS_KEY)
        if existing:
            return existing

    refresh = llm_keys.get_key(_REFRESH_KEY)
    if not refresh:
        raise GoogleAuthError(
            "Google Calendar not connected. Click 'Connect Google Calendar' first."
        )

    data = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "refresh_token": refresh,
        "grant_type": "refresh_token",
    }
    if config.GOOGLE_CLIENT_SECRET:
        data["client_secret"] = config.GOOGLE_CLIENT_SECRET
    resp = requests.post(TOKEN_URL, data=data, timeout=REQUEST_TIMEOUT)
    if not resp.ok:
        raise GoogleAuthError(f"Refresh failed: {resp.status_code} {resp.text[:200]}")
    payload = resp.json()
    _save_tokens(payload)
    return payload["access_token"]


# ============================================================================
# OAuth flow — loopback redirect + PKCE
# ============================================================================


def _generate_pkce() -> tuple[str, str]:
    """Returns (verifier, challenge) for PKCE S256."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _CaptureHandler(http.server.BaseHTTPRequestHandler):
    captured: dict = {}

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        _CaptureHandler.captured = params
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if params.get("error"):
            body = f"<h2>Authorization failed</h2><p>{params.get('error_description', params['error'])}</p>"
        else:
            body = (
                "<h2 style='font-family:system-ui;color:#43a047'>Google Calendar connected ✓</h2>"
                "<p style='font-family:system-ui'>You can close this tab and return to JobHunt.</p>"
            )
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *_args, **_kwargs):
        # Silence the default stderr noise
        pass


def run_auth_code_flow(*, timeout: int = 180) -> dict:
    """Open the user's browser to Google's consent screen, capture the auth code
    on a localhost loopback, exchange it for tokens, persist them, and return
    the email + token payload."""
    if not config.GOOGLE_CLIENT_ID:
        raise GoogleAuthError(
            "GOOGLE_CLIENT_ID is empty. Set it in jobhunt/config.py first."
        )

    verifier, challenge = _generate_pkce()
    port = _find_free_port()
    redirect_uri = f"http://localhost:{port}"
    state = secrets.token_urlsafe(16)

    auth_params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",  # force refresh_token issuance on re-grant
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    auth_url = AUTH_URL + "?" + urllib.parse.urlencode(auth_params)

    _CaptureHandler.captured = {}
    server = http.server.HTTPServer(("127.0.0.1", port), _CaptureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        webbrowser.open(auth_url)
        deadline = datetime.now() + timedelta(seconds=timeout)
        while not _CaptureHandler.captured and datetime.now() < deadline:
            threading.Event().wait(0.2)
        params = dict(_CaptureHandler.captured)
    finally:
        server.shutdown()
        thread.join(timeout=2)

    if params.get("error"):
        raise GoogleAuthError(
            f"Google said no: {params.get('error_description', params['error'])}"
        )
    if not params.get("code"):
        raise GoogleAuthError("Timed out waiting for Google sign-in.")
    if params.get("state") != state:
        raise GoogleAuthError("OAuth state mismatch (possible CSRF) — aborted.")

    token_data = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "code": params["code"],
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    if config.GOOGLE_CLIENT_SECRET:
        token_data["client_secret"] = config.GOOGLE_CLIENT_SECRET
    resp = requests.post(TOKEN_URL, data=token_data, timeout=REQUEST_TIMEOUT)
    if not resp.ok:
        raise GoogleAuthError(
            f"Token exchange failed: {resp.status_code} {resp.text[:300]}"
        )
    payload = resp.json()

    email = _email_from_id_token(payload.get("id_token", ""))
    _save_tokens(payload, email=email)
    DB.log_audit("google_calendar_connected", {"email": email or "(unknown)"})
    return {"email": email, "token": payload}


def _email_from_id_token(id_token: str) -> str | None:
    """Best-effort email extraction from the unsigned id_token payload — we
    skip signature verification because the token came from the live OAuth
    exchange we just made (TLS already validates the source)."""
    if not id_token:
        return None
    try:
        _header, body, *_ = id_token.split(".")
        # JWT base64-url with no padding
        padded = body + "=" * (-len(body) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return claims.get("email")
    except Exception:
        return None


def _parse_iso(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        # Python 3.11+ handles ISO timezone offsets directly
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


# ============================================================================
# Calendar event create / update / delete
# ============================================================================


def push_event(interview) -> str:
    """Create (or update if google_event_id present in outlook_event_id field)
    a Google Calendar event. We reuse the outlook_event_id column to keep the
    schema simple — only one provider's event-id lives there at a time."""
    token = _fresh_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = _build_event_payload(interview)

    if interview.outlook_event_id:
        url = f"{CAL_BASE}/calendars/primary/events/{interview.outlook_event_id}"
        resp = requests.put(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code in (404, 410):
            log.info("Google event %s no longer exists — creating fresh.",
                     interview.outlook_event_id)
        else:
            _raise_for_status(resp)
            event_id = resp.json().get("id") or interview.outlook_event_id
            _persist_event_id(interview.id, event_id)
            return event_id

    url = f"{CAL_BASE}/calendars/primary/events"
    resp = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    _raise_for_status(resp)
    event_id = resp.json().get("id")
    if not event_id:
        raise GoogleAuthError("Google didn't return an event id.")
    _persist_event_id(interview.id, event_id)
    return event_id


def delete_event(interview) -> None:
    if not interview.outlook_event_id:
        return
    token = _fresh_access_token()
    url = f"{CAL_BASE}/calendars/primary/events/{interview.outlook_event_id}"
    resp = requests.delete(
        url, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code not in (204, 404, 410):
        _raise_for_status(resp)
    DB.execute(
        "UPDATE interviews SET outlook_event_id = NULL WHERE id = ?",
        (interview.id,),
    )


def _build_event_payload(interview) -> dict:
    start_dt = _parse_naive(interview.interview_datetime)
    if start_dt is None:
        start_dt = (datetime.now() + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    duration = timedelta(minutes=int(interview.duration_minutes or 60))
    end_dt = start_dt + duration

    bits = ["Interview"]
    if interview.company:
        bits.append(interview.company)
    if interview.role:
        bits.append(interview.role)
    summary = " · ".join(bits)
    if interview.round_type:
        summary = f"{summary} ({interview.round_type})"

    body_lines: list[str] = []
    if interview.role and interview.company:
        body_lines.append(f"Role: {interview.role} at {interview.company}")
    if interview.round_type:
        body_lines.append(f"Round: {interview.round_type}")
    if interview.meeting_url:
        body_lines.append(f"Meeting URL: {interview.meeting_url}")
    if interview.prep_notes:
        body_lines.append("")
        body_lines.append("=== Prep notes ===")
        body_lines.append(interview.prep_notes)
    description = "\n".join(body_lines) or "Interview scheduled via JobHunt."

    payload: dict = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
        "end":   {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),   "timeZone": "UTC"},
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 15}],
        },
    }
    if interview.location:
        payload["location"] = interview.location

    attendees = []
    for a in (interview.attendees or []):
        if a.email:
            attendees.append({
                "email": a.email,
                "displayName": a.name or a.email,
                "responseStatus": "needsAction",
            })
    if attendees:
        payload["attendees"] = attendees

    return payload


def _parse_naive(text: str | None) -> datetime | None:
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
    DB.log_audit("interview_pushed_to_google", {
        "interview_id": interview_id, "event_id": event_id,
    })


def _raise_for_status(resp: requests.Response) -> None:
    if 200 <= resp.status_code < 300:
        return
    try:
        body = resp.json()
        msg = (body.get("error", {}) or {}).get("message") or str(body)[:300]
    except Exception:
        msg = resp.text[:300] if resp.text else f"HTTP {resp.status_code}"
    raise GoogleAuthError(f"Google error {resp.status_code}: {msg}")
