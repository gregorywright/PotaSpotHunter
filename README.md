# POTA Spot Hunter

**A live POTA hunter's dashboard — spot browser, award tracker, and one-click rig control.**

POTA Spot Hunter fetches active [Parks on the Air](https://parksontheair.com) activator spots from the [POTA API](https://api.pota.app) and gives hunters everything they need in one place: a filterable, sortable spot table with park type icons and age indicators; award tier progress and endorsement tracking tied to your callsign; hint icons that flag spots qualifying for active award events (Late Shift, Early Shift, New Years, Support Your Parks); an interactive world map; and one-click rig control for MacLoggerDX, flrig, and rigctld. Fully themeable. Works with no radio connected at all.

> 🛠 **Status:** Active development. Tested on macOS with MacLoggerDX, flrig, and rigctld (Icom IC-7300), and on Windows with Log4OM.

---

## GIFS/Screenshots

### Screenshots

![Main spot list](docs/screenshots/Screenshot-1.png)

![Filtering example](docs/screenshots/Screenshot-2.png)

![Theme example](docs/screenshots/Screenshot-3.png)

---

## Features

- 📡 **Live spot data** from `api.pota.app` — auto-refreshes at a configurable interval
- 🎛 **Band and mode filtering**
- 🔃 **Flexible sorting** — click any column header to sort by that column; click again to reverse. Sorts by frequency (low to high) by default — ideal for tuning up through the band.
- 🖱 **One-click tuning** — click any row to tune your radio, trigger a callsign lookup, and pre-fill the park reference in your logging software (MacLoggerDX only for now)
- 🔗 **Clickable links** — callsigns and park references link directly to POTA activator and park detail pages
- 🟢 **Age indicators** — spots are colour-coded by how fresh they are
- 🆕 **New spot indicator** — a green dot marks spots that appeared in the most recent refresh and haven't been seen before in this session
- 🔁 **Configurable auto-refresh** — 2, 5, 10, 15, 30, or 60 minutes, or manual only
- 🗺 **Interactive world map** — all active spots plotted on a resizable map; hover a marker to preview, click to tune
- 📻 **Auto Scan** — automatically cycles through the visible spot list, dwelling on each spot for a configurable interval (5s, 10s, 30s, or 1m) and tuning the radio as if you clicked the row. Designed for scanning the bands when propagation is uncertain. Any click or keypress stops the scan; restarting resumes from where you left off.
- 🎨 **Themes** — switch between color themes using the 🎨 dropdown in the header. Includes built-in dark and light themes. Drop a `.json` file into the `themes/` folder to install a custom theme. See [THEMES.md](THEMES.md) for how to create your own.
- 🏕 **Park type icons** — a Type column shows an emoji for each park's type (National Park, State Forest, Wildlife Area, etc.), fetched in the background and updated dynamically as data arrives. Clicking the Type column header sorts spots by park type.
- 🏆 **Award tracking** — enter your callsign once and the app fetches your POTA hunter profile. A badge in the header shows your current award tier and clicking it reveals a progress bar toward your next tier, plus band/mode endorsements earned so far.
- 🌙 **Award hint icons** on spot rows — small icons flag spots that qualify for active award opportunities: Late Shift (🌙), Early Shift (🌅), New Years week (🎆), Support Your Parks event weekend (🎪), and bands not yet in your endorsements (✨). Shift windows are calculated from each park's longitude per POTA rules.
- 📋 **Worked callsign indicator** — each spot row shows a `×N` lifetime QSO count badge and a colored dot if worked today: amber if band/mode unknown, red if band+mode match the spot (likely no new points). Hover for full details. Supported on MacLoggerDX and Log4OM (beta).
- 🎛 **Multiple rig control backends:**
  - **MacLoggerDX** — full integration via AppleScript (frequency, mode, callsign lookup, park reference note)
  - **flrig** — frequency and mode via XML-RPC
  - **rigctld (Hamlib)** — frequency and mode via TCP
  - **Log4OM** *(beta)* — frequency and callsign lookup via UDP; worked callsign history via SQLite
  - **None** — browse spots without sending any commands

---

## Quick Start

### 1. Download and unzip

Download the latest release ZIP from the [Releases page](https://github.com/gregorywright/PotaSpotHunter/releases/latest) and unzip it. You'll get a few files including:

- `www/` — the web app (HTML, CSS, JavaScript)
- `PotaProxy.py` — the local proxy server

Keep all the files in the same folder.

### 2. Start the proxy

Open a terminal in the unzipped folder and run `python3 PotaProxy.py`. On Windows, after installing Python, you can also just double-click `PotaProxy.py` in File Explorer. The proxy will automatically open your browser. The **Rig Control** dropdown defaults to **None**, so you can browse live spots right away without any radio attached.

### 3. (Optional) Click-to-tune

If you want to use POTA Spot Hunter to tune your rig, start MacLoggerDX, flrig, rigctld, or Log4OM, then select the appropriate backend from the **Rig Control** dropdown. Click any row or map marker to tune your radio.

---

## How It Works

The app is split into two files that work together:

| File | Purpose |
|---|---|
| `www/index.html` | The web UI — served by the proxy at `http://localhost:8080/` |
| `PotaProxy.py` | Local Python proxy — bridges the browser to rig-control software |

The browser cannot talk directly to MacLoggerDX, flrig, or rigctld because of the browser's same-origin security policy. The proxy runs locally on your machine, accepts simple HTTP requests from the web page, and forwards commands to whichever rig-control backend you have configured.

```
Browser (www/index.html — served by proxy)
        │
        │  HTTP  GET /tune/mldx?freq=14074&mode=FT8&callsign=W1AW&note=POTA+US-1234
        ▼
PotaProxy.py  (localhost:8080)
        │
        ├── MacLoggerDX  via osascript / AppleScript
        ├── flrig        via XML-RPC  (port 12345)
        └── rigctld      via TCP      (port 4532)
```

---

## Requirements

| Requirement | Notes |
|---|---|
| Python 3.7+ | Standard on macOS 12+. Install via [Homebrew](https://brew.sh): `brew install python` |
| A modern browser | Safari, Chrome, Firefox, or Edge |
| **One** of the following *(optional — only needed for click-to-tune)*: | |
| [MacLoggerDX](https://dogparksoftware.com/MacLoggerDX.html) | macOS only. |
| [flrig](http://www.w1hkj.com/files/flrig/) | macOS, Linux, Windows. |
| [rigctld](https://hamlib.github.io) (Hamlib) | macOS, Linux, Windows. `brew install hamlib` on macOS. |
| [Log4OM](https://www.log4om.com) *(beta)* | Windows only. |

No third-party Python packages are required — only the standard library.

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
python3 PotaProxy.py --rig-port 12346
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
python3 PotaProxy.py --rigctld-port 4533
```

### Log4OM *(beta, Windows only)*

Log4OM must be running. When you click Tune, the proxy will:
1. Set the VFO frequency
2. Trigger a callsign lookup (Log4OM auto-runs a QRZ lookup on receipt)

The worked callsign indicator (`×N` badges) works automatically — PSH reads your Log4OM QSO database directly with no extra configuration needed.

**Required — verify Remote Control is enabled:**

Log4OM enables Remote Control by default, so most users won't need to change anything. If tuning does not work, confirm it is on:

1. Open **Configuration** → **Software integration** → **Connections** → **Remote Control** tab
2. Confirm **Enable remote control** is checked and the port is **2241**

> ⚠️ UDP commands are fire-and-forget — if Remote Control is disabled, tune clicks are silently dropped with no error message.

**Known limitations (beta):**
- **Mode is not set** when tuning — Log4OM's `SetMode` command is non-functional in the current release. Set the mode manually in Log4OM or via your CAT interface.
- **Park reference note is not pre-filled** — Log4OM has no equivalent to MacLoggerDX's Note field.

**Optional — faster disconnect detection:**

By default, PSH detects whether Log4OM is running by checking the Windows process list. For faster detection, enable the heartbeat:

1. On the Remote Control tab, check **Enable data output through UDP**
2. Check **Send 5 seconds status messages**

With this enabled, PSH will detect Log4OM going offline within ~15 seconds instead of up to ~30 seconds.

---

## Proxy Command-Line Options

```
usage: PotaProxy.py [-h] [--backend {mldx,flrig,rigctld}]
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
python3 PotaProxy.py

# Use flrig on a non-default port, suppress browser auto-open
python3 PotaProxy.py --backend flrig --rig-port 12346 --no-browser

# Use rigctld on a remote machine on the local network
python3 PotaProxy.py --backend rigctld --rig-host 192.168.1.50
```

---

## Filtering and Sorting

| Control | Options |
|---|---|
| **Band** | All, 160m through 2m |
| **Mode** | All, CW, SSB, FT8, FT4, Other Digital |
| **Auto-refresh** | 2, 5, 10, 15, 30, 60 min, or Manual |
| **Auto Scan** | Off, 5s, 10s, 30s, 1m |

Click any column header to sort by that column; click again to reverse. The default sort is frequency ascending. Filters apply instantly without reloading.

---

## Proxy API Reference

The proxy exposes a simple REST-like API on `http://localhost:8080`. You can call these endpoints directly from a terminal for testing:

```bash
# Get the app version
curl http://localhost:8080/version

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

1. Create a class that inherits from `RigBackend` in `PotaProxy.py`
2. Implement `tune(freq_hz, mode)` — receives frequency in Hz and a mode string
3. Optionally implement `ping()` for connection health checks
4. Register it in the `_build_backends()` function
5. Add it to the `rig-select` dropdown in `www/index.html`

See the `FlrigBackend` and `RigctldBackend` classes for worked examples.

---

## File Structure

```
PotaSpotHunter/
├── www/                  # Web app — served by the proxy
│   ├── index.html        # HTML shell
│   ├── style.css         # All styles
│   └── app.js            # All JavaScript
├── PotaProxy.py          # Local proxy server
├── LICENSE               # MIT License
├── .gitignore
├── CHANGELOG.md          # Version history
├── requirements.txt      # No third-party dependencies (documents intent)
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
