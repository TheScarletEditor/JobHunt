from __future__ import annotations

import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

BLOCKED_HOSTS = (
    "linkedin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com",
    "monster.com", "dice.com",
)


class FetchError(Exception):
    pass


def fetch_job_listing(url: str, timeout: int = 15) -> str:
    if not url or not url.strip():
        raise FetchError("Empty URL")
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url

    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if any(b in host for b in BLOCKED_HOSTS):
        raise FetchError(
            f"{host} blocks automated fetching. Open the listing in your browser "
            f"and paste the text directly."
        )

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise FetchError(f"Network error: {e}")
    if resp.status_code != 200:
        raise FetchError(f"HTTP {resp.status_code} from {host}")

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag_name in ("script", "style", "nav", "footer", "header", "noscript"):
        for tag in soup.find_all(tag_name):
            tag.decompose()

    if "greenhouse" in host:
        text = _extract_greenhouse(soup)
    elif "lever.co" in host:
        text = _extract_lever(soup)
    elif "ashbyhq" in host or "ashby.com" in host:
        text = _extract_ashby(soup)
    elif "workable.com" in host:
        text = _extract_workable(soup)
    elif "smartrecruiters.com" in host:
        text = _extract_generic(soup)
    elif "jobvite" in host:
        text = _extract_generic(soup)
    else:
        text = _extract_generic(soup)

    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 120:
        raise FetchError(
            f"Couldn't extract enough content from {host}. "
            f"Paste the listing text manually instead."
        )
    return text


def _gtext(tag) -> str:
    if tag is None:
        return ""
    return tag.get_text("\n", strip=True)


def _extract_greenhouse(soup) -> str:
    parts = []
    title = soup.find("h1")
    if title:
        parts.append(_gtext(title))
    company = soup.find("span", class_="company-name") or soup.find("a", class_="company-name")
    if company:
        parts.append(_gtext(company))
    content = (
        soup.find("div", id="content")
        or soup.find("div", id="job-content")
        or soup.find("div", class_="content")
        or soup.find("main")
    )
    if content:
        parts.append(_gtext(content))
    if not any(parts):
        return _extract_generic(soup)
    return "\n\n".join(p for p in parts if p)


def _extract_lever(soup) -> str:
    parts = []
    title = soup.find(["h1", "h2"])
    if title:
        parts.append(_gtext(title))
    sections = soup.find_all("div", class_=lambda c: c and "section-wrapper" in c)
    if not sections:
        sections = soup.find_all("section")
    for s in sections:
        parts.append(_gtext(s))
    if not parts:
        return _extract_generic(soup)
    return "\n\n".join(p for p in parts if p)


def _extract_ashby(soup) -> str:
    parts = []
    title = soup.find(["h1", "h2"])
    if title:
        parts.append(_gtext(title))
    main = soup.find("main") or soup.find("article")
    if main:
        parts.append(_gtext(main))
    if not parts:
        return _extract_generic(soup)
    return "\n\n".join(p for p in parts if p)


def _extract_workable(soup) -> str:
    parts = []
    title = soup.find(["h1", "h2"])
    if title:
        parts.append(_gtext(title))
    content = (
        soup.find("div", attrs={"data-ui": "job-description"})
        or soup.find("article")
        or soup.find("main")
    )
    if content:
        parts.append(_gtext(content))
    if not parts:
        return _extract_generic(soup)
    return "\n\n".join(p for p in parts if p)


def _extract_generic(soup) -> str:
    main = soup.find("main") or soup.find("article") or soup.find("body")
    return _gtext(main)
