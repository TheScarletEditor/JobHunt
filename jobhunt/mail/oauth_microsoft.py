"""Microsoft Identity Platform OAuth2 flows for JobHunt.

Primary flow: authorization-code + PKCE with localhost loopback (works for
personal Microsoft accounts via Microsoft Graph). Device-code helpers are kept
for completeness but the dialog no longer uses them.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import secrets
import socket
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime, timedelta
from typing import Callable, Optional

import requests


AUTHORITY = "https://login.microsoftonline.com/common"
DEVICE_CODE_URL = f"{AUTHORITY}/oauth2/v2.0/devicecode"
TOKEN_URL = f"{AUTHORITY}/oauth2/v2.0/token"

# Native-client redirect URI: Microsoft's "no actual redirect" placeholder for
# desktop apps. The Azure app must have this URI configured under
# Authentication → Mobile and desktop applications platform.
REDIRECT_URI = "https://login.microsoftonline.com/common/oauth2/nativeclient"

SCOPE = (
    "https://graph.microsoft.com/Mail.Read "
    "https://graph.microsoft.com/Calendars.ReadWrite "
    "offline_access"
)


class OAuthError(Exception):
    pass


def start_device_flow(client_id: str, scope: str = SCOPE, timeout: int = 30) -> dict:
    """Initiate the device-code flow. Returns a dict with keys:
    user_code, device_code, verification_uri, expires_in, interval, message."""
    try:
        resp = requests.post(
            DEVICE_CODE_URL,
            data={
                "client_id": client_id,
                "scope": scope,
                "redirect_uri": REDIRECT_URI,
            },
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise OAuthError(f"Network error starting device flow: {e}")

    if resp.status_code != 200:
        try:
            err = resp.json()
        except Exception:
            err = {"error": resp.text[:200]}
        msg = err.get("error_description") or err.get("error") or str(resp.status_code)
        raise OAuthError(f"Device flow start failed: {msg}")

    return resp.json()


def poll_for_token(
    device_code: str,
    client_id: str,
    interval: int = 5,
    timeout: int = 900,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> dict:
    """Poll until the user completes sign-in. Returns the token dict from Microsoft
    (access_token, refresh_token, expires_in, id_token, ...).
    Raises OAuthError on failure or timeout."""
    end_time = time.time() + timeout
    current_interval = max(int(interval), 1)

    while time.time() < end_time:
        if is_cancelled and is_cancelled():
            raise OAuthError("Cancelled")

        try:
            resp = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": client_id,
                    "device_code": device_code,
                    "redirect_uri": REDIRECT_URI,
                },
                timeout=30,
            )
        except requests.RequestException as e:
            raise OAuthError(f"Network error polling for token: {e}")

        try:
            data = resp.json()
        except Exception:
            raise OAuthError(f"Unexpected response: {resp.text[:200]}")

        if resp.status_code == 200 and "access_token" in data:
            return data

        error = data.get("error", "")
        if error == "authorization_pending":
            time.sleep(current_interval)
            continue
        if error == "slow_down":
            current_interval = min(current_interval + 5, 30)
            time.sleep(current_interval)
            continue
        if error in ("expired_token", "code_expired"):
            raise OAuthError("Sign-in code expired. Start over.")
        if error == "authorization_declined":
            raise OAuthError("Sign-in declined in browser.")
        if error == "bad_verification_code":
            raise OAuthError("Bad verification code.")
        if error == "invalid_client":
            raise OAuthError(
                "Azure app rejected the request. Verify the Microsoft client ID in Settings "
                "(it must be a multi-tenant public client app with IMAP.AccessAsUser.All "
                "delegated permission, and 'Allow public client flows' enabled)."
            )
        raise OAuthError(f"OAuth error: {data.get('error_description') or error}")

    raise OAuthError("Sign-in timed out after 15 minutes.")


def refresh_access_token(refresh_token: str, client_id: str, scope: str = SCOPE) -> dict:
    """Exchange a refresh token for a new access token."""
    try:
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
                "scope": scope,
                "redirect_uri": REDIRECT_URI,
            },
            timeout=30,
        )
    except requests.RequestException as e:
        raise OAuthError(f"Network error: {e}")

    try:
        data = resp.json()
    except Exception:
        raise OAuthError(f"Unexpected response: {resp.text[:200]}")

    if resp.status_code == 200 and "access_token" in data:
        return data
    raise OAuthError(
        f"Refresh failed: {data.get('error_description') or data.get('error') or resp.status_code}"
    )


def _generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    return verifier, challenge


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _CaptureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" not in params and "error" not in params:
            self.send_response(204)
            self.end_headers()
            return
        self.server.received_params = {k: (v[0] if v else "") for k, v in params.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"""<!DOCTYPE html><html><head><title>JobHunt</title>
<style>html,body{margin:0;padding:0;background:#0a0a0a;color:#fff;
font-family:Segoe UI,-apple-system,sans-serif;}
.box{max-width:520px;margin:96px auto;padding:32px;background:#141414;border-radius:12px;}
h1{color:#C8102E;margin:0 0 12px 0;font-size:24px;}p{color:#a8a8a8;line-height:1.5;}
</style></head><body><div class="box"><h1>Signed in</h1>
<p>JobHunt has captured your sign-in. You can close this tab and return to the app.</p>
</div></body></html>""")

    def log_message(self, *args, **kwargs):
        return


def run_auth_code_flow(
    client_id: str,
    scope: str = SCOPE,
    timeout: int = 300,
    on_ready: Optional[Callable[[str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> dict:
    """Run authorization-code + PKCE flow with a localhost loopback redirect.

    on_ready(url): called once the auth URL is built. The caller should open it
    in a browser. If None, this function opens the browser itself.
    is_cancelled(): polled periodically; if True, abort.
    """
    verifier, challenge = _generate_pkce()
    port = _find_free_port()
    redirect_uri = f"http://localhost:{port}"
    state = secrets.token_urlsafe(16)

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": scope,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "prompt": "select_account",
    }
    auth_url = f"{AUTHORITY}/oauth2/v2.0/authorize?" + urllib.parse.urlencode(params)

    server = http.server.HTTPServer(("127.0.0.1", port), _CaptureHandler)
    server.received_params = None
    server.timeout = 1

    if on_ready:
        on_ready(auth_url)
    else:
        webbrowser.open(auth_url)

    end_time = time.time() + timeout
    try:
        while server.received_params is None and time.time() < end_time:
            if is_cancelled and is_cancelled():
                raise OAuthError("Cancelled")
            server.handle_request()
    finally:
        try:
            server.server_close()
        except Exception:
            pass

    if server.received_params is None:
        raise OAuthError("Sign-in timed out")

    received = server.received_params
    if "error" in received:
        raise OAuthError(
            received.get("error_description") or received.get("error") or "Auth error"
        )
    if received.get("state") != state:
        raise OAuthError("Sign-in failed (state mismatch).")
    code = received.get("code")
    if not code:
        raise OAuthError("No authorization code received.")

    try:
        resp = requests.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "scope": scope,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            timeout=30,
        )
    except requests.RequestException as e:
        raise OAuthError(f"Network error exchanging code: {e}")

    try:
        data = resp.json()
    except Exception:
        raise OAuthError(f"Unexpected token response: {resp.text[:200]}")

    if resp.status_code == 200 and "access_token" in data:
        return data
    raise OAuthError(
        f"Token exchange failed: {data.get('error_description') or data.get('error') or resp.status_code}"
    )


def is_token_expired(expires_at_iso: Optional[str], margin_seconds: int = 300) -> bool:
    if not expires_at_iso:
        return True
    try:
        expires_at = datetime.fromisoformat(expires_at_iso)
    except (ValueError, TypeError):
        return True
    return datetime.now() + timedelta(seconds=margin_seconds) >= expires_at


def expires_at_from_now(expires_in_seconds) -> str:
    try:
        seconds = int(expires_in_seconds)
    except (TypeError, ValueError):
        seconds = 3600
    return (datetime.now() + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def extract_email_from_id_token(id_token: str) -> Optional[str]:
    """Pull the user's email/upn from the ID token JWT payload without verifying the signature."""
    import base64
    import json
    try:
        parts = id_token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return (
            payload.get("email")
            or payload.get("preferred_username")
            or payload.get("upn")
        )
    except Exception:
        return None
