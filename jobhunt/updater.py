"""Auto-updater. Checks GitHub Releases on startup; offers to download + install.

How it works:
  1. On startup, hit GET /repos/{owner}/{repo}/releases/latest.
  2. Compare `tag_name` (stripped of leading 'v') to the bundled __version__
     using semver-style int-tuple ordering.
  3. If newer, find the first .exe asset on the release and prompt the user.
  4. On accept, download to %TEMP%, launch the installer with /SILENT, and
     close the running app. Inno Setup's /SILENT flag finishes the install
     in the background; Windows then launches the new exe via the Start
     Menu / desktop shortcut the user created.

The whole thing is best-effort: if the network is down, the GitHub API rate
limits us, or any step fails, we log + carry on. Users never lose work to
the updater.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass

from .__version__ import __version__


log = logging.getLogger(__name__)


# Override these per-fork by editing here. The README's "Sharing" section
# explains how to publish releases that this code will pick up.
GITHUB_OWNER = "TheScarletEditor"
GITHUB_REPO = "JobHunt"

# Skip the network call entirely when this env var is set — handy for dev /
# CI runs where you don't want surprise update prompts.
DISABLE_UPDATER_ENV = "JOBHUNT_NO_UPDATE"


@dataclass
class UpdateInfo:
    version: str               # e.g. "0.7.1"
    asset_url: str             # direct URL to the .exe asset
    release_url: str           # html URL to the release page
    notes: str = ""            # release body (markdown), for the prompt


# ============================================================================
# Version comparison
# ============================================================================


def _parse_version(text: str) -> tuple[int, ...]:
    """Lenient: '0.6.0' / 'v0.6.0' / '0.6' all parse. Non-numeric trailing
    components (e.g. '-beta') are dropped."""
    text = (text or "").lstrip("v").strip()
    parts: list[int] = []
    for chunk in text.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def is_newer(remote: str, local: str = __version__) -> bool:
    """Return True iff `remote` parses as a strictly greater version than `local`."""
    try:
        return _parse_version(remote) > _parse_version(local)
    except Exception:
        return False


# ============================================================================
# GitHub Releases check
# ============================================================================


def check_for_update(*, timeout: int = 5) -> UpdateInfo | None:
    """Return UpdateInfo if a newer release exists, else None.
    Best-effort: any error → None + a debug log line."""
    if os.environ.get(DISABLE_UPDATER_ENV):
        return None
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"JobHunt/{__version__}",
    })
    log.info("Update check: GET %s", url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        log.info("Update check skipped (network): %s", e)
        return None
    except Exception as e:
        log.info("Update check failed: %s", e)
        return None

    remote = data.get("tag_name") or data.get("name") or ""
    log.info("Update check: remote=%s local=%s newer=%s", remote, __version__, is_newer(remote))
    if not remote or not is_newer(remote):
        return None

    # Find the .exe asset on the release. Convention: name ends with .exe
    # (e.g. JobHunt-Setup-0.7.0.exe).
    asset_url = ""
    for asset in data.get("assets") or []:
        name = (asset.get("name") or "").lower()
        if name.endswith(".exe"):
            asset_url = asset.get("browser_download_url") or ""
            break
    if not asset_url:
        log.info("Newer release %s found but no .exe asset attached", remote)
        return None

    return UpdateInfo(
        version=remote.lstrip("v"),
        asset_url=asset_url,
        release_url=data.get("html_url") or "",
        notes=(data.get("body") or "").strip(),
    )


# ============================================================================
# Download + launch installer
# ============================================================================


def download_installer(info: UpdateInfo, *, progress_cb=None) -> str:
    """Download the installer to %TEMP% and return the local path.
    `progress_cb(done, total)` is called as bytes are received (best-effort)."""
    fd, path = tempfile.mkstemp(
        prefix=f"JobHunt-Setup-{info.version}-", suffix=".exe",
    )
    os.close(fd)

    req = urllib.request.Request(info.asset_url, headers={
        "User-Agent": f"JobHunt/{__version__}",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        chunk_size = 65536
        with open(path, "wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb is not None:
                    try:
                        progress_cb(done, total)
                    except Exception:
                        pass
    log.info("Downloaded update installer to %s (%d bytes)", path, done)
    return path


def launch_installer(installer_path: str, *, silent: bool = True) -> None:
    """Spawn the installer detached, so the running app can exit without
    killing the installation. /SILENT + /CLOSEAPPLICATIONS lets Inno Setup
    upgrade in place without further prompts."""
    args = [installer_path]
    if silent:
        # Inno Setup silent-install flags. /SP- disables the "this will install
        # X, continue?" prompt; /SILENT shows a progress window only (good
        # feedback); /CLOSEAPPLICATIONS shuts JobHunt down cleanly before
        # overwriting the .exe; /NORESTART avoids forced reboots.
        args += ["/SP-", "/SILENT", "/CLOSEAPPLICATIONS", "/NORESTART"]
    creationflags = 0
    if os.name == "nt":
        # DETACHED_PROCESS so the installer survives our exit.
        creationflags = 0x00000008  # DETACHED_PROCESS
    subprocess.Popen(args, close_fds=True, creationflags=creationflags)
