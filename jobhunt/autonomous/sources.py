"""Job-source backends.

Each source converts criteria (from a saved search) into a stream of JobListing
objects. The scanner takes that stream, dedupes against job_queue, and inserts
new entries.

All HTTP calls use a short timeout and bail with a clear exception on error.
The Greenhouse / Lever / Ashby / Workable APIs are public — no auth needed.
Adzuna requires app_id + app_key (stored encrypted in the api_keys table).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterator
from urllib.parse import urlencode

import requests

from ..llm import keys as llm_keys


log = logging.getLogger(__name__)


REQUEST_TIMEOUT = 15  # seconds — per HTTP call
DEFAULT_HEADERS = {
    "User-Agent": "JobHunt/1.0 (personal job-search desktop app)",
    "Accept": "application/json",
}


@dataclass
class JobListing:
    source_url: str        # canonical URL — used as the dedupe key (hashed)
    company: str
    role: str
    location: str
    posted_at: str | None  # ISO date if the source provides one
    listing_text: str      # plain-text description for fit scoring


# ============================================================================
# HTML → plain text (sources return HTML descriptions; we want plain text)
# ============================================================================


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data):
        self._parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("p", "div", "li"):
            self._parts.append("\n")

    @property
    def text(self) -> str:
        joined = "".join(self._parts)
        return re.sub(r"\n{3,}", "\n\n", joined).strip()


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    parser = _HTMLStripper()
    try:
        parser.feed(html)
    except Exception:
        return html
    return parser.text


# ============================================================================
# Greenhouse
# ============================================================================


def fetch_greenhouse(slug: str) -> Iterator[JobListing]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
    if resp.status_code == 404:
        raise SourceError(f"Greenhouse board not found: {slug}")
    resp.raise_for_status()
    data = resp.json()
    for job in data.get("jobs", []):
        location = (job.get("location") or {}).get("name") or ""
        yield JobListing(
            source_url=job.get("absolute_url", ""),
            company=slug,
            role=job.get("title", ""),
            location=location,
            posted_at=job.get("updated_at"),
            listing_text=_html_to_text(job.get("content") or ""),
        )


# ============================================================================
# Lever
# ============================================================================


def fetch_lever(slug: str) -> Iterator[JobListing]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
    if resp.status_code == 404:
        raise SourceError(f"Lever account not found: {slug}")
    resp.raise_for_status()
    postings = resp.json()
    if not isinstance(postings, list):
        return
    for posting in postings:
        cats = posting.get("categories") or {}
        location = cats.get("location") or ""
        yield JobListing(
            source_url=posting.get("hostedUrl", ""),
            company=slug,
            role=posting.get("text", ""),
            location=location,
            posted_at=_lever_created_at(posting.get("createdAt")),
            listing_text=posting.get("descriptionPlain")
                or _html_to_text(posting.get("description") or ""),
        )


def _lever_created_at(ms: int | None) -> str | None:
    if ms is None:
        return None
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return None


# ============================================================================
# Ashby
# ============================================================================


def fetch_ashby(slug: str) -> Iterator[JobListing]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
    if resp.status_code == 404:
        raise SourceError(f"Ashby board not found: {slug}")
    resp.raise_for_status()
    data = resp.json()
    for job in data.get("jobs", []):
        if not job.get("isListed", True):
            continue
        yield JobListing(
            source_url=job.get("jobUrl", ""),
            company=slug,
            role=job.get("title", ""),
            location=job.get("locationName") or "",
            posted_at=job.get("publishedAt"),
            listing_text=job.get("descriptionPlain")
                or _html_to_text(job.get("descriptionHtml") or ""),
        )


# ============================================================================
# Workable
# ============================================================================


def fetch_workable(slug: str) -> Iterator[JobListing]:
    """Workable's public widget API returns a job list per account."""
    list_url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}/jobs"
    resp = requests.get(list_url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
    if resp.status_code == 404:
        raise SourceError(f"Workable account not found: {slug}")
    resp.raise_for_status()
    data = resp.json()
    for job in data.get("jobs", []) or []:
        shortcode = job.get("shortcode") or ""
        public_url = (
            job.get("application_url")
            or f"https://apply.workable.com/{slug}/j/{shortcode}/"
        )
        location_parts = []
        for k in ("city", "region", "country"):
            v = job.get(k)
            if v:
                location_parts.append(v)
        location = ", ".join(location_parts) or (job.get("location") or "")
        yield JobListing(
            source_url=public_url,
            company=slug,
            role=job.get("title", ""),
            location=location,
            posted_at=job.get("published_on"),
            # Widget API doesn't include description; fall back to title only.
            # A future enhancement could fetch the per-job page for the body.
            listing_text=job.get("description", "") or job.get("title", ""),
        )


# ============================================================================
# Adzuna
# ============================================================================


ADZUNA_PROVIDER = "adzuna"  # composite — id|key stored together


def fetch_adzuna(criteria: dict) -> Iterator[JobListing]:
    app_id, app_key = _adzuna_credentials()
    if not (app_id and app_key):
        raise SourceError(
            "Adzuna API credentials missing. Add app_id and app_key in "
            "Settings → API Keys."
        )
    country = (criteria.get("where") or "us").lower()
    query = (criteria.get("query") or "").strip()
    max_age = int(criteria.get("max_age_days") or 7)
    salary_min = criteria.get("salary_min")

    page = 1
    pulled = 0
    page_limit = 3  # 3 pages × 50 = 150 results max
    while page <= page_limit:
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": 50,
            "what": query,
            "max_days_old": max_age,
            "content-type": "application/json",
        }
        if salary_min:
            params["salary_min"] = int(salary_min)
        url = (
            f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}?"
            f"{urlencode(params)}"
        )
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
        if resp.status_code in (401, 403):
            raise SourceError("Adzuna rejected your credentials (401/403).")
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results") or []
        if not results:
            return
        for job in results:
            yield JobListing(
                source_url=job.get("redirect_url", ""),
                company=(job.get("company") or {}).get("display_name") or "",
                role=job.get("title") or "",
                location=(job.get("location") or {}).get("display_name") or "",
                posted_at=job.get("created"),
                listing_text=job.get("description", ""),
            )
        pulled += len(results)
        if pulled >= int(data.get("count") or pulled):
            return
        page += 1


def _adzuna_credentials() -> tuple[str | None, str | None]:
    """Adzuna needs an app_id AND an app_key. We store them as two rows in
    api_keys: 'adzuna_app_id' and 'adzuna_app_key'."""
    app_id = llm_keys.get_key("adzuna_app_id")
    app_key = llm_keys.get_key("adzuna_app_key")
    return app_id, app_key


# ============================================================================
# Dispatch
# ============================================================================


class SourceError(Exception):
    """Raised when a source can't be reached / has bad credentials / etc."""


ATS_FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever":      fetch_lever,
    "ashby":      fetch_ashby,
    "workable":   fetch_workable,
}


def fetch_company_ats(criteria: dict) -> Iterator[tuple[JobListing, str | None]]:
    """Yields (job, error_for_this_company_or_None).
    The error string lets the scanner surface per-company failures without
    aborting the whole scan."""
    for company in criteria.get("companies") or []:
        ats = (company.get("ats") or "").lower()
        slug = (company.get("slug") or "").strip()
        if ats not in ATS_FETCHERS or not slug:
            continue
        try:
            for job in ATS_FETCHERS[ats](slug):
                yield job, None
        except SourceError as e:
            log.warning("Source error for %s:%s — %s", ats, slug, e)
            yield None, f"{ats}:{slug} — {e}"
        except requests.RequestException as e:
            log.warning("Network error for %s:%s — %s", ats, slug, e)
            yield None, f"{ats}:{slug} — network error: {e}"
        except Exception as e:
            log.exception("Unexpected error for %s:%s", ats, slug)
            yield None, f"{ats}:{slug} — {type(e).__name__}: {e}"


def matches_criteria(job: JobListing, criteria: dict) -> bool:
    """Post-fetch keyword filter for company-ATS sources (Adzuna does its own
    server-side filtering)."""
    kws = [k.lower() for k in (criteria.get("keywords") or []) if k]
    if kws:
        title_lower = (job.role or "").lower()
        if not any(kw in title_lower for kw in kws):
            return False
    loc_kws = [k.lower() for k in (criteria.get("location_keywords") or []) if k]
    if loc_kws:
        loc_lower = (job.location or "").lower()
        # Treat empty location as "remote-eligible" if user wants remote
        if not loc_lower:
            return "remote" in loc_kws
        if not any(kw in loc_lower for kw in loc_kws):
            return False
    return True
