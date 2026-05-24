# JobHunt — Bug & Fix Log

Running log of bugs hit during development and how each was fixed. Newest
entries at the top of each section. Use this as a debugging cheat-sheet — most
"weird Qt behavior" you see has already been hit and fixed once.

---

## Common pitfalls in this codebase

A few patterns that have bitten more than once. Check these first before going
deep on any new "weird" symptom:

| Symptom | Likely cause |
|---|---|
| Black bars / strips painted *inside* a card | A bare `QWidget` was added as a spacer. The global `QWidget { background-color: COLOR_BG }` rule paints it darker than the card. **Use `layout.addSpacing(px)` or `QSpacerItem` instead** — they're layout items, not paintable widgets. |
| Label text rendering as tiny dots / not visible | The label's `setStyleSheet("color: ...")` was set with property-only rules (no `QLabel { ... }` selector). The global `QWidget { color: COLOR_TEXT }` rule wins on specificity. **Wrap in selector form: `setStyleSheet("QLabel { color: #cfcfcf; }")`** or use `setObjectName("FormLabel")` + the theme's QSS rule. |
| Form rows overlap each other | Two or more `QFormLayout` instances stacked in one `QVBoxLayout`. Each form computes its own column widths and they collide. **Use one form per card**, or switch to a single-column `QVBoxLayout` of label-above-field rows. |
| Field labels stack tight while fields spread out (two-column drift) | `QGridLayout` doesn't guarantee row alignment when widget heights differ. **Use single-column label-above-field layout instead** — no second column to drift against. |
| `TypeError: runJavaScript called with wrong argument types` | PySide6 ≥ 6.6 changed the 2-arg form to `(script, worldId)`. **Use 3 args: `runJavaScript(js, 0, callback)`** with world 0 for the main world. |
| `sqlite3.ProgrammingError: type 'XxxPage' is not supported` | A widget object got passed as a SQL parameter. Usually a constructor was called positionally where the first param expects an int/str. **Search for `XxxDialog(self)` calls and verify the dialog's signature** — pass `parent=self` explicitly if it's ambiguous. |
| `ProgrammingError: SQLite objects created in a thread can only be used in that same thread` | The DB connection was created on the main thread but used from a worker. **Already fixed globally** via `check_same_thread=False` + `threading.RLock` in `db/manager.py`. |
| `Client.__init__() got an unexpected keyword argument 'proxies'` | Anthropic / OpenAI SDK pinned to an old version that's incompatible with `httpx >= 0.28`. **Bump SDK pins** to `anthropic>=0.40` and `openai>=1.55`. |
| Microsoft OAuth: `AADSTS50020` or `invalid_request redirect_uri` | Personal MSA accounts don't support every flow. **Use auth-code + PKCE + loopback redirect** (already wired in `mail/oauth_microsoft.py`). |
| Outlook calendar push fails with 401/403 | Existing token only has `Mail.Read` scope. **Click Settings → Calendar → "Re-authorize Microsoft"** to grant `Calendars.ReadWrite`. |

---

## UI / Qt

### Multi-checkbox container overflowing its layout slot
**Symptom:** `QFrame` containing 7 checkboxes rendered with the checkboxes overlapping subsequent rows (group headers, fields below the frame).
**Root cause:** `QSizePolicy.Expanding` (or `MinimumExpanding`) on the container makes the layout uncertain about how much space to allocate. Even with `setMinimumHeight(220)`, the layout sometimes assigns less and the children paint outside the allocated rect.
**Fix:** `setFixedHeight(N)` + `QSizePolicy.Preferred, Fixed`. The parent layout gets an exact, unambiguous size and positions every sibling correctly. Add `addStretch(1)` inside the container to absorb any unused pixels if the fixed height is larger than the children's natural total.
**Rule of thumb:** For multi-widget containers nested in a `QVBoxLayout`, **prefer fixed height over expanding**. The layout's row-positioning math is more reliable with concrete numbers.

### Labels invisible when only objectName is set (no inline stylesheet)
**Symptom:** Even with `setObjectName("FormLabel")` + theme QSS for that selector, real-app rendering showed Demographics labels as completely invisible — widget had height, just no painted text.
**Root cause:** Unclear (Qt rendering pipeline quirk specific to certain widget trees). The same `_styled_label("text")` helper works in the Profile tab. The difference might be related to QVBoxLayout vs QFormLayout context, parent QFrame shadows, or QSS rule timing.
**Fix:** Belt-and-suspenders: set BOTH `objectName` AND an inline stylesheet with the same color/padding rules. Use multi-selector form `QLabel#FormLabel, QLabel { ... }` so either matching path applies. Also explicitly call `setMinimumHeight()` so the widget reserves space regardless of which path takes effect.
**Rule of thumb:** **For mission-critical labels that MUST render, set objectName, inline stylesheet, AND minimumHeight all three.** Don't trust any single approach.

### Labels render at near-zero height despite QFont set
**Symptom:** After removing `setMinimumHeight` from labels, real-app rendering showed labels as ~1-2px slivers (tiny dashes / dots) even though headless tests showed correct 14px+ heights.
**Root cause:** Inline `setStyleSheet("QLabel { color: ...; }")` combined with `setSizePolicy(Fixed)` doesn't reliably allocate the label its sizeHint in the real Windows rendering pipeline — the layout sometimes squeezes the widget below its text height. Offscreen platform doesn't reproduce this.
**Fix:** Use `objectName()` + theme QSS (the path the Profile tab has always used). The theme rule has explicit `padding: 8px 4px 0 0` which forces a real height. Added a `QLabel#GroupHeader` rule to `theme.py` for the red group headers; field labels use the existing `QLabel#FormLabel` via `_styled_label()`.
**Rule of thumb:** **Always use theme-QSS via `objectName()` for non-trivial label styling**, never inline `setStyleSheet`. The theme stylesheet is the only path that reliably renders the same way on Windows as in offscreen tests.

### Demographics labels overlapping fields in real rendering (but not headless)
**Symptom:** After switching to single-column `label-above-field`, real-app rendering showed each label and field painted at the same y, glyphs superimposed. Headless smoke tests reported them at different y as expected.
**Root cause:** Combination of `setStyleSheet("padding: 0; margin: 0;")` + explicit `setMinimumHeight(56)` + `card_layout.setSpacing(0)` + `setContentsMargins(0, 6, 0, 0)` on labels. The QSS box-model overrides interact unpredictably with QVBoxLayout's geometry pass; offscreen platform doesn't trigger the bug.
**Fix:** Stopped overriding label sizing. `_make_label` now sets only color + font + `QSizePolicy.Fixed` vertical. Layout uses natural `setSpacing(8)` + explicit `addSpacing(12)` before each label + `addSpacing(24)` before each group. Each label takes its sizeHint (~14px), each field takes its natural height (~43px), gaps come from layout spacing — no box-model fighting.
**Rule of thumb:** Don't combine `setMinimumHeight`, `setContentsMargins`, `setStyleSheet("padding/margin")`, AND a zero-spacing parent layout on the same widget. Pick one source of spacing and trust it.

### Demographics tab — column drift in QGridLayout
**Symptom:** Left column labels packed tight while right column fields had natural input spacing — rows of label/field pairs visibly out of sync down the page.
**Root cause:** `QGridLayout` row height = `max(widgets in row)` but with `Preferred` size policies on QLabel, the labels were shrinking below their min-height, while fields kept their full ~43px input height. The grid couldn't synchronize them.
**Fix:** Abandoned two-column grid. Switched to single-column label-above-field layout in `_DemographicsTab` — no second column means no drift to manage. Generous `addSpacing(24)` between rows.

### Black-bar strip artifacts inside Demographics card
**Symptom:** Whole rows rendered as solid black bars covering the labels and fields.
**Root cause:** `_field_row` wrapped each row in a fresh `QWidget()`. Global QSS rule `QWidget { background-color: COLOR_BG }` paints every plain QWidget at `#080808`, *darker* than the card's `COLOR_BG_RAISED = #141414`. The wrappers showed as dark strips on top of the card.
**Fix:** Stopped using wrapper QWidgets. Added labels + fields directly to the card's `QVBoxLayout`. For gaps, use `addSpacing(px)` (layout item, not painted) instead of `QWidget` spacers.

### Demographics labels rendering as tiny dots / not visible
**Symptom:** Field labels showed as ~2-pixel-tall ghost text, just descender slivers.
**Root cause:** The theme's `QLabel#FormLabel { padding: 8px 4px 0 0 }` combined with the layout's tight vertical spacing was clipping the label rendering box. Plus `setStyleSheet("color: ...; font-size: ...;")` (property-only, no selector) was losing the cascade fight against `QWidget { color: COLOR_TEXT }`.
**Fix:** Two-pronged. (1) Set color via wrapped selector: `setStyleSheet("QLabel { color: #cfcfcf; }")` — higher specificity. (2) Set `minimumHeight` explicitly so the row has space for the text. Used `_make_label` helper with QFont + selector-form stylesheet.

### Saved-search dialog overflowing the screen
**Symptom:** Save button was below the visible window on shorter displays; dialog had no scrollbar.
**Root cause:** The form body was added directly to the dialog's `QVBoxLayout` with no scroll area. Dialog had `setMinimumWidth(640)` but no maximum height.
**Fix:** Wrapped the form body in a `QScrollArea` (widget-resizable, horizontal scroll off). Title row + buttons stay outside the scroll. Dialog sizes to `min(820×880, 85% of screen)`.

### Resume editor — bullets cut off
**Symptom:** Multi-line résumé bullets truncated; only the first line visible.
**Root cause:** Used `QLineEdit` for bullet rows — single-line widget. Fusion style added its own frame regardless of QSS.
**Fix:** Switched to `QPlainTextEdit` with `WidgetWidth` line wrap, scrollbars off, auto-resize wired via `documentLayout().documentSizeChanged`. Each row auto-grows to fit content.

### Pipeline-stages table-as-form was unwieldy
**Symptom:** Editing stage names via a `QTableWidget` cell felt clunky; the color picker was a `QColorDialog` modal.
**Root cause:** Tables are for display, not editing. Color pickers without presets force the user to dial RGB by hand.
**Fix:** Replaced with vertical list of `_StageRow` cards (color swatch button + full-width name input + ↑/↓/×). Color swatch opens a small popup with **10 preset colors** + a "Custom color wheel" button that opens the full `QColorDialog` as a fallback.

### Synonym Groups / Resume Types tables — same issue
**Symptom:** Editing inline in a QTableWidget cell was awkward; per-row actions buried in toolbars.
**Fix:** Rebuilt both as vertical `_GroupRow` / `_TypeRow` cards with inline edit fields, per-row buttons, and a "Save" action at the bottom for batched changes.

### Pronouns combo defaulted to "Prefer not to say" with no custom option
**Symptom:** Editable combo populated with placeholder pronouns; no way to enter custom pronouns cleanly.
**Fix:** Switched to a fixed dropdown with 8 preset options + a final "Custom…" item. Picking Custom pops a `QInputDialog` for the user's pronouns; the entered value gets inserted into the list above "Custom…" and selected.

### `_on_autofill_files_done` duplicated
**Symptom:** Two definitions of the same method on `BrowserPage`. Python silently keeps the second; first is dead code.
**Fix:** Removed the original. Left a comment pointing at the live definition further down (inside the Fire-mode block, where it also triggers `_fire_click_submit`).

### `_kind_user_set` flag — silent kind-conversion on title typing
**Symptom:** Typing "Skills" into a section title triggered the section to auto-convert its items into the LIST kind mid-keystroke — destroying in-progress data.
**Fix:** Removed the auto-detect-on-title-changed code path. Section kind is now detected on `load()` only and changes via the explicit dropdown.

---

## OAuth + Microsoft Graph

### `runJavaScript` signature changed in PySide6 ≥ 6.6
**Symptom:** `TypeError: runJavaScript called with wrong argument types: (str, method)` when clicking Auto-fill on an ATS page.
**Root cause:** PySide6 ≥ 6.6 reinterpreted the 2-arg form as `(script, worldId)` instead of `(script, callback)`.
**Fix:** Pass `0` as the worldId before the callback: `runJavaScript(js, 0, callback)`.

### Microsoft IMAP basic auth dead for personal accounts
**Symptom:** `AUTHENTICATE failed.` from outlook.office365.com despite correct app password.
**Root cause:** Microsoft retired basic IMAP for personal/MSA accounts.
**Fix:** Replaced IMAP entirely with **Microsoft Graph** `/me/mailFolders/Inbox/messages`. Auth is auth-code + PKCE + loopback redirect; scope is `Mail.Read offline_access`.

### `AADSTS50020 — User account from identity provider does not exist in tenant`
**Symptom:** Microsoft sign-in errored with this code despite valid personal credentials.
**Root cause:** Tried to use the device-code flow with a multi-tenant client_id, which Microsoft tied to a specific tenant.
**Fix:** Switched the entire flow to auth-code + PKCE with `/common` endpoint and `redirect_uri = http://localhost:{port}` (loopback). Works for both work and personal accounts.

### `invalid_request — redirect_uri is not valid`
**Symptom:** Token exchange step returned this error despite the redirect_uri working for the initial auth request.
**Root cause:** Spec requires the *same* redirect_uri on both the `/authorize` and `/token` calls, character-for-character. We were stripping `/auth` from the path on token exchange.
**Fix:** Use the bare `http://localhost:{port}` (no path) on **both** calls.

### Outlook calendar push returns 401/403
**Symptom:** Existing users hit "InvalidAuthenticationToken" or "InsufficientPermissions" when calling `/me/events`.
**Root cause:** Their stored OAuth tokens were issued before `Calendars.ReadWrite` was added to the scope. Refreshing the access token doesn't get new scopes — the user has to re-grant consent.
**Fix:** In `interviews/outlook.py`'s `_raise_for_graph`, detect 401/403 with permission/scope keywords and replace the message with: *"Microsoft hasn't authorized JobHunt to write to your calendar yet. Open Settings → Calendar and click 'Re-authorize Microsoft'..."* The Calendar tab has a `Re-authorize Microsoft` button that runs the sign-in dialog again and overwrites the stored tokens.

---

## DB / SQLite

### `ProgrammingError: SQLite objects created in a thread can only be used in that same thread`
**Symptom:** Background workers (mail scanner, AI suggestion worker, etc.) crashed with this when querying the DB.
**Root cause:** `sqlite3.connect()` defaults to `check_same_thread=True`. Background threads got the same `_conn` instance and tripped the safety check.
**Fix:** In `db/manager.py`, open the connection with `check_same_thread=False` and wrap every `cursor()` use in `with self._lock:` (a `threading.RLock`). Single-writer at a time, but cross-thread reads now work.

### `Error binding parameter 1: type 'PipelinePage' is not supported`
**Symptom:** Clicking `+ Add application` from the Pipeline page crashed with the above when the dialog tried to `SELECT ... WHERE id = ?`.
**Root cause:** Pipeline called `AddApplicationDialog(self)` (positional). The dialog's signature is `__init__(self, application_id=None, parent=None)`, so `application_id = <PipelinePage instance>`. The "is_edit" branch ran SQL with that as a param.
**Fix:** Changed callers to `AddApplicationDialog(parent=self)`. Same fix on Dashboard.

### Trusted ATS list cleared on every startup
**Symptom:** User-added ATS shortcuts disappeared after relaunch.
**Root cause:** Schema-seeded ATS aggregator entries used non-functional URLs (e.g., `boards.greenhouse.io` — there's no aggregator page, just per-company subdomains). Old installs had these in their DB.
**Fix:** `_migrate()` now `DELETE`s those known-bad seed rows on startup. New installs never get them.

---

## LLM / API clients

### `Client.__init__() got an unexpected keyword argument 'proxies'`
**Symptom:** AI sidebar errored on first call; nothing in JobHunt could reach Claude or OpenAI.
**Root cause:** `httpx 0.28` removed the `proxies` kwarg, but `anthropic==0.39.0` / `openai==1.54.4` still passed it.
**Fix:** Bumped pins to `anthropic>=0.40` and `openai>=1.55`. The newer SDKs use `proxy` (singular) or skip it entirely on httpx 0.28+.

### `Unknown provider: adzuna_app_id` when saving Adzuna keys
**Symptom:** Clicking Save in Settings → API Keys threw `ValueError`.
**Root cause:** `llm/keys.py` had a hard-coded `PROVIDERS = ("claude", "openai")` allowlist. Adzuna credentials use the same encrypted store but tripped the validation.
**Fix:** Added `EXTRA_PROVIDERS = ("adzuna_app_id", "adzuna_app_key", "google_calendar_access_token", "google_calendar_refresh_token")`; `store_key` now accepts both lists.

### Resume parser putting email/phone/links in the summary field
**Symptom:** After importing a `.docx` resume, the parser would stash contact lines into the `summary` field instead of the `contact` array.
**Root cause:** The LLM didn't reliably separate the contact-block from the summary paragraph when they sat adjacent in the source.
**Fix:** Two-layer defense. (1) Tightened `SYSTEM_PARSE_RESUME` prompt with explicit "CONTACT vs SUMMARY — STRICT SEPARATION" rules. (2) Post-process: `_scrub_contact_from_summary()` extracts email/phone/URL/location patterns out of `summary` and into `contact` after parsing.

### Resume parser creating a "Summary" section instead of using the top-level summary field
**Symptom:** Imported resumes had a duplicate Summary section in the sections array AND nothing in the top-level `summary` string.
**Fix:** Added explicit prompt rule banning a "Summary" section. Post-process: `_merge_summary_sections()` hoists any Summary-titled section's content into the top-level `summary` and drops the section.

### Signal arity: `content_changed() only accepts 0 argument(s), 1 given!`
**Symptom:** Crashed on any text change in the resume editor.
**Root cause:** `QLineEdit.textChanged` emits a `str` arg, but `content_changed` was declared as `Signal()` (no args). Direct connection passed the arg into a 0-arg signal.
**Fix:** Wrapped the connection: `self.header.textChanged.connect(lambda _t: self.content_changed.emit())`. Five sites fixed.

---

## Dialogs & state

### Dialog cancel crashed when a background worker was running
**Symptom:** Closing a dialog while a worker QThread was active produced a crash from a late `done.emit(...)` reaching a destroyed slot.
**Fix:** Added `_cleanup_worker()` to each dialog that (1) disconnects the worker's signals FIRST, then (2) cancels the worker, then (3) waits up to 2s for the thread to quit. `reject()` and `closeEvent()` both call it.

### IMAP autoscan crashing JobHunt on add-account-fail
**Symptom:** Adding an IMAP account that failed sign-in crashed the whole app instead of just the dialog.
**Fix:** Same `_cleanup_worker` pattern. The OAuth worker's failure signal now reaches the dialog cleanly, the dialog displays the error, and the app stays up.

---

## Adding entries

When you hit a new bug, append to the right section with:

```
### Short title
**Symptom:** What you observed.
**Root cause:** What was actually happening.
**Fix:** What was changed to make it work.
```

Keep titles searchable — the exception class + a key word from the message is usually enough.
