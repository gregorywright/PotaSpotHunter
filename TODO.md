# TODO.md — POTA Spot Hunter
## Future feature ideas and implementation plans

---

## Log4OM backend

Support Log4OM as another backend logging program. Goal: full feature parity
with the MacLoggerDX backend (frequency/mode tune, callsign lookup, park
reference note, worked-callsign indicator with real-time QSO updates) and more
if Log4OM's API allows it. Log4OM runs on Windows/Mac/Linux so this would also
expand platform support beyond macOS-only MLDX.

Research needed:
- Log4OM API/scripting interface (UDP? XML-RPC? REST?)
- Whether it exposes QSO history for the worked-callsign indicator
- Whether it supports real-time log event notifications (for SSE push)

---

## SSE event types (future)

The SSE broker is designed to carry additional event types beyond `worked_update`.
Two candidates already identified:

| event name       | data payload             | trigger                          |
|------------------|--------------------------|----------------------------------|
| `spots`          | `[{spotId, …}, …]`       | Proxy-side spot refresh          |
| `backend_status` | `{backend, ok, error}`   | Backend connect/disconnect — **done in v1.12.0** |
