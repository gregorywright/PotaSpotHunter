## [Unreleased]
### Added
- **Log4OM backend (beta, Windows only)** — frequency tuning and callsign lookup
  via UDP Remote Control Interface; worked callsign history (`×N` badges) via
  direct SQLite read of the Log4OM QSO database (same approach as JTAlert).
  Requires no extra Log4OM configuration beyond the default install — Remote
  Control is enabled by default.
- **Worked callsign indicator now supported on Log4OM** in addition to MacLoggerDX.
  Newly logged QSOs appear as worked within ~10 seconds without a manual refresh.
### Known limitations (Log4OM beta)
- Mode is not set when tuning — Log4OM's `SetMode` UDP command is non-functional
  in the current Log4OM release. Set mode manually or via your CAT interface.
- Park reference note is not pre-filled — Log4OM has no equivalent field.

## [1.11.1] - 2026-04-10
### Fixed
- Backend monitor thread now pings the active backend every 10 seconds and
  publishes a `backend_status` SSE event only on status change, preventing
  spurious disconnected/reconnected dialogs.
- MacLoggerDX `ping()` and `get_worked()` now guard against launching MLDX
  when it is not already running (via `_mldx_is_running()` System Events check).
- Selecting MacLoggerDX from the dropdown now immediately pings it and shows
  an error dialog if MLDX is not running (previously the ping was skipped).
### Added
- Backend disconnect/reconnect dialog — when the active rig backend goes
  offline, an amber blocking modal pauses auto-scan (saving dwell); on
  reconnect the modal auto-dismisses and auto-scan resumes at the saved rate.
  A "Continue without rig control" button switches to None without restarting
  scan.

## [1.11.0] - 2026-04-09
### Fixed
- `NoneBackend` added so selecting "None" rig backend correctly syncs with
  the proxy — previously the proxy silently fell back to rigctld.
- Undefined `_send_error()` replaced with `_json_response()` — previously
  caused a crash (AttributeError) on unknown POST paths or missing `www/` files.
- `PROXY_BASE` now derived from `window.location.origin` instead of hardcoded
  `http://localhost:8080` — changing `--port` no longer silently breaks all
  proxy API calls from the frontend.
- Worked-callsign tooltip no longer shows "Invalid Date" when MacLoggerDX
  returns a date string that `new Date()` cannot parse; falls back to raw string.
- Path traversal attack on `/themes/<name>.json` now blocked with a 403.
- SSE `EventSource` now stops retrying after 5 consecutive failures instead
  of reconnecting forever when the proxy is down.
- Python module docstring corrected: 3.6+ → 3.7+.
### Changed
- New-spot indicator (●) column moved to first position in the table for
  quicker visual scanning; column is compact (24px).
- Status bar now shows a live countdown ("Next refresh: M:SS") instead of
  a static "Auto-refresh: every N min" label.
- Even table rows get a subtle stripe via new `--row-stripe` CSS variable
  (theme-aware; transparent on dark themes, faint on light themes).
- Row divider color uses new `--row-border` CSS variable; all bundled themes
  updated with both new variables.
- Status line gains a left border that color-matches the current state
  (green/amber/red).
- Vertical divider added between the refresh controls and auto-scan pills.
- Park name truncation threshold raised 36 → 44 characters (max-width 240 → 300px).
- Location and recent-age columns use theme text color at reduced opacity
  instead of a fixed dim color, improving legibility across all themes.
- Disabled scan-pill opacity raised 0.35 → 0.70 for better legibility.
- `import inspect` moved to top-level (was inside the `/tune/` hot path).
- Duplicate `datetime` import inside `get_worked()` loop removed.
- `%-d` strftime directive replaced with an f-string for Windows portability.
### Documentation
- `CONTRIBUTING.md` updated to reference `www/` files instead of the legacy
  `PotaSpotHunter.html`.
- Release workflow comment block updated to match actual zip contents.
- `.claude/` and `.playwright-mcp/` added to `.gitignore`.

## [1.10.0] - 2026-04-08
### Added
- **Worked callsign indicator** — when MacLoggerDX backend is selected,
  each spot row shows a `×N` lifetime QSO count badge after the callsign,
  and a colored dot if worked today:
  - Amber ● — worked today, band/mode unknown (AppleScript source)
  - Red ● — worked today on matching band/mode (likely no points)
  Hover the callsign cell for full details. Data comes from two sources:
  AppleScript batch query (historical counts) and UDP log listener on
  port 9932 (real-time, adds band/mode). No lookups happen until the
  user explicitly selects the MacLoggerDX backend.
- **SSE push channel** — a persistent `GET /events` connection replaces
  all polling for worked-callsign data. Real-time QSO badges appear
  within ~1s of logging; AppleScript history results stream in as they
  arrive rather than waiting for a fixed delay. Only one browser tab
  may hold the connection — a second tab receives a blocking conflict
  overlay and all its timers are stopped (no residual load on the proxy
  or pota.app). The primary tab releases its slot immediately on close
  via `sendBeacon`; a 5s heartbeat catches any cases `sendBeacon`
  misses (browser crash, etc.).
### Changed
- Rig dropdown change now calls `GET /set_backend` to sync the proxy's
  active backend, starting/stopping the UDP log listener as needed.
- Minimum Python version raised from 3.6 to 3.7 (`ThreadingHTTPServer`
  is required for the SSE handler thread to coexist with other routes).

## [1.9.3] - 2026-04-04
### Changed
- Quick Start instructions now mention that Windows users can double-click
  `PotaProxy.py` in File Explorer after installing Python.

## [1.9.2] - 2026-04-04
### Fixed
- Startup no longer pings MacLoggerDX — fixes spurious "mldx unreachable"
  error on Windows and any system where MacLoggerDX is not installed.
  Rig backend availability is now only checked when the user selects one.

## [1.9.1] - 2026-04-01
### Fixed
- Map button colors now use CSS variables so they update correctly when
  switching themes.
### Changed
- Updated screenshots in README to show current UI including themes.

## [1.9.0] - 2026-04-01
### Added
- **Theme system** — 🎨 dropdown in the header lets users switch color
  themes. Built-in `green-terminal` theme hardcoded in the app; additional
  themes loaded from `themes/` directory at startup. Themes persist across
  sessions via localStorage. Ctrl+T cycles themes.
- Bundled themes: `delta-loop`, `firefly-browncoats`, `green-terminal-crt`, `locutus-of-borg`, `mr-clean`, `solarized-light`. Built-in default: `the-matrix`.
  `opentopomap`, `solarized-light`.
- `--map-filter` theme variable applies a CSS filter to map tiles — enables
  dark maps (`invert(1) hue-rotate(180deg)`), sepia tones, dimming, etc.
- `THEMES.md` — theme authoring guide with variable reference and examples.

## [1.8.0] - 2026-03-31
### Changed
- `PotaSpotHunter.html` split into `www/index.html`, `www/style.css`,
  and `www/app.js`. The proxy serves all three files directly — no build
  step required. `PotaSpotHunter.html` is retained in the repo root as
  a legacy reference. Release ZIP now contains `www/` instead of the
  single HTML file.

## [1.7.0] - 2026-03-31
### Added
- Rig backend dropdown moved from toolbar to header bar, alongside the
  awards badge and map button.
- Auto Scan pills disabled when rig backend is "None" — scanning without
  a rig does nothing useful. Pills re-enable when a backend is selected.
  Tooltip on the pill group explains why they are disabled.
- "Set callsign" award button renamed to "Track Awards".
### Changed
- Auto Scan no longer stops on any click — only stops when clicking a
  spot row or interacting with the scan pill control. Allows resizing the
  map, changing filters, and other UI interactions without interrupting
  a running scan.
- Map/table split minimum loosened from 25% to 5% — allows nearly
  full-screen map or nearly full-screen spot list.
### Fixed
- All remaining native browser `title=` tooltips replaced with custom
  styled tooltips (`data-tip=`).
- Location tooltip now shows spaces after commas (e.g. "US-OR, US-WA"
  instead of "US-OR,US-WA").
- Auto Scan pills now correctly disabled after a failed backend ping
  resets the dropdown to None.

## [1.6.1] - 2026-03-29
### Added
- **Custom tooltips** — replaced native browser `title=` tooltips with
  styled dark tooltips matching the app theme (amber border, amber-tinted
  background). 300ms delay, appear on hover, dismiss immediately on mouse
  leave or element change. Callsign and park ref links show the full URL
  in the tooltip. Award hint icons show descriptive text.
### Changed
- Proxy now serves `PotaSpotHunter.html` at `http://localhost:{port}/`
  instead of opening it as a `file://` URL. This gives the page a real
  HTTP origin, which the browser sends as the Referer header on OSM tile
  requests — fixing intermittent 403r errors when zooming the map.
### Fixed
- Wilderness Area park type now correctly classified as `national_wildlife`
  (🦅) instead of ❓.
- Park type classifier expanded to cover more API variants: State Trail 🥾,
  State Beach 🏖, BLM land 🪨, World Heritage Site → historic 🪧, and
  additional state/federal subtypes seen in live spot data.

## [1.6.0] - 2026-03-28
### Added
- **Park type column** — a new "Type" column between Park Ref and Park Name
  shows an emoji indicating the park type, fetched in the background from
  `api.pota.app/park/<ref>` after each spot refresh. ⏳ shown while
  fetching, then the resolved emoji (or ❓ for unrecognised types). Clicking
  the column header sorts by park type in a meaningful order (federal →
  state → other). A 200ms debounced render fires as data arrives so icons
  appear dynamically without waiting for the next auto-refresh.

  Park type emoji: 🏛 National Park · 🌲 National Forest · 🗿 Monument ·
  🦅 National Wildlife · 🪨 BLM/Other Federal · 🏕 State Park · 🌳 State
  Forest · 🥾 State Trail · 🏖 State Beach · 🎯 Recreation · 🦌 Wildlife
  Mgmt · 🌿 Nature Reserve · 🌾 Wetland · 🪧 Historic · ❓ Unknown
### Changed
- Release notes now include a Quick Start section at the top so users
  see setup instructions directly on the GitHub release page.

## [1.5.1] - 2026-03-28
### Added
- Unit test suite for `PotaProxy.py` backends using pytest (`python3 build.py test`).
  Tests cover MacLoggerDX note sanitization (ASCII stripping, quote removal,
  empty note handling) and rigctld command format (split-off command, frequency,
  mode mapping). No radio software required to run tests.
- `CONTRIBUTING.md` with setup and test instructions for new contributors.
- `requirements-dev.txt` listing pytest as the only dev dependency.
- `build.py` developer utility — currently supports `python3 build.py test`.

### Fixed
- Auto-refresh interval dropdown had no change event listener — the timer
  always ran at the startup default of 2 minutes regardless of selection.
- MacLoggerDX crashed with osascript error -2741 on spots whose park name
  contained non-ASCII characters (Cyrillic, Chinese, etc.) or embedded
  double-quotes. The proxy now strips both before building the AppleScript.


## [1.5.0] - 2026-03-27
### Added
- **Award tracking badge** — a 🏆 button in the header lets hunters enter
  their callsign (stored in localStorage). Once set, the badge shows the
  hunter's current award tier (e.g. "🏆 W7GFW · Arizona Agave"). Clicking
  the badge opens a popover showing current tier, parks count, progress bar
  toward the next tier, and band/mode endorsements earned on the current tier.
  Callsign can be cleared by saving an empty value.
- **Time-based award hint icons** on spot rows — small emoji icons appear
  next to the park reference when a spot qualifies for an active award
  opportunity: 🌙 Late Shift, 🌅 Early Shift, 🎆 New Years week (Jan 1–7),
  🎪 Support Your Parks event weekend. Shift windows are calculated from
  the park's longitude per the POTA award rules. Icons update immediately
  when the hunter callsign is set or cleared.
- **Endorsement hint icon** (✨) on spot rows — shown when the hunter's
  callsign is set and the spot's band is not yet in the hunter's endorsements
  for their current award tier. Indicates a potential new endorsement
  opportunity. Requires callsign to be set.
### Documentation
- Updated screenshots and demo GIF to reflect current UI.

## [1.4.0] - 2026-03-22
### Changed
- "Other" mode filter renamed to "Other Digital" and now excludes FT8 and FT4,
  making all five mode filter options mutually exclusive.
- Removed pulsing/throbbing animation from the age column. The green colour
  coding already communicates freshness without the visual distraction.

### Fixed
- Split mode is now explicitly turned off on every tune command for all rig
  backends (flrig, rigctld, MacLoggerDX). Previously, if the radio was left
  in split mode, clicking a spot would tune the frequency but leave split
  active, causing the radio to transmit on the wrong frequency.

### Internal
- Code cleanup: removed dead `freshCls` variable, stale tombstone comments,
  unused `data-new` DOM attribute, and duplicate comment in `autoScanStep()`.
- Replaced `_isNew` mutation on API spot objects with a `newSpotIds` Set
  looked up at render time, avoiding mutation of objects we don't own.

## [1.3.0] - 2025-03-20
### Added
- **Auto-scan resume** — interrupting a scan (any click or keypress) and
  restarting it now resumes from the spot where it was paused, rather than
  always restarting from the top of the list. Clicking any row while not
  scanning sets that row as the resume point. If the resume spot has
  expired from the list, the scan restarts from index 0.
- **Unified active-spot model** — a new `activeSpotId` state variable and
  `setActiveSpot()` function serve as the single source of truth for which
  spot is "active". This drives the amber bar, map marker selection, and
  auto-scan resume point consistently. Previously these were three separate
  tracking mechanisms (`selectedMarkerId`, `.scanning` class management, and
  `autoScanIndex`) that could get out of sync.
- **"New" column** — a sortable column showing a green dot (●) next to spots
  that appeared in the most recent refresh and haven't been seen before in
  this session. Uses the POTA QSO uniqueness key (callsign + band + mode +
  park ref + UTC date) so that re-spots of the same activation are not
  flagged as new — only genuinely new scoring opportunities are marked.
  The indicator clears automatically on the next refresh cycle.

### Changed
- **Amber bar is now solid when not scanning** — the left-edge amber bar
  persists on the last active spot after a scan stops or the user clicks a
  row, giving a clear visual indication of the auto-scan resume point. The
  bar only pulses while auto-scan is actively running; it is solid at rest.
- **Active spot green background** — the active spot row now shows a green
  background, repurposed from the removed tuned-row highlight. Combined with
  the amber bar it clearly marks the currently selected spot. During
  auto-scan both the green background and the amber bar pulse in sync at
  the same 1.4s timing.
- `sortCol` and `sortDir` reintroduced as the primary sort state, now driven
  by column header clicks rather than the removed dropdown (the 1.2.0
  release notes describe these as unused and removed; they are now
  meaningfully used).
- **Amber bar now survives sort and filter changes** — `render()` restores
  the `.scanning` class on the active row after every rebuild, so changing
  the sort column, sort direction, band filter, or mode filter no longer
  loses the amber bar.
- **Location column** — multi-region locations (e.g. "JP-HB, JP-OS, JP-CH")
  are now displayed compactly as "JP-HB, +2". The full location string is
  still shown on hover via the title attribute.
- **"Spotted (UTC)" and "Age" columns merged into "Last Heard"** — shows the
  relative age (e.g. "4m") with colour coding, with the absolute UTC time
  available on hover. Matches the "Last Heard" terminology used on pota.app.
- **Column header sorting replaces sort dropdown** — all data columns are
  now sortable by clicking the column header. Clicking the same header again
  reverses the sort direction. The active sort column shows ▲ or ▼ in green.
  The Sort dropdown has been removed from the toolbar.
- **Default sort changed to frequency ascending** — spots are now sorted
  lowest frequency first on load, so operators can tune up through the band.
  Time-based sorts default to newest-first when clicking the Last Heard header.
- **GitHub Actions workflow** — updated `actions/checkout` from `v4` to `v6`
  to resolve Node.js 20 deprecation warning (Node.js 24 becomes the default
  on GitHub Actions runners in June 2026).

### Removed
- `selectedMarkerId` state variable — replaced by `activeSpotId`
- `highlightTableRow()` function — replaced by `setActiveSpot()`
- `tr.map-selected` CSS rule — the amber `.scanning` bar now serves as the
  unified active-spot indicator for both scanning and manual row selection
- Sort dropdown from toolbar — replaced by column header clicks
- **Tune column and tuned-spot tracking** — the "Tune" button column,
  `tunedIds` Set, `tr.tuned` CSS, and "Clear Tuned" button have all been
  removed. Tracking which stations have been worked is a logging concern
  handled by MacLoggerDX and similar software, not a spot-browser concern.
  Clicking any row now tunes the radio directly; no separate button is needed.
- `autoScanStep()` tunedIds save/restore — no longer needed now that
  tuned tracking is removed; the function is simplified accordingly.

## [1.2.0] - 2025-03-18
### Fixed
- Tuned/highlighted rows now survive a spot list refresh. Previously, when an
  activator was re-spotted by another operator (generating a new spotId), the
  highlight was lost on the next refresh. The fix replaces the spotId-based
  tracking with a composite key: callsign + band + normalised mode + park
  reference + UTC date — matching the POTA rules definition of a unique QSO.
  USB and LSB are both treated as SSB; frequency changes within the same band
  are ignored, since POTA awards credit per band, not per frequency.

### Added
- **Auto Scan** — a segmented pill control (Off / 5s / 10s / 30s / 1m) that
  automatically cycles through the visible spot list, dwelling on each spot for
  the selected interval and tuning the radio as if the user clicked the row.
  Designed for scanning the bands when propagation is uncertain. Any mouse
  click or keypress stops the scan. Clicking the active pill a second time also
  stops it. Changing the dwell time mid-scan keeps scanning at the new rate.
  Auto-scan does NOT mark spots as tuned — only deliberate user clicks do.
- **Scan highlight** — the currently active auto-scan row shows an amber
  pulsing left-edge bar (inset box-shadow, zero layout impact) that is visible
  even on already-tuned (solid green) rows.
- **Scroll-to-top on scan start** — the spot table scrolls to the top when
  auto-scan begins; subsequent steps keep the active row in view automatically.
- **Version display** — the app version is now shown in the header next to
  the logo (e.g. "POTA ► SPOT HUNTER  v1.2.0"). The proxy reads the version
  from the new `VERSION` file at startup and serves it via a `/version`
  endpoint; the page fetches it on load so the version number is never
  hardcoded in two places.
- **`VERSION` file** — single source of truth for the version number, used
  by the proxy at startup, displayed in the page header, and will be read
  by the GitHub Actions release workflow when that is added.

### Changed
- Refresh button is now an SVG icon (no text label) to save toolbar space
- `PotaProxy.py` startup log banner now includes the version number
- `pathlib` import in `PotaProxy.py` moved to top-level (was previously
  imported inside `main()`; needed at module load time to read `VERSION`)
- Band dropdown labels shortened: frequency ranges removed (e.g. "20m" not
  "20m (14.0–14.35 MHz)") — operators know their bands
- Mode dropdown: "Digital (other)" shortened to "Other"; "All Modes" to "All"
- Rig Control dropdown: "(proxy)" suffix removed; "None (display only)" to "None"
- Auto-refresh dropdown labels shortened to "2 min", "5 min", etc.
- "Rig Control" label in toolbar shortened to "Rig"
- All toolbar label+control pairs are now wrapped as atomic flex units so they
  always wrap together — labels can no longer be stranded on a line without
  their control
- "Clear Tuned" and "Map" buttons moved from the toolbar into the header row,
  right-justified, to reduce toolbar crowding

### Removed
- Rig status indicator (the inline "● flrig v1.2" / "✖ unreachable" badge in
  the toolbar) — the error dialog alone is sufficient feedback; the inline
  badge was redundant and added visual noise
- Unused `sortCol` and `sortDir` state variables (sorting is driven entirely
  by the dropdown; these were never read)

## [1.1.0] - 2025-03-16
### Added
- All active spots are plotted on a live world map, filtered and sorted to match whatever you have selected in the controls
- The divider between the spot list and the map is draggable — resize to taste; neither pane can shrink below 25%
- Hover over any marker to see a popup with callsign, frequency, mode, park reference, and park name
- Click any marker to tune your radio — identical to clicking a row in the spot list
- Marker colour matches the age indicator: green = fresh, dim green = recent, dark = old
- Clicking a table row pans and zooms the map to that park and highlights the marker

## [1.0.0] - 2025-03-14
### Added
- Initial release
- MacLoggerDX, flrig, rigctld backends
- Band/mode filtering and sorting
