#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (c) 2025 Gregory Wright (W7GFW) <greg@gregorywright.org>
# SPDX-License-Identifier: MIT
# https://github.com/gregorywright/PotaSpotHunter
#
"""
pota_proxy.py
=============
A lightweight local HTTP proxy that bridges POTASpotHunter.html
to radio-control backends running on the same machine.

WHY THIS EXISTS
---------------
Browsers block direct JavaScript access to localhost services
(flrig, rigctld, etc.) because of the Same-Origin Policy / CORS.
This proxy runs as a tiny HTTP server on localhost:8080, accepts
simple GET requests from the HTML page, adds the required CORS
headers, and forwards the tune/mode commands to whatever backend
the operator has configured.

HOW TO START
------------
    python3 pota_proxy.py                    # default: flrig on port 12345
    python3 pota_proxy.py --backend flrig    # explicit
    python3 pota_proxy.py --port 8080        # change proxy port
    python3 pota_proxy.py --rig-host 192.168.1.10 --rig-port 12345

HOW THE HTML PAGE USES IT
--------------------------
Instead of firing mldx:// URLs, the page sends HTTP GET requests:

    GET http://localhost:8080/tune/flrig?freq=14074000&mode=USB
                             ^^^^^  ^^^^^ ^^^^^^^^^^^^^^^^^^^^^^^^^
                             |      |     parameters
                             |      backend name (for future routing)
                             proxy port

The /tune/{backend} path scheme is intentional: it makes the backend
explicit in the URL so the proxy (and logs) always show which backend
handled each request, and it leaves room to add other backends
(/tune/rigctld, /tune/omnirig, etc.) without changing the URL structure.

The proxy responds with JSON:
    {"ok": true,  "backend": "flrig", "freq_hz": 14074000, "mode": "USB"}
    {"ok": false, "error": "Connection refused — is flrig running?"}

ADDING A NEW BACKEND
--------------------
1.  Create a new class that inherits from RigBackend (see below).
2.  Implement tune(freq_hz, mode) -> None.  Raise RuntimeError with a
    human-readable message on failure.
3.  Register it in BACKENDS at the bottom of this file.
4.  In POTASpotHunter.html, add the backend name to the "Rig Control"
    dropdown and point the fetch URL at /tune/<your-backend-name>.

That's it.  No changes to the proxy HTTP plumbing needed.

INFORMATION SOURCES
-------------------
flrig XML-RPC API:
  http://www.w1hkj.com/flrig-help/xmlrpc_commands.html
  http://www.w1hkj.org/flrig-help/xmlrpc_server.html
  Key methods used:
    main.set_frequency  d:d  — set VFO frequency in Hz (integer or float)
    rig.set_mode        n:s  — set mode string (e.g. "USB", "CW", "FT8")
    main.get_version    s:n  — returns version string (used for ping/health)
  Default host: 127.0.0.1   Default port: 12345
  Note: flrig expects frequency in HERTZ, not kHz or MHz.
  Note: rig.set_mode requires the mode string to exactly match one of
        the modes the rig supports.  Common strings: USB, LSB, CW, CW-R,
        AM, FM, RTTY, FT8, FT4, PSK31.  If the rig does not recognise
        the string, flrig silently ignores it — no error is returned.
        Source: winfldigi@groups.io thread "FLRIG XMLRPC commands"

hamlib rigctld (implemented):
  rigctld listens on TCP port 4532 (default) with a plain-text line protocol.
  It is NOT HTTP, so xmlrpc.client cannot be used — raw socket.socket() is used.
  Command to set frequency: \\set_freq <Hz>  (short form: F <Hz>)
  Command to set mode:      \\set_mode <MODE> <passband>  (short form: M <MODE> <bw>)
  Source: https://hamlib.sourceforge.net/html/rigctld.1.html
  IC-7300 users: start rigctld with --set-conf=rts_state=OFF --set-conf=dtr_state=OFF
  See RigctldBackend class docstring for full details.

omnirig / flrig-on-Windows (NOT YET IMPLEMENTED):
  OmniRig uses a COM/ActiveX interface on Windows.  Bridging from Python
  would require pywin32.  Out of scope for the initial macOS release.

Python standard library used:
  xmlrpc.client  — XML-RPC client (built-in, no pip install needed)
  http.server    — simple HTTP server base class (built-in)
  argparse       — command-line argument parsing (built-in)
  json           — JSON encoding for responses (built-in)
  logging        — structured log output (built-in)
  urllib.parse   — query-string parsing (built-in)

REQUIREMENTS
------------
  Python 3.7+    (no third-party packages needed)
  flrig          running and connected to the radio
"""

import argparse
import inspect
import json
import logging
import pathlib
import queue
import socket
import sys
import threading
import webbrowser
import xmlrpc.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs


# ── Logging setup ────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pota_proxy")

# ── Version ──────────────────────────────────────────────────────────────
# Read from the VERSION file in the same directory as this script.
# Falls back to "unknown" if the file is missing so the proxy still starts.
# The version is exposed via the /version HTTP route so www/index.html
# can display it in the header without hardcoding it in two places.
_version_file = pathlib.Path(__file__).parent / "VERSION"
try:
    APP_VERSION = _version_file.read_text(encoding="utf-8").strip()
except OSError:
    APP_VERSION = "unknown"


# ════════════════════════════════════════════════════════════
# WORKED CACHE  —  tracks QSO history for visible activators
# ════════════════════════════════════════════════════════════
#
# Populated by two sources:
#   1. AppleScript batch query (historical counts, no band/mode)
#   2. UDP log listener on port 9932 (real-time, has band/mode)
#
# Protected by a threading.Lock — the UDP listener and the
# background worker thread both write to it concurrently.
#
# Schema per callsign entry:
#   count        (int)         lifetime QSO count
#   last_date    (str|None)    ISO-8601 UTC timestamp of most recent QSO
#   worked_today (bool)        any QSO with UTC date == today
#   last_band    (str|None)    e.g. "20m" — None if unknown (AppleScript)
#   last_mode    (str|None)    SSB-collapsed — None if unknown
#   last_freq_mhz (str|None)   e.g. "14.074" — None if unknown
#   last_park_ref (str|None)   e.g. "US-1234" — None if not provided

worked_cache: dict = {}
worked_cache_lock = threading.Lock()

# Queue of callsigns waiting for AppleScript lookup.
# The background worker drains this in batches of up to 50.
_lookup_queue: queue.Queue = queue.Queue()


# ════════════════════════════════════════════════════════════
# BASE CLASS  —  defines the interface every backend must implement
# ════════════════════════════════════════════════════════════

class RigBackend:
    """
    Abstract base class for all rig-control backends.

    Subclass this, implement tune(), and register the subclass in
    BACKENDS at the bottom of this file.  The proxy HTTP handler
    calls tune() and handles all error reporting — the backend only
    needs to worry about talking to its specific rig-control program.
    """

    # Human-readable name shown in log messages and JSON responses.
    name: str = "base"

    def tune(self, freq_hz: int, mode: str) -> None:
        """
        Tune the radio to freq_hz (integer, in Hz) and set the mode.

        Parameters
        ----------
        freq_hz : int
            Frequency in Hz.  The HTML page sends kHz; conversion to Hz
            happens in the HTTP handler before calling this method, so
            backends always receive Hz regardless of what the rig or its
            control protocol expects.
        mode : str
            Mode string, already resolved from SSB to USB or LSB by the
            HTML page (e.g. "USB", "LSB", "CW", "FT8", "FT4").

        Raises
        ------
        RuntimeError
            With a human-readable message if the command fails.
            ConnectionRefusedError / OSError are caught by the HTTP handler
            and converted to a user-friendly "is <backend> running?" message.
        """
        raise NotImplementedError

    def get_worked(self, callsigns: list) -> dict:
        """
        Return worked history for a batch of callsigns.
        Returns {callsign: {count, last_date, worked_today, last_band,
                             last_mode, last_freq_mhz, last_park_ref}}.
        Default: returns empty dict (no-op for backends without log access).
        """
        return {}

    def start_log_listener(self, callback) -> None:
        """
        Start a background listener for real-time QSO log events.
        Calls callback(entry_dict) whenever a new QSO is logged.
        Default: no-op.
        """
        pass

    def stop_log_listener(self) -> None:
        """
        Stop the log listener thread. BLOCKS until fully stopped.
        Default: no-op.
        """
        pass


# ════════════════════════════════════════════════════════════
# BACKEND: flrig
# ════════════════════════════════════════════════════════════

class FlrigBackend(RigBackend):
    """
    Rig control via flrig's built-in XML-RPC server.

    flrig is a standalone transceiver control program that connects to
    the radio over USB/serial CAT and exposes an XML-RPC interface that
    other programs (fldigi, WSJT-X, logging software) can use to read
    and set VFO frequency and mode.

    XML-RPC endpoint : http://127.0.0.1:12345/RPC2   (flrig default)

    Methods used
    ------------
    main.set_frequency  d:d
        Set the current VFO frequency.
        Argument : frequency in Hz as a float (double).
        Returns  : the new frequency.
        Source   : http://www.w1hkj.com/flrig-help/xmlrpc_commands.html

    rig.set_mode  n:s
        Set the current VFO mode.
        Argument : mode string — must exactly match a mode the connected
                   radio supports.  flrig silently ignores unknown strings.
        Returns  : nothing meaningful.
        Source   : http://www.w1hkj.org/flrig-help/xmlrpc_server.html

    main.get_version  s:n
        Returns the flrig version string.  Used here only as a
        connectivity check — if this call succeeds, flrig is running.

    Frequency units
    ---------------
    flrig XML-RPC expects HERTZ (not kHz, not MHz).
    The HTML page sends kHz; the HTTP handler converts to Hz before
    calling tune(), so this class always receives Hz.
    Example: 14.074 MHz = 14074 kHz = 14,074,000 Hz

    Mode strings
    ------------
    Mode strings must match the radio's own mode names as reported by
    rig.get_modes.  Common values: USB, LSB, CW, CW-R, AM, FM, RTTY,
    FT8, FT4, DATA-U, DATA-L.  If the radio does not recognise the
    string, flrig ignores the mode change without returning an error.
    Source: winfldigi@groups.io, "FLRIG XMLRPC commands" thread.
    """

    name = "flrig"

    def __init__(self, host: str = "127.0.0.1", port: int = 12345):
        self.host = host
        self.port = port
        # xmlrpc.client.ServerProxy is lazy — it does not connect until
        # the first method call, so construction always succeeds.
        self._endpoint = f"http://{host}:{port}/RPC2"

    def _client(self):
        """Return a fresh ServerProxy for each call to avoid stale sockets."""
        return xmlrpc.client.ServerProxy(self._endpoint, allow_none=True)

    def ping(self) -> str:
        """
        Check connectivity and return the flrig version string.
        Raises ConnectionRefusedError if flrig is not running.
        """
        return self._client().main.get_version()

    def tune(self, freq_hz: int, mode: str) -> None:
        """
        Set VFO frequency (Hz) and mode via flrig XML-RPC.

        flrig processes each XML-RPC call synchronously and typically
        responds within a few milliseconds.  We send frequency first,
        then mode, matching the order used by fldigi and WSJT-X when
        tuning to a DX spot.
        """
        client = self._client()

        # Set frequency — flrig expects a float (double) in Hz.
        log.info("flrig  set_frequency  %d Hz", freq_hz)
        client.main.set_frequency(float(freq_hz))

        # Set mode — flrig expects a plain string.
        log.info("flrig  set_mode       %s", mode)
        client.rig.set_mode(mode)

        # Ensure split is off — POTA activators never work split.
        log.info("flrig  set_split      0")
        client.rig.set_split(0)


# ════════════════════════════════════════════════════════════
# BACKEND: hamlib rigctld
# ════════════════════════════════════════════════════════════

class RigctldBackend(RigBackend):
    """
    Rig control via Hamlib's rigctld TCP daemon.

    rigctld is part of the Hamlib project and acts as a universal
    radio-control server.  It connects to the radio over serial/USB CAT
    and exposes a simple plain-text TCP protocol that other programs
    (WSJT-X, fldigi, JS8Call, etc.) use to read and set the VFO.

    Install Hamlib
    --------------
    macOS (Homebrew):   brew install hamlib
    Linux (Debian/Ubuntu): sudo apt install libhamlib-utils
    Windows:            Download installer from https://hamlib.github.io

    Starting rigctld
    ----------------
    Basic:
      rigctld -m <model> -r <device> -t 4532

    Icom IC-7300 (model 3073) on macOS — IMPORTANT:
      The IC-7300 requires RTS and DTR serial lines to be held OFF,
      otherwise rigctld resets the radio when it opens the serial port.
      Always use:
        rigctld -m 3073 -r /dev/tty.usbserial-XXXX -t 4532 \\
          --set-conf=rts_state=OFF --set-conf=dtr_state=OFF
      Source: https://github.com/Hamlib/Hamlib/blob/master/NEWS

    Find your radio's model number:
      rigctld -l | grep -i <radio-name>
      e.g. rigctld -l | grep -i "7300"

    Protocol reference
    ------------------
    https://hamlib.sourceforge.net/html/rigctld.1.html
    https://manpages.ubuntu.com/manpages/xenial/man8/rigctld.8.html

    Default host: 127.0.0.1   Default port: 4532

    Protocol summary (plain text over TCP, each command ends with \\n)
    -------------------------------------------------------------------
    Set frequency:   F <Hz>\\n
      e.g.           F 14074000\\n
      Response:      RPRT 0\\n      (0 = success, negative = error)

    Set mode:        M <MODE> <passband_Hz>\\n
      e.g.           M PKTUSB 0\\n  (0 = radio default passband)
      Response:      RPRT 0\\n
      Full mode token list: USB, LSB, CW, CWR, RTTY, RTTYR, AM, FM,
        WFM, AMS, PKTLSB, PKTUSB, PKTFM, ECSSUSB, ECSSLSB, FAX,
        SAM, SAL, SAH, DSB

    Get frequency:   f\\n            (used as ping fallback)
      Response:      <Hz>\\nRPRT 0\\n

    Dump caps:       \\dump_caps\\n   (used as primary ping)
      Response:      many key:value lines, then RPRT 0\\n

    Cross-platform notes
    --------------------
    The socket-based protocol is identical on macOS, Linux, and Windows.
    The only platform-specific part is the serial device path passed to
    rigctld at startup:
      macOS:   /dev/tty.usbserial-XXXX  or  /dev/cu.usbmodem-XXXX
      Linux:   /dev/ttyUSB0  or  /dev/ttyACM0
      Windows: COM3  (or whichever COM port Device Manager shows)
    pota_proxy.py itself has no platform-specific code for rigctld.
    """

    name = "rigctld"

    # Maps POTA/common mode strings to Hamlib rigctld mode names.
    # Any mode not in this table is passed through unchanged.
    #
    # Source: rigctld man page mode list
    #   https://hamlib.sourceforge.net/html/rigctld.1.html
    # Confirmed by WSJT-X source which maps FT8/FT4 -> PKTUSB:
    #   https://github.com/m5evt/wsjtx/blob/master/HamlibTransceiver.cpp
    #
    # Full Hamlib mode token list (from man page):
    #   USB, LSB, CW, CWR, RTTY, RTTYR, AM, FM, WFM, AMS,
    #   PKTLSB, PKTUSB, PKTFM, ECSSUSB, ECSSLSB, FAX, SAM, SAL, SAH, DSB
    MODE_MAP = {
        "FT8":   "PKTUSB",
        "FT4":   "PKTUSB",
        "JS8":   "PKTUSB",
        "PSK31": "PKTUSB",
        "PSK63": "PKTUSB",
        "RTTY":  "RTTY",
        "CW-R":  "CWR",
    }

    # Default passband width in Hz passed to rigctld's M command.
    # 0 means "use the radio's default passband for this mode".
    # Source: rigctld man page — "0 for the radio backend default"
    DEFAULT_PASSBAND = 0

    # Socket timeout in seconds for each send/receive operation.
    # Kept short (3s) so a ping to a non-running rigctld fails quickly
    # and returns a proper JSON 503 error to the browser rather than
    # making the browser's own 8s fetch() timeout fire first (which
    # would incorrectly show "proxy not running" instead of
    # "rigctld unreachable").
    TIMEOUT = 3.0

    # IC-7300 / Icom CI-V note (model 3073):
    # The IC-7300 requires RTS and DTR lines to be held OFF or the radio
    # resets when rigctld opens the serial port.  Always start rigctld with:
    #   rigctld -m 3073 -r /dev/tty.usbserial-XXXX -t 4532 \
    #     --set-conf=rts_state=OFF --set-conf=dtr_state=OFF
    # Source: Hamlib NEWS file, IC-7300 multicast example:
    #   https://github.com/Hamlib/Hamlib/blob/master/NEWS
    # This is a rigctld startup requirement, not something we handle here.

    def __init__(self, host: str = "127.0.0.1", port: int = 4532):
        self.host = host
        self.port = port

    def _send_command(self, sock: socket.socket, cmd: str) -> str:
        """
        Send a single newline-terminated command and read back the response.

        Protocol: each command is a single line ending in \\n.
        Response: one or more lines ending with "RPRT <code>\\n".
        RPRT 0 = success; RPRT -N = Hamlib error code N.

        Source: rigctld default protocol
          https://hamlib.sourceforge.net/html/rigctld.1.html

        Raises RuntimeError if rigctld reports a non-zero RPRT code.
        The caller is responsible for not reusing the socket after an
        exception, since the read buffer state is undefined on error.
        """
        sock.sendall((cmd + "\n").encode("ascii"))
        # Read until we see a line starting with "RPRT" — that is always
        # the last line of any rigctld response.
        buf = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
            if b"RPRT" in buf:
                break
        response = buf.decode("ascii", errors="replace").strip()
        # Check for error response — RPRT followed by a negative number.
        for line in response.splitlines():
            if line.startswith("RPRT"):
                code = line.split()[-1]
                if code != "0":
                    raise RuntimeError(
                        f"rigctld returned error code {code} "
                        f"for command: {cmd!r}"
                    )
        return response

    def _connect(self) -> socket.socket:
        """
        Open a fresh TCP connection to rigctld.
        Raises ConnectionRefusedError / OSError if rigctld is not running.

        We open a fresh connection per command sequence (tune or ping)
        rather than keeping a long-lived socket.  This is the same pattern
        used by WSJT-X and fldigi and avoids stale-socket problems if
        rigctld is restarted between calls.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.TIMEOUT)
        sock.connect((self.host, self.port))
        return sock

    def ping(self) -> str:
        """
        Check connectivity and return a version/status string.
        Raises ConnectionRefusedError / OSError if rigctld is not running.

        Ping strategy:
          1. Try '\\dump_caps' — returns many key:value lines including
             the Hamlib version and radio model.  Not all radio backends
             respond to dump_caps, but it is the most widely supported
             introspection command in rigctld.
             Source: rigctld man page, dump_caps command.

          2. Fall back to 'f' (get_freq) if dump_caps fails.  This is the
             most basic command supported by every radio backend.  We open
             a FRESH socket for the fallback so we are not reading from a
             socket whose buffer is in an undefined state after the error.

        NOTE: '\\get_info' was used in an earlier version of this code but
        is NOT a valid rigctld command — it returns RPRT -11 (not
        implemented) on most backends.  dump_caps and f are the correct
        choices.  Source: rigctld command list:
          https://hamlib.sourceforge.net/html/rigctld.1.html
        """
        # Attempt 1: dump_caps — returns Hamlib version and caps summary
        try:
            with self._connect() as sock:
                resp = self._send_command(sock, "\\dump_caps")
                # Extract "Hamlib version" line if present
                for line in resp.splitlines():
                    if line.lower().startswith("hamlib version"):
                        return line.split(":", 1)[-1].strip()
                return "ok"
        except RuntimeError:
            # dump_caps not supported — fall through to f
            pass

        # Attempt 2: f (get_freq) — supported by every radio backend.
        # Fresh connection — do NOT reuse the socket from attempt 1.
        with self._connect() as sock:
            self._send_command(sock, "f")
            return "ok"

    def tune(self, freq_hz: int, mode: str) -> None:
        """
        Set VFO frequency (Hz) and mode via rigctld TCP protocol.

        Opens a single fresh TCP connection, sends frequency then mode.
        Both commands are sent on the same connection since rigctld
        handles multiple commands per connection fine, and reusing the
        connection avoids a second TCP handshake overhead.

        Commands sent (plain ASCII, newline-terminated):
          F <freq_hz>              — set VFO frequency in Hz (integer)
          M <hamlib_mode> <bw_hz>  — set mode, passband 0 = radio default

        Example for 14.074 MHz FT8:
          F 14074000
          M PKTUSB 0

        Source: rigctld default protocol
          https://hamlib.sourceforge.net/html/rigctld.1.html
          https://manpages.ubuntu.com/manpages/xenial/man8/rigctld.8.html
        """
        # Translate mode string to Hamlib token if needed (e.g. FT8 -> PKTUSB)
        hamlib_mode = self.MODE_MAP.get(mode.upper(), mode.upper())

        with self._connect() as sock:
            log.info("rigctld  F  %d Hz", freq_hz)
            self._send_command(sock, f"F {freq_hz}")

            log.info("rigctld  M  %s  passband=%d", hamlib_mode, self.DEFAULT_PASSBAND)
            self._send_command(sock, f"M {hamlib_mode} {self.DEFAULT_PASSBAND}")

            # Ensure split is off — POTA activators never work split.
            log.info("rigctld  S  0 VFOA")
            self._send_command(sock, "S 0 VFOA")


# ════════════════════════════════════════════════════════════
# BACKEND: MacLoggerDX (via osascript)
# ════════════════════════════════════════════════════════════

class MacLoggerDXBackend(RigBackend):
    """
    Rig control and logging integration via MacLoggerDX on macOS.

    MacLoggerDX is a ham radio logging application for macOS that also
    controls the radio VFO.  It exposes an AppleScript dictionary with
    commands for setting frequency, mode, callsign lookup, and notes.

    This backend calls those commands via the macOS 'osascript' utility,
    which executes AppleScript from the command line.  The proxy must be
    running on the same Mac as MacLoggerDX.

    AppleScript reference:
      https://dogparksoftware.com/MacLoggerDX%20Help/mldxfc_script.html

    Commands used
    -------------
    setLogFrequency <MHz string>
        Sets the VFO frequency.  MacLoggerDX expects MHz (e.g. "14.074"),
        NOT kHz or Hz.  Conversion from Hz to MHz is done in tune() below.
        When a radio is connected this physically tunes the VFO.

    setLogMode <mode string>
        Sets the operating mode (e.g. "USB", "CW", "FT8").

    lookup <callsign string>
        Triggers an async QRZ/HamCall lookup for the callsign.
        Populates name, QTH, DXCC, grid etc. in the DX/Contest panel.
        This call is asynchronous — MacLoggerDX contacts QRZ in the
        background, so we delay before calling setNOTE to avoid a race
        condition where the lookup clears the Note field after we set it.

    setNOTE <string>
        Pre-populates the Note field in the DX/Contest panel with the
        POTA park reference and park name, e.g. "POTA US-1234 Yosemite".

    osascript usage
    ---------------
    Each -e argument is one line of AppleScript.  We build a multi-line
    script as a list of -e arguments, which is the standard pattern for
    driving AppleScript from a Python subprocess.
    Source: https://ss64.com/mac/osascript.html
            https://scriptingosx.com/2022/05/launching-scripts-4-applescript-from-shell-script/

    Security note
    -------------
    User input (callsign, park ref, park name) is passed via subprocess
    argument list — never interpolated into a shell string — so there is
    no shell injection risk even if a callsign or park name contains
    quotes or special characters.
    """

    name = "mldx"

    # Delay in seconds between the lookup call and the setNOTE call.
    # The lookup is asynchronous; MacLoggerDX contacts QRZ in the background.
    # If setNOTE is called too soon, MacLoggerDX may overwrite the note field
    # when the lookup response arrives.  1.5 s matches the original AppleScript.
    LOOKUP_DELAY = 1.5

    def _mldx_is_running(self) -> bool:
        """Return True if MacLoggerDX is in the running process list.
        Uses System Events so we never accidentally launch MLDX by addressing it."""
        result = self._osascript([
            'tell application "System Events"',
            'return (name of processes) contains "MacLoggerDX"',
            'end tell',
        ])
        return result.strip() == 'true'

    def ping(self) -> str:
        """
        Check that MacLoggerDX is running by fetching its version string
        via AppleScript.  Raises RuntimeError if MacLoggerDX is not running.

        IMPORTANT: We must check the running process list via System Events
        BEFORE sending 'tell application "MacLoggerDX"' — a bare tell will
        launch MLDX if it is not already running, which is the opposite of
        what a ping should do.
        """
        if not self._mldx_is_running():
            raise RuntimeError("MacLoggerDX is not running")
        result = self._osascript([
            'tell application "MacLoggerDX"',
            'get version',
            'end tell',
        ])
        return result.strip() or "ok"

    def check_udp_pref(self) -> dict:
        """
        Read the MacLoggerDX preferences plist to check whether UDP log
        broadcast is enabled.

        MLDX stores its prefs in:
          ~/Library/Preferences/com.dogparksoftware.MacLoggerDX.plist
        The relevant key is send_udp_broadcasts_<N> where N is the station
        number (usually 1).  Value is 1 when enabled, 0 when disabled.

        Returns a dict:
          {
            "found":   bool,  # plist file found
            "enabled": bool,  # any send_udp_broadcasts_* key is non-zero
          }
        """
        import plistlib

        plist_path = pathlib.Path.home() / "Library" / "Preferences" / \
                     "com.dogparksoftware.MacLoggerDX.plist"
        if not plist_path.exists():
            return {"found": False, "enabled": False}

        try:
            with open(plist_path, "rb") as f:
                prefs = plistlib.load(f)
        except Exception as e:
            log.debug("check_udp_pref: plist read error: %s", e)
            return {"found": True, "enabled": False, "error": str(e)}

        # Check any send_udp_broadcasts_<N> key — true if any station has it on.
        enabled = any(
            bool(v)
            for k, v in prefs.items()
            if k.startswith("send_udp_broadcasts_")
        )
        return {"found": True, "enabled": enabled}

    def tune(self, freq_hz: int, mode: str, callsign: str = "",
             note: str = "") -> None:
        """
        Tune MacLoggerDX to freq_hz/mode, look up the callsign, and
        set the Note field to the park reference.

        Sequence (mirrors the original POTASpots AppleScript):
          1. setLogFrequency  — tunes the VFO (MHz string required)
          2. setLogMode       — sets the mode
          3. lookup           — async QRZ/HamCall lookup
          4. delay            — wait for lookup to complete
          5. setNOTE          — pre-fill Note with POTA park reference

        freq_hz is in Hz (as received from the HTTP handler).
        MacLoggerDX wants MHz, so we convert here.
        """
        # Convert Hz -> MHz string (e.g. 14074000 -> "14.074")
        freq_mhz = f"{freq_hz / 1_000_000:.6f}".rstrip('0').rstrip('.')

        log.info("mldx  setLogFrequency  %s MHz", freq_mhz)
        log.info("mldx  setLogMode       %s", mode)
        log.info("mldx  lookup           %s", callsign)
        log.info("mldx  setNOTE          %s", note)

        # Build the AppleScript.  The delay command pauses execution inside
        # the tell block so the lookup has time to populate the fields before
        # setNOTE is called.  All values are injected via quoted string
        # literals in AppleScript — never interpolated into shell strings.
        script_lines = [
            'tell application "MacLoggerDX"',
            f'setLogFrequency "{freq_mhz}"',
            f'setLogMode "{mode}"',
            'setSplitKhz "0"',
        ]
        if callsign:
            script_lines += [
                f'lookup "{callsign}"',
                f'delay {self.LOOKUP_DELAY}',
            ]
        if note:
            safe_note = note.encode('ascii', errors='ignore').decode('ascii').replace('"', '').strip()
            if safe_note:
                script_lines.append(f'setNOTE "{safe_note}"')
        script_lines.append('end tell')

        self._osascript(script_lines)

    def get_worked(self, callsigns: list) -> dict:
        """
        Batch-query MacLoggerDX for QSO history for a list of callsigns.

        Makes a single pass over all QSOs, collecting count and most recent
        qso_start for each requested callsign. One osascript call total.

        Returns {callsign: {count, last_date, worked_today, last_band=None,
                             last_mode=None, last_freq_mhz=None, last_park_ref=None}}
        """
        if not callsigns:
            return {}

        # Guard: don't send 'tell application "MacLoggerDX"' if MLDX is not
        # already running — that would silently launch it.
        if not self._mldx_is_running():
            return {}

        from datetime import datetime, timezone
        today_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        # Build a set literal for AppleScript membership test
        calls_set = '{' + ', '.join(f'"{c}"' for c in callsigns) + '}'

        # Single pass over all QSOs — collect count + last date per callsign.
        # Returns pipe-delimited lines: CALL|count|last_date_string
        script = f'''
set targetCalls to {calls_set}
set cntList to {{}}
set dateList to {{}}
repeat with c in targetCalls
  set end of cntList to 0
  set end of dateList to ""
end repeat
tell application "MacLoggerDX"
  set total to count every qso
  repeat with i from 1 to total
    set c to call of qso i
    set pos to 0
    repeat with j from 1 to (count targetCalls)
      if item j of targetCalls is c then
        set pos to j
        exit repeat
      end if
    end repeat
    if pos > 0 then
      set item pos of cntList to (item pos of cntList) + 1
      set d to qso_start of qso i as string
      if d > item pos of dateList then set item pos of dateList to d
    end if
  end repeat
end tell
set result to ""
repeat with j from 1 to (count targetCalls)
  set result to result & item j of targetCalls & "|" & item j of cntList & "|" & item j of dateList & linefeed
end repeat
return result
'''
        try:
            raw = self._osascript([script])
        except RuntimeError as e:
            log.debug("get_worked AppleScript error: %s", e)
            return {}

        results = {}
        for line in raw.strip().splitlines():
            parts = line.split('|')
            if len(parts) < 3:
                continue
            call, count_str, last_date_str = parts[0], parts[1], parts[2]
            try:
                count = int(count_str)
            except ValueError:
                count = 0
            last_date = last_date_str.strip() or None
            # MLDX returns dates like "Saturday, April 4, 2026 at 14:28:49"
            # Check if today's date appears in the string.
            # Use str(day) to avoid %-d which is not portable to Windows.
            now_utc = datetime.now(timezone.utc)
            today_mldx = f"{now_utc.strftime('%B')} {now_utc.day}, {now_utc.year}"
            worked_today = bool(last_date and (today_utc in last_date or today_mldx in last_date))
            results[call] = {
                'count':         count,
                'last_date':     last_date,
                'worked_today':  worked_today,
                'last_band':     None,
                'last_mode':     None,
                'last_freq_mhz': None,
                'last_park_ref': None,
            }
        return results

    def start_log_listener(self, callback) -> None:
        """
        Bind UDP socket on port 9932 and listen for MacLoggerDX Log Report
        broadcasts. Calls callback(entry_dict) for each QSO logged.

        Log Report packet format (space-delimited key:value pairs):
          Log Report: Call:N2BJ, RxMHz:21.08580, TxMHz:21.08580, Band:15M,
          Mode:FSK, Power:5, logged_time:2014-12-30 17:33:57 +0000, ...

        Runs in a daemon thread. Safe to call multiple times — stops any
        existing listener first.
        """
        self.stop_log_listener()  # stop any existing listener

        self._listener_stop = threading.Event()

        def _listen():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('', 9932))
                sock.settimeout(1.0)
            except OSError as e:
                log.warning("UDP listener: cannot bind port 9932: %s", e)
                return

            log.info("UDP log listener started on port 9932")
            while not self._listener_stop.is_set():
                try:
                    data, _ = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    msg = data.decode('utf-8', errors='replace')
                    if 'Log Report:' not in msg:
                        continue
                    log.debug("UDP packet received: %s", msg.strip())
                    # Strip the "Log Report: " prefix so "Call:N2BJ" becomes
                    # the first token rather than being embedded in
                    # "Log Report: Call:N2BJ" where it would parse as
                    # key="log report", value="Call:N2BJ" — losing the call.
                    payload = msg[msg.index('Log Report:') + len('Log Report:'):].strip()
                    entry = {}
                    for token in payload.split(','):
                        token = token.strip()
                        if ':' in token:
                            k, _, v = token.partition(':')
                            entry[k.strip().lower()] = v.strip()
                    call = entry.get('call', '').upper()
                    if not call:
                        log.debug("UDP packet had no Call field: %s", entry)
                        continue
                    band = entry.get('band', '').lower()   # e.g. "20m"
                    mode = entry.get('mode', '').upper()   # e.g. "FT8"
                    # Collapse SSB variants
                    if mode in ('USB', 'LSB', 'AM'):
                        mode = 'SSB'
                    freq_tx = entry.get('txmhz', '') or entry.get('rxmhz', '')
                    logged_time = entry.get('logged_time', '')
                    log.info("UDP QSO: call=%s band=%s mode=%s", call, band or '?', mode or '?')
                    callback({
                        'call':         call,
                        'band':         band or None,
                        'mode':         mode or None,
                        'last_freq_mhz': freq_tx or None,
                        'last_date':    logged_time or None,
                        'last_park_ref': None,  # not in UDP packet
                    })
                except Exception as e:
                    log.debug("UDP parse error: %s", e)

            sock.close()
            log.info("UDP log listener stopped")

        self._listener_thread = threading.Thread(target=_listen, daemon=True)
        self._listener_thread.start()

    def stop_log_listener(self) -> None:
        """Stop the UDP listener thread and block until it exits."""
        stop_event = getattr(self, '_listener_stop', None)
        if stop_event:
            stop_event.set()
        thread = getattr(self, '_listener_thread', None)
        if thread and thread.is_alive():
            thread.join(timeout=3)
        self._listener_stop = None
        self._listener_thread = None

    def _osascript(self, lines: list) -> str:
        """
        Run a multi-line AppleScript via osascript.
        Each element of lines is passed as a separate -e argument.
        Returns stdout as a string.
        Raises RuntimeError on non-zero exit code.

        Values are passed as pre-built AppleScript string literals so
        that no user data ever touches the shell command string itself.
        Non-ASCII characters and embedded double-quotes are stripped from
        every line — both cause AppleScript syntax error -2741.
        Source: https://scriptingosx.com/2022/05/launching-scripts-4-applescript-from-shell-script/
        """
        import subprocess
        cmd = ["/usr/bin/osascript"]
        for line in lines:
            safe = line.encode('ascii', errors='ignore').decode('ascii')
            cmd += ["-e", safe]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"osascript error (exit {result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return result.stdout


# ════════════════════════════════════════════════════════════
# BACKEND: none (display only)
# ════════════════════════════════════════════════════════════

class NoneBackend(RigBackend):
    """No-op backend — browse spots without sending any rig commands."""

    name = "none"

    def tune(self, freq_hz: int, mode: str) -> None:
        log.info("none  (display only — no tune sent)")

    def ping(self) -> str:
        return "ok"


# ════════════════════════════════════════════════════════════
# BACKEND REGISTRY
# ════════════════════════════════════════════════════════════
#
# Maps the backend name (as it appears in the /tune/<backend> URL path
# and in the HTML dropdown) to a factory function that returns an
# instance of the corresponding RigBackend subclass.
#
# The factory receives the parsed command-line args so each backend can
# read its own host/port settings without the proxy needing to know
# what parameters each backend needs.
#
# To add a new backend:
#   1. Write the class above.
#   2. Add an entry here: "mybackend": lambda args: MyBackend(...)

def _build_backends(args):
    """
    Instantiate all registered backends using the provided CLI args.
    Returns a dict mapping name -> RigBackend instance.
    """
    return {
        "mldx":    MacLoggerDXBackend(),
        "flrig":   FlrigBackend(host=args.rig_host, port=args.rig_port),
        "rigctld": RigctldBackend(host=args.rig_host, port=args.rigctld_port),
        "none":    NoneBackend(),
    }


def _worked_cache_worker(get_active_backend):
    """
    Background thread that drains _lookup_queue and populates worked_cache.

    Pulls callsigns from the queue in batches of up to 50, calls
    active_backend.get_worked(), and writes results into worked_cache
    under the lock.  Runs forever as a daemon thread.
    """
    import time
    while True:
        batch = []
        try:
            # Block until at least one callsign is available
            batch.append(_lookup_queue.get(timeout=5))
        except queue.Empty:
            continue
        # Drain up to 49 more without blocking
        while len(batch) < 50:
            try:
                batch.append(_lookup_queue.get_nowait())
            except queue.Empty:
                break

        backend = get_active_backend()
        try:
            results = backend.get_worked(batch)
        except Exception as e:
            log.debug("get_worked error: %s", e)
            results = {}

        updates = {}
        with worked_cache_lock:
            for call, data in results.items():
                # Only update if not already in cache with richer data
                # (UDP listener may have already populated band/mode)
                existing = worked_cache.get(call)
                if existing and existing.get('last_band'):
                    # Keep the richer UDP data, just update count/date
                    existing['count'] = data['count']
                    if data['last_date']:
                        existing['last_date'] = data['last_date']
                    existing['worked_today'] = existing['worked_today'] or data['worked_today']
                    updates[call] = dict(existing)
                else:
                    worked_cache[call] = data
                    updates[call] = dict(data)

        for call, entry in updates.items():
            broker.publish('worked_update', {'call': call, 'entry': entry})


def _backend_monitor_worker(get_active_backend, interval=10):
    """
    Background thread that periodically pings the active backend and
    publishes 'backend_status' SSE events when status changes.

    Only fires an event on transition (up→down or down→up), not on
    every poll.  Skips NoneBackend entirely.  Resets state when the
    active backend changes so the first check after a switch always
    publishes an event.
    """
    import time
    last_name = None
    last_ok   = None

    while True:
        time.sleep(interval)
        backend = get_active_backend()
        name    = backend.name

        if name == 'none':
            last_name = None
            last_ok   = None
            continue

        # Backend switched — treat status as unknown so first check fires
        if name != last_name:
            last_name = name
            last_ok   = None

        try:
            backend.ping()
            ok    = True
            error = None
        except Exception as exc:
            ok    = False
            error = str(exc)

        if ok != last_ok:
            last_ok = ok
            broker.publish('backend_status', {
                'backend': name,
                'ok':      ok,
                'error':   error,
            })
            if ok:
                log.info("Backend '%s' reconnected.", name)
            else:
                log.warning("Backend '%s' went down: %s", name, error)


# ════════════════════════════════════════════════════════════
# SSE BROKER
# ════════════════════════════════════════════════════════════

class SSEBroker:
    """Push-channel broker. Holds one client slot; a second connection
    receives a 'conflict' event and is closed immediately."""

    def __init__(self):
        self._client: "queue.Queue | None" = None
        self._lock = threading.Lock()

    def connect(self) -> "tuple[queue.Queue, bool]":
        """Register a client. Returns (queue, is_primary).
        Non-primary callers should send the conflict event then disconnect."""
        q: queue.Queue = queue.Queue()
        with self._lock:
            if self._client is None:
                self._client = q
                return q, True
        return q, False  # conflict

    def disconnect(self, q: "queue.Queue") -> None:
        with self._lock:
            if self._client is q:
                self._client = None

    def publish(self, event_type: str, data: dict) -> None:
        with self._lock:
            q = self._client
        if q is not None:
            q.put((event_type, data))

    def close_current(self) -> None:
        """Signal the current client to disconnect immediately."""
        with self._lock:
            q = self._client
        if q is not None:
            q.put(None)  # sentinel — causes the handler loop to exit


broker = SSEBroker()


# HTTP PROXY HANDLER
# ════════════════════════════════════════════════════════════

class ProxyHandler(BaseHTTPRequestHandler):
    """
    Handles HTTP requests from POTASpotHunter.html.

    Supported routes
    ----------------
    GET /tune/<backend>?freq=<kHz>&mode=<mode>
        Tune the radio via the named backend.
        freq  : frequency in kHz (e.g. "14074.0") — converted to Hz here.
        mode  : mode string (e.g. "USB", "CW", "FT8").
        Returns JSON: {"ok": true, "backend": "...", "freq_hz": ..., "mode": "..."}

    GET /ping/<backend>
        Check that the named backend's rig-control program is reachable.
        Returns JSON: {"ok": true, "backend": "...", "version": "..."}
                   or {"ok": false, "error": "..."}

    GET /backends
        List all registered backends and their current host:port config.
        Returns JSON: {"backends": ["flrig", "rigctld"]}

    GET /version
        Return the app version string read from the VERSION file.
        Returns JSON: {"version": "1.2.0"}
        Used by www/index.html to display the version in the header
        without hardcoding it in two places.

    All responses include CORS headers so the browser does not block them
    when the page is loaded from a file:// URL.
    """

    # Injected by the server setup below so the handler can reach backends
    backends: dict = {}

    def log_message(self, fmt, *args):
        """Route http.server's default access log through our logger."""
        log.info("HTTP  " + fmt % args)

    def _cors_headers(self):
        """
        Emit CORS headers that allow the file:// origin used by the HTML page.
        Access-Control-Allow-Origin: * is intentional — this server only
        binds to 127.0.0.1 (localhost) so it is not reachable from the
        internet.  Restricting to a specific origin would require knowing
        the exact file:// path, which varies per user.
        """
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json_response(self, status: int, payload: dict):
        """Send a JSON response with CORS headers."""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        """
        Handle CORS preflight requests.
        The browser sends OPTIONS before a cross-origin GET; we must
        respond with the appropriate headers or the real request is blocked.
        """
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_POST(self):
        """Handle POST requests. Currently only /events/close (sendBeacon)."""
        path = urlparse(self.path).path.rstrip("/")
        if path == "/events/close":
            broker.close_current()
            self._json_response(200, {"ok": True})
        else:
            self._json_response(404, {"ok": False, "error": "Not found"})

    def do_GET(self):
        parsed   = urlparse(self.path)
        path     = parsed.path.rstrip("/")
        qs       = parse_qs(parsed.query)

        # ── Static file serving from www/ ───────────────────
        # The app is split into www/index.html, www/style.css, www/app.js.
        # Serving over HTTP (rather than file://) gives the page a real
        # origin (http://localhost:8080), which the browser sends as the
        # Referer header on tile requests to OpenStreetMap.
        WWW = pathlib.Path(__file__).parent / "www"
        STATIC = {
            "":          ("index.html",  "text/html; charset=utf-8"),
            "/":         ("index.html",  "text/html; charset=utf-8"),
            "/style.css": ("style.css",  "text/css; charset=utf-8"),
            "/app.js":    ("app.js",     "application/javascript; charset=utf-8"),
        }
        if path in ("", "/") or path in STATIC:
            filename, content_type = STATIC.get(path, STATIC[""])
            file_path = WWW / filename
            if not file_path.exists():
                self._json_response(404, {"ok": False, "error": f"{filename} not found in www/"})
                return
            content = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        # ── Route: /backends ────────────────────────────────
        if path == "/backends":
            self._json_response(200, {
                "backends": list(self.backends.keys())
            })
            return

        # ── Route: /version ──────────────────────────────────
        if path == "/version":
            self._json_response(200, {"version": APP_VERSION})
            return

        # ── Route: /worked ───────────────────────────────────
        # Returns a snapshot of the full worked_cache as JSON.
        # The browser polls this after each spot refresh.
        if path == "/worked":
            with worked_cache_lock:
                snapshot = dict(worked_cache)
            self._json_response(200, snapshot)
            return

        # ── Route: /events ───────────────────────────────────
        # SSE push channel. Holds the connection open and streams events.
        # Only one client is allowed; a second receives a conflict event.
        if path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            q, is_primary = broker.connect()
            if not is_primary:
                try:
                    self.wfile.write(b"event: conflict\ndata: {}\n\n")
                    self.wfile.flush()
                except OSError:
                    pass
                return
            try:
                while True:
                    try:
                        msg = q.get(timeout=5)
                        if msg is None:  # sentinel from close_current()
                            break
                        event_type, data = msg
                        payload = (
                            f"event: {event_type}\n"
                            f"data: {json.dumps(data)}\n\n"
                        ).encode()
                        self.wfile.write(payload)
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
            except OSError:
                pass
            finally:
                broker.disconnect(q)
            return

        # ── Route: /lookup_calls ─────────────────────────────
        # Enqueues callsigns for background AppleScript lookup.
        # Only queues if the active backend supports get_worked (i.e. MLDX).
        if path == "/lookup_calls":
            calls_param = (qs.get("calls") or [""])[0]
            calls = [c.strip().upper() for c in calls_param.split(",") if c.strip()]
            # Check if active backend actually implements get_worked
            active = self.get_active_backend()
            if type(active).get_worked is RigBackend.get_worked:
                # Base class no-op — don't bother queuing
                self._json_response(200, {"queued": 0})
                return
            queued = 0
            with worked_cache_lock:
                for call in calls:
                    if call not in worked_cache:
                        worked_cache[call] = None  # mark as in-flight
                        _lookup_queue.put(call)
                        queued += 1
            self._json_response(200, {"queued": queued})
            return

        # ── Route: /themes ───────────────────────────────────
        # Returns a list of theme names available in the themes/ directory.
        # The page fetches this at startup and loads each theme JSON file.
        if path == "/themes":
            themes_dir = pathlib.Path(__file__).parent / "themes"
            if themes_dir.exists():
                names = [f.stem for f in sorted(themes_dir.glob("*.json"))]
            else:
                names = []
            self._json_response(200, {"themes": names})
            return

        # ── Route: /themes/<name>.json ───────────────────────
        # Serves individual theme JSON files from the themes/ directory.
        if path.startswith("/themes/") and path.endswith(".json"):
            themes_dir = pathlib.Path(__file__).parent / "themes"
            theme_file = (themes_dir / path[len("/themes/"):]).resolve()
            if not str(theme_file).startswith(str(themes_dir.resolve())):
                self._json_response(403, {"ok": False, "error": "Forbidden"})
                return
            if not theme_file.exists() or not theme_file.is_file():
                self._json_response(404, {"error": "Theme not found"})
                return
            content = theme_file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self._cors_headers()
            self.end_headers()
            self.wfile.write(content)
            return

        # ── Route: /set_backend ──────────────────────────────
        # Switches the active backend, stopping/starting the log listener.
        # Called by the frontend when the user changes the Rig dropdown.
        if path == "/set_backend":
            name = (qs.get("backend") or [""])[0].strip()
            if self.set_active_backend(name):
                resp = {"ok": True, "backend": name}
                if name == "mldx":
                    backend = self.backends.get("mldx")
                    if hasattr(backend, "check_udp_pref"):
                        resp["udp_pref"] = backend.check_udp_pref()
                self._json_response(200, resp)
            else:
                self._json_response(400, {"ok": False, "error": f"Unknown backend '{name}'"})
            return

        # ── Route: /ping/<backend> ───────────────────────────
        if path.startswith("/ping/"):
            backend_name = path[len("/ping/"):]
            backend = self.backends.get(backend_name)
            if backend is None:
                self._json_response(404, {
                    "ok": False,
                    "error": f"Unknown backend '{backend_name}'. "
                             f"Available: {list(self.backends.keys())}"
                })
                return
            try:
                # Only FlrigBackend has ping(); others get a simple ok:true
                version = backend.ping() if hasattr(backend, "ping") else "n/a"
                resp = {"ok": True, "backend": backend_name, "version": version}
                # For MLDX, include UDP broadcast pref status so the UI can warn
                if backend_name == "mldx" and hasattr(backend, "check_udp_pref"):
                    resp["udp_pref"] = backend.check_udp_pref()
                self._json_response(200, resp)
            except (ConnectionRefusedError, OSError, RuntimeError) as e:
                self._json_response(503, {
                    "ok":    False,
                    "error": f"Cannot reach {backend_name} — is it running? ({e})"
                })
            return

        # ── Route: /tune/<backend> ───────────────────────────
        if path.startswith("/tune/"):
            backend_name = path[len("/tune/"):]
            backend = self.backends.get(backend_name)
            if backend is None:
                self._json_response(404, {
                    "ok": False,
                    "error": f"Unknown backend '{backend_name}'. "
                             f"Available: {list(self.backends.keys())}"
                })
                return

            # Parse and validate required query parameters.
            # callsign and note are optional — not all backends use them,
            # but MacLoggerDX uses both for lookup and park reference.
            freq_khz_str = (qs.get("freq")     or [None])[0]
            mode_str     = (qs.get("mode")     or [None])[0]
            callsign     = (qs.get("callsign") or [""])[0].strip()
            note         = (qs.get("note")     or [""])[0].strip()

            if not freq_khz_str or not mode_str:
                self._json_response(400, {
                    "ok":    False,
                    "error": "Missing required query parameters: freq (kHz) and mode."
                })
                return

            try:
                freq_khz = float(freq_khz_str)
            except ValueError:
                self._json_response(400, {
                    "ok":    False,
                    "error": f"Invalid freq value '{freq_khz_str}' — expected a number in kHz."
                })
                return

            # Convert kHz → Hz for the backend.
            # All backends receive Hz; each backend converts further if its
            # protocol uses a different unit (e.g. MHz for MacLoggerDX).
            freq_hz = int(round(freq_khz * 1000))
            mode    = mode_str.upper().strip()

            log.info(
                "TUNE  backend=%-8s  freq=%d Hz (%.3f kHz)  mode=%-6s  "
                "callsign=%-10s  note=%s",
                backend_name, freq_hz, freq_khz, mode, callsign or "-", note or "-"
            )

            try:
                # Pass callsign and note as keyword args.
                # Backends that don't accept them (flrig, rigctld) use the
                # base signature tune(freq_hz, mode) and will ignore extras
                # if we use inspect to check, but it's cleaner to just try
                # with kwargs and let Python raise TypeError if unsupported.
                sig = inspect.signature(backend.tune)
                kwargs = {}
                if "callsign" in sig.parameters:
                    kwargs["callsign"] = callsign
                if "note" in sig.parameters:
                    kwargs["note"] = note
                backend.tune(freq_hz, mode, **kwargs)

                self._json_response(200, {
                    "ok":       True,
                    "backend":  backend_name,
                    "freq_hz":  freq_hz,
                    "freq_khz": freq_khz,
                    "mode":     mode,
                    "callsign": callsign,
                    "note":     note,
                })
            except NotImplementedError as e:
                self._json_response(501, {
                    "ok":    False,
                    "error": str(e)
                })
            except (ConnectionRefusedError, OSError) as e:
                self._json_response(503, {
                    "ok":    False,
                    "error": f"Cannot reach {backend_name} — is it running? ({e})"
                })
            except RuntimeError as e:
                self._json_response(500, {
                    "ok":    False,
                    "error": str(e)
                })
            return

        # ── 404 for everything else ──────────────────────────
        self._json_response(404, {
            "ok":    False,
            "error": f"Unknown route '{path}'. "
                     "Valid routes: /tune/<backend>, /ping/<backend>, /backends"
        })


# ════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════

def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "POTA Spot Hunter local proxy — bridges POTASpotHunter.html "
            "to local rig-control software (flrig, rigctld, etc.)."
        )
    )
    p.add_argument(
        "--backend",
        default="mldx",
        choices=["mldx", "flrig", "rigctld"],
        help="Default rig-control backend to use (default: mldx).",
    )
    p.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for this proxy to listen on (default: 8080).",
    )
    p.add_argument(
        "--rig-host",
        default="127.0.0.1",
        metavar="HOST",
        help="Hostname/IP of the rig-control program (default: 127.0.0.1).",
    )
    p.add_argument(
        "--rig-port",
        type=int,
        default=12345,
        metavar="PORT",
        help="Port for flrig (default: 12345).",
    )
    p.add_argument(
        "--rigctld-port",
        type=int,
        default=4532,
        metavar="PORT",
        help="Port for rigctld (default: 4532).",
    )
    p.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically open POTASpotHunter.html in the browser.",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose debug logging.",
    )
    return p.parse_args()


def main():
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Build backend instances
    backends = _build_backends(args)

    # Active backend — starts as 'none' regardless of --backend arg.
    # The user must explicitly select a backend in the UI to activate it.
    # This prevents MLDX AppleScript calls before the user opts in.
    _active_backend_lock = threading.Lock()
    _active_backend = [backends['none']]

    def get_active_backend():
        with _active_backend_lock:
            return _active_backend[0]

    def set_active_backend(name):
        backend = backends.get(name)
        if not backend:
            return False
        with _active_backend_lock:
            old = _active_backend[0]
            old.stop_log_listener()
            _active_backend[0] = backend
            backend.start_log_listener(_on_qso_logged)
        return True

    def _on_qso_logged(entry):
        """Callback from UDP listener — update worked_cache with real-time QSO data."""
        call = entry.get('call', '').upper()
        if not call:
            return
        from datetime import datetime, timezone
        today_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        with worked_cache_lock:
            existing = worked_cache.get(call) or {'count': 0, 'last_date': None,
                                                   'worked_today': False, 'last_band': None,
                                                   'last_mode': None, 'last_freq_mhz': None,
                                                   'last_park_ref': None}
            existing['count'] += 1
            existing['last_date'] = entry.get('last_date') or existing['last_date']
            existing['worked_today'] = True
            existing['last_band'] = entry.get('band') or existing['last_band']
            existing['last_mode'] = entry.get('mode') or existing['last_mode']
            existing['last_freq_mhz'] = entry.get('last_freq_mhz') or existing['last_freq_mhz']
            worked_cache[call] = existing
        log.info("QSO logged: %s  band=%s  mode=%s", call,
                 entry.get('band'), entry.get('mode'))
        broker.publish('worked_update', {'call': call, 'entry': dict(existing)})

    # Inject backends and active_backend accessor into the handler class
    ProxyHandler.backends = backends
    ProxyHandler.get_active_backend = staticmethod(get_active_backend)
    ProxyHandler.set_active_backend = staticmethod(set_active_backend)

    # Start background worker thread for AppleScript batch lookups
    worker = threading.Thread(
        target=_worked_cache_worker,
        args=(get_active_backend,),
        daemon=True,
        name="worked-cache-worker",
    )
    worker.start()

    # Start backend monitor thread — pings the active backend every 10s
    # and publishes 'backend_status' SSE events on status changes.
    monitor = threading.Thread(
        target=_backend_monitor_worker,
        args=(get_active_backend,),
        daemon=True,
        name="backend-monitor",
    )
    monitor.start()

    # Bind to localhost only — never expose this to the network.
    server = ThreadingHTTPServer(("127.0.0.1", args.port), ProxyHandler)

    # Resolve the www/ directory path relative to this script's location.
    script_dir = pathlib.Path(__file__).parent.resolve()
    html_path  = script_dir / "www" / "index.html"

    log.info("=" * 60)
    log.info("POTA Spot Hunter v%s  —  listening on 127.0.0.1:%d", APP_VERSION, args.port)
    log.info("Default backend : %s",   args.backend)
    log.info("flrig           : %s:%d", args.rig_host, args.rig_port)
    log.info("rigctld         : %s:%d", args.rig_host, args.rigctld_port)
    log.info("Registered backends: %s", ", ".join(backends.keys()))
    log.info("")
    log.info("Routes:")
    log.info("  GET /tune/<backend>?freq=<kHz>&mode=<mode>")
    log.info("  GET /ping/<backend>")
    log.info("  GET /backends")
    log.info("")
    log.info("HTML file: %s", html_path)

    # Open the HTML page in the default browser unless suppressed.
    # We wait until after the server is confirmed to be bound (the
    # HTTPServer constructor raises immediately if the port is in use)
    # before opening the browser, so the page's startup ping will
    # always find the proxy ready.
    if args.no_browser:
        log.info("Browser auto-open suppressed (--no-browser).")
    elif not html_path.exists():
        log.warning(
            "POTASpotHunter.html not found at %s — "
            "cannot open browser automatically.  "
            "Place POTASpotHunter.html in the same directory as pota_proxy.py.",
            html_path,
        )
    else:
        # Open in a background thread so it doesn't block serve_forever().
        def _open():
            import time
            time.sleep(0.5)
            url = f"http://localhost:{args.port}/"
            log.info("Opening browser: %s", url)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    log.info("Press Ctrl-C to stop.")
    log.info("=" * 60)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
