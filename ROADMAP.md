# Roadmap

Living document for what's planned beyond v0.6.x. Past-tense items live in [SPEC.md](SPEC.md) and the [GitHub Releases page](https://github.com/TheScarletEditor/JobHunt/releases). Bugs already resolved are in [BUGS.md](BUGS.md).

---

## v0.7.x — multi-platform + companion-on-phone

The theme of v0.7 is **reach.** The product itself stays the same; the surfaces it's available on widen. macOS first, then a phone-friendly LAN web view, then push notifications.

The three releases ship independently so each can be reverted without affecting the others.

### v0.7.0 — macOS port  · ~1-2 weeks

PySide6 runs on macOS as-is; the work is replacing Windows-specific shims and producing a `.app`/`.dmg`.

- New `jobhunt/credentials/keychain.py` (uses the `keyring` library or direct `security` CLI calls) parallel to the existing DPAPI module
- `jobhunt/credentials/__init__.py` picks the impl by `sys.platform`
- `jobhunt/config.py` macOS branch:
  - `APPDATA_DIR` → `~/Library/Application Support/JobHunt/`
  - log path → `~/Library/Logs/JobHunt/jobhunt.log`
- `installer/JobHunt-mac.spec` — PyInstaller spec for the `.app` bundle
- `installer/build-dmg.sh` — assembles the `.dmg` (`create-dmg` or `dmgbuild`)
- `build.py` gains `--os macos` flag; current OS is default
- Auto-updater learns to pick the right asset by extension (`.exe` on Windows, `.dmg` on macOS) — needs `info.asset_url` selection by platform
- Unsigned: friends right-click the `.app` → Open → "Open anyway" on first launch. Documented in ABOUT.md.
- GitHub Actions: add a `macos-latest` runner that runs `python build.py --os macos` on every push, uploads the `.dmg` as an artifact

**Mac testing:** smoke test on a real Mac before each public release. CI handles the build; the human-validation step requires actual hardware.

**Not in this release:** code signing or notarization. $99/year Apple Developer Program + the notarization workflow can be added later if friend feedback says the Gatekeeper warning is too rough.

### v0.7.1 — LAN web server (phone pipeline view)  · ~2-3 weeks

A tiny HTTP server inside JobHunt serves a mobile-friendly UI. Phone connects via Tailscale (or home WiFi) — no native app, no app store, no second codebase. Read + simple writes.

- New `jobhunt/web/` module:
  - `server.py` — `ThreadingHTTPServer` running on a `QThread` so it doesn't block Qt
  - `routes.py` — request dispatch
  - `templates/` — `.html` files using stdlib `string.Template` (no Jinja)
  - `static/` — single dark mobile-first CSS file matching the desktop palette
- Routes:
  - `POST /login` — accept password, set HTTP-only cookie
  - `GET /` — pipeline grouped by stage, mobile-styled
  - `GET /app/<id>` — application detail (stage, history, notes, attached docs as read-only summary)
  - `POST /app/<id>/stage` — change stage (drop-down on the detail page)
  - `POST /app/<id>/note` — append a note (text area on the detail page)
  - `GET /interviews` — upcoming list
  - `GET /search?q=` — quick text search across applications + companies
- Password auth: auto-generated at first server start, stored in `settings_kv`. HTTP-only cookie remembers the phone for 30 days. Regenerate-password button in Settings invalidates all cookies.
- Settings → new **Mobile View** tab:
  - Toggle: server on/off (default OFF; opt-in)
  - URL display: `http://<hostname>:8765/` + the Tailscale hostname if Tailscale is detected
  - Password display (hidden behind a "reveal" button) + regenerate button
  - "Open on this device" button (launches default browser pointed at `127.0.0.1:8765`)
- Bind to `0.0.0.0` so Tailscale picks it up; option to switch to `127.0.0.1` for the paranoid
- Audit log every login attempt and every write action

**Threats considered:**
- Tailscale isn't perfectly private — sharing screens, joint tailnets exist. Password defense-in-depth.
- Topic name in URL is fine because URLs aren't logged by the server itself.
- Mobile UI doesn't store secrets — just the auth cookie.

### v0.7.2 — Push notifications via ntfy.sh  · ~1 week

Phone gets pinged when interesting events happen. Uses ntfy.sh's free public server (or self-hosted, advanced option).

- New `jobhunt/notifications/` module:
  - `ntfy.py` — thin HTTP POST client to `ntfy.sh/<topic>`
  - `events.py` — central dispatch from existing event paths
- Event hooks:
  - Email classifier finishing on a non-`unrelated` message → "Recruiter email: <subject>"
  - Autonomous queue match above fit-threshold → "<Company>: <Role> — fit <score>"
  - Interview created/scheduled → "Interview at <Company> on <date>"
  - Future: offer detected, rejection detected, etc.
- Per-event toggles so users can mute the noisy ones
- New Settings → **Push** tab:
  - Topic name input + "Generate random" button (default empty = disabled)
  - QR code render of the ntfy.sh URL so the user scans it into the ntfy phone app
  - Per-event-type checkboxes
  - "Test push" button — sends a "JobHunt is connected" message
- Documentation: Tailscale setup + ntfy app install in ABOUT.md

---

## Beyond v0.7

### Reports page (Phase 6 holdover)
The biggest unbuilt feature from the original SPEC. Pipeline conversion funnels, applications/week time series, response rate by job board, **response rate by résumé version** (highest-signal data the user gets), average time-in-stage, API cost report, autonomous-apply outcomes. Custom report builder. Export to PDF/Excel/CSV. Easily 2-3 weeks of focused work; deferred until v0.7.x ships and we see what users actually want to measure.

### Theme presets
User picks from a set of pre-built color schemes ("Scarlet" [default], maybe a light mode, high-contrast, etc.) instead of editing the red shade directly. ~1 week. Low priority — most users won't care.

### "Ask Raven" support chatbot
In-app AI assistant that knows the JobHunt codebase + user's data. Helps with "how do I do X" or "summarize this listing for me" without leaving the app. Reuses the existing LLM provider. The Raven mascot finally earns its name. Unscoped — depends on what feels useful after a few months of real use.

### macOS code signing + notarization
$99/year Apple Developer Program + automation of the notarization workflow. Adds friction-free `.dmg` install on macOS. Cost-benefit depends on how many macOS friends end up using JobHunt.

### Windows code signing
~$300/year cert that kills the SmartScreen warning on Windows. Same calculus as macOS — depends on adoption.

### Background Windows service
Autonomous Apply currently runs only while the app is open. A future v2 could add a Windows service for 24/7 operation. Hard scope; risky; probably v1.0+ if ever.

---

## Decision log

Locked decisions from planning sessions, in case the rationale matters later:

- **Personal-tier, not SaaS.** JobHunt stays single-user single-machine. Multi-device sync explicitly via the v0.7.1 LAN web server, not via a hosted backend. The "all your data is local" privacy story is more valuable than the convenience of cloud sync.
- **Mobile = web view, not native app.** Lower complexity, no app store, single codebase, preserves privacy. Trade-off: works only when desktop is on and on the same network/tailnet.
- **Tailscale for "outside the home" access.** User installs Tailscale themselves; JobHunt just binds to `0.0.0.0`. Tailscale handles the encryption + identity.
- **ntfy.sh for push.** No iOS/Android push infrastructure of our own. Cost: $0. Trade-off: user must install the ntfy phone app.
- **Inno Setup AppId GUID + Windows AppUserModelID never change.** Brand rename in v0.6.3 ("Scarlet Raven" → "Scarlet Coder") didn't touch these because in-place upgrade detection depends on them being stable.
- **Unsigned binaries on both platforms in v0.7.0.** Code signing is real money that can wait until adoption justifies it.
