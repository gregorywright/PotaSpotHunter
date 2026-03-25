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

- **Startup ping fix** — ping the selected backend on startup, not always
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
