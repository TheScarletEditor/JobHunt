from __future__ import annotations

from ..db import DB
from ..credentials import encrypt, decrypt


PROVIDERS = ("claude", "openai")
# Additional credentials stored in the same encrypted api_keys table.
EXTRA_PROVIDERS = (
    "adzuna_app_id",
    "adzuna_app_key",
    "google_calendar_access_token",
    "google_calendar_refresh_token",
)


def store_key(provider: str, plaintext: str | None):
    provider = provider.lower()
    if provider not in PROVIDERS and provider not in EXTRA_PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")
    if not plaintext:
        DB.execute("DELETE FROM api_keys WHERE provider = ?", (provider,))
        return
    blob = encrypt(plaintext)
    DB.execute(
        "INSERT INTO api_keys (provider, encrypted_key) VALUES (?, ?) "
        "ON CONFLICT(provider) DO UPDATE SET encrypted_key = excluded.encrypted_key",
        (provider, blob),
    )


def get_key(provider: str) -> str | None:
    row = DB.query_one(
        "SELECT encrypted_key FROM api_keys WHERE provider = ?",
        (provider.lower(),),
    )
    if not row or not row["encrypted_key"]:
        return None
    try:
        return decrypt(row["encrypted_key"])
    except Exception:
        return None


def is_configured(provider: str) -> bool:
    return get_key(provider) is not None


def configured_providers() -> list[str]:
    return [p for p in PROVIDERS if is_configured(p)]


def get_preference() -> str:
    pref = DB.get_setting("llm_preference", "claude")
    return pref or "claude"


def set_preference(preference: str):
    DB.set_setting("llm_preference", preference.lower())
