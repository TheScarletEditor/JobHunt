"""Calendar provider dispatcher.

Picks Microsoft Outlook (via Graph) or Google Calendar based on the user's
profile email. Falls back to Outlook (the older path) if detection is
inconclusive — but only if a Microsoft account is configured.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..db import DB
from . import google_calendar as gcal
from . import outlook as outlook_mod


log = logging.getLogger(__name__)


PROVIDER_GOOGLE = "google"
PROVIDER_OUTLOOK = "outlook"


@dataclass
class ProviderAvailability:
    provider: str            # "google" or "outlook"
    available: bool          # is this provider actually ready to use?
    reason: str = ""         # if unavailable, why
    label: str = ""          # human label for the button (e.g. "Push to Google Calendar")
    connected_email: str | None = None


GMAIL_HOSTS = ("gmail.com", "googlemail.com")


def detect_provider() -> str:
    """Pick a provider based on the user's profile email host. Defaults to
    Outlook (since the older Microsoft OAuth path exists) when ambiguous."""
    row = DB.query_one("SELECT email FROM profile WHERE id = 1")
    email = (row["email"] if row else "") or ""
    host = email.split("@", 1)[-1].lower().strip() if "@" in email else ""
    if host in GMAIL_HOSTS:
        return PROVIDER_GOOGLE
    return PROVIDER_OUTLOOK


def availability() -> ProviderAvailability:
    """Inspect both providers' state and return what's actually usable, so the
    UI can render the right button text + tooltip."""
    provider = detect_provider()

    if provider == PROVIDER_GOOGLE:
        connected = gcal.is_connected()
        email = gcal.stored_email()
        from .. import config
        if not config.GOOGLE_CLIENT_ID:
            return ProviderAvailability(
                provider=PROVIDER_GOOGLE, available=False,
                reason=(
                    "Google Calendar isn't set up yet. Add a GOOGLE_CLIENT_ID in "
                    "jobhunt/config.py — see the Settings → Calendar tab for steps."
                ),
                label="📅 Set up Google Calendar",
            )
        if not connected:
            return ProviderAvailability(
                provider=PROVIDER_GOOGLE, available=False,
                reason="Not signed in to Google Calendar yet.",
                label="📅 Connect Google Calendar",
            )
        return ProviderAvailability(
            provider=PROVIDER_GOOGLE, available=True,
            label="📅 Push to Google Calendar",
            connected_email=email,
        )

    # Outlook path
    account = outlook_mod.find_oauth_account()
    if account is None:
        return ProviderAvailability(
            provider=PROVIDER_OUTLOOK, available=False,
            reason="No Microsoft account configured. Add one in Settings → IMAP.",
            label="📅 Set up Outlook",
        )
    return ProviderAvailability(
        provider=PROVIDER_OUTLOOK, available=True,
        label="📅 Push to Outlook",
        connected_email=account.get("username"),
    )


def push_event(interview) -> tuple[str, str]:
    """Push to whichever provider the user is set up with. Returns (event_id, provider)."""
    avail = availability()
    if not avail.available:
        raise CalendarPushError(avail.reason)
    if avail.provider == PROVIDER_GOOGLE:
        try:
            event_id = gcal.push_event(interview)
        except gcal.GoogleAuthError as e:
            raise CalendarPushError(str(e)) from e
        return event_id, PROVIDER_GOOGLE
    else:
        try:
            event_id = outlook_mod.push_event(interview)
        except outlook_mod.OutlookPushError as e:
            raise CalendarPushError(str(e)) from e
        return event_id, PROVIDER_OUTLOOK


def delete_event(interview) -> None:
    """Try to delete the linked event from whichever provider hosts it.
    Best-effort — non-fatal if the provider isn't reachable."""
    provider = detect_provider()
    try:
        if provider == PROVIDER_GOOGLE:
            gcal.delete_event(interview)
        else:
            outlook_mod.delete_event(interview)
    except Exception as e:
        log.warning("Calendar delete failed (non-fatal): %s", e)


class CalendarPushError(Exception):
    """Provider-agnostic push failure."""
