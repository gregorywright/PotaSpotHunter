# TODO.md — POTA Spot Hunter
## Future feature ideas and implementation plans

---

## Log4OM backend

Support Log4OM as another backend logging program. Log4OM is Windows-only,
which complements MacLoggerDX (macOS-only) and expands coverage to the larger
Windows ham radio audience. Goal: best-possible feature parity with the MLDX
backend within the constraints of what Log4OM's API exposes.

### Research complete — API summary

Log4OM communicates via **UDP only** (no AppleScript, no XML-RPC, no REST).
Three relevant interfaces:

#### 1. Remote Control Interface v1.1 — UDP XML on port 2241 (inbound)
Send XML datagrams to control Log4OM. This is the tune/lookup path.

```xml
<RemoteControlRequest>
  <MessageId>C0FC027F-D09E-49F5-9CA6-33A11E05A053</MessageId>
  <RemoteControlMessage>SetTxFrequency</RemoteControlMessage>
  <Frequency>14075000</Frequency>   <!-- Hz -->
</RemoteControlRequest>
```

Known commands:

| Command | Status | Notes |
|---|---|---|
| `SetTxFrequency` | ✅ Works | Frequency in Hz |
| `SetRxFrequency` | ✅ Works | Frequency in Hz |
| `SetCallsign` | ✅ Works | Sets callsign field AND auto-triggers QRZ lookup |
| `ClearUI` | ✅ Works | Clears callsign/UI fields |
| `SetMode` | ⚠️ Broken | Reportedly non-functional as of Oct 2025 |
| `GetRadioStatus` | ⚠️ Broken | Causes XML parse errors |

Official spec PDF: https://www.log4om.com/l4ong/usermanual/RemoteControlInterface_1_1.pdf
Forum discussion: https://forum.log4om.com/viewtopic.php?t=9984

#### 2. UDP ADIF Inbound — configurable port (typically 2235–2236)
Send an ADIF-formatted UDP packet to log a QSO directly into the log.
Used for logging integrations (WSJT-X, JTAlert, N1MM, etc.), not for UI control.

#### 3. UDP Outbound Broadcasts — N1MM XML `<contactinfo>` format
Log4OM broadcasts a QSO notification on every logged contact, in the
N1MM `<contactinfo>` XML format on a configurable port (default 12060).
Key fields: `call`, `band`, `rxfreq`/`txfreq` (in tens of Hz), `mode`, `timestamp`, `mycall`.
This is equivalent to MLDX's UDP "Log Report" on port 9932.

N1MM format reference: https://n1mmwp.hamdocs.com/appendices/external-udp-broadcasts/

### Capability gap analysis vs. MacLoggerDX

| Capability | MLDX mechanism | Log4OM mechanism | Gap? |
|---|---|---|---|
| Tune frequency | AppleScript `setLogFrequency` | UDP XML `SetTxFrequency` port 2241 | None |
| Set mode | AppleScript `setLogMode` | UDP XML `SetMode` | ⚠️ SetMode broken |
| Callsign lookup | AppleScript `lookup` | UDP XML `SetCallsign` (auto-triggers QRZ) | None (simpler) |
| Set park note | AppleScript `setNOTE` | **No equivalent confirmed** | ❌ Gap |
| QSO history query | AppleScript iterate all QSOs | **No query API exists** | ❌ Gap |
| Real-time QSO events | UDP port 9932 "Log Report" | N1MM XML `<contactinfo>` UDP port 12060 | None (different format) |
| Process health check | System Events (macOS) | TBD — Windows process list or UDP probe | TBD |

### Key constraints

1. **No QSO history query** — Log4OM has no API to ask "has this callsign been
   worked before?". The worked-callsign indicator can only be built from
   real-time N1MM UDP broadcast events captured during the current session.
   Historical QSO data is not accessible. This is the biggest UX difference vs. MLDX.

2. **No park note field** — No confirmed command to pre-populate a note or
   comment field with the POTA park reference. Options:
   - (a) Skip it — just tune + lookup, no note
   - (b) Append park ref to the callsign field (hacky, pollutes the call field)
   - (c) Use ADIF inbound UDP to submit a partial QSO record with a comment

3. **SetMode bug** — `SetMode` reportedly doesn't work as of Oct 2025. Validate
   against the current Log4OM release before implementing. May need to omit mode
   setting and document the limitation.

4. **Windows-only** — Cannot test on macOS. Needs a Windows test environment or VM.

### Proposed implementation sketch

```python
class Log4OmBackend(RigBackend):
    name = "log4om"
    DEFAULT_CONTROL_PORT = 2241   # Remote Control Interface v1.1 (inbound)
    DEFAULT_LISTEN_PORT  = 12060  # N1MM-format outbound QSO broadcasts

    def ping(self) -> str:
        # Send a UDP packet and check for response, or probe Windows process list

    def tune(self, freq_hz, mode, callsign="", note="") -> None:
        # 1. SetTxFrequency (Hz) → port 2241
        # 2. SetMode (if/when fixed)
        # 3. SetCallsign (auto-triggers QRZ lookup in Log4OM)
        # note: no park note equivalent — TBD

    def get_worked(self, callsigns) -> dict:
        # Return {} — no query API; worked cache built from live events only

    def start_log_listener(self, callback) -> None:
        # Listen for N1MM <contactinfo> XML on DEFAULT_LISTEN_PORT
        # Parse: call, band, rxfreq/txfreq (÷10 for Hz → MHz), mode, timestamp

    def stop_log_listener(self) -> None:
        # Stop listener thread
```

### Open questions

1. Is `SetMode` fixed in recent Log4OM builds? Check forum thread t=9984.
2. Is there a `SetNote`, `SetComment`, or `SetRemarks` command in the v1.1 spec
   PDF that didn't show up in forum discussions?
3. Best ping/health-check approach on Windows — UDP probe vs. process list?
4. Should the UI indicate that worked history is "this session only" when Log4OM
   is the active backend (vs. full history with MLDX)?
5. Does Log4OM require explicit user configuration (enable Remote Control, set
   port 2241) before our integration works? If so, the UI should show a setup guide.

### Implementation milestones

Each milestone is independently testable. Architecture note for each: identify
any places where adding a new backend would require changes beyond writing the
class, and fix those so future backends stay self-contained.

#### Milestone 1 — Frequency tuning (basic smoke test) ✅ DONE
- `Log4OmBackend` class in `PotaProxy.py`: `tune()` sends `SetTxFrequency`
  UDP XML to port 2241; `ping()` stubs to `"ok"` (no query interface yet)
- Register in `_build_backends()`; add `--log4om-port` CLI arg
- Add "Log4OM" option to `#rig-select` dropdown in `www/index.html`
- Architecture fix: add `ping()` to `RigBackend` base class with a default
  `"ok"` return so all backends are consistent; fix stale comment in the
  `/ping/` HTTP route handler

**Verify:** Select Log4OM in dropdown, click a spot row, confirm Log4OM tunes.

#### Milestone 2 — Mode setting
- Add `SetMode` to the `tune()` sequence after `SetTxFrequency`
- Empirically test against current Log4OM — if still broken, remove and
  document as a known gap (answers open question 1)

#### Milestone 3 — Callsign lookup
- Add `SetCallsign` to the `tune()` sequence; Log4OM auto-triggers QRZ lookup
- Update `tune()` signature to accept `callsign=""` kwarg (same pattern as MLDX)

#### Milestone 4 — Ping / health check
- Log4OM sends a UDP heartbeat every 5s on port 2242 when "Send 5 second
  status messages" is enabled in Remote Control settings
- Replace the stub `ping()` with a listener on port 2242 — declare backend
  up if a heartbeat arrived within the last ~15s, down otherwise
- No Windows process-list check needed (answers open question 3)
- Enables the existing backend-down dialog to work for Log4OM disconnects

#### Milestone 5 — Real-time worked cache
- Start a listener thread on port 12060 for Log4OM's N1MM-format
  `<contactinfo>` UDP broadcasts
- Parse `call`, `band`, `rxfreq`/`txfreq` (÷10 for Hz), `mode`, `timestamp`
- Feed into the existing `worked_cache` so `×N` badges and colored dots appear
- Session-only (no historical data); consider a UI hint when Log4OM is active
  (answers open question 4)

---

## CI: run tests in GitHub Actions release workflow

The release workflow (`.github/workflows/release.yml`) does not currently run
the test suite. Add a test step before the zip is built so a failing test
aborts the release early.

GitHub Actions runners have Python pre-installed but not pytest. Add two steps:

```yaml
- name: Install test dependencies
  run: pip install pytest

- name: Run tests
  run: python3 build.py test
```

Place these after the checkout step and before the "Create release zip" step.

---

## Document required backend setup steps in README

Users won't know to enable these settings before the integrations work.
Add a "Setup" or "Before you start" note to each backend's section in README.md:

### Log4OM
Log4OM's Remote Control Interface must be enabled before the integration works.

Exact path (verified on v2.40.0.0):
Open Configuration, then in the left-hand tree:
**Software integration → Connections → Remote Control** (tab button at top)

Settings on that page:
- **Remote control port** — inbound commands, default 2241 (our tune target)
- **Enable remote control** checkbox — **must be checked** or all commands
  are silently ignored (UDP has no error feedback)
- **Enable data output through UDP** checkbox
  - **Remote control output port** — outbound, default 2242
  - Send to specific IP/port (127.0.0.1 default) or Broadcast
- **Send 5 seconds status messages** checkbox — Log4OM broadcasts a heartbeat
  every 5s on port 2242 when enabled. **This is the ping mechanism for
  Milestone 4** — listen on 2242 and declare the backend up if a heartbeat
  arrived within ~15s. No process-list check needed.

README should tell users to:
1. Open Configuration → Software integration → Connections → Remote Control
2. Check **Enable remote control** (port 2241)
3. Check **Enable data output through UDP**, then check
   **Send 5 seconds status messages** (needed for backend health monitor)

Without step 2, tune commands are silently dropped.

### MacLoggerDX
MLDX's UDP Broadcast must be enabled for the worked-callsign indicator to work:
- Preferences → Networking → UDP Broadcast → enable, port 9932
- Without this, the `×N` worked badges won't update in real time (the
  historical AppleScript batch query still works, but live updates won't fire)
- Add this as a note in the MacLoggerDX section of README.md

---

## Add a favicon

The browser always requests `/favicon.ico` and currently gets a 404. Add a
simple favicon — a small antenna or radio wave icon would fit the theme — and
serve it from the proxy so the 404 goes away.

---

## SSE event types (future)

The SSE broker is designed to carry additional event types beyond `worked_update`.
Two candidates already identified:

| event name       | data payload             | trigger                          |
|------------------|--------------------------|----------------------------------|
| `spots`          | `[{spotId, …}, …]`       | Proxy-side spot refresh          |
| `backend_status` | `{backend, ok, error}`   | Backend connect/disconnect — **done in v1.12.0** |
