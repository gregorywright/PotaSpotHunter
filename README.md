# POTA Spot Hunter

**A live POTA activator spot browser with one-click rig control.**

POTA Spot Hunter fetches active [Parks on the Air](https://parksontheair.com) activator spots from the [POTA API](https://api.pota.app), displays them in a clean filterable table, and lets you tune your radio to any spot with a single click. If you happen to be using MacLoggerDX, then this app will not only tune the radio, but also set the callsign, look up the callsign data, and set the comment field with the POTA reference. You can also use this app with no radio connected at all if you want.

> 🛠 **Status:** Active development. Tested on macOS with MacLoggerDX, flrig, and rigctld (Icom IC-7300).

---

## Screenshots

![Main spot list](docs/screenshots/DefaultLaunchWindow.png)

![Filtering example](docs/screenshots/FilteredWindowExample.png)

![Demo](docs/screenshots/demo.gif)

---

## Features

- 📡 **Live spot data** from `api.pota.app` — auto-refreshes at a configurable interval
- 🎛 **Band and mode filtering**
- 🔃 **Flexible sorting** — by frequency, callsign, or spot time (newest/oldest)
- 🖱 **One-click tuning** — tunes your radio, triggers a callsign lookup, and pre-fills the park reference in your logging software (MacLoggerDX only for now)
- 🔗 **Clickable links** — callsigns and park references link directly to POTA activator and park detail pages
- 🟢 **Age indicators** — spots are colour-coded by how fresh they are
- 🔁 **Configurable auto-refresh** — 2, 5, 10, 15, 30, or 60 minutes, or manual only
- 🖥 **Multiple rig control backends:**
  - **MacLoggerDX** — full integration via AppleScript (frequency, mode, callsign lookup, park reference note)
  - **flrig** — frequency and mode via XML-RPC
  - **rigctld (Hamlib)** — frequency and mode via TCP
  - **None** — browse spots without sending any commands

---

## How It Works

The app is split into two files that work together:

| File | Purpose |
|---|---|
| `POTASpotHunter.html` | The web UI — runs in any modern browser |
| `pota_proxy.py` | Local Python proxy — bridges the browser to rig-control software |

The browser cannot talk directly to MacLoggerDX, flrig, or rigctld because of the browser's same-origin security policy. The proxy runs locally on your machine, accepts simple HTTP requests from the web page, and forwards commands to whichever rig-control backend you have configured.

```
Browser (POTASpotHunter.html)
        │
        │  HTTP  GET /tune/mldx?freq=14074&mode=FT8&callsign=W1AW&note=POTA+US-1234
        ▼
pota_proxy.py  (localhost:8080)
        │
        ├── MacLoggerDX  via osascript / AppleScript
        ├── flrig        via XML-RPC  (port 12345)
        └── rigctld      via TCP      (port 4532)
```

---

## Requirements

| Requirement | Notes |
|---|---|
| Python 3.6+ | Standard on macOS 12+. Install via [Homebrew](https://brew.sh): `brew install python` |
| A modern browser | Safari, Chrome, Firefox, or Edge |
| **One** of the following: | |
| [MacLoggerDX](https://dogparksoftware.com/MacLoggerDX.html) | macOS only. Must be running before you click Tune. |
| [flrig](http://www.w1hkj.com/files/flrig/) | macOS, Linux, Windows. |
| [rigctld](https://hamlib.github.io) (Hamlib) | macOS, Linux, Windows. `brew install hamlib` on macOS. |

No third-party Python packages are required — only the standard library.

---

## Quick Start

### 1. Download the files

Clone the repository or download both files into the same folder:

```bash
git clone https://github.com/gregorywright/PotaSpotHunter.git
cd PotaSpotHunter
```

### 2. Start your rig-control software

Make sure MacLoggerDX, flrig, or rigctld is running and connected to your radio **before** starting the proxy.

### 3. Start the proxy

```bash
python3 pota_proxy.py
```

The proxy will automatically open `POTASpotHunter.html` in your default browser. Both files must be in the same directory.

### 4. Select a backend and start hunting

Choose your rig-control backend from the **Rig Control** dropdown. The app will confirm the connection, then load live spots. Click any row or the **Tune** button to tune your radio.

---

## Rig Control Setup

### MacLoggerDX

MacLoggerDX must be running on the same Mac as the proxy. No extra configuration is needed — the proxy communicates with MacLoggerDX via AppleScript.

When you click Tune, the proxy will:
1. Set the VFO frequency and mode
2. Trigger a callsign lookup
3. Pre-fill the Note field with the POTA park reference

### flrig

flrig must be running and connected to your radio. Default host/port is `127.0.0.1:12345`. To use a non-default port:

```bash
python3 pota_proxy.py --rig-port 12346
```

### rigctld (Hamlib)

Install Hamlib, then start rigctld with your radio's model number and serial port. Default host/port is `127.0.0.1:4532`.

**Find your radio's model number:**
```bash
rigctld -l | grep -i "your radio name"
```

**Basic start:**
```bash
rigctld -m <model> -r <device> -t 4532
```

**Platform-specific device paths:**

| Platform | Example device path |
|---|---|
| macOS | `/dev/tty.usbserial-XXXX` or `/dev/cu.usbmodem-XXXX` |
| Linux (not tested) | `/dev/ttyUSB0` or `/dev/ttyACM0` |
| Windows (not tested) | `COM3` (check Device Manager) |

> ⚠️ **Icom IC-7300 users (model 3073):** The IC-7300 requires RTS and DTR lines to be held OFF or the radio will reset when rigctld connects. Always start rigctld with the extra flags:
> ```bash
> rigctld -m 3073 -r /dev/tty.usbserial-XXXX -t 4532 \
>   --set-conf=rts_state=OFF --set-conf=dtr_state=OFF
> ```

To use a non-default rigctld port:
```bash
python3 pota_proxy.py --rigctld-port 4533
```

---

## Proxy Command-Line Options

```
usage: pota_proxy.py [-h] [--backend {mldx,flrig,rigctld}]
                     [--port PORT] [--rig-host HOST]
                     [--rig-port PORT] [--rigctld-port PORT]
                     [--no-browser] [--debug]

options:
  --backend    Default rig-control backend (default: mldx)
  --port       Proxy listen port (default: 8080)
  --rig-host   Host for flrig/rigctld (default: 127.0.0.1)
  --rig-port   Port for flrig (default: 12345)
  --rigctld-port  Port for rigctld (default: 4532)
  --no-browser Do not automatically open the browser
  --debug      Enable verbose debug logging
```

**Examples:**

```bash
# Default — MacLoggerDX backend, opens browser automatically
python3 pota_proxy.py

# Use flrig on a non-default port, suppress browser auto-open
python3 pota_proxy.py --backend flrig --rig-port 12346 --no-browser

# Use rigctld on a remote machine on the local network
python3 pota_proxy.py --backend rigctld --rig-host 192.168.1.50
```

---

## Filtering and Sorting

| Control | Options |
|---|---|
| **Band** | All Bands, 160m through 70cm |
| **Mode** | All Modes, CW, SSB, FT8, FT4, Digital (other) |
| **Sort** | Newest first, Oldest first, Freq ↑, Freq ↓, Callsign A–Z |
| **Auto-refresh** | Every 2, 5, 10, 15, 30, 60 minutes, or Manual only |

You can also click any column header to sort by that column. Filters apply instantly without reloading.

---

## Proxy API Reference

The proxy exposes a simple REST-like API on `http://localhost:8080`. You can call these endpoints directly from a terminal for testing:

```bash
# List available backends
curl http://localhost:8080/backends

# Ping a backend (check if rig software is reachable)
curl http://localhost:8080/ping/mldx
curl http://localhost:8080/ping/flrig
curl http://localhost:8080/ping/rigctld

# Tune a radio (freq in kHz)
curl "http://localhost:8080/tune/flrig?freq=14074&mode=FT8"
curl "http://localhost:8080/tune/mldx?freq=14074&mode=FT8&callsign=W1AW&note=POTA+US-1234+Yosemite"
```

All responses are JSON with an `ok` field:
```json
{ "ok": true,  "backend": "flrig", "freq_hz": 14074000, "mode": "FT8" }
{ "ok": false, "error": "Cannot reach flrig — is it running?" }
```

---

## Adding a New Rig Control Backend

The proxy is designed to be extended. To add a new backend (e.g. OmniRig, DX Lab Suite Commander):

1. Create a class that inherits from `RigBackend` in `pota_proxy.py`
2. Implement `tune(freq_hz, mode)` — receives frequency in Hz and a mode string
3. Optionally implement `ping()` for connection health checks
4. Register it in the `_build_backends()` function
5. Add it to the `rig-select` dropdown in `POTASpotHunter.html`

See the `FlrigBackend` and `RigctldBackend` classes for worked examples.

---

## File Structure

```
PotaSpotHunter/
├── POTASpotHunter.html   # Web UI — open this in your browser
├── pota_proxy.py         # Local proxy server
├── LICENSE               # MIT License
├── .gitignore
└── README.md
```

---

## Data Sources

| Source | URL |
|---|---|
| POTA spot API | https://api.pota.app/spot/activator |
| POTA activator profile | `https://pota.app/#/profile/<CALLSIGN>` |
| POTA park detail | `https://pota.app/#/park/<REFERENCE>` |
| MacLoggerDX scripting reference | https://dogparksoftware.com/MacLoggerDX%20Help/mldxfc_script.html |
| Hamlib / rigctld reference | https://hamlib.sourceforge.net/html/rigctld.1.html |
| flrig XML-RPC reference | http://www.w1hkj.com/flrig-help/xmlrpc_commands.html |

---

## License

MIT License — see [LICENSE](LICENSE) for full text.

Copyright (c) 2025 Gregory Wright (W7GFW) &lt;greg@gregorywright.org&gt;

---

## 73

See you on the air. I am usually doing CW at parks near Seattle, and the random contest. 

*de W7GFW*