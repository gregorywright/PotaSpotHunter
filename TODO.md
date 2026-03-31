# TODO.md — POTA Spot Hunter
## Future feature ideas and implementation plans

---

## [PLANNED] Worked Callsign Indicator

Show hunters how many times they've worked each visible activator, and
whether working them again would score points. Uses MacLoggerDX as the
data source (other backends show nothing).

### User-visible behaviour

- **`×N` badge** inline after the callsign link — grey, small font, lifetime
  QSO count. Hidden if count is 0 and not worked today.
- **Colored dot** next to the badge:
  - No dot — not worked today
  - **Amber ●** — worked today, band/mode unknown (AppleScript source only)
  - **Red ●** — worked today, band + mode match (strong signal, likely no points)
  - **Red ●** (hover distinguishes) — worked today, band + mode + park ref match
    (certain duplicate, no points)
- **Single hover tooltip** on the callsign cell covering everything:
  - `"Worked 5 times. Last worked: 2025-11-03"`
  - `"Worked 5 times. Last worked: today 14:23 UTC. Band/mode unknown — possible duplicate."`
  - `"Worked 3 times. Last worked: today 14:23 UTC on 20m FT8 — likely no points."`
  - `"Worked 2 times. Last worked: today 14:23 UTC on 20m FT8 at US-1234 — no points."`

### Data sources

**AppleScript batch query (historical):**
MacLoggerDX QSO objects only expose: `call`, `first_name`, `last_name`,
`qso_start`. No band or mode. Batch all callsigns in one osascript call:
```applescript
tell application "MacLoggerDX"
  set counts to {}
  repeat with c in {"W1AW", "K8BSR"}
    set end of counts to (count every qso whose call is c)
  end repeat
  return counts
end tell
```
Gives: count + most recent qso_start per callsign. `worked_today` = True
if any qso_start is UTC today.

**UDP broadcast (real-time, port 9932):**
MacLoggerDX broadcasts a `Log Report` packet whenever a QSO is logged:
```
Log Report: Call:N2BJ, RxMHz:21.08580, TxMHz:21.08580, Band:15M,
Mode:FSK, Power:5, dxcc_num:291, logged_time:2014-12-30 17:33:57 +0000,
dxcc_string:United States, city:NEW LENOX, state:IL,
first_name:Barry, last_name:COHEN
```
No park ref in this packet. Cache has a `park_ref` field for backends
that do provide it (future Log4OM support etc.).

### worked_cache structure

Module-level dict in PotaProxy.py, protected by a threading.Lock.
Each entry is an open dict — new fields can be added by any backend
without breaking existing consumers:

```python
worked_cache = {
  "W1AW": {
    "count":         5,        # lifetime QSO count
    "last_date":     "2026-03-24T14:23:00+00:00",  # ISO, None if unknown
    "worked_today":  True,     # any QSO with UTC date == today
    "last_band":     "20m",    # None if unknown (AppleScript source)
    "last_mode":     "FT8",    # None if unknown; SSB-collapsed
    "last_freq_mhz": "14.074", # None if unknown
    "last_park_ref": "US-1234" # None if not provided by backend
  }
}
```

SSB collapse for mode matching: USB and LSB both treated as SSB,
same logic as `spotKey()` in the HTML.

POTA uniqueness rule: call + band + mode + UTC date + park ref.
Dot color logic:
- `worked_today=True`, no band/mode → amber
- `worked_today=True`, band+mode match spot → red
- `worked_today=True`, band+mode+park_ref match spot → red (hover says "certain")

### Backend interface (forward-compatible)

Three new methods on RigBackend base class (all no-ops by default):

```python
def get_worked(self, callsigns: list) -> dict:
    """Return {callsign: {count, last_date, worked_today, ...}} for a batch."""
    raise NotImplementedError

def start_log_listener(self, callback) -> None:
    """Start background listener; call callback(entry_dict) on new QSO."""
    pass

def stop_log_listener(self) -> None:
    """Stop listener thread; BLOCKS until thread exits and socket is closed."""
    pass
```

`MacLoggerDXBackend` implements all three.
`FlrigBackend` / `RigctldBackend` leave all as no-ops — badges hidden.
Future `Log4OMBackend` would implement all three via its UDP remote control.

### Backend switching lifecycle

When user changes rig dropdown:
1. `old_backend.stop_log_listener()` — blocks until thread exits + socket closed
2. Set new active backend
3. `new_backend.start_log_listener(callback)`
4. `worked_cache` is NOT cleared — counts survive backend switches

### New proxy endpoints

```
GET /worked
    Returns full worked_cache snapshot as JSON.
    {"W1AW": {"count": 5, "last_date": "...", "worked_today": true, ...}, ...}

GET /lookup_calls?calls=W1AW,K8BSR,...
    Enqueues callsigns not already in cache for background AppleScript lookup.
    Returns immediately: {"queued": 3}
```

### Implementation tasks

**Task 1: Define backend interface and worked_cache structure**
- Add three no-op methods to `RigBackend`: `get_worked(callsigns) -> dict`,
  `start_log_listener(callback)`, `stop_log_listener()`
- Define cache entry schema as an open dict with known fields: `count` (int),
  `last_date` (ISO string|None), `worked_today` (bool), `last_band` (str|None),
  `last_mode` (str|None), `last_freq_mhz` (str|None), `last_park_ref` (str|None)
- Add module-level `worked_cache = {}` and a `threading.Lock` for safe
  concurrent access
- No behavior yet — just the scaffolding
- Demo: proxy starts cleanly, `worked_cache` exists, backend base class has
  the new methods

**Task 2: Implement batched AppleScript get_worked() on MacLoggerDXBackend**
- Implement `get_worked(callsigns)` — builds a single AppleScript that loops
  over all callsigns, returns count + most recent `qso_start` for each
- Returns dict of `{callsign: {count, last_date, worked_today}}`
- `worked_today` = True if any `qso_start` for that call is UTC today
- Add background worker thread in proxy: drains a `Queue` of callsigns, calls
  `active_backend.get_worked()` in batches of up to 50, writes results into
  `worked_cache` under the lock
- Only enqueues callsigns not already in cache
- Demo: manually enqueue a known callsign, verify `/worked` returns correct
  count and date after a few seconds

**Task 3: Add /worked and /lookup_calls endpoints**
- `GET /worked` — returns full `worked_cache` snapshot as JSON (under lock)
- `GET /lookup_calls?calls=W1AW,K8BSR,...` — enqueues callsigns not already
  cached; returns immediately with `{"queued": N}`
- Demo: browser can call both endpoints; `/lookup_calls` with 10 callsigns
  enqueues only the new ones; `/worked` returns results as they populate

**Task 4: Implement UDP log listener on MacLoggerDXBackend**
- Implement `start_log_listener(callback)` — binds UDP socket to port 9932,
  starts listener thread, parses `Log Report:` packets, calls
  `callback({call, band, mode, freq_mhz, logged_time, ...})`
- Implement `stop_log_listener()` — sets stop event, closes socket, joins
  thread (blocks until fully stopped)
- Proxy calls `start_log_listener` when MLDX is selected, `stop_log_listener`
  when backend switches
- Callback updates `worked_cache`: increments count, sets `worked_today=True`,
  updates all available fields
- Demo: log a QSO in MLDX, verify `/worked` updates within 1 second with
  band/mode populated

**Task 5: Wire backend switching to listener lifecycle**
- Add `GET /set_backend?backend=<name>` route (or extend existing backend
  selection)
- On switch: call `old_backend.stop_log_listener()` (blocks until done), set
  new active backend, call `new_backend.start_log_listener(callback)`
- `worked_cache` is NOT cleared on switch
- Demo: switch from MLDX to flrig and back; verify no port conflicts, listener
  restarts cleanly, cache preserved

**Task 6: Render worked badge in HTML**
- After each spot refresh, call `/lookup_calls` with all visible callsigns
- Poll `/worked` (same interval as spot refresh, or piggyback on it)
- In `render()`, for each spot look up callsign in worked data and build badge
  HTML inline in the callsign cell:
  - `×N` count badge (grey, small, after the callsign link)
  - Colored dot: no dot / amber ● / red ● based on `worked_today` + band+mode
    match + park_ref match
  - Single `title` attribute on the cell wrapper with full hover text
- SSB collapse for mode matching (USB/LSB → SSB), same logic as `spotKey()`
- Badge absent entirely if count=0 and not worked today
- Demo: spots with worked callsigns show badges; hover shows rich text; dot
  color reflects confidence level

**Task 7: Update AGENTS.md and CHANGELOG**
- Document `/worked` and `/lookup_calls` endpoints in proxy API reference section
- Document new backend interface methods in development notes
- Add `workedCache` to JS state variables table (it lives in the browser as
  the polled snapshot)
- Add CHANGELOG entry under `[Unreleased]`

---

## Other ideas (not yet planned)

- **Park type icon** — fetch `/park/<ref>` in the background (cached, same
  pattern as activator profile) and show an emoji/SVG icon in the spot row
  indicating the park type. Known types from live API sampling:

  | parktypeDesc | Proposed icon |
  |---|---|
  | National Park | 🏛 |
  | National Forest | 🌲 |
  | State Park | 🏕 |
  | State Recreation Area | 🏕 |
  | Wildlife Management Area | 🦅 |
  | Wetland Management District | 🌿 |
  | Conservation Area | 🌿 |
  | Memorial Parkway | 🪧 |
  | Park (generic) | 🌳 |
  | Prefectural Park | 🗾 |

  Also: make the park name a clickable link to the official park website
  using the `website` field from `/park/<ref>`. No auth required.

- **Rare park indicator** — flag spots where the park has few activations or
  hasn't been activated recently. All data is public, no auth required.

  APIs:
  ```
  GET https://api.pota.app/park/stats/<ref>
  → {"reference": "US-2961", "attempts": 129, "activations": 124, "contacts": 3628}

  GET https://api.pota.app/park/activations/<ref>
  → [{"activeCallsign": "W8SEE", "qso_date": "20260318", "totalQSOs": 12,
      "qsosCW": 0, "qsosDATA": 12, "qsosPHONE": 0}, ...]
  ```
  First entry in `/park/activations/<ref>` is the most recent activation.

  Suggested rarity criteria (thresholds TBD):
  - Total activations < 10 → "rarely activated"
  - Last activation > 6 months ago → "not activated recently"
  - Total QSOs < 50 → "low contact count"

  UI: a small flame/star/gem icon on the park ref cell, with hover text
  explaining why it's flagged (e.g. "Only 3 activations ever" or "Last
  activated 8 months ago"). Fetch and cache per park ref, same background
  pattern as other park data lookups.

- **Nation flag in Location column** — show the country's flag emoji next
  to the location descriptor (e.g. 🇺🇸 US-WA, 🇨🇦 CA-ON, 🇯🇵 JA-HB).
  The `entityId` and `entityName` fields from `/park/<ref>` (or the
  `referencePrefix` from the spot's `reference` field) identify the country.
  Flag emoji are just Unicode: 🇺🇸 = U+1F1FA U+1F1F8. No external library
  needed — map referencePrefix (US, CA, JA, etc.) to flag emoji. No auth
  required.

- **Awards tracking / gamification** — ask the user for their callsign once
  (stored in localStorage), fetch their POTA profile, and show award progress
  and gamification hints inline. No authentication required for the features
  listed below.

  **Public API endpoints used:**
  ```
  GET https://api.pota.app/profile/<call>
  → full awards list with names, granted dates, and band/mode endorsements
  → hunter parks count and recent hunter QSOs (last 25)

  GET https://api.pota.app/stats/user/<call>
  → summary counts (parks, QSOs, awards, endorsements)
  ```

  **Award tier ladder (hunter parks required):**
  Bronze(10) → Silver(20) → Gold(30) → Platinum(40) → Diamond(50) →
  Sapphire(75) → Arizona Agave(100) → Enrubio(200) → Ouachita Mountain
  Goldenrod(300) → Stenogyne Kanehoana(400) → Howell's Spectacular
  Thelypody(500) → Texas Wild Rice(600) → ... continuing in increments of
  500 with endangered species names up to 20,000 parks.

  **Features achievable without auth:**

  1. **Award tier progress bar** — show current tier, parks count, and parks
     needed for next tier. E.g.:
     `🏆 Sapphire → Arizona Agave: 135/200 ████████░░ 65 to go`
     Display in header or collapsible panel.

  2. **Band/mode endorsement hints** — profile returns existing endorsements
     (e.g. 20m, CW). Highlight spots on bands/modes the hunter doesn't yet
     have an endorsement for with a small ✨ indicator on the spot row.
     "Working this spot would earn you a new 40m endorsement."

  3. **Activator experience badge** — fetch `/profile/<activator_call>` in
     the background (cached, same pattern as worked_cache). Show activator's
     total activation count as a small badge on the callsign. "37 activations"
     signals a reliable operator likely to make the 10 QSO minimum.

  4. **Operator-to-operator count** — from the worked_cache (already planned),
     show how many times the hunter has worked this specific activator.
     Fun social element — "You've worked W1AW 5 times."

  5. **Recent activity context** — profile includes last 25 hunter QSOs with
     band, mode, park ref, and date. Use this at session start to seed the
     worked_cache with "worked recently" data before the UDP listener takes
     over for the current session.

  **What requires auth (not yet possible):**
  - "Have I worked this specific park before?" — needs full logbook
  - New park highlighting on spot rows
  - The `/user/logbook` endpoint requires a valid session token

  **Authentication research notes:**
  - POTA uses AWS Cognito with PKCE OAuth2
  - Login: `parksontheair.auth.us-east-2.amazoncognito.com`
  - Cognito client ID: `7hluqct0n2nckib7i7sd5753oa`
  - Redirect is hardcoded to `https://pota.app/` — we cannot intercept it
    without POTA registering `http://localhost:8080/auth/callback`
  - POTA API docs mention an "Application Key" system but docs are incomplete
  - POTA API terms prohibit use in apps with third-party tracking

  **⚠️ POTA API status (confirmed 2026-03-26):**
  The POTA APIs were built solely to separate their own front-end from
  back-end. They have no public documentation, no auth/application key
  program, and cannot guarantee API stability or continued availability.
  Use public endpoints as best-effort only. No authenticated API access
  is possible. Auth-free fallbacks (ADIF import, MLDX log mining) are
  the only path for worked parks data.

  **Auth-free fallback for worked parks:**
  - ADIF import — user exports log from pota.app, imports into PotaSpotHunter.
    Parse to extract hunted park refs. One-time setup, re-import to refresh.
  - MLDX log mining — extract park refs from `note` field of MLDX QSOs
    (set to "POTA US-1234" on every tune). MLDX users only.

  **Additional awards trackable without auth:**

  These can be highlighted on spot rows in real time based on current time,
  park location, and the user's profile — no logbook access needed.

  | Award | Rule | How to detect |
  |-------|------|---------------|
  | New Years Hunter | Hunt Jan 1–7 (UTC) | Is today Jan 1–7? Flag all spots |
  | Early Shift Hunter | Hunt during Early Shift (~02:00 UTC ±1hr/15° lon) | Calculate shift window from park longitude; flag if active now |
  | Late Shift Hunter | Hunt during Late Shift (~18:00 UTC ±1hr/15° lon) | Same calculation; flag if active now |
  | Support Your Parks Hunter | Hunt during 3rd weekend of Jan/Apr/Jul/Oct | Is today that weekend? Flag all spots |
  | DX Hunter | Hunt activators in DX entities (increments of 5) | Flag spots where reference prefix ≠ user's home entity |
  | Six Pack Hunter | 1 QSO from 6 different parks on 6m | Flag all 6m spots |
  | N1CC Hunter | QSOs from 10 parks on 10 different bands | Flag spots on bands not yet in user's endorsements |
  | Repeat Offender (Oasis) | 20 hunter QSOs from same single park | Needs worked_cache or MLDX log |
  | Operator-to-Operator | 50 QSOs with same activator | Partially covered by worked_cache count |

  Early/Late Shift formula (from POTA docs):
  - Early Shift start (UTC) = 2 − (park_longitude / 15), rounded to nearest hour
  - Late Shift start (UTC) = 18 − (park_longitude / 15), rounded to nearest hour
  - Early Shift duration: 6 hours; Late Shift duration: 8 hours
  - Park longitude is already in the spot data

  **UI treatment for award hints:**
  Small colored pill or icon on the spot row when a spot qualifies for an
  active award opportunity. Examples:
  - 🌙 Late Shift window active for this park right now
  - 🎆 New Years week
  - 🎪 Support Your Parks event weekend
  - 🌍 DX entity (counts toward DX Hunter)
  - 📻 6m spot (counts toward Six Pack)
  - 🆕 Band not yet in your endorsements (counts toward N1CC)

  Hover text explains which award and why.

  **What's available without auth (public API):**
  ```
  GET https://api.pota.app/profile/<call>
  → full awards list with names, granted dates, and band/mode endorsements
  → hunter parks count and recent hunter QSOs (last 25)

  GET https://api.pota.app/stats/user/<call>
  → summary counts only (parks, QSOs, awards, endorsements)
  ```

  **Award tier ladder (hunter parks required):**
  Bronze(10) → Silver(20) → Gold(30) → Platinum(40) → Diamond(50) →
  Sapphire(75) → Arizona Agave(100) → Enrubio(200) → Ouachita Mountain
  Goldenrod(300) → Stenogyne Kanehoana(400) → Howell's Spectacular
  Thelypody(500) → Texas Wild Rice(600) → ... continuing in increments of
  500 with endangered species names up to 20,000 parks.

  **Without auth we can show:**
  - Current award tier and parks count
  - Parks needed for next tier (e.g. "135 parks — 65 to Enrubio (200)")
  - Band/mode endorsement progress (you have 20m+CW; working 40m FT8 would
    be a new endorsement)
  - Progress bar in the UI header or a sidebar panel

  **What requires auth (worked parks list):**
  The `/user/logbook` endpoint requires authentication. Without it we cannot
  highlight "you haven't worked this park before" on individual spots.

  **Authentication findings:**
  - POTA uses AWS Cognito with PKCE OAuth2 flow
  - Login URL: `parksontheair.auth.us-east-2.amazoncognito.com`
  - Cognito client ID: `7hluqct0n2nckib7i7sd5753oa`
  - PKCE means we cannot POST credentials directly — requires browser redirect
    and a pre-registered callback URI
  - POTA has an **Application Key** system for third-party developers:
    GET `/session` with an Application Key returns a Session Key for
    authenticated API calls
  - POTA API terms: "does not permit use of the API in an application
    containing any form of 3rd party tracking"
  - **Action required:** Contact POTA team to request an Application Key for
    PotaSpotHunter. App is open source, hunter-focused, no tracking — good
    candidate for approval.

  **Fallback without Application Key:**
  - ADIF import — user exports their full log from pota.app as ADIF, imports
    into PotaSpotHunter. Parse to extract all hunted park refs. One-time
    setup, works for any logger. Re-import to refresh.
  - MLDX log mining — query `every qso` via AppleScript and extract park refs
    from the `note` field (set to "POTA US-1234" on every tune). Local,
    no auth, MLDX users only.

  **UI ideas:**
  - Callsign entry at startup (optional, dismissible, stored in localStorage)
  - Progress indicator in header: "🏆 Enrubio: 135/200 parks"
  - Spot rows: dim or badge parks already worked (requires auth or ADIF import)
  - New park highlight: green glow or ★ on park ref for parks not yet worked
  MLDX. Or ping all backends silently and only error if ALL fail.

- **Persist filter settings** — remember band/mode filter and rig selection
  across sessions via localStorage.

- **Keyboard shortcuts** — j/k to move up/down the list, Enter to tune,
  Space to pause/resume auto-scan.

- **Spotter column** — show who posted the spot; useful for judging
  reliability. Already in the API response (`spotter` field).

- **Spot count badge** — show the `count` field from the API (number of
  times this activation has been spotted). A spot with count=12 is more
  reliable than count=1.

- **Watchlist / alerts** — notify (sound or visual) when a specific
  callsign or park reference appears in the spot list.

- **Auto-scan index recovery** — when the spot list refreshes mid-scan,
  try to find the current spot by composite key in the new list before
  falling back to the same index.

- **Mobile layout** — the table is hard to use on a phone; a card-based
  layout for narrow viewports would help.

- **Themes** — support selectable color themes (e.g. dark green, dark blue,
  high contrast). CSS variables are already used throughout, so a theme
  switcher would just swap a small set of root variable values. Store
  preference in localStorage.

  **Status:** Theme system is implemented and working. `Ctrl+T` cycles
  through themes for testing. Not yet exposed in the UI.

  **Current themes defined in `THEMES` object:**
  - `green-terminal` — default dark green, no CRT effect
  - `green-terminal-crt` — same but with subtle CRT scanlines (`rgba(0,0,0,0.09)`)
  - `dracula` — purple-tinted dark, cyan/green accent
  - `solarized-light` — warm cream background, teal accent
  - `github-light` — clean white, green/amber accent

  **Exact theme definitions to restore:**
  ```javascript
  const THEMES = {
    'green-terminal': {
      '--bg': '#0d0f0e', '--surface': '#141714', '--surface2': '#1a1d1a',
      '--border': '#2a2e2a',
      '--green': '#39ff6a', '--green-dim': '#1a7a35', '--green-faint': '#0d3319',
      '--amber': '#ffb830', '--amber-dim': '#7a5010',
      '--red': '#ff4444',
      '--text': '#c8d4c8', '--text-dim': '#5a6b5a', '--text-bright': '#e8f4e8',
      '--tooltip-bg': '#1e1a0e', '--tooltip-text': '#e8f4e8',
      '--scanline': 'transparent',
    },
    'green-terminal-crt': {
      '--bg': '#0d0f0e', '--surface': '#141714', '--surface2': '#1a1d1a',
      '--border': '#2a2e2a',
      '--green': '#39ff6a', '--green-dim': '#1a7a35', '--green-faint': '#0d3319',
      '--amber': '#ffb830', '--amber-dim': '#7a5010',
      '--red': '#ff4444',
      '--text': '#c8d4c8', '--text-dim': '#5a6b5a', '--text-bright': '#e8f4e8',
      '--tooltip-bg': '#1e1a0e', '--tooltip-text': '#e8f4e8',
      '--scanline': 'rgba(0,0,0,0.09)',
    },
    'dracula': {
      '--bg': '#282a36', '--surface': '#313442', '--surface2': '#3a3d4e',
      '--border': '#44475a',
      '--green': '#50fa7b', '--green-dim': '#1e6b35', '--green-faint': '#0d2e1a',
      '--amber': '#ffb86c', '--amber-dim': '#7a5020',
      '--red': '#ff5555',
      '--text': '#f8f8f2', '--text-dim': '#6272a4', '--text-bright': '#ffffff',
      '--tooltip-bg': '#1e1a2e', '--tooltip-text': '#f8f8f2',
      '--scanline': 'rgba(0,0,0,0.07)',
    },
    'solarized-light': {
      '--bg': '#fdf6e3', '--surface': '#eee8d5', '--surface2': '#e8e0cc',
      '--border': '#ccc4b0',
      '--green': '#2aa198', '--green-dim': '#1a6b65', '--green-faint': '#d4efed',
      '--amber': '#b58900', '--amber-dim': '#7a5c00',
      '--red': '#dc322f',
      '--text': '#657b83', '--text-dim': '#93a1a1', '--text-bright': '#073642',
      '--scanline': 'transparent',
      '--tooltip-bg': '#eee8d5', '--tooltip-text': '#073642',
    },
    'github-light': {
      '--bg': '#ffffff', '--surface': '#f6f8fa', '--surface2': '#eaeef2',
      '--border': '#d0d7de',
      '--green': '#1a7f37', '--green-dim': '#2da44e', '--green-faint': '#dafbe1',
      '--amber': '#9a6700', '--amber-dim': '#bf8700',
      '--red': '#cf222e',
      '--text': '#1f2328', '--text-dim': '#656d76', '--text-bright': '#000000',
      '--scanline': 'transparent',
      '--tooltip-bg': '#f6f8fa', '--tooltip-text': '#1f2328',
    },
  };
  ```

  **Remaining work:**

  1. **Rename CSS variables** to role-based names (do alongside file split):

     | Current | Proposed | Role |
     |---|---|---|
     | `--bg` | `--color-bg` | Page background |
     | `--surface` | `--color-surface` | Elevated surface |
     | `--surface2` | `--color-surface-hover` | Hover/active surface |
     | `--border` | `--color-border` | Borders and dividers |
     | `--green` | `--color-accent` | Primary accent (logo, active states) |
     | `--green-dim` | `--color-accent-dim` | Dimmed accent |
     | `--green-faint` | `--color-accent-faint` | Active row background |
     | `--amber` | `--color-highlight` | Secondary highlight (freq, scan bar) |
     | `--amber-dim` | `--color-highlight-dim` | Dimmed highlight |
     | `--red` | `--color-danger` | Errors, warnings |
     | `--text` | `--color-text` | Body text |
     | `--text-dim` | `--color-text-dim` | Muted/secondary text |
     | `--text-bright` | `--color-text-bright` | High emphasis text |
     | `--scanline` | `--effect-scanline` | CRT scanline overlay |
     | `--tooltip-bg` | `--color-tooltip-bg` | Tooltip background |
     | `--tooltip-text` | `--color-tooltip-text` | Tooltip text |

  2. **Add theme picker UI** — a small dropdown or swatch row, probably in
     a settings popover or the header. Remove the `Ctrl+T` dev shortcut
     once the UI is in place.

  3. **Theme files in `themes/` directory:**
     - Only the default `green-terminal` theme is hardcoded in the app
     - All other themes ship as JSON files in a `themes/` directory
     - At least one extra theme ships in the ZIP so users see the format
       and are encouraged to create their own
     - The proxy exposes a `GET /themes` endpoint listing available `.json`
       files; the page fetches and merges them into the theme picker at startup
     - Users install new themes by dropping a `.json` file into `themes/`
       — no code changes needed
     - Theme JSON format matches the `THEMES` object entries above
       (keys are CSS variable names, values are CSS values)

  4. **Consider more themes** — Monokai, Nord, One Dark, high-contrast
     accessibility theme.

  **Notes:**
  - Each theme must set ALL variables — no partial overrides, since
    switching themes doesn't reset variables not present in the new theme
    (they bleed from the previous theme).
  - `--scanline: transparent` disables the CRT effect for light themes.
  - Do the variable rename alongside the file split — ~80-100 occurrences,
    mechanical find-and-replace, low risk.

---

## [PLANNED] Split PotaSpotHunter.html into separate files

Now that the proxy serves the HTML over HTTP (required since v1.6.1), the
single-file constraint no longer applies. The proxy can serve `style.css`
and `app.js` directly alongside `index.html` — no build step needed.

### Proposed file layout
```
PotaSpotHunter.html   ← renamed to index.html (proxy serves at /)
style.css             ← all CSS extracted
app.js                ← all JavaScript extracted
PotaProxy.py          ← add routes to serve style.css and app.js
```

### What changes in the proxy
Add two static file routes alongside the existing `/` route:
```python
GET /style.css  → serve style.css
GET /app.js     → serve app.js
```

### What changes in the HTML
Replace the inline `<style>` block with:
```html
<link rel="stylesheet" href="/style.css">
```
Replace the inline `<script>` block with:
```html
<script src="/app.js"></script>
```

### Release ZIP
The ZIP gains two files (`style.css`, `app.js`) but the user experience
is identical — they still just unzip and run `python3 PotaProxy.py`.
No build step, no npm, no tooling.

### Why not a JS framework (React/Vue/Svelte)?
The app has ~5 pieces of state and one main `render()` function. Frameworks
solve cascading state, component reuse, and virtual DOM diffing — none of
which are significant problems here. The overhead (npm, build tooling,
dependency maintenance) outweighs the benefit at current scale.

If the app grows significantly (multiple views, complex settings UI), Svelte
would be the best option — it compiles away at build time with no runtime
overhead. Revisit if complexity grows.

### Why not a CSS framework (Tailwind/Bootstrap)?
The CSS is ~400 lines of intentional dark-theme styling. A framework would
fight against the custom theme. Not worth it.

### Notes
- No build step required — proxy serves files directly
- Contributors can edit CSS/JS independently with proper syntax highlighting
- Git diffs become meaningful (CSS change only touches style.css)
- The old "build script" plan in this file is superseded by this approach
