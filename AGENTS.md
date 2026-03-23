# AGENTS.md — POTA Spot Hunter
## Steering document and memory aid for AI-assisted development

This file is named **AGENTS.md** and lives in the project repo root.
Load it at the start of any new session to restore project context.

Note: this file was previously named CLAUDE.md, then PotaSpotHunter.md.
References to either name in older notes or git history refer to this same file.

---

## Instructions for the AI agent

**Always keep this file up to date.** After any session where decisions are
made, changes are implemented, or a release is cut, update the relevant
sections of this file before the session ends. Specifically:

- **Design decisions** — add any new decisions to the "Key design decisions"
  section, including the rationale and any "don't do this" warnings.
- **Current version** — update after every release.
- **Known issues / future work** — add new items as they are identified;
  mark resolved items as done or remove them.
- **Current state of the UI** — update if the UI layout or controls change.
- **Development notes** — update if new gotchas or workflow notes emerge.

Do not wait to be asked — updating this file is part of completing any task.

---

## What this project is

**POTA Spot Hunter** is a two-file local web app for browsing live
[Parks on the Air](https://parksontheair.com) activator spots and tuning a
ham radio with one click.

- **Author:** Gregory Wright, W7GFW (greg@gregorywright.org)
- **Repo:** https://github.com/gregorywright/PotaSpotHunter
- **Branch:** `mainline` (not `main`)
- **License:** MIT

| File | Purpose |
|------|---------|
| `PotaSpotHunter.html` | Self-contained single-file browser UI |
| `PotaProxy.py` | Local Python HTTP proxy on localhost:8080 |
| `VERSION` | Single source of truth for version number (e.g. `1.4.0`, no `v` prefix) |
| `CHANGELOG.md` | Version history in keep-a-changelog style |
| `AGENTS.md` | This file — AI steering document |
| `requirements.txt` | Intentionally empty — no third-party dependencies |
| `.github/workflows/release.yml` | GitHub Actions release workflow |

---

## Architecture

```
Browser (PotaSpotHunter.html)
        │
        │  HTTP GET /tune/mldx?freq=14074&mode=FT8&callsign=W1AW&note=POTA+US-1234
        ▼
PotaProxy.py  (localhost:8080)
        │
        ├── MacLoggerDX  via osascript / AppleScript  (setFreq, setMode,
        │                                              lookup, setNOTE)
        ├── flrig        via XML-RPC  (port 12345)
        └── rigctld      via TCP      (port 4532)
```

The proxy is **required** — the browser cannot reach rig-control software
directly due to the same-origin policy. On page load, the HTML pings
`/ping/mldx` and shows a full-screen blocking overlay if the proxy is not
running. The user can retry; the proxy auto-opens the browser on startup.

---

## Key design decisions (don't reverse without good reason)

### Split mode — always turned off on tune
All three backends explicitly turn off split mode on every tune command:
- **flrig**: `client.rig.set_split(0)`
- **rigctld**: `S 0 VFOA`  (note: requires both args — `S 0` alone is malformed)
- **MacLoggerDX**: `setSplitKhz "0"` (sent AFTER setLogFrequency/setLogMode)

POTA activators never work split. The POTA API has no split field.

### New-spot detection — composite key, not spotId
`spotKey()` builds a composite key: `"callsign|band|mode|ref|utcDate"`.
Used to identify genuinely new scoring opportunities on each refresh.
`seenSpotKeys` accumulates all keys ever seen; `newSpotKeys` holds only
keys that are new in the most recent refresh cycle.

A re-spot of the same activation (new `spotId`, same park/band/mode) is
NOT treated as new — it's the same scoring opportunity for the hunter.

Rules (from https://docs.pota.app/docs/rules.html):
- POTA QSO uniqueness = CALL + MODE + BAND + QSO_DATE + park ref
- **Frequency is irrelevant** — band is what counts
- **USB and LSB are both SSB** — collapsed in `spotKey()`
- **UTC date** — activator across UTC midnight = new scoring opportunity

### newSpotIds Set — no mutation of API objects
`render()` builds a local `newSpotIds` Set (spotId → boolean) from
`newSpotKeys` at render time. Do NOT stamp `_isNew` onto spot objects from
`allSpots` — that mutates objects we don't own. The `data-new` DOM attribute
was also removed (it was never read anywhere).

### Auto-scan does NOT mark spots as worked
`autoScanStep()` calls `tuneSpot()` which tunes the radio and sets the
active spot. There is no tuned-spot tracking — working a station is a
logging concern handled by MacLoggerDX and similar software.

### Rig status indicator removed (v1.2)
The inline toolbar badge ("● flrig" / "✖ unreachable") was removed. Error
feedback is handled entirely by the modal dialog. Do not re-add the badge.

### Box-shadow for scan highlight — zero layout cost
The scanning row indicator uses `box-shadow: inset 3px 0 0 0 amber` on
`td:first-child`. This draws inside existing padding — no column shifting,
no layout reflow. Do NOT switch to `border-left` (that shifts columns).

### VERSION file — no `v` prefix
The `VERSION` file contains just the bare version number, e.g. `1.4.0`.
The `v` prefix is added by the workflow and the HTML display where needed.
`PotaProxy.py` reads this file at module load time (not inside `main()`)
and stores it as `APP_VERSION`. It is served via the `/version` HTTP route.

---

## Current state of the UI

### Header row
```
POTA ► SPOT HUNTER v1.4.0   [status line]                         [⊕ Map]
```
The version number is fetched from the proxy `/version` endpoint at startup
and injected into `#version-label` — it is never hardcoded in the HTML.

### Toolbar (wraps gracefully; each label+control is an atomic flex unit)
```
Band [All▾]  Mode [All▾]  Rig [None▾]
Refresh [2min▾][↺]  Auto Scan [Off][5s][10s][30s][1m]   N spots
```
Sort dropdown removed — click any column header to sort.
Each label+control pair is wrapped in `.ctrl-group` (inline-flex,
flex-shrink:0) so they always wrap as a unit — labels never strand alone.

### Mode filter options
All, CW, SSB, FT8, FT4, Other Digital

"Other Digital" shows all digital modes **except** FT8 and FT4 (e.g. RTTY,
JS8, PSK, OLIVIA). All five options are mutually exclusive. The value in the
`<select>` for Other Digital is `"DIGITAL"`.

### Spot table columns
Freq (kHz) | Mode | Callsign | Park Ref | Park Name | Location | Last Heard | New | Tune button removed — click row to tune

### Map panel
- Leaflet.js + OpenStreetMap (no API key)
- Resizable split pane (25% min each side)
- Markers colour-coded by age: green=fresh, dim=recent, dark=old
- Click marker → tune + highlight table row
- Click table row → pan map to marker

---

## Proxy API reference

All responses are JSON. Routes with an `ok` field indicate success/failure.

```
GET /version                           → {"version": "1.4.0"}
GET /backends                          → {"backends": ["mldx","flrig","rigctld"]}
GET /ping/<backend>                    → {"ok": true/false, "version": "...", "error": "..."}
GET /tune/mldx?freq=<kHz>&mode=<mode>&callsign=<call>&note=<text>
GET /tune/flrig?freq=<kHz>&mode=<mode>
GET /tune/rigctld?freq=<kHz>&mode=<mode>
```

freq is in **kHz** — the proxy converts to Hz internally.
MacLoggerDX further converts to MHz for AppleScript.

---

## State variables (JS)

| Variable | Type | Purpose |
|----------|------|---------|
| `allSpots` | Array | Raw API response, QRT filtered out |
| `lastRenderedSpots` | Array | Filtered+sorted subset shown in table; used by auto-scan |
| `seenSpotKeys` | Set\<string\> | Composite keys of every spot ever seen this session. Never cleared. Used to detect new spots on each refresh. |
| `newSpotKeys` | Set\<string\> | Composite keys new in the most recent refresh. Cleared at the start of each `fetchSpots()` and repopulated. |
| `lastFetch` | Date | Timestamp of last successful API fetch |
| `activeSpotId` | number\|null | spotId of the active spot — drives amber bar, green background, map selection, and auto-scan resume. Set by any row click, scan step, or map marker click. Persists across scan stop/start. |
| `sortCol` | string | Active sort column (matches `data-col` on `<th>`). Default: `'freq'`. |
| `sortDir` | string | `'asc'` or `'desc'`. Default: `'asc'`. |
| `autoScanTimer` | interval id | null when not scanning |
| `autoScanIndex` | number | Current position in `lastRenderedSpots` |
| `autoScanDwell` | number | Active dwell in seconds (0 = off) |
| `leafletMap` | L.Map | Created once on first map open |
| `markersLayer` | L.LayerGroup | Rebuilt on every render() |
| `markerIndex` | Object | spotId → Leaflet marker |
| `tableRatio` | number | Fraction of split-area given to table (0.25–0.75) |
| `mapIsOpen` | boolean | Whether map panel is visible |
| `autoRefreshTimer` | interval id | null when manual-only |

---

## Auto-scan state machine

```
OFF → user clicks dwell pill        → autoScanStart(dwell)
ON  → user clicks different pill    → autoScanStart(newDwell)  [keeps going]
ON  → user clicks active pill       → autoScanStop()           [toggle off]
ON  → user clicks OFF pill          → autoScanStop()
ON  → any other click or keypress   → autoScanStop()
```

On start: look up `activeSpotId` in `lastRenderedSpots` — resume from there
  if found, otherwise start from index 0. Tune immediately, then start interval.
On each tick: increment index (wrap at end), call `tuneSpot()` which calls
  `setActiveSpot()`. No tunedIds save/restore — tuned tracking was removed.
On stop: clear interval, remove `.active-scan` class (stops pulse), keep
  `.scanning` class (amber bar stays as resume indicator), reset pills to OFF.

**IMPORTANT call order:** `render()` rebuilds all `<tr>` elements from scratch.
  `setActiveSpot()` must always be called AFTER `render()`, never before —
  otherwise render() destroys the `.scanning` class immediately. This is why
  `tuneSpot()` calls `render()` first, then `setActiveSpot()`.

Dwell options: Off, 5s, 10s, 30s, 1m. (1s was removed — too fast.)

---

## CSS classes to know

| Class | Applied to | Meaning |
|-------|-----------|---------|
| `tr.scanning` | `<tr>` | Active spot — green background + solid amber bar on `td:first-child`. Persists after scan stops as resume indicator. Set by `setActiveSpot()`, restored by `render()`. |
| `tr.scanning.active-scan` | `<tr>` | Active spot AND scan is running — amber bar AND green background both pulse in sync (1.4s). Added by `autoScanStep()`, removed by `autoScanStop()`. |
| `td.new-spot` | new column cell | Contains ● when spot is new this refresh cycle, blank otherwise. |
| `td.age.fresh` | age cell | < 10 min old — green |
| `td.age.recent` | age cell | 10–60 min old — dim green |
| `td.age.old` | age cell | > 60 min old — grey |
| `.fresh-pulse` | age cell | < 60s old — opacity pulse animation — **REMOVED in post-v1.3.0** |
| `.scan-pill.active` | pill button | Currently selected dwell time |
| `.scan-pill.scanning-active` | OFF pill | Shown when scan is running (red tint hint) |
| `#btn-refresh.spinning` | refresh button | SVG rotates while fetch is in flight |
| `#version-label` | span in logo | Displays "v1.4.0" fetched from proxy at startup |
| `.ctrl-group` | span in toolbar | Wraps label+control as atomic wrap unit |

---

## Release process

### Files to update before tagging
- `VERSION` — bump this (bare number, no `v`, e.g. `1.4.0`)
- `CHANGELOG.md` — rename `[Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`, add new empty `[Unreleased]` at top
- `README.md` — update if new features need documenting
- `AGENTS.md` — update current version and any other changed sections

### Steps
```bash
# 1. Update files, commit and push
git add VERSION CHANGELOG.md README.md AGENTS.md
git commit -m "Release vX.Y.Z"
git push origin mainline

# 2. Tag and push — this triggers the GitHub Actions workflow
git tag vX.Y.Z
git push origin mainline --tags
```

### What the workflow does (.github/workflows/release.yml)
1. Reads `VERSION`, verifies the tag matches (fails fast if not)
2. Extracts the matching `## [X.Y.Z]` section from `CHANGELOG.md` as release notes
3. Creates `PotaSpotHunter-vX.Y.Z.zip` containing:
   `PotaSpotHunter.html`, `PotaProxy.py`, `VERSION`, `README.md`,
   `CHANGELOG.md`, `LICENSE`, `requirements.txt`
   (Note: `AGENTS.md` is intentionally excluded from the release zip)
4. Creates a **draft** GitHub release with the zip attached

### Publishing the draft
- Go to https://github.com/gregorywright/PotaSpotHunter/releases
- Click the pencil/edit icon on the draft
- Review title, notes, and zip attachment
- Click **Publish release** at the bottom

### Monitoring the workflow
- Watch live at https://github.com/gregorywright/PotaSpotHunter/actions
- Typically completes in 30–60 seconds
- The draft release appears immediately when the workflow goes green

---

## Current version

`VERSION` file contains `1.4.0`. The next release will be v1.5.0 (or v1.4.1
if the next changes are patch-level). Unreleased changes are tracked in
`CHANGELOG.md` under `[Unreleased]`.

---

## Known issues / future work ideas

- **Startup ping always checks MacLoggerDX** — `startupProxyCheck()` pings
  `/ping/mldx` regardless of the user's chosen rig backend. If MacLoggerDX
  is not running but flrig is, the page shows an error unnecessarily. The fix
  would be to either ping all backends silently and only error if ALL fail, or
  to remember the last-used backend and ping that one.

- **Auto-scan and spot list refresh** — if the list refreshes mid-scan and
  the currently-scanning spot disappears, the scanner continues at the same
  index in the new list (which may be a different spot). This is intentional
  and documented, but could be surprising. A future option might try to
  find the same spot by composite key in the new list before falling back
  to index.

- **No persistence** — `seenSpotKeys` is in-memory only; closing the
  browser resets new-spot detection so all spots appear new on the next
  session. This is acceptable — the "new" flag is a per-session UI hint.

---

## Development notes

- `PotaSpotHunter.html` is entirely self-contained — no build step, no npm,
  no bundler. Open directly in a browser (after starting the proxy).
- `PotaProxy.py` requires Python 3.6+ and no third-party packages.
- The HTML file is ~2300 lines. Always read the relevant section before
  editing — don't rely on memory of exact whitespace.
- Always verify edits with a grep/check pass after making changes.
- The branch is `mainline`.
- **render() / setActiveSpot() call order is critical** — `render()` rebuilds
  `tbody.innerHTML` completely, destroying any classes on `<tr>` elements.
  Always call `setActiveSpot()` AFTER `render()`. This has bitten us before —
  see the v1.3.0 amber bar fix. If the amber bar ever stops appearing, check
  this order first.
- **CHANGELOG.md workflow** — maintain the `[Unreleased]` section as we go.
  At release time: rename it to `## [X.Y.Z] - YYYY-MM-DD`, bump `VERSION`,
  update `README.md` and `AGENTS.md` if needed, commit, tag, push.

---

## Useful external links

| Resource | URL |
|----------|-----|
| POTA spot API | https://api.pota.app/spot/activator |
| POTA rules | https://docs.pota.app/docs/rules.html |
| POTA activator profile | `https://pota.app/#/profile/<CALL>` |
| POTA park detail | `https://pota.app/#/park/<REF>` |
| MacLoggerDX scripting | https://dogparksoftware.com/MacLoggerDX%20Help/mldxfc_script.html |
| flrig XML-RPC | http://www.w1hkj.com/flrig-help/xmlrpc_commands.html |
| Hamlib rigctld | https://hamlib.sourceforge.net/html/rigctld.1.html |
| Leaflet.js | https://leafletjs.com |
| ARRL band plan | https://www.arrl.org/frequency-allocations |
| GitHub Actions (monitor) | https://github.com/gregorywright/PotaSpotHunter/actions |
| GitHub Releases | https://github.com/gregorywright/PotaSpotHunter/releases |
