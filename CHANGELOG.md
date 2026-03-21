## [1.0.0] - 2025-03-14
### Added
- Initial release
- MacLoggerDX, flrig, rigctld backends
- Band/mode filtering and sorting

## [1.1.0] - 2025-03-16
### Added
- All active spots are plotted on a live world map, filtered and sorted to match whatever you have selected in the controls
- The divider between the spot list and the map is draggable — resize to taste; neither pane can shrink below 25%
- Hover over any marker to see a popup with callsign, frequency, mode, park reference, and park name
- Click any marker to tune your radio — identical to clicking a row in the spot list
- Marker colour matches the age indicator: green = fresh, dim green = recent, dark = old
- Clicking a table row pans and zooms the map to that park and highlights the marker

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

### Changed
- **Amber bar is now solid when not scanning** — the left-edge amber bar
  persists on the last active spot after a scan stops or the user clicks a
  row, giving a clear visual indication of the auto-scan resume point. The
  bar only pulses while auto-scan is actively running; it is solid at rest.
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
