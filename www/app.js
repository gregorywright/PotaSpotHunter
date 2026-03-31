// ============================================================
// POTASpotHunter.html  —  JavaScript core
//
// SOURCES
// -------
// POTA API:       https://api.pota.app/spot/activator
// MacLoggerDX URL scheme:
//   mldx://tune?freq=XX.XXX&mode=YYY
//   mldx://lookup?call=CALLSIGN
//   Documented at: https://dogparksoftware.com/MacLoggerDX%20Help/mldxfc_script.html
// US band plan:   https://www.arrl.org/frequency-allocations
// POTA rules (QSO uniqueness key): https://docs.pota.app/docs/rules.html
//
// ARCHITECTURE
// ------------
// allSpots        — raw array of spot objects from the API (QRT filtered out)
// lastRenderedSpots — the currently visible (filtered + sorted) subset,
//                   kept in sync by render() and used directly by auto-scan
// seenSpotKeys    — Set of composite keys for every spot ever seen. Used to
//                   detect genuinely new spots on each refresh.
// newSpotKeys     — Set of composite keys new in the most recent refresh.
//                   Cleared at the start of each fetch and repopulated.
// activeSpotId    — spotId of the "active" spot — unified concept that drives
//                   the amber bar, map selection, and auto-scan resume point.
//                   Set by any user click, by auto-scan steps, and by map
//                   marker clicks.  Persists across scan start/stop so the
//                   scan always resumes from where it left off.
// autoScan*       — state for the band-scanner feature (see auto-scan section)
//
// Filters and sort are applied in-place on every change; no page reload.
//
// SSB -> USB/LSB resolution:
//   < 10 MHz  -> LSB   (standard amateur band-plan convention)
//   >= 10 MHz -> USB
//
// RIG CONTROL
// -----------
// All rig commands go through pota_proxy.py (localhost:8080).
// The proxy handles AppleScript (MacLoggerDX), XML-RPC (flrig),
// and TCP (rigctld).  If the proxy is not running on startup,
// the UI is blocked with an overlay until it becomes reachable.
// mldx also has a URL-scheme fallback (freq+mode+lookup only,
// no setNOTE) if the proxy is unreachable at tune time.
//
// AUTO-SCAN (band scanner)
// ------------------------
// Cycles through the visible spot list, dwelling on each spot for a
// configurable number of seconds (5/10/30/60).  Calls tuneSpot() as if
// the user clicked but does NOT mark spots as tuned.  Any mouse click or
// keypress outside the pill control stops the scan.  See the auto-scan
// section below for the full state machine.
// ============================================================

// ── Band table (kHz ranges) ──────────────────────────────
const BANDS = {
  '160': [1800,   2000],
  '80':  [3500,   4000],
  '60':  [5330,   5407],
  '40':  [7000,   7300],
  '30':  [10100, 10150],
  '20':  [14000, 14350],
  '17':  [18068, 18168],
  '15':  [21000, 21450],
  '12':  [24890, 24990],
  '10':  [28000, 29700],
  '6':   [50000, 54000],
  '2':   [144000, 148000],
};

// ── State ────────────────────────────────────────────────
let allSpots     = [];
// ── New-spot tracking ───────────────────────────────────
// seenSpotKeys — composite keys of every spot seen across all refreshes.
//   Grows each cycle; never cleared.  Used to detect genuinely new spots.
// newSpotKeys  — composite keys of spots that appeared in the MOST RECENT
//   refresh and were not in seenSpotKeys before that refresh.
//   Cleared at the start of each fetchSpots() call and repopulated after.
//   A spot is "new" only for one refresh cycle.
//
// We use spotKey() (callsign+band+mode+ref+date) rather than spotId so
// that a re-spot of the same activation (new spotId, same park/band/mode)
// is NOT treated as new — it's the same scoring opportunity for the hunter.
let seenSpotKeys = new Set();   // all composite keys ever seen
let newSpotKeys  = new Set();   // composite keys new in the latest refresh
let lastFetch    = null;        // Date of the most recent successful API fetch
let activeSpotId = null;        // spotId of the currently active spot — drives the
                                // amber bar, map selection, and auto-scan resume.

// ── Sort state ───────────────────────────────────────────
// Driven entirely by column header clicks — no dropdown.
// sortCol matches the data-col attribute on <th> elements.
// Default: frequency ascending (lowest freq first) so the
// operator can tune up through the band.
let sortCol = 'freq';           // active sort column
let sortDir = 'asc';            // 'asc' | 'desc'

// ── Park type classification ─────────────────────────────
//
// Two pure functions kept separate so classifyParkType() can be unit-tested
// independently of any display concerns.
//
// classifyParkType(parktypeDesc) → canonical type string
//   Input:  parktypeDesc from api.pota.app/park/<ref>  (e.g. "National Park")
//   Output: one of the PARK_TYPE_ORDER keys below, or 'unknown'
//
// parkTypeEmoji(type) → display emoji for that type
//
// Sort order is defined by PARK_TYPE_ORDER so clicking the Type column
// groups parks in a meaningful sequence (federal → state → other).
// Array.prototype.sort() in modern JS engines is stable, so within each
// type group the existing sort order (e.g. frequency) is preserved.

const PARK_TYPE_ORDER = [
  'national_park',
  'national_forest',
  'national_monument',
  'national_wildlife',
  'national_other',
  'state_park',
  'state_forest',
  'state_trail',
  'state_beach',
  'recreation',
  'wildlife',
  'nature_reserve',
  'wetland',
  'historic',
  'unknown',
];

const PARK_TYPE_EMOJI = {
  national_park:      '🏛',
  national_forest:    '🌲',
  national_monument:  '🗿',
  national_wildlife:  '🦅',
  national_other:     '🪨',
  state_park:         '🏕',
  state_forest:       '🌳',
  state_trail:        '🥾',
  state_beach:        '🏖',
  recreation:         '🎯',
  wildlife:           '🦌',
  nature_reserve:     '🌿',
  wetland:            '🌾',
  historic:           '🪧',
  unknown:            '❓',
};

function classifyParkType(parktypeDesc) {
  if (!parktypeDesc) return 'unknown';
  const t = parktypeDesc.toLowerCase();
  if (t.includes('national park') ||
      t.includes('national historical park') ||
      t.includes('national historic site') ||
      t.includes('national battlefield') ||
      t.includes('national seashore') ||
      t.includes('national heritage'))              return 'national_park';
  if (t.includes('world heritage'))                 return 'historic';
  if (t.includes('national forest'))             return 'national_forest';
  if (t.includes('national monument') ||
      t.includes('natural monument'))            return 'national_monument';
  if (t.includes('national wildlife') ||
      t.includes('national wild and scenic') ||
      t.includes('national scenic trail') ||
      t.includes('wilderness area'))             return 'national_wildlife';
  if (t.includes('blm') ||
      t.includes('national'))                    return 'national_other';
  if (t.includes('state park') ||
      t.includes('provincial park') ||
      t.includes('state historical park') ||
      t.includes('state historic site') ||
      t.includes('state natural area') ||
      t.includes('state nature preserve') ||
      t.includes('state preserve'))              return 'state_park';
  if (t.includes('state forest'))                return 'state_forest';
  if (t.includes('state trail'))                 return 'state_trail';
  if (t.includes('state beach'))                 return 'state_beach';
  if (t.includes('state recreation') ||
      t.includes('state vehicle recreational') ||
      t.includes('recreation area') ||
      t.includes('recreation park') ||
      t.includes('recreation site'))             return 'recreation';
  if (t.includes('wildlife management') ||
      t.includes('wildlife area') ||
      t.includes('waterfowl management') ||
      t.includes('state fish and wildlife') ||
      t.includes('state game land') ||
      t.includes('state fishing lake'))          return 'wildlife';
  if (t.includes('nature reserve') ||
      t.includes('nature park') ||
      t.includes('state conservation') ||
      t.includes('conservation area') ||
      t.includes('protected landscape'))         return 'nature_reserve';
  if (t.includes('wetland') ||
      t.includes('marsh'))                       return 'wetland';
  if (t.includes('historic') ||
      t.includes('memorial') ||
      t.includes('heritage'))                    return 'historic';
  if (t.includes('park'))                        return 'state_park';  // generic "Park", "Regional Park" etc.
  return 'unknown';
}

function parkTypeEmoji(type) {
  return PARK_TYPE_EMOJI[type] || '❓';
}

// ── Park type cache ──────────────────────────────────────
// Background-fetched from api.pota.app/park/<ref> for each visible spot.
// Values: undefined = not yet fetched, null = fetch in-flight,
//         string = parktypeDesc from API ('' if API returned nothing).
//
// Design decisions:
//   - Fetch is fire-and-forget; render() uses whatever is cached at draw time.
//   - ⏳ shown while fetch is in-flight; real emoji (or ❓) shown after.
//   - Failed fetches store '' so we don't retry on every render cycle.
//   - Cache is never cleared — park types don't change between sessions.
const parkTypeCache = {};

// Debounce timer for the post-fetch render triggered by park type lookups.
// 200ms debounce coalesces rapid completions into a small number of renders.
let parkRenderTimer = null;
function scheduleParkRender() {
  clearTimeout(parkRenderTimer);
  parkRenderTimer = setTimeout(render, 200);
}

async function fetchParkType(ref) {
  if (ref in parkTypeCache) return;   // already cached or in-flight
  parkTypeCache[ref] = null;          // null = in-flight
  try {
    const r = await fetch(`https://api.pota.app/park/${encodeURIComponent(ref)}`,
                          { signal: AbortSignal.timeout(5000) });
    const d = await r.json();
    parkTypeCache[ref] = d.parktypeDesc || '';
  } catch {
    parkTypeCache[ref] = '';  // failed — don't retry
  }
  scheduleParkRender();
}

function fetchParkTypes() {
  allSpots.forEach(s => { if (s.reference) fetchParkType(s.reference); });
}

// ── Utility functions ────────────────────────────────────

// Convert kHz string to MHz string with up to 6 decimal places.
// MacLoggerDX tune URL expects MHz.
// Only used by the mldx:// URL-scheme fallback in tuneSpot() — MacLoggerDX
// normally goes through the proxy which handles the kHz→MHz conversion itself.
function khzToMhz(khz) {
  const n = parseFloat(khz);
  if (isNaN(n)) return khz;
  // Strip trailing zeros but keep at least 3 decimal places
  return (n / 1000).toFixed(6).replace(/0+$/, '').replace(/\.$/, '');
}

// Resolve "SSB" to "USB" or "LSB" based on frequency (kHz).
// Standard amateur band-plan convention:
//   < 10 MHz -> LSB,  >= 10 MHz -> USB
function resolveMode(mode, freqKhz) {
  const m = (mode || '').toUpperCase();
  if (m === 'SSB') {
    return parseFloat(freqKhz) < 10000 ? 'LSB' : 'USB';
  }
  return m || 'SSB';
}

// Parse ISO-8601 UTC spotTime to a Date object.
function parseSpotTime(iso) {
  // "2024-03-14T16:04:00" -> treat as UTC
  return new Date(iso.endsWith('Z') ? iso : iso + 'Z');
}

// Format a Date to "HH:MM" UTC string.
function fmtUTC(d) {
  return d.toISOString().slice(11, 16) + 'Z';
}

// Return a human-readable age string and CSS class.
function spotAge(d) {
  const sec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (sec < 60)         return { text: sec + 's',              cls: 'fresh'  };
  if (sec < 3600)       return { text: Math.floor(sec/60) + 'm', cls: sec < 600 ? 'fresh' : 'recent' };
  return { text: Math.floor(sec/3600) + 'h',  cls: 'old' };
}

// Escape HTML special chars for safe insertion.
function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Format a locationDesc string for compact display.
// The API can return multiple comma-separated regions, e.g. "JP-HB, JP-OS, JP-CH".
// We show the first entry and a "+N" count for the rest to keep the column narrow.
// The full string is preserved in the title attribute for hover display.
//   "JP-HB"               → "JP-HB"
//   "JP-HB, JP-OS"        → "JP-HB, +1"
//   "JP-HB, JP-OS, JP-CH" → "JP-HB, +2"
function fmtLocation(loc) {
  if (!loc) return '';
  const parts = loc.split(',').map(p => p.trim()).filter(Boolean);
  if (parts.length <= 1) return loc.trim();
  return parts[0] + ', +' + (parts.length - 1);
}

// Full location string with spaces after commas, for tooltips.
function fmtLocationFull(loc) {
  if (!loc) return '';
  return loc.split(',').map(p => p.trim()).filter(Boolean).join(', ');
}

// Determine which band name a frequency (kHz) falls in.
function bandOf(freqKhz) {
  const f = parseFloat(freqKhz);
  for (const [name, [lo, hi]] of Object.entries(BANDS)) {
    if (f >= lo && f <= hi) return name;
  }
  return null;
}

// ── Composite spot key ──────────────────────────────────
//
// Identifies a unique POTA scoring opportunity: callsign + band +
// normalised mode + park ref + UTC date.  Used for new-spot detection.
//
// Frequency is intentionally excluded — an activator can move a few kHz
// within a band and it's still the same scoring opportunity (POTA awards
// credit per band, not per frequency).
// USB and LSB are both collapsed to SSB (same QSO for POTA purposes).
// UTC date is included because an activator operating across UTC midnight
// is a new scoring opportunity.
//
// Source for POTA QSO uniqueness key:
//   https://docs.pota.app/docs/rules.html  (Logging Requirements section)
//   Uniqueness = STATION_CALLSIGN + CALL + MODE + QSO_DATE + BAND +
//                MY_SIG_INFO + SIG_INFO
function spotKey(callsign, freqKhz, modeRaw, reference, spotTime) {
  const band = bandOf(freqKhz) || 'unknown';
  // Normalise mode: collapse USB/LSB -> SSB
  let mode = (modeRaw || '').toUpperCase();
  if (mode === 'USB' || mode === 'LSB') mode = 'SSB';
  // UTC date string "YYYY-MM-DD"
  const utcDate = spotTime.toISOString().slice(0, 10);
  return `${callsign}|${band}|${mode}|${reference}|${utcDate}`;
}

// ── Fetch spots from POTA API ────────────────────────────
async function fetchSpots() {
  setStatus('loading', 'Fetching spots from api.pota.app…');
  document.getElementById('btn-refresh').classList.add('spinning');

  try {
    const res = await fetch('https://api.pota.app/spot/activator', {
      cache: 'no-cache'
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();

    // Filter out QRT spots
    allSpots = data.filter(s => {
      const c = (s.comments || '').toUpperCase();
      return !c.includes('QRT');
    });

    // Detect new spots — those whose composite key wasn't seen before.
    // newSpotKeys is cleared first so only this refresh cycle's new spots
    // are flagged.  seenSpotKeys accumulates across all refreshes.
    newSpotKeys.clear();
    allSpots.forEach(s => {
      const key = spotKey(
        s.activator || '',
        s.frequency || '',
        (s.mode || '').toUpperCase(),
        s.reference || '',
        parseSpotTime(s.spotTime)
      );
      if (!seenSpotKeys.has(key)) {
        newSpotKeys.add(key);
        seenSpotKeys.add(key);
      }
    });

    lastFetch = new Date();
    updateRefreshLabel();

    setStatus('ok', allSpots.length + ' active spots loaded.');
    render();
    fetchParkTypes();  // background — icons appear via debounced render as data arrives

  } catch (err) {
    setStatus('error', 'Fetch failed: ' + err.message +
      ' — Check internet connection and that api.pota.app is reachable.');
  } finally {
    document.getElementById('btn-refresh').classList.remove('spinning');
  }
}

// ── Status line helper ───────────────────────────────────
function setStatus(type, msg) {
  const el = document.getElementById('status-line');
  el.textContent = msg;
  el.className = type;
}

// ── Sort header indicator ───────────────────────────────
// Walks all sortable <th> elements and applies sort-asc or sort-desc
// to whichever column matches sortCol/sortDir.  All others are cleared.
// Called at the start of every render() so the indicators always match
// the current sort state even after a spot-list refresh.
function updateSortHeaders() {
  document.querySelectorAll('th[data-col]').forEach(th => {
    th.classList.remove('sort-asc', 'sort-desc');
    if (th.dataset.col === sortCol) {
      th.classList.add(sortDir === 'asc' ? 'sort-asc' : 'sort-desc');
    }
  });
}

// ── Filter + sort + render ───────────────────────────────
function render() {
  const bs   = document.getElementById('band-select');
  const band = bs.value;
  const mode = document.getElementById('mode-select').value;

  // Update band select styling
  bs.classList.toggle('active', band !== 'ALL');

  // Keep column header sort indicators in sync with sortCol/sortDir
  updateSortHeaders();

  // --- Filter ---
  let spots = allSpots.filter(s => {
    // Band filter
    if (band !== 'ALL') {
      const [lo, hi] = BANDS[band];
      const f = parseFloat(s.frequency);
      if (isNaN(f) || f < lo || f > hi) return false;
    }
    // Mode filter
    if (mode !== 'ALL') {
      const m = (s.mode || '').toUpperCase();
      if (mode === 'SSB') {
        if (m !== 'SSB' && m !== 'USB' && m !== 'LSB' && m !== 'AM') return false;
      } else if (mode === 'DIGITAL') {
        const known = ['CW','SSB','USB','LSB','AM','FM','FT8','FT4'];
        if (known.includes(m) || m === '') return false;
      } else {
        if (m !== mode) return false;
      }
    }
    return true;
  });

  // Build a Set of spotIds that are new this cycle, for use in sort and render.
  // Avoids mutating the API objects from allSpots.
  const newSpotIds = new Set(
    spots.filter(s => newSpotKeys.has(spotKey(
      s.activator || '',
      s.frequency || '',
      (s.mode || '').toUpperCase(),
      s.reference || '',
      parseSpotTime(s.spotTime)
    ))).map(s => s.spotId)
  );

  // --- Sort ---
  // sortCol and sortDir are module-level state set by column header clicks.
  // String columns use localeCompare; numeric/time columns use subtraction.
  spots.sort((a, b) => {
    const dir = sortDir === 'asc' ? 1 : -1;
    switch (sortCol) {
      case 'freq':
        return dir * ((parseFloat(a.frequency) || 0) - (parseFloat(b.frequency) || 0));
      case 'mode':
        return dir * (a.mode || '').localeCompare(b.mode || '');
      case 'callsign':
        return dir * (a.activator || '').localeCompare(b.activator || '');
      case 'ref':
        return dir * (a.reference || '').localeCompare(b.reference || '');
      case 'parktype': {
        // Sort by canonical type order (federal → state → other → unknown).
        // Stable sort preserves existing order within each type group.
        // In-flight fetches (null) and unfetched (undefined) sort as 'unknown'.
        const ta = PARK_TYPE_ORDER.indexOf(classifyParkType(parkTypeCache[a.reference] || ''));
        const tb = PARK_TYPE_ORDER.indexOf(classifyParkType(parkTypeCache[b.reference] || ''));
        return dir * (ta - tb);
      }
      case 'park':
        return dir * (a.name || '').localeCompare(b.name || '');
      case 'loc':
        return dir * (a.locationDesc || '').localeCompare(b.locationDesc || '');
      case 'new':
        // Sort new spots first (asc = new first since '1' > '0' would be wrong,
        // so we invert: new=1 sorts before not-new=0 when dir is asc)
        return -dir * ((newSpotIds.has(a.spotId) ? 1 : 0) - (newSpotIds.has(b.spotId) ? 1 : 0));
      case 'time':
      default:
        return dir * (parseSpotTime(a.spotTime).getTime() - parseSpotTime(b.spotTime).getTime());
    }
  });

  // --- Update count ---
  document.getElementById('spot-count').innerHTML =
    '<strong>' + spots.length + '</strong> spot' + (spots.length !== 1 ? 's' : '') +
    (band !== 'ALL' ? ' on ' + band + 'm' : '') +
    (mode !== 'ALL' ? ' / ' + mode : '');

  // --- Render rows ---
  const tbody = document.getElementById('spot-tbody');
  const empty = document.getElementById('empty-state');

  if (spots.length === 0) {
    tbody.innerHTML = '';
    empty.style.display = 'block';
    updateMap([]);
    return;
  }
  empty.style.display = 'none';

  const rows = spots.map(s => {
    const freqKhz  = s.frequency || '';
    const modeRaw  = (s.mode || '').toUpperCase();
    const modeDisp = resolveMode(s.mode, freqKhz);
    const callsign = s.activator || '';
    const ref      = s.reference || '';
    const park     = s.name || '';
    const loc      = s.locationDesc || '';
    const spotTime = parseSpotTime(s.spotTime);
    const age      = spotAge(spotTime);
    const id       = s.spotId;
    // Use composite key to recognise re-spotted activations after a refresh.
    // spotId changes each time a spot is re-posted; callsign+band+mode+ref+date
    // correctly identifies the same scoring opportunity across refreshes.
    const isNew    = newSpotIds.has(id);
    const hints    = spotAwardHints(s);
    const hintHTML = renderHintIcons(hints);

    return `<tr data-id="${id}" data-freq="${esc(freqKhz)}" data-mode="${esc(modeRaw)}"
                data-callsign="${esc(callsign)}" data-ref="${esc(ref)}" data-park="${esc(park)}">
      <td class="freq">${esc(freqKhz)}</td>
      <td class="mode">${esc(modeDisp)}</td>
      <td class="callsign"><a class="spot-link" href="https://pota.app/#/profile/${esc(callsign)}" target="_blank" data-tip="https://pota.app/#/profile/${esc(callsign)}">${esc(callsign)}</a></td>
      <td class="ref"><a class="spot-link" href="https://pota.app/#/park/${esc(ref)}" target="_blank" data-tip="https://pota.app/#/park/${esc(ref)}">${esc(ref)}</a>${hintHTML ? ' '+hintHTML : ''}</td>
      <td class="parktype" data-tip="${esc(parkTypeCache[ref] || '')}">${
        parkTypeCache[ref] === undefined ? '' :        // not yet fetched — blank
        parkTypeCache[ref] === null      ? '⏳' :      // fetch in-flight
        parkTypeEmoji(classifyParkType(parkTypeCache[ref]))  // resolved
      }</td>
      <td class="park" data-tip="${esc(park)}">${esc(park.length > 36 ? park.slice(0,34)+'…' : park)}</td>
      <td class="loc" data-tip="${esc(fmtLocationFull(loc))}">${esc(fmtLocation(loc))}</td>
      <td class="age ${age.cls}" data-tip="${fmtUTC(spotTime)}">${age.text}</td>
      <td class="new-spot" data-tip="New since last refresh">${isNew ? '&#9679;' : ''}</td>
    </tr>`;
  });

  tbody.innerHTML = rows.join('');
  updateMap(spots);

  // Re-apply the amber bar after every render() — render() rebuilds all
  // <tr> elements from scratch, wiping any classes.  If there is an active
  // spot, restore .scanning (and .active-scan if scanning is running) to the
  // matching row so the bar survives sort changes, filter changes, and
  // spot-list refreshes.
  if (activeSpotId !== null) {
    const activeRow = document.querySelector(`#spot-tbody tr[data-id="${activeSpotId}"]`);
    if (activeRow) {
      activeRow.classList.add('scanning');
      if (autoScanTimer) activeRow.classList.add('active-scan');
    }
  }
}

// ── Rig control routing ──────────────────────────────────
//
// The "Rig Control" dropdown controls which backend handles tune clicks:
//
//   mldx    — MacLoggerDX URL scheme (no proxy needed)
//               mldx://tune?freq=<MHz>&mode=<mode>
//               mldx://lookup?call=<callsign>
//               Ref: https://dogparksoftware.com/MacLoggerDX%20Help/mldxfc_script.html
//
//   flrig   — flrig XML-RPC via pota_proxy.py
//               GET http://localhost:8080/tune/flrig?freq=<kHz>&mode=<mode>
//               Proxy handles kHz→Hz conversion and XML-RPC call.
//               Ref: http://www.w1hkj.com/flrig-help/xmlrpc_commands.html
//
//   rigctld — Hamlib rigctld via pota_proxy.py  (stub, not yet implemented)
//               GET http://localhost:8080/tune/rigctld?freq=<kHz>&mode=<mode>
//
//   none    — Display only; logs the action but sends no commands.
//
// The proxy URL scheme is /tune/<backend>?freq=<kHz>&mode=<mode>.
// The backend name in the path makes routing explicit and extensible —
// new backends are added to pota_proxy.py without changing this URL structure.
//
// PROXY BASE URL — change this if you run pota_proxy.py on a non-default port.
const PROXY_BASE = 'http://localhost:8080';

// Show a styled modal dialog explaining a rig connectivity failure.
// Two distinct failure cases get different instructions:
//   proxyDown  — pota_proxy.py is not running at all
//   backendDown — proxy is running but it can't reach the rig software
function showRigError(backend, proxyDown, detail) {
  // Remove any existing dialog
  const old = document.getElementById('rig-error-dialog');
  if (old) old.remove();

  const backendLabel = {
    flrig:   'flrig',
    rigctld: 'rigctld (Hamlib)',
  }[backend] || backend;

  const proxyInstructions = `
    <p><strong>pota_proxy.py is not running.</strong></p>
    <p>Open a terminal and run:</p>
    <pre>python3 pota_proxy.py</pre>
    <p>The proxy must be running before you can use the
    <em>${backendLabel}</em> rig control backend.</p>`;

  const backendInstructions = `
    <p><strong>${backendLabel} is not reachable.</strong></p>
    <p>pota_proxy.py is running, but it cannot connect to
    <em>${backendLabel}</em>. Make sure:</p>
    <ul>
      <li>${backendLabel} is open and running on this machine.</li>
      <li>The radio (or a virtual serial port) is connected.</li>
      <li>${backendLabel} is configured to listen on the default port
          ${backend === 'flrig' ? '(12345)' : '(4532)'}.</li>
    </ul>
    ${backend === 'rigctld' ? `
    <p>To install Hamlib and start rigctld:</p>
    <pre>brew install hamlib          # macOS (Homebrew)
sudo apt install libhamlib-utils  # Linux
rigctld -m &lt;model&gt; -r /dev/ttyUSB0 &amp;</pre>
    <p>Find your radio's model number with: <code>rigctld -l</code></p>` : ''}
    ${detail ? '<p class="detail">Detail: ' + esc(detail) + '</p>' : ''}`;

  const dialog = document.createElement('div');
  dialog.id = 'rig-error-dialog';
  dialog.innerHTML = `
    <div id="rig-error-box">
      <div id="rig-error-title">&#9888; Rig Control — ${backendLabel} Unreachable</div>
      <div id="rig-error-body">
        ${proxyDown ? proxyInstructions : backendInstructions}
      </div>
      <div id="rig-error-footer">
        <button id="rig-error-close">Dismiss</button>
      </div>
    </div>`;
  document.body.appendChild(dialog);
  document.getElementById('rig-error-close').addEventListener('click', () => dialog.remove());
  // Also dismiss on backdrop click
  dialog.addEventListener('click', e => { if (e.target === dialog) dialog.remove(); });
}

// Show a blocking "Connecting…" overlay while a backend ping is in flight.
// This prevents the user from clicking spots or switching backends while
// we are waiting for a potentially slow TCP timeout (up to ~3-8 seconds).
function showConnecting(backendLabel) {
  const old = document.getElementById('connecting-overlay');
  if (old) old.remove();
  const div = document.createElement('div');
  div.id = 'connecting-overlay';
  div.innerHTML = `
    <div id="connecting-box">
      <span id="connecting-spinner">&#8635;</span>
      Connecting to ${backendLabel}…
    </div>`;
  document.body.appendChild(div);
}

function hideConnecting() {
  const el = document.getElementById('connecting-overlay');
  if (el) el.remove();
}

// Ping the proxy and show an error dialog on any failure.
// On failure, resets the dropdown to "None" so no rig control
// appears active when the backend can't be reached.
// Called whenever the rig-select dropdown changes.
async function pingRigBackend(backend) {
  const sel = document.getElementById('rig-select');

  // mldx and none don't use the proxy — nothing to ping
  if (backend === 'mldx' || backend === 'none') return;

  const backendLabel = { flrig: 'flrig', rigctld: 'rigctld' }[backend] || backend;

  // Block the UI while we wait — rigctld can take several seconds to
  // respond if the rig software is not running (TCP timeout).
  showConnecting(backendLabel);

  try {
    // Timeout is 8s: the proxy's rigctld socket timeout is 3s, so this
    // gives the proxy enough time to return a proper JSON error rather
    // than the browser's own fetch() timing out first (which would
    // incorrectly show "proxy not running" instead of "rigctld unreachable").
    const res  = await fetch(`${PROXY_BASE}/ping/${backend}`,
                             { signal: AbortSignal.timeout(8000) });
    const data = await res.json();
    hideConnecting();

    if (!data.ok) {
      sel.value = 'none';
      updateScanPills();
      showRigError(backend, false, data.error);
    }
  } catch (err) {
    hideConnecting();
    sel.value = 'none';
    updateScanPills();
    showRigError(backend, true, null);
  }
}

// ── tuneSpot — routes to the correct backend ─────────────
//
// freq and mode are always passed as the raw values from the
// POTA API (freq in kHz, mode as returned by the API).
// Each routing branch is responsible for any further conversion
// its target needs (MHz for mldx://, kHz passed straight to
// the proxy which converts to Hz internally).
//
function tuneSpot(evt, id, freqKhz, modeRaw, callsign, ref, park) {
  evt.stopPropagation();

  const modeDisp = resolveMode(modeRaw, freqKhz);
  const rig      = document.getElementById('rig-select').value;

  if (rig === 'mldx') {
    // ── MacLoggerDX via pota_proxy.py ────────────────────
    // All MacLoggerDX commands are sent through the proxy using
    // osascript on the server side.  This gives us setNOTE support
    // (not available via the mldx:// URL scheme) and avoids all
    // the popup-blocker and page-navigation issues of URL schemes.
    //
    // The proxy calls in sequence (with delay between 3 and 5):
    //   1. setLogFrequency <MHz>
    //   2. setLogMode <mode>
    //   3. lookup <callsign>        — async QRZ/HamCall lookup
    //   4. delay 1.5s               — wait for lookup to complete
    //   5. setNOTE <park ref+name>  — pre-fill the Note field
    //
    // Fallback: if the proxy is not running, fall back to the
    // mldx:// URL scheme for freq+mode+lookup only (no setNOTE).
    const noteText = ('POTA ' + ref + (park ? ' ' + park : '')).slice(0, 60);
    const url = `${PROXY_BASE}/tune/mldx` +
                `?freq=${encodeURIComponent(freqKhz)}` +
                `&mode=${encodeURIComponent(modeDisp)}` +
                `&callsign=${encodeURIComponent(callsign)}` +
                `&note=${encodeURIComponent(noteText)}`;

    fetch(url)
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          setStatus('ok',
            'Tuned via MacLoggerDX: ' + freqKhz + ' kHz  ' + modeDisp +
            '  ' + callsign + '  ' + ref);
        } else {
          setStatus('error', 'MacLoggerDX error: ' + (data.error || 'unknown'));
        }
      })
      .catch(() => {
        // Proxy not running — fall back to mldx:// URL scheme.
        // setNOTE is not available via URL scheme so only freq+mode+lookup.
        setStatus('waiting',
          'Proxy not running — using mldx:// fallback (Note field not set)');
        function fireMldxUrl(u) {
          const a = document.createElement('a');
          a.href = u; a.style.display = 'none';
          document.body.appendChild(a); a.click();
          setTimeout(() => a.remove(), 100);
        }
        fireMldxUrl('mldx://tune?freq=' + encodeURIComponent(khzToMhz(freqKhz)) +
                    '&mode=' + encodeURIComponent(modeDisp));
        setTimeout(() => {
          fireMldxUrl('mldx://lookup?call=' + encodeURIComponent(callsign));
        }, 400);
      });
    setStatus('waiting', 'Sending to MacLoggerDX…');

  } else if (rig === 'flrig' || rig === 'rigctld') {
    // ── Proxy backends (flrig, rigctld, …) ──────────────
    // Send freq in kHz; pota_proxy.py converts to Hz internally.
    // The backend name is embedded in the URL path so the proxy
    // log always shows which backend handled each request, and
    // adding a new backend never changes the URL structure.
    const url = `${PROXY_BASE}/tune/${rig}` +
                `?freq=${encodeURIComponent(freqKhz)}` +
                `&mode=${encodeURIComponent(modeDisp)}`;

    fetch(url)
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          setStatus('ok',
            'Tuned via ' + rig + ': ' + freqKhz + ' kHz  ' + modeDisp +
            '  ' + callsign + '  —  Park ref: ' + ref);
        } else {
          setStatus('error', rig + ' error: ' + (data.error || 'unknown error'));
        }
      })
      .catch(err => {
        setStatus('error',
          'Cannot reach proxy at ' + PROXY_BASE +
          ' — is pota_proxy.py running?  (' + err.message + ')');
      });

    setStatus('waiting', 'Sending to ' + rig + '…');

  } else {
    // ── None / display only ──────────────────────────────
    setStatus('ok',
      'Display only — no tune sent.  ' + freqKhz + ' kHz  ' +
      modeDisp + '  ' + callsign + '  ' + ref);
  }

  // render() rebuilds tbody.innerHTML so the .scanning class must be applied
  // AFTER render(), not before — otherwise render() destroys it immediately.
  render();

  // Update the active spot — moves the amber bar and keeps the map in sync.
  // Called after render() so the newly-built row elements are in the DOM.
  // This is the single place where a manual tune click sets the active spot,
  // which also becomes the auto-scan resume point.
  setActiveSpot(id);
}

// ── Row click tunes the spot ────────────────────────────
// Clicking anywhere on a row tunes the radio and sets the active spot.
// tuneSpot() calls setActiveSpot() which moves the amber bar and
// updates the map marker selection. We also pan the map to the spot.
document.getElementById('spot-tbody').addEventListener('click', e => {
  const row = e.target.closest('tr');
  if (!row) return;
  if (e.target.closest('a.spot-link')) return;
  const { id, freq, mode, callsign, ref, park } = row.dataset;
  const spotId = parseInt(id);
  tuneSpot(e, spotId, freq, mode, callsign, ref, park);
  // Pan map to this spot (setActiveSpot handles the marker selection,
  // mapPanToSpot handles the viewport pan and popup)
  mapPanToSpot(spotId);
});

// ── Map ──────────────────────────────────────────────────
//
// Uses Leaflet.js with OpenStreetMap tiles (no API key required).
// The map is hidden by default and toggled with the ⊕ Map button.
// It stays in sync with the filtered spot list via updateMap(),
// which is called at the end of render().
//
// Marker colours mirror the age-indicator scheme:
//   green  — fresh  (< 10 min)
//   #8eb88e — recent (10–60 min)
//   dim     — old   (> 60 min)
//
// Clicking a marker:
//   1. Opens a popup with callsign / freq / mode / park ref / park name
//   2. Highlights the matching table row and scrolls it into view
//   3. Tunes the radio (same as clicking the table row)
//
// Clicking a table row (via the existing listener above) pans and
// zooms the map to that spot's marker.

let leafletMap   = null;   // Leaflet map instance (created on first open)
let markersLayer = null;   // Leaflet LayerGroup holding all circle markers
let markerIndex  = {};     // spotId → Leaflet marker, rebuilt on each render

// Colour for a spot based on its age class
function markerColor(ageClass) {
  if (ageClass === 'fresh')  return '#39ff6a';
  if (ageClass === 'recent') return '#8eb88e';
  return '#2a3a2a';
}

// Build a Leaflet divIcon circle so we can colour it freely
function makeMarkerIcon(ageClass, selected) {
  const color  = markerColor(ageClass);
  const size   = selected ? 14 : 10;
  const shadow = selected
    ? `box-shadow:0 0 8px 3px rgba(57,255,106,0.7);` : '';
  return L.divIcon({
    className: '',
    html: `<div style="
      width:${size}px;height:${size}px;
      border-radius:50%;
      background:${color};
      border:2px solid ${selected ? '#fff' : 'rgba(0,0,0,0.5)'};
      ${shadow}
      box-sizing:border-box;
    "></div>`,
    iconSize:   [size, size],
    iconAnchor: [size/2, size/2],
    popupAnchor:[0, -(size/2 + 4)],
  });
}

// Initialise the Leaflet map exactly once, the first time the panel opens.
function initMap() {
  if (leafletMap) return;

  leafletMap = L.map('map-container', {
    center: [20, 0],
    zoom:   2,
    minZoom: 1,
    worldCopyJump: true,
    zoomControl: true,
  });

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a>',
    maxZoom: 18,
    // OSM tile policy requires a Referer header. When served from file://
    // the browser sends none by default, causing 403r errors on zoom.
    // strict-origin-when-cross-origin sends the origin as Referer for
    // cross-origin requests, which satisfies OSM's requirement.
    referrerPolicy: 'strict-origin-when-cross-origin',
  }).addTo(leafletMap);

  markersLayer = L.layerGroup().addTo(leafletMap);
}

// ── Active spot — unified selection model ────────────────
//
// setActiveSpot() is the single point of truth for changing which spot
// is "active".  It updates activeSpotId, applies the amber .scanning bar
// to the matching table row, and keeps the map marker selection in sync.
//
// Called from:
//   tuneSpot()       — when the user clicks a row
//   autoScanStep()   — as the scanner advances through the list
//   map marker click — when the user clicks a map marker
//
// The .scanning class persists after scan stops so the amber bar shows
// which spot the scan will resume from.  It is only cleared when
// setActiveSpot() moves it to a different row, or when no matching row
// exists in the current rendered list (spot expired/filtered out).
function setActiveSpot(spotId) {
  activeSpotId = spotId;

  // Move the amber bar to the new active row.
  document.querySelectorAll('tr.scanning').forEach(r => r.classList.remove('scanning'));
  const row = document.querySelector(`#spot-tbody tr[data-id="${spotId}"]`);
  if (row) {
    row.classList.add('scanning');
    row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // Keep the map marker selection in sync.
  // updateMap() uses activeSpotId directly, so just redraw markers.
  if (leafletMap) updateMap(lastRenderedSpots);
}

// Called by render() to keep the map in sync with the filtered spot list.
// renderedSpots is the same filtered+sorted array render() displays.
let lastRenderedSpots = [];

function updateMap(spots) {
  lastRenderedSpots = spots;
  if (!leafletMap) return;   // map not open yet — will be populated on open

  markersLayer.clearLayers();
  markerIndex = {};

  spots.forEach(s => {
    if (s.latitude == null || s.longitude == null) return;

    const freqKhz  = s.frequency || '';
    const modeRaw  = (s.mode || '').toUpperCase();
    const modeDisp = resolveMode(s.mode, freqKhz);
    const callsign = s.activator || '';
    const ref      = s.reference || '';
    const park     = s.name || '';
    const id       = s.spotId;
    const spotTime = parseSpotTime(s.spotTime);
    const age      = spotAge(spotTime);
    const selected = (id === activeSpotId);

    const marker = L.marker([s.latitude, s.longitude], {
      icon: makeMarkerIcon(age.cls, selected),
      title: callsign + ' – ' + ref,
    });

    // Popup content — callsign and ref are clickable links matching the table
    const popupHtml = `
      <div class="map-popup-call">
        <a class="spot-link" href="https://pota.app/#/profile/${esc(callsign)}"
           target="_blank" title="POTA profile: ${esc(callsign)}">${esc(callsign)}</a>
      </div>
      <div class="map-popup-freq">${esc(freqKhz)} kHz &nbsp; ${esc(modeDisp)}</div>
      <div class="map-popup-ref">
        <a class="spot-link" href="https://pota.app/#/park/${esc(ref)}"
           target="_blank" title="POTA park: ${esc(ref)}">${esc(ref)}</a>
      </div>
      <div class="map-popup-park" title="${esc(park)}">${esc(park.length > 30 ? park.slice(0,28)+'…' : park)}</div>`;

    marker.bindPopup(popupHtml, { maxWidth: 240, autoPan: false });

    // Hover: open popup without tuning
    marker.on('mouseover', () => {
      marker.openPopup();
    });

    // Mouse out: close popup only if this marker wasn't clicked/selected
    marker.on('mouseout', () => {
      if (activeSpotId !== id) {
        marker.closePopup();
      }
    });

    marker.on('click', () => {
      // Tune the radio and set this as the active spot.
      // setActiveSpot() handles the amber bar, map redraw, and scroll.
      const fakeEvt = { stopPropagation: () => {} };
      tuneSpot(fakeEvt, id, freqKhz, modeRaw, callsign, ref, park);
      // Re-open popup on the new marker after redraw (updateMap redraws markers)
      const newMarker = markerIndex[id];
      if (newMarker) newMarker.openPopup();
    });

    marker.addTo(markersLayer);
    markerIndex[id] = marker;
  });

  // Update the map toolbar count
  const countEl = document.getElementById('map-spot-count');
  if (countEl) {
    const n = Object.keys(markerIndex).length;
    countEl.textContent = n + ' park' + (n !== 1 ? 's' : '') + ' on map';
  }
}

// Pan/zoom the map to a specific spot (called when a table row is clicked).
function mapPanToSpot(spotId) {
  if (!leafletMap) return;
  const spot = lastRenderedSpots.find(s => s.spotId === spotId);
  if (!spot || spot.latitude == null) return;

  // activeSpotId is already set by setActiveSpot() before this is called;
  // we just need to pan the map view and open the popup.
  leafletMap.setView([spot.latitude, spot.longitude], Math.max(leafletMap.getZoom(), 5), {
    animate: true,
  });

  // Open popup after the map redraws (markers already updated by setActiveSpot)
  requestAnimationFrame(() => {
    const marker = markerIndex[spotId];
    if (marker) marker.openPopup();
  });
}

// ── Resizable split pane ─────────────────────────────────
//
// The split area (table + map) fills all remaining vertical space.
// Heights are tracked as a percentage split: tableRatio is the
// fraction of split-area height given to the table (0.25–0.75).
// The map always gets the remainder.  Both panes have a 25% min.
//
// When the map is hidden the table simply gets 100% of the area.

const SPLIT_MIN = 0.05;   // neither pane may be smaller than 5%
let tableRatio  = 0.75;   // default: table 75%, map 25%
let mapIsOpen   = false;

function applySplit() {
  const splitArea   = document.getElementById('split-area');
  const tableWrap   = document.getElementById('table-wrap');
  const mapPanel    = document.getElementById('map-panel');
  const divider     = document.getElementById('split-divider');
  const totalH      = splitArea.clientHeight;

  if (!mapIsOpen) {
    tableWrap.style.height = totalH + 'px';
    mapPanel.style.height  = '0';
    divider.classList.remove('visible');
    return;
  }

  divider.classList.add('visible');
  const divH    = divider.offsetHeight;
  const usable  = totalH - divH;
  const tableH  = Math.round(usable * tableRatio);
  const mapH    = usable - tableH;

  tableWrap.style.height = tableH + 'px';
  mapPanel.style.height  = mapH  + 'px';

  if (leafletMap) leafletMap.invalidateSize();
}

// Reapply split whenever window resizes
window.addEventListener('resize', applySplit);

// ── Drag logic ───────────────────────────────────────────
(function() {
  const divider = document.getElementById('split-divider');
  let dragging  = false;
  let startY    = 0;
  let startRatio = 0;

  divider.addEventListener('mousedown', e => {
    dragging   = true;
    startY     = e.clientY;
    startRatio = tableRatio;
    divider.classList.add('dragging');
    document.body.style.cursor        = 'ns-resize';
    document.body.style.userSelect    = 'none';
    document.body.style.pointerEvents = 'none';
    divider.style.pointerEvents       = 'auto';
    e.preventDefault();
  });

  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const splitArea = document.getElementById('split-area');
    const totalH    = splitArea.clientHeight - document.getElementById('split-divider').offsetHeight;
    const delta     = e.clientY - startY;
    let newRatio    = startRatio + delta / totalH;
    newRatio        = Math.max(SPLIT_MIN, Math.min(1 - SPLIT_MIN, newRatio));
    tableRatio      = newRatio;
    applySplit();
  });

  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    divider.classList.remove('dragging');
    document.body.style.cursor        = '';
    document.body.style.userSelect    = '';
    document.body.style.pointerEvents = '';
    divider.style.pointerEvents       = '';
  });
})();

// ── Open / close map ─────────────────────────────────────
function closeMap() {
  mapIsOpen = false;
  document.getElementById('map-panel').classList.remove('open');
  document.getElementById('btn-map').classList.remove('active');
  applySplit();
}

function openMap() {
  mapIsOpen = true;
  document.getElementById('map-panel').classList.add('open');
  document.getElementById('btn-map').classList.add('active');

  if (!leafletMap) initMap();

  applySplit();

  // Belt-and-suspenders: fire invalidateSize a few times after paint
  [100, 300, 600].forEach(ms => setTimeout(() => {
    if (leafletMap) leafletMap.invalidateSize();
  }, ms));

  setTimeout(() => updateMap(lastRenderedSpots), 150);
}

document.getElementById('btn-map').addEventListener('click', () => {
  if (mapIsOpen) closeMap(); else openMap();
});

document.getElementById('map-close').addEventListener('click', closeMap);

document.getElementById('band-select').addEventListener('change', render);
document.getElementById('mode-select').addEventListener('change', render);
document.getElementById('refresh-interval').addEventListener('change', startAutoRefresh);

// ── Custom tooltip ───────────────────────────────────────
// Replaces native title= tooltips. Elements use data-tip="..." instead.
// Event delegation on document — one mousemove listener handles everything.
// 300ms delay feels responsive without flashing on accidental hover.
const tooltipEl = document.getElementById('tooltip');
let tooltipTimer = null;
let tooltipTarget = null;  // track current hovered element to detect changes

function showTooltip(text, x, y) {
  tooltipEl.textContent = text;
  tooltipEl.classList.add('visible');
  positionTooltip(x, y);
}

function positionTooltip(x, y) {
  // Keep tooltip within viewport — flip left if too close to right edge
  const pad = 12;
  const tw = tooltipEl.offsetWidth;
  const left = (x + pad + tw > window.innerWidth) ? x - tw - pad : x + pad;
  tooltipEl.style.left = left + 'px';
  tooltipEl.style.top  = (y + pad) + 'px';
}

function hideTooltip() {
  clearTimeout(tooltipTimer);
  tooltipTimer = null;
  tooltipTarget = null;
  tooltipEl.classList.remove('visible');
}

document.addEventListener('mousemove', e => {
  const el = e.target.closest('[data-tip]');

  // If we've moved to a different element (or no element), reset
  if (el !== tooltipTarget) {
    hideTooltip();
    tooltipTarget = el;
  }

  if (!el || !el.dataset.tip) return;

  // Reposition if already visible
  if (tooltipEl.classList.contains('visible')) {
    positionTooltip(e.clientX, e.clientY);
    return;
  }

  // Start delay timer for new element
  clearTimeout(tooltipTimer);
  tooltipTimer = setTimeout(() => showTooltip(el.dataset.tip, e.clientX, e.clientY), 300);
});

document.addEventListener('mouseleave', hideTooltip);

// When the rig backend changes, ping it immediately so the operator
// gets instant feedback on whether the proxy / rig software is running.
// On failure, pingRigBackend resets the dropdown to "none" automatically.
document.getElementById('rig-select').addEventListener('change', e => {
  pingRigBackend(e.target.value);
  updateScanPills();
});

document.getElementById('btn-refresh').addEventListener('click', () => {
  if (!document.getElementById('btn-refresh').classList.contains('spinning')) {
    fetchSpots();
  }
});

// ── Column header sort ───────────────────────────────────
// Clicking a sortable header (any th with data-col) sets that column as
// the sort key.  Clicking the same column again reverses the direction.
// sortCol and sortDir persist across filter changes — the sort preference
// is never reset by a band/mode change or spot-list refresh.
document.querySelectorAll('th[data-col]').forEach(th => {
  th.addEventListener('click', () => {
    const col = th.dataset.col;
    if (sortCol === col) {
      // Same column — toggle direction
      sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      // New column — default direction: asc for strings, desc for time
      // (newest-first is the natural default for time)
      sortCol = col;
      sortDir = col === 'time' ? 'desc' : 'asc';
    }
    render();
  });
});

// ── Auto-refresh — driven by the interval dropdown ───────
// Choices: 2, 5, 10, 15, 30, 60 minutes, or 0 = manual only.
// The timer is cancelled and restarted whenever the selection
// changes, so the new interval takes effect immediately.
// We never auto-refresh when the tab is hidden (document.hidden)
// to avoid waking the network unnecessarily.
let autoRefreshTimer = null;

function startAutoRefresh() {
  if (autoRefreshTimer) {
    clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
  }
  const minutes = parseInt(document.getElementById('refresh-interval').value, 10);
  if (minutes > 0) {
    autoRefreshTimer = setInterval(() => {
      if (!document.hidden) fetchSpots();
    }, minutes * 60 * 1000);
  }
  updateRefreshLabel();
}

function updateRefreshLabel() {
  const minutes = parseInt(document.getElementById('refresh-interval').value, 10);
  const el = document.getElementById('last-fetch');
  const fetchStr = lastFetch ? 'Last fetch: ' + fmtUTC(lastFetch) : '';
  const intervalStr = minutes > 0
    ? '  |  Auto-refresh: every ' + minutes + ' min'
    : '  |  Auto-refresh: off';
  el.textContent = fetchStr + intervalStr;
}

// ── Auto-scan ────────────────────────────────────────────
//
// The pill control lets the operator automatically cycle through every
// visible (filtered+sorted) spot, dwelling on each for a configurable
// number of seconds.  This is the "band scanner" feature: let the app
// step through spots while you listen for a station you can actually hear.
//
// State machine
// -------------
//   OFF  →  user clicks a dwell pill          → start scanning at that dwell
//   ON   →  user clicks a different dwell pill → keep scanning, new dwell
//   ON   →  user clicks the ACTIVE dwell pill  → stop (toggle off)
//   ON   →  user clicks OFF pill               → stop
//   ON   →  any other click or keypress        → stop
//
// Auto-tune vs manual tune
// ------------------------
// During auto-scan, tuneSpot() is called exactly as if the user clicked
// a row. Auto-scan does NOT mark spots as worked — it just tunes the radio.
// permanently mark spots as "worked", only the user's deliberate click does.
//
// Scan resume behaviour
// ----------------------
// activeSpotId persists across scan stop/start.  When a scan is started,
// autoScanStart() looks up activeSpotId in lastRenderedSpots:
//   - Found  → resume from that spot
//   - Not found / null → start from index 0
// This means interrupting a scan and restarting always picks up where
// you left off, and clicking a row while not scanning sets the start point.
//
// Spot list refresh during scan
// ------------------------------
// The scan continues from the current autoScanIndex in the new list.
// If the index is past the end of the new list it wraps to 0.
// If the active spot disappears from the list on next scan start,
// the scan restarts from index 0.

let autoScanTimer   = null;   // setInterval handle
let autoScanIndex   = 0;      // index into the currently rendered spot list
let autoScanDwell   = 0;      // active dwell in seconds (0 = off)

// The rendered spot list is already tracked as lastRenderedSpots.
// We use that directly so auto-scan always works on whatever is visible
// after filters, including after a spot-list refresh.

function autoScanStart(dwellSecs) {
  autoScanStop(false);   // clear any existing timer without resetting pills

  autoScanDwell = dwellSecs;

  // Resume from the active spot if it's still in the current list,
  // otherwise start from the beginning.
  // This means: if the user interrupted a scan, or clicked a row while
  // not scanning, the scan picks up from the amber bar's current position.
  const resumeIndex = activeSpotId !== null
    ? lastRenderedSpots.findIndex(s => s.spotId === activeSpotId)
    : -1;
  autoScanIndex = resumeIndex >= 0 ? resumeIndex : 0;

  // Tune the active spot immediately, then start the interval
  autoScanStep();

  autoScanTimer = setInterval(() => {
    autoScanIndex++;
    if (autoScanIndex >= lastRenderedSpots.length) autoScanIndex = 0;
    autoScanStep();
  }, dwellSecs * 1000);

  updateScanPills();
}

function autoScanStep() {
  if (!lastRenderedSpots.length) return;
  if (autoScanIndex >= lastRenderedSpots.length) autoScanIndex = 0;

  const s        = lastRenderedSpots[autoScanIndex];
  const freqKhz  = s.frequency || '';
  const modeRaw  = (s.mode || '').toUpperCase();
  const callsign = s.activator || '';
  const ref      = s.reference || '';
  const park     = s.name || '';

  // tuneSpot() handles rig control, render(), and setActiveSpot() internally.
  // NOTE: do NOT call render() again after tuneSpot() — it already does so.
  const fakeEvt = { stopPropagation: () => {} };
  tuneSpot(fakeEvt, s.spotId, freqKhz, modeRaw, callsign, ref, park);

  // Mark the row as actively scanning (adds pulse animation).
  // setActiveSpot() (called inside tuneSpot) applied .scanning;
  // we now also add .active-scan so the bar pulses while scanning is running.
  const scanRow = document.querySelector(`#spot-tbody tr[data-id="${s.spotId}"]`);
  if (scanRow) scanRow.classList.add('active-scan');

  // Pan the map to this spot if the map is open.
  // The amber bar and marker selection are already handled by setActiveSpot()
  // (called inside tuneSpot above).
  mapPanToSpot(s.spotId);
}

// stop: if resetPills is true (default), reset pill UI to OFF.
// Pass false when changing dwell mid-scan so we update pills separately.
//
// NOTE: we deliberately do NOT clear the .scanning class here.
// The amber bar stays on the last active spot so the user can see
// where the scan will resume from when they start it again.
// The bar is only moved (not cleared) by the next setActiveSpot() call.
function autoScanStop(resetPills = true) {
  if (autoScanTimer) {
    clearInterval(autoScanTimer);
    autoScanTimer = null;
  }
  autoScanDwell = 0;
  // Remove the pulse animation — bar stays solid on the last active spot
  // so the user can see the resume point, but it no longer pulses.
  document.querySelectorAll('tr.active-scan').forEach(r => r.classList.remove('active-scan'));
  if (resetPills) updateScanPills();
}

function updateScanPills() {
  const rigIsNone = document.getElementById('rig-select').value === 'none';
  const pillsEl = document.getElementById('auto-scan-pills');
  // Show tooltip on the container when disabled — disabled buttons don't
  // fire mouse events so we can't put data-tip on the buttons themselves.
  if (rigIsNone) {
    pillsEl.dataset.tip = 'Select a rig backend to enable Auto Scan';
  } else {
    delete pillsEl.dataset.tip;
  }
  document.querySelectorAll('.scan-pill').forEach(btn => {
    const d = parseInt(btn.dataset.dwell, 10);
    btn.disabled = rigIsNone && d !== 0;
    btn.classList.toggle('active', d === autoScanDwell);
    if (d === 0) {
      btn.classList.toggle('scanning-active', autoScanDwell !== 0);
    }
  });
}

// Pill click handler
document.getElementById('auto-scan-pills').addEventListener('click', e => {
  const pill = e.target.closest('.scan-pill');
  if (!pill) return;

  // This is a deliberate pill interaction — don't let the global
  // "any click stops scan" listener fire for this same event.
  e.stopPropagation();

  const dwell = parseInt(pill.dataset.dwell, 10);

  if (dwell === 0) {
    // OFF pill — always stop
    autoScanStop();
    return;
  }

  if (dwell === autoScanDwell) {
    // Clicking the active pill toggles it off
    autoScanStop();
    return;
  }

  // Clicking a different dwell pill — start or change dwell
  autoScanStart(dwell);
});

// Only stop auto-scan when the user clicks a spot row or interacts with
// the auto-scan pill control. Clicks elsewhere (map resize, filters,
// header buttons) are ignored so the user can adjust the UI mid-scan.
document.addEventListener('click', e => {
  if (!autoScanTimer) return;
  if (e.target.closest('#auto-scan-pills')) return;  // handled by pill listener
  if (e.target.closest('#spot-tbody')) autoScanStop();  // clicking a spot stops scan
}, true);

// ── Startup: require proxy to be running ─────────────────
//
// The proxy is not optional.  On every page load we ping it before
// doing anything else.  If it responds we proceed normally.
// If it does not respond we block the entire UI and show a clear
// error explaining how to start pota_proxy.py.
//
// This covers all four scenarios:
//   1. Proxy started first, opens browser automatically → ping succeeds.
//   2. Browser opened while proxy is running → ping succeeds.
//   3. Browser opened with no proxy → ping fails → error shown.
//   4. Proxy was running, user closed the tab, re-opens it → ping
//      succeeds because the proxy is still running.
//
async function startupProxyCheck() {
  setStatus('loading', 'Connecting to pota_proxy.py…');

  try {
    // Fetch the proxy version and the mldx ping in parallel so startup
    // is no slower than before. The version endpoint is always available
    // as long as the proxy is running, regardless of rig backend.
    const [versionRes, pingRes] = await Promise.all([
      fetch(`${PROXY_BASE}/version`, { signal: AbortSignal.timeout(3000) }),
      fetch(`${PROXY_BASE}/ping/mldx`, { signal: AbortSignal.timeout(3000) }),
    ]);

    const versionData = await versionRes.json();
    const data        = await pingRes.json();

    // Display the version in the header logo area.
    const verLabel = document.getElementById('version-label');
    if (verLabel && versionData.version) {
      verLabel.textContent = 'v' + versionData.version;
    }

    if (data.ok) {
      // Proxy is up and MacLoggerDX is reachable — proceed normally.
      setStatus('ok', 'Connected to proxy  ·  MacLoggerDX v' + (data.version || '?'));

      // Start auto-refresh timer and load initial spot data.
      startAutoRefresh();
      fetchSpots().then(() => openMap());

    } else {
      // Proxy is up but MacLoggerDX is not running.
      // Still let the page load — the operator may want to
      // browse spots and switch to a different backend.
      setStatus('error', 'Proxy running but MacLoggerDX unreachable: ' + (data.error || ''));
      showRigError('mldx', false, data.error);
      startAutoRefresh();
      fetchSpots().then(() => openMap());
    }

  } catch (err) {
    // Proxy is not running at all — block the UI entirely.
    showProxyDownError();
  }
}

// Show a full-screen blocking error when the proxy cannot be reached.
// This replaces the normal UI so the user cannot accidentally try to
// use the app without the proxy.
function showProxyDownError() {
  setStatus('error', 'pota_proxy.py is not running');

  // Dim the app and overlay a blocking message.
  // We do not use the standard rig-error modal here because we want
  // something more prominent that covers the whole interface.
  document.getElementById('app').style.filter = 'blur(3px) opacity(0.3)';

  const overlay = document.createElement('div');
  overlay.id = 'proxy-down-overlay';
  overlay.innerHTML = `
    <div id="proxy-down-box">
      <div id="proxy-down-icon">&#9888;</div>
      <div id="proxy-down-title">POTA Spot Hunter requires pota_proxy.py</div>
      <div id="proxy-down-body">
        <p>The local proxy server is not running. The proxy is required to:</p>
        <ul>
          <li>Control MacLoggerDX (set frequency, mode, callsign, and note)</li>
          <li>Interface with flrig and rigctld rig-control backends</li>
        </ul>
        <p><strong>To start the proxy, open a terminal and run:</strong></p>
        <pre>python3 pota_proxy.py</pre>
        <p>The proxy will automatically open this page in your browser
           once it is ready. You can also reload this page after
           starting the proxy.</p>
        <p class="note">pota_proxy.py must be in the same folder as
           POTASpotHunter.html.</p>
      </div>
      <div id="proxy-down-footer">
        <button id="proxy-down-retry">&#8635; Retry</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  document.getElementById('proxy-down-retry').addEventListener('click', async () => {
    overlay.remove();
    document.getElementById('app').style.filter = '';
    await startupProxyCheck();
  });
}

// ── Time-based award hint helpers ────────────────────────

// Returns a Set of hint codes that apply to a spot right now.
// Codes: 'lateshift', 'earlyshift', 'newyears', 'supportyourparks', 'newendo'
//
// Early Shift: 6-hour window starting at (2 - lon/15) UTC, rounded to hour
// Late Shift:  8-hour window starting at (18 - lon/15) UTC, rounded to hour
// Source: https://docs.pota.app/docs/awards.html
function spotAwardHints(spot) {
  const hints = new Set();
  const now = new Date();
  const utcH = now.getUTCHours() + now.getUTCMinutes() / 60;
  const utcMonth = now.getUTCMonth() + 1; // 1-12
  const utcDay   = now.getUTCDate();
  const utcDow   = now.getUTCDay(); // 0=Sun

  // New Years Hunter: Jan 1–7
  if (utcMonth === 1 && utcDay >= 1 && utcDay <= 7) hints.add('newyears');

  // Support Your Parks: 3rd full weekend of Jan/Apr/Jul/Oct
  // 3rd weekend = Sat/Sun where the Saturday is the 15th–21st of the month
  if ([1, 4, 7, 10].includes(utcMonth) && (utcDow === 0 || utcDow === 6)) {
    const sat = utcDow === 6 ? utcDay : utcDay - 1;
    if (sat >= 15 && sat <= 21) hints.add('supportyourparks');
  }

  // Shift awards — need park longitude
  const lon = spot.longitude;
  if (lon != null) {
    const earlyStart = Math.round(2  - lon / 15);
    const lateStart  = Math.round(18 - lon / 15);
    const eStart = ((earlyStart % 24) + 24) % 24;
    const lStart = ((lateStart  % 24) + 24) % 24;
    const inWindow = (start, duration) => {
      const end = (start + duration) % 24;
      return start < end
        ? utcH >= start && utcH < end
        : utcH >= start || utcH < end;
    };
    if (inWindow(eStart, 6)) hints.add('earlyshift');
    if (inWindow(lStart, 8)) hints.add('lateshift');
  }

  // Endorsement hint — only if hunter profile is loaded
  if (hunterProfile) {
    const awards = hunterProfile.awards ?? [];
    // Find highest earned hunter tier
    const parks = hunterProfile.stats?.hunter?.parks ?? 0;
    let currentTierName = null;
    for (const t of AWARD_TIERS) {
      if (parks >= t.parks) currentTierName = t.name;
    }
    if (currentTierName) {
      const entry = awards.find(a => a.name === currentTierName);
      const endorsements = entry ? entry.endorsements : [];
      const band = bandOf(spot.frequency);
      if (band && !endorsements.includes(band + 'M')) hints.add('newendo');
    }
  }

  return hints;
}

// Render hint icons as a small HTML string with tooltip
function renderHintIcons(hints) {
  const s = 'style="margin-left:5px"';
  const icons = [];
  if (hints.has('lateshift'))        icons.push(`<span ${s} data-tip="Late Shift window active — counts toward Late Shift Hunter award">🌙</span>`);
  if (hints.has('earlyshift'))       icons.push(`<span ${s} data-tip="Early Shift window active — counts toward Early Shift Hunter award">🌅</span>`);
  if (hints.has('newyears'))         icons.push(`<span ${s} data-tip="New Years week (Jan 1–7) — counts toward New Years Hunter award">🎆</span>`);
  if (hints.has('supportyourparks')) icons.push(`<span ${s} data-tip="Support Your Parks event weekend — counts toward Support Your Parks Hunter award">🎪</span>`);
  if (hints.has('newendo'))          icons.push(`<span ${s} data-tip="You have no endorsement on this band yet — working this spot could help earn one">✨</span>`);
  return icons.join('');
}

// Award tier ladder — hunter parks required for each tier.
const AWARD_TIERS = [
  { name: 'Bronze Hunter',                    parks: 10   },
  { name: 'Silver Hunter',                    parks: 20   },
  { name: 'Gold Hunter',                      parks: 30   },
  { name: 'Platinum Hunter',                  parks: 40   },
  { name: 'Diamond Hunter',                   parks: 50   },
  { name: 'Sapphire Hunter',                  parks: 75   },
  { name: 'Arizona Agave Hunter',             parks: 100  },
  { name: 'Enrubio Hunter',                   parks: 200  },
  { name: 'Ouachita Mountain Goldenrod Hunter', parks: 300 },
  { name: 'Stenogyne Kanehoana Hunter',       parks: 400  },
  { name: "Howell's Spectacular Thelypody Hunter", parks: 500 },
  { name: 'Texas Wild Rice Hunter',           parks: 600  },
  { name: "Wiggin's Acalypha Hunter",         parks: 700  },
  { name: 'Georgia Aster Hunter',             parks: 800  },
  { name: 'Rafflesia Flower Hunter',          parks: 900  },
  { name: 'Western Prairie Fringed Orchid Hunter', parks: 1000 },
];

let hunterProfile = null;  // cached profile from api.pota.app/profile/<call>

async function loadHunterProfile(callsign) {
  try {
    const r = await fetch(`https://api.pota.app/profile/${encodeURIComponent(callsign)}`);
    if (!r.ok) return null;
    return await r.json();
  } catch (e) {
    return null;
  }
}

function renderAwardsBadge() {
  const btn = document.getElementById('btn-awards');
  const call = localStorage.getItem('hunterCallsign');
  if (!call) {
    btn.textContent = '🏆 Track Awards';
    return;
  }
  if (!hunterProfile) {
    btn.textContent = `🏆 ${call} · …`;
    return;
  }
  const parks = hunterProfile.stats?.hunter?.parks ?? 0;
  // Find highest earned tier
  let tierName = 'Unranked';
  for (const t of AWARD_TIERS) {
    if (parks >= t.parks) tierName = t.name.replace(' Hunter', '');
  }
  btn.textContent = `🏆 ${call} · ${tierName}`;
}

function renderAwardsPopover() {
  const el = document.getElementById('awards-progress');
  const call = localStorage.getItem('hunterCallsign');
  if (!call || !hunterProfile) {
    el.innerHTML = '<span style="color:var(--text-dim);font-size:12px">Enter your callsign to see award progress.</span>';
    return;
  }

  const parks = hunterProfile.stats?.hunter?.parks ?? 0;
  const qsos  = hunterProfile.stats?.hunter?.qsos  ?? 0;

  // Find current and next tier
  let currentTier = null, nextTier = null;
  for (let i = 0; i < AWARD_TIERS.length; i++) {
    if (parks >= AWARD_TIERS[i].parks) currentTier = AWARD_TIERS[i];
    else if (!nextTier) nextTier = AWARD_TIERS[i];
  }

  // Progress bar
  const prevParks = currentTier ? currentTier.parks : 0;
  const nextParks = nextTier ? nextTier.parks : (currentTier ? currentTier.parks : 10);
  const pct = nextTier ? Math.round(((parks - prevParks) / (nextParks - prevParks)) * 100) : 100;

  // Endorsements from profile awards array
  const earnedAwards = hunterProfile.awards ?? [];
  const currentAwardEntry = earnedAwards.find(a => currentTier && a.name === currentTier.name);
  const endorsements = currentAwardEntry ? currentAwardEntry.endorsements : [];
  const allBands = ['160M','80M','60M','40M','30M','20M','17M','15M','12M','10M','6M','2M'];
  const allModes = ['CW','DATA','PHONE','FT8','FT4'];

  const endoHTML = [...allBands, ...allModes].map(e => {
    const have = endorsements.includes(e);
    return `<span class="${have ? 'have' : 'need'}" data-tip="${have ? 'Earned' : 'Not yet earned'}">${e}</span>`;
  }).join(' ');

  el.innerHTML = `
    <div style="margin-bottom:6px">
      <span style="color:var(--text-dim)">Hunter parks: </span>
      <strong style="color:var(--green)">${parks}</strong>
      <span style="color:var(--text-dim)"> · QSOs: ${qsos}</span>
    </div>
    ${currentTier ? `<div class="awards-tier-name">${currentTier.name}</div>` : '<div style="color:var(--text-dim)">No tier yet</div>'}
    ${nextTier ? `
      <div style="color:var(--text-dim);margin-top:2px">
        Next: ${nextTier.name} (${nextTier.parks} parks) — ${nextTier.parks - parks} to go
      </div>
      <div class="awards-progress-bar">
        <div class="awards-progress-fill" style="width:${pct}%"></div>
      </div>
    ` : '<div style="color:var(--green);margin-top:4px">Maximum standard tier reached!</div>'}
    ${currentTier ? `
      <div class="awards-endorsements">
        <span style="color:var(--text-dim)">Endorsements on ${currentTier.name.replace(' Hunter','')}:</span><br>
        ${endoHTML}
      </div>
    ` : ''}
  `;
}

// Toggle popover open/close
document.getElementById('btn-awards').addEventListener('click', e => {
  e.stopPropagation();
  const pop = document.getElementById('awards-popover');
  const btn = document.getElementById('btn-awards');
  const isOpen = pop.classList.toggle('open');
  btn.classList.toggle('active', isOpen);
  if (isOpen) {
    renderAwardsPopover();
    document.getElementById('awards-callsign-input').value =
      localStorage.getItem('hunterCallsign') ?? '';
  }
});

// Save callsign and reload profile
document.getElementById('awards-callsign-save').addEventListener('click', async () => {
  const input = document.getElementById('awards-callsign-input');
  const call = input.value.trim().toUpperCase();
  if (!call) {
    localStorage.removeItem('hunterCallsign');
    hunterProfile = null;
    renderAwardsBadge();
    renderAwardsPopover();
    render();
    return;
  }
  localStorage.setItem('hunterCallsign', call);
  hunterProfile = null;
  renderAwardsBadge();
  hunterProfile = await loadHunterProfile(call);
  renderAwardsBadge();
  renderAwardsPopover();
  render();
});

// Also save on Enter key in the input
document.getElementById('awards-callsign-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('awards-callsign-save').click();
});

// Close popover when clicking outside
document.addEventListener('click', e => {
  const pop = document.getElementById('awards-popover');
  if (pop.classList.contains('open') &&
      !document.getElementById('btn-awards').parentElement.contains(e.target)) {
    pop.classList.remove('open');
    document.getElementById('btn-awards').classList.remove('active');
  }
});

// Kick off the startup check.  Everything else waits for this.
// Note: the rig dropdown defaults to "none" (set in the HTML), so
// startupProxyCheck only needs to ping mldx — it does not need to
// seed any previous-value tracker since pingRigBackend always falls
// back to 'none' on error rather than a stored previous value.
startupProxyCheck();
updateScanPills();  // disable scan pills if rig starts as None

// Load hunter profile on startup if callsign is stored
(async () => {
  const call = localStorage.getItem('hunterCallsign');
  if (call) {
    renderAwardsBadge();  // show "🏆 W7GFW · …" while loading
    hunterProfile = await loadHunterProfile(call);
    renderAwardsBadge();
    render();
  }
})();
