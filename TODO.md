# TODO.md — POTA Spot Hunter
## Future feature ideas and implementation plans

---

## Log4OM backend

Support Log4OM as another backend logging program. Log4OM is Windows-only,
which complements MacLoggerDX (macOS-only) and expands coverage to the larger
Windows ham radio audience. Goal: best-possible feature parity with the MLDX
backend within the constraints of what Log4OM's API exposes.

### Log4OM CAT interface landscape

Log4OM supports three CAT engines (Hardware Configuration → CAT interface):

#### OmniRig (most popular — default installer option)
- Windows COM server; bundled in the Log4OM installer
- Designed from the ground up for multiple simultaneous clients (DX Atlas,
  CW Skimmer, Log4OM, others all share a single COM port connection)
- Better Icom radio support than Hamlib in user reports
- To connect from Python: requires `pywin32` (COM automation) — a third-party
  dependency we have avoided so far
- OmniRig v2 may have a TCP/network server mode; worth investigating as a
  way to avoid the pywin32 dependency
- **This is what most Log4OM users will have** — critical for mode setting

#### Hamlib / rigctld
- Log4OM can either spawn its own internal rigctld OR connect to an existing
  external instance ("Connect to active HAMLIB instance" checkbox, port 4532)
- Forum warns: *"no other CAT software should be active or they will conflict"*
  — sharing rigctld between Log4OM and POTA Spot Hunter is therefore risky
- Our existing `RigctldBackend` already speaks the rigctld protocol perfectly
- Less popular than OmniRig among Log4OM users; more configuration complexity

#### TCI (Transceiver Control Interface)
- WebSocket-based protocol (`ws://localhost:40001` by default; 50001 stock)
- Command syntax: `command:parameters;` e.g. `vfo:0,0,14074000;` and
  `modulation:0,USB;`
- Designed for ExpertSDR / SunSDR hardware; also supported by some other SDRs
- Multiple simultaneous clients supported
- Python needs a WebSocket library (`websockets` or similar) — third-party dep
- Less common in the general Log4OM user base; niche SDR hardware audience

#### OmniRig — interface details (research complete)
- OmniRig is **COM-only** — confirmed by reading the type library source
  (github.com/VE3NEA/OmniRig). There is no built-in TCP or network interface.
- OmniRig v2 does NOT add a network interface — it replaces the exe but still
  registers as a COM object in the same way.
- To connect from Python: `pywin32` (`win32com.client`) is the standard path.
  The `omnipyrig` library (github.com/4Z1KD/omnipyrig) is a ready-made wrapper.
- `pywin32` v300+ (Oct 2020) installs cleanly via pip with no admin rights and
  no manual post-install step — covers Python 3.9+ (our new minimum).
- If pywin32 is missing, the right UX is a clear error in the status bar:
  *"OmniRig mode control requires pywin32 — run: pip install pywin32, then
  restart the proxy."* Do NOT auto-install silently; do NOT pop a dialog
  (not standard Python practice and requires a proxy restart anyway).

#### Mode setting gap — root cause and decision
Log4OM's UDP Remote Control `SetMode` is confirmed broken in v2.40.0.0
(tested Apr 2026; also reported broken Oct 2025 in forum thread t=9984).

Full option analysis:

| Approach | Mode works? | Dependencies | User disruption |
|---|---|---|---|
| Log4OM UDP `SetMode` | ❌ broken | none | none |
| OmniRig COM via `pywin32` | ✅ | `pywin32` (optional) | none — already running |
| OmniRig v2 TCP | ❌ no TCP interface | — | — |
| rigctld shared with Log4OM | ✅ | none | must switch CAT engine; conflict risk |
| TCI WebSocket | ✅ | `websockets` dep | niche SDR hardware only |

**Decision: punt on mode setting for now.** Rationale:
- Mode setting is the *only* reason to talk to OmniRig directly right now
- Adding pywin32 + a hybrid two-channel tune() (OmniRig for mode, UDP for
  everything else) is real complexity for one feature
- Milestones 3–5 (callsign lookup, ping, worked cache) deliver more user value
  with zero new dependencies
- If Log4OM fixes `SetMode` in a future release, we get it for free
- Revisit after Milestones 3–5 ship, or if users specifically request it

**Future OmniRig mode setting implementation path (when we revisit):**
1. Add optional `pywin32` import in `Log4OmBackend.__init__()` — catch
   `ImportError` and set `self._omnirig = None`
2. If available, connect to OmniRig COM object and call `Rig1.Mode = PM_CW_U`
   etc. after the `SetTxFrequency` UDP send
3. Map POTA mode strings → OmniRig `PM_*` enum values
4. If pywin32 not installed, log a one-time info message with install instructions
   and continue (frequency still tunes correctly)

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

1. ~~Is `SetMode` fixed in recent Log4OM builds?~~ **Answered:** Still broken in
   v2.40.0.0 (Apr 2026). OmniRig COM path deferred — see mode setting section.
2. Is there a `SetNote`, `SetComment`, or `SetRemarks` command in the v1.1 spec
   PDF that didn't show up in forum discussions?
3. ~~Best ping/health-check approach?~~ **Answered:** Listen on port 2242 for
   the 5-second heartbeat Log4OM sends when "Send 5 seconds status messages"
   is enabled. Declare backend up if heartbeat arrived within ~15s.
4. Should the UI indicate that worked history is "this session only" when Log4OM
   is the active backend (vs. full history with MLDX)?
5. ~~Does Log4OM require explicit user configuration?~~ **Answered:** Yes —
   Configuration → Software integration → Connections → Remote Control →
   check "Enable remote control" (port 2241). Documented in TODO setup section.

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

#### Milestone 2 — Mode setting ✅ DONE (punted — broken in Log4OM)
- `SetMode` confirmed broken in Log4OM v2.40.0.0 — not sent
- A comment in `tune()` documents the gap and links to the forum thread
- OmniRig COM via `pywin32` is the future path; deferred until after M3–M5
- See "Mode setting gap" section above for full analysis and future approach

#### Milestone 3 — Callsign lookup ✅ DONE
- Added `callsign=""` kwarg to `tune()` — proxy's `inspect.signature` mechanism
  passes it through automatically from the query string
- Sends `SetCallsign` UDP XML after `SetTxFrequency`; only sent if callsign
  is non-empty; Log4OM auto-triggers QRZ lookup on receipt

#### Milestone 4 — Ping / health check ✅ DONE
Two-tier approach so it works with default Log4OM install config:

1. **Heartbeat (optional, fast):** listener on port 2242 receives Log4OM's
   5-second UDP status message when "Send 5 seconds status messages" is
   enabled. If a heartbeat has ever been received, use it exclusively —
   stale > 15s raises ConnectionRefusedError.

2. **Process list (default fallback):** if no heartbeat has ever arrived,
   call `tasklist /FO CSV /NH` and check for `L4ONG` or `Log4OM` in output.
   Works with zero Log4OM configuration. Log4OM's exe is `L4ONG.exe`
   (confirmed in Task Manager); process title shows "Log4OM 2".
   Both strings are checked for forward-compatibility.

Users get backend-down detection out of the box. Enabling the heartbeat
in Log4OM settings upgrades to faster/more reliable detection automatically.

#### Milestone 5 — Real-time worked cache ✅
- Start a listener thread on port 12060 for Log4OM's N1MM-format
  `<contactinfo>` UDP broadcasts
- Parse `call`, `band`, `rxfreq`/`txfreq` (÷100000 for MHz), `mode`, `timestamp`
- Feed into the existing `worked_cache` so `×N` badges and colored dots appear
- Session-only (no historical data)
- USB/LSB/AM collapsed to SSB (matching MLDX behaviour)
- `--log4om-listen-port` CLI arg for non-default setups
- 8 unit tests added (36 total passing)

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

README should tell users:

**Required — tune and callsign lookup:**
1. Open Configuration → Software integration → Connections → **Remote Control** tab
2. Confirm **Enable remote control** is checked (it is by default), port 2241
3. Without this, tune/callsign commands are silently dropped (UDP, no feedback)

**Required — worked callsign indicator (×N badges):**
4. On the same page, go to the **UDP** tab (Software integration → Connections → UDP)
5. In the **UDP OUTBOUND** section, fill in:
   - **Port**: `12060`
   - **Connection name**: anything, e.g. `PSH`
   - **Service type**: `N1MM_CONTACT` (select from dropdown)
   - **Destination IP Address**: `127.0.0.1`
6. Click the green **+** button to add it to the outbound connections list
7. Click **Save and apply**
8. Without this, QSOs logged in Log4OM will never appear as worked in PSH

**Optional — improves backend health detection:**
9. On the Remote Control tab, check **Enable data output through UDP**
10. Check **Send 5 seconds status messages**
11. With this enabled, PSH detects when Log4OM closes faster. Without it,
    a process-list check is used instead — still works, just slightly slower.

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

## Update minimum required Python version to 3.9+

Currently documented as Python 3.7+ (released June 2018, EOL June 2023).
Raise the minimum to **Python 3.9+** (released October 2020, still supported).

Reason: pywin32 v300+ (required for OmniRig COM access on Windows) guarantees
clean pip installation with no admin rights and no manual post-install step
from Python 3.9 onward. Python 3.7/3.8 are end-of-life and should not be
targeted for new dependencies.

Files to update: `README.md` requirements table, any other version references.

---

## SSE event types (future)

The SSE broker is designed to carry additional event types beyond `worked_update`.
Two candidates already identified:

| event name       | data payload             | trigger                          |
|------------------|--------------------------|----------------------------------|
| `spots`          | `[{spotId, …}, …]`       | Proxy-side spot refresh          |
| `backend_status` | `{backend, ok, error}`   | Backend connect/disconnect — **done in v1.12.0** |
