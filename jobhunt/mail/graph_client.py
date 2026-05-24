"""Microsoft Graph mail client — used for OAuth2 accounts where Microsoft has
killed IMAP basic auth and the user's tenant lacks the Exchange Online API."""
from __future__ import annotations

import re
from dataclasses import dataclass

import requests


class GraphError(Exception):
    pass


@dataclass
class GraphMessage:
    message_id: str
    subject: str
    sender: str
    body: str
    received_at: str


def _strip_html(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class GraphMailClient:
    BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self, access_token: str, timeout: int = 30):
        self._token = access_token
        self._timeout = timeout

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "Prefer": 'outlook.body-content-type="text"',
        }

    def fetch_recent_messages(
        self,
        since_iso: str | None = None,
        max_messages: int = 200,
    ) -> list[GraphMessage]:
        params = {
            "$top": min(max_messages, 50),
            "$orderby": "receivedDateTime desc",
            "$select": (
                "id,internetMessageId,subject,from,"
                "receivedDateTime,body,bodyPreview"
            ),
        }
        if since_iso:
            iso = since_iso
            if not iso.endswith("Z") and "+" not in iso:
                iso = iso + "Z"
            params["$filter"] = f"receivedDateTime ge {iso}"

        url = f"{self.BASE}/me/mailFolders/Inbox/messages"
        results: list[GraphMessage] = []

        while url and len(results) < max_messages:
            try:
                resp = requests.get(
                    url,
                    params=params if params else None,
                    headers=self._headers(),
                    timeout=self._timeout,
                )
            except requests.RequestException as e:
                raise GraphError(f"Network error: {e}")

            if resp.status_code == 401:
                raise GraphError("Access token rejected — needs refresh")
            if resp.status_code == 403:
                raise GraphError(
                    "Permission denied. The app may be missing the Mail.Read scope "
                    "or the user has not consented to it."
                )
            if resp.status_code != 200:
                raise GraphError(
                    f"Graph error {resp.status_code}: {resp.text[:200]}"
                )

            try:
                data = resp.json()
            except Exception:
                raise GraphError(f"Unexpected response: {resp.text[:200]}")

            for raw in data.get("value", []):
                results.append(self._parse(raw))
                if len(results) >= max_messages:
                    break

            url = data.get("@odata.nextLink")
            params = None

        return results

    def _parse(self, raw: dict) -> GraphMessage:
        from_field = raw.get("from") or {}
        addr = from_field.get("emailAddress") or {}
        name = addr.get("name", "")
        email = addr.get("address", "")
        if name and email:
            sender = f"{name} <{email}>"
        else:
            sender = email or name

        body_field = raw.get("body") or {}
        content = body_field.get("content") or raw.get("bodyPreview") or ""
        content_type = (body_field.get("contentType") or "").lower()
        if content_type == "html":
            content = _strip_html(content)

        return GraphMessage(
            message_id=raw.get("internetMessageId") or raw.get("id") or "",
            subject=raw.get("subject") or "",
            sender=sender,
            body=content,
            received_at=raw.get("receivedDateTime") or "",
        )


def test_connection(access_token: str) -> dict:
    """Hit /me/messages with $top=1 to verify the token + scope."""
    try:
        resp = requests.get(
            f"{GraphMailClient.BASE}/me/messages",
            params={"$top": 1, "$select": "id,subject"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
    except requests.RequestException as e:
        return {"ok": False, "error": f"Network error: {e}"}
    if resp.status_code == 200:
        return {"ok": True, "error": None}
    if resp.status_code == 401:
        return {"ok": False, "error": "Token rejected (needs refresh)"}
    if resp.status_code == 403:
        return {"ok": False, "error": "Mail.Read permission not granted"}
    return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
