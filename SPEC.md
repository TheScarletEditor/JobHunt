# JobHunt — Product Specification v1

## Overview

JobHunt is a Windows desktop application for running an AI-augmented job search. It pulls activity from any IMAP email account, tracks applications through a customizable pipeline, generates tailored resumes and cover letters using AI, and can autonomously apply to jobs on trusted ATS platforms. Designed for the owner first, distributable to friends as a shareable installer.

---

## Platform & Distribution

- **OS:** Windows 10 / Windows 11 (x64 only)
- **Installer:** .exe setup installer (Inno Setup)
- **Auto-update:** checks a GitHub releases URL on launch; downloads and installs new versions in place
- **Bundled runtime:** Microsoft Edge WebView2 runtime ships with installer (~120MB)
- **Code signing:** none in v1 (Windows SmartScreen warning expected on first run). Can be added later by purchasing an EV or OV certificate and signing the installer at build time — no code changes required.

---

## Theme & Branding

- **Palette:** black background, red accent (recommended `#C8102E`), silver / light-gray secondary
- **Logo space:** 64×64 region top-left of main window, placeholder image until logo is supplied
- **Font:** Segoe UI (Windows native) or Inter
- **Style:** dark, high-contrast, modern; native Windows look-and-feel

---

## Tech Stack

| Layer | Choice | Reasoning |
|---|---|---|
| UI framework | PySide6 (Qt 6 for Python) | Native Windows look, mature widgets, excellent embedded browser support |
| Embedded browser | QWebEngineView (Chromium) | Wrapped equivalent of WebView2; same engine |
| Database | SQLite | Local, zero-config, file lives in `%APPDATA%\JobHunt\` |
| Credential storage | Windows DPAPI | Encrypts IMAP passwords and API keys at rest |
| Word parsing/export | `python-docx` | Best Python library for .docx |
| PDF parsing | `pdfplumber` + `pypdf` fallback | Best-effort text extraction |
| PDF generation | ReportLab | Professional output |
| Email | `imaplib` + `email` (stdlib) | IMAP is open standard, works with any provider |
| AI — Claude | `anthropic` SDK | Primary AI provider |
| AI — OpenAI | `openai` SDK | Fallback / alternative API key option |
| Browser automation | Playwright | For ATS form auto-fill and autonomous submit |
| Calendar export | `icalendar` | .ics file generation |
| Calendar sync | `caldav` | Two-way sync with Google / iCloud / FastMail |
| Installer | Inno Setup | Standard Windows installer toolkit |
| Auto-updater | Custom GitHub-release-poller | Checks releases API on launch |

---

## Core Features

### 1. Dashboard (Home Screen)

- **Logo placeholder** top-left (64×64)
- **Pipeline graphic** — at-a-glance funnel/kanban/bar visualization of application counts by stage
  - Default stages: Applied → Screening → Interview → Offer → Rejected/Withdrawn
  - User can rename, add, remove, reorder stages
  - User can choose graphic type (funnel, kanban-style columns, horizontal bar chart)
- **Stats strip:** applications this week / response rate / active in pipeline / next interview countdown
- **Recent activity feed:** last 10 events (emails parsed, applications submitted, stage changes, autonomous actions)
- **Autonomous-apply status panel:** ON/OFF toggle, today's count vs. cap, last 5 auto-applied jobs
- **Quick actions:** "Add application manually," "Open job board panel," "Run autonomous scan now"

### 2. Pipeline / Applications List

- Filterable, sortable table: company, role, stage, source, date applied, last activity, resume version used, fit score, autonomous (Y/N)
- Click row → application detail view: full email thread, attached resume + cover letter versions, interview notes, contacts
- Bulk operations: change stage, archive, export
- Search across companies, roles, notes

### 3. Resume Editor

- **Resume library:** unlimited *resume types* (e.g., "Engineering Resume," "Management Resume," "PM Resume"); each type retains last 5 versions automatically (older versions pruned)
- **Import:** paste text / open .docx / open .pdf — parsed into editable structured sections (header, summary, experience with bullets, skills, education, certifications, etc.)
- **Synonym list manager:** user-defined groups (e.g., React ↔ React.js ↔ ReactJS); AI suggests new groups by scanning the user's resume and historical job listings
- **Tailoring panel:**
  - Paste job listing (text or URL)
  - "Tailor for this job" button → AI rewrites bullets, applies synonym swaps, reorders bullets by relevance, flags missing skills
  - Side-by-side diff view: original ↔ tailored
  - Save as new version (auto-named "v3 for {Company - Role}")
- **Bullet reordering:** drag-and-drop manual + "sort by relevance" button (keyword-match scoring against active job listing)
- **Export:** .docx or .pdf, formatting preserved

### 4. Cover Letter Studio

- **Master story bank:** library of reusable paragraphs and anecdotes, tagged by theme (leadership, technical depth, cross-functional impact, etc.)
- **Generate for this job:** AI assembles a personalized draft from the story bank, tailored to the pasted/linked job listing
- **WYSIWYG editor** for refinement
- **Save per application;** export .docx or .pdf
- **Synonym list and keyword tailoring** applied here as well

### 5. Job Search Panel (Embedded Browser)

- **Customizable shortcut rail:** user-editable list of job boards in the left rail
- **Default set:** LinkedIn, Indeed, Glassdoor, ZipRecruiter, Monster, Dice, Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Jobvite, RemoteOK, We Work Remotely, Wellfound, BuiltIn, YC Work at a Startup, Hired, Otta
- **Embedded Chromium browser** loads the selected site
- **Floating copilot bar** reacts to page content:
  - On a job listing page → "Save to pipeline / Generate tailored resume / Draft cover letter / Apply (if ATS)"
  - On an ATS application form → "Auto-fill from profile / Upload tailored materials / Submit (if site is in Trusted ATS list)"
  - On LinkedIn / Indeed / blocked sites → "Pre-load tailored materials to clipboard for manual apply"

### 6. Autonomous Apply Console

- **Saved searches:** criteria-based (role keywords, location, salary range, remote flag, seniority, exclude-keywords)
- **Per saved search settings:**
  - Which job boards to scan
  - Scan schedule (default: hourly during business hours)
  - Minimum fit-score threshold (default 75%)
  - Daily application cap (default 15)
  - Execution mode: **Queue mode** or **Fire mode**
- **Queue mode:** matches above threshold are tailored, materials generated, surfaced in a review queue; user clicks "approve and apply" (per-item or bulk)
- **Fire mode:** matches above threshold get fully auto-applied if the target ATS is in the Trusted ATS list; otherwise fall through to Queue mode
- **Kill switch:** master pause toggle on dashboard halts all autonomous activity instantly
- **Audit log:** every autonomous action logged with timestamp, fit score, materials used, submission outcome, listing URL

### 7. Interview & Contact Tracking

- **Interview records** (linked to application): date/time, round type (phone screen, technical, system design, behavioral, onsite, final), interviewer list (name, title, LinkedIn), prep notes, post-interview debrief
- **Calendar integration:**
  - One-click .ics export for any interview (works with every calendar app including Outlook)
  - Optional CalDAV two-way sync for Google Calendar, iCloud, FastMail
  - *Outlook two-way sync is not supported* (Outlook does not speak CalDAV; would require Microsoft Graph — deferred)
- **Contacts:** tracked only for applications that have reached Interview stage or beyond
- Contact card: name, title, company, role in your application, last interaction date, freeform notes

### 8. Reports

- **On-screen dashboards** + **export to PDF / Excel / CSV**
- **Default reports:**
  - Pipeline conversion funnel (counts and percentages by stage)
  - Applications per week (time series)
  - Response rate by job board
  - Response rate by resume version (which version performs best)
  - Average time-in-stage
  - API cost report (spend over time, broken down by feature)
  - Autonomous-apply outcomes (applied / replied / interviewed)
- **Custom report builder:** pick columns, filters, date range, chart type, save as named custom report

### 9. Settings

- **Profile** — auto-fill data: legal name, preferred name, email, phone, address, LinkedIn URL, portfolio URL, GitHub URL, work auth status, citizenship, salary expectations, EEO answers (gender, race, veteran, disability — all optional with "decline to state")
- **IMAP accounts** — add/remove multiple accounts; per-account folder mapping for what to scan
- **API keys** — Claude key field, OpenAI key field. App uses whichever is provided; if both, Claude is preferred. If neither, falls back to rule-based mode.
- **Trusted ATS list** — which ATS platforms are allowed for autonomous "send it" submission
- **Pipeline stages** — add/remove/rename/reorder stages, set colors
- **Theme tweaks** — pick the exact red shade
- **Auto-updater** — opt-out, check frequency
- **Backup / restore** — export all data to JSON; import from JSON

---

## Data Model (High-Level)

- `applications` — id, company, role, source, date_applied, current_stage_id, fit_score, resume_version_id, cover_letter_id, listing_url, listing_text, autonomous_flag, notes
- `pipeline_stages` — id, name, order, color
- `resume_types` — id, name (e.g., "Engineering")
- `resume_versions` — id, resume_type_id, version_number, content_json (structured), source_format, created_at
- `cover_letters` — id, application_id, content, created_at
- `story_bank` — id, theme_tag, title, body
- `synonym_groups` — id, terms_json
- `imap_accounts` — id, server, username, encrypted_password, port, folder_filter
- `emails` — id, account_id, message_id, application_id (nullable), detected_stage, raw_body, received_at, processed_flag
- `interviews` — id, application_id, datetime, round_type, prep_notes, debrief
- `interview_attendees` — id, interview_id, name, title, linkedin_url
- `contacts` — id, application_id, name, title, company, last_interaction, notes
- `saved_searches` — id, name, criteria_json, schedule_cron, mode, threshold, daily_cap, enabled
- `audit_log` — id, action_type, timestamp, details_json
- `api_keys` — provider, encrypted_key
- `trusted_ats` — id, ats_name, enabled
- `profile` — single-row table for the user's auto-fill data
- `offers` — id, application_id, base, equity, bonus, benefits_json, deadline, notes

---

## Email → Pipeline Flow

1. Scheduled IMAP fetch (configurable interval, default 15 min)
2. New emails matched to existing applications by sender domain, subject keywords, and AI similarity check
3. AI (Haiku-tier model for cost) classifies each email: interview invite / rejection / offer / scheduling / follow-up needed / unrelated
4. Application stage auto-updated, audit log entry created
5. If interview detected → prompt the user to confirm details and create an Interview record + .ics file

---

## Autonomous Apply Flow

1. Saved search runs on schedule (or "Run now" button)
2. App scans eligible job boards via their public ATS APIs / structured pages: Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Jobvite, RemoteOK, We Work Remotely, Wellfound, BuiltIn, YC Work at a Startup
3. For each new listing not already in the pipeline: AI scores fit (0–100) against the user's active resume in that type
4. If score ≥ threshold:
   - Generate tailored resume (Sonnet)
   - Generate cover letter (Sonnet)
   - Create application record with status "queued" or "applying"
5. **Fire mode + Trusted ATS:** Playwright opens the ATS form in a headless browser context, fills from profile, uploads materials, submits. Updates application to "applied," logs full audit entry.
6. **Queue mode (or Fire mode + untrusted ATS):** application surfaces in the review queue. User reviews and clicks "approve and apply" (which then runs the same Playwright flow) or "skip."
7. Daily cap enforced; kill switch checked before each action.

---

## Build Phases

| Phase | Weeks | Deliverables |
|---|---|---|
| 1. Foundation | 1–2 | Project skeleton, Qt theme, dashboard shell, SQLite schema, settings, profile, DPAPI credential storage, manual application entry, pipeline graphic (default funnel) |
| 2. Documents | 2–4 | Resume parsing (Word/PDF/paste), resume editor, version management (5-version retention), synonym manager, AI tailoring, story bank, cover letter studio, Word/PDF export |
| 3. Email | 4–5 | IMAP multi-account, email fetching, AI stage classification, auto-update pipeline + audit log |
| 4. Browser Copilot | 5–7 | Embedded browser, customizable shortcut rail, page-aware copilot bar, ATS form auto-fill for trusted sites, clipboard prefill for LinkedIn/Indeed |
| 5. Autonomous | 7–9 | Saved searches, job board scanners, fit-score scoring, Queue mode, Fire mode, audit log, kill switch, Playwright submit flows for top 6 ATS platforms |
| 6. Polish | 9–10 | Interviews, contacts, calendar (.ics + CalDAV), reports + export, installer, auto-updater, backup/restore, onboarding wizard |

**Total estimate: 9–10 weeks of focused build time to a stable v1.**

---

## Known Constraints & Limitations

- **LinkedIn, Indeed, Glassdoor are not in autonomous scanning** (anti-bot protections, ToS, account-ban risk). They work fine in the embedded browser for manual browsing, and the copilot pre-loads tailored materials to clipboard for manual apply.
- **Resume parsing of complex PDFs** (multi-column layouts, tables, graphics, fancy fonts) will sometimes produce messy text that needs manual cleanup in the editor. Plain-text-heavy resumes parse cleanly.
- **Outlook calendar two-way sync is not supported** — only .ics export works for Outlook users. Google / iCloud / FastMail support full CalDAV two-way sync.
- **Code signing is not present in v1** — friends will see a Windows SmartScreen warning ("Windows protected your PC") on first install and need to click "More info" → "Run anyway." Can be added later by purchasing a cert.
- **API key required for full feature set.** Rule-based fallback mode is available but materially less capable: no AI resume rewriting (just keyword swap), no AI cover letter generation (just template fill), no AI email classification (just keyword rules), no AI fit scoring.
- **ATS auto-submit scripts require maintenance.** Each ATS platform (Greenhouse, Lever, Ashby, Workable, etc.) has different form structures. When they update their UI, the corresponding Playwright script may break and need a fix. Expect occasional maintenance.
- **API cost reality for autonomous power-user mode:** $40–100/month is realistic at full tilt (hundreds of listings scanned, ~15–20 tailored applications/day).
- **Autonomous applying runs only while the app is running** in v1. Closing the app pauses scans and submissions. A future v2 could add a background Windows service for 24/7 operation.

---

## Open Items

| Item | Default I'll use unless you say otherwise |
|---|---|
| Logo asset | Placeholder box; you supply when ready |
| Exact red shade | `#C8102E` |
| Default scan schedule | Hourly 8am–8pm local time, off overnight |
| Background operation | App must be running (no Windows service in v1) |
| GitHub releases hosting | I'll use placeholder URL; you set up the repo and update config |
| API provider preference order | Claude first, OpenAI fallback if Claude key missing |
| Default fit-score threshold | 75 |
| Default daily cap | 15 |

---

## What "Done" Looks Like for v1

A friend downloads the installer, accepts the SmartScreen warning, runs through a five-minute onboarding wizard (IMAP setup, profile, API key, import existing resume), and within ten minutes is browsing LinkedIn through the embedded panel, generating a tailored resume from a job listing, and watching the pipeline update as emails arrive. By the next morning, they wake up to a review queue of overnight matches from Greenhouse and Lever, generated with their resume and cover letter, ready to send with one click.
