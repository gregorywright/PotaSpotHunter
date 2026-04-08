# TODO.md — POTA Spot Hunter
## Future feature ideas and implementation plans

---

## SSE event types (future)

The SSE broker is designed to carry additional event types beyond `worked_update`.
Two candidates already identified:

| event name       | data payload             | trigger                          |
|------------------|--------------------------|----------------------------------|
| `spots`          | `[{spotId, …}, …]`       | Proxy-side spot refresh          |
| `backend_status` | `{backend, ok, error}`   | Backend connect/disconnect       |
