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
  Python 3.6+    (no third-party packages needed)
  flrig          running and connected to the radio
"""

import argparse
import json
import logging
import pathlib
import socket
import sys
import xmlrpc.client
from http.server import BaseHTTPRequestHandler, HTTPServer
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
# The version is exposed via the /version HTTP route so PotaSpotHunter.html
# can display it in the header without hardcoding it in two places.
_version_file = pathlib.Path(__file__).parent / "VERSION"
try:
    APP_VERSION = _version_file.read_text(encoding="utf-8").strip()
except OSError:
    APP_VERSION = "unknown"


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

    def ping(self) -> str:
        """
        Check that MacLoggerDX is running by fetching its version string
        via AppleScript.  Raises RuntimeError if MacLoggerDX is not running.
        """
        result = self._osascript([
            'tell application "MacLoggerDX"',
            'get version',
            'end tell',
        ])
        return result.strip() or "ok"

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
            # AppleScript string literals cannot contain non-ASCII characters
            # or embedded double-quotes — both cause a syntax error (-2741).
            # Strip them before injecting into the script.
            safe_note = note.encode('ascii', errors='ignore').decode('ascii').replace('"', '').strip()
            if safe_note:
                script_lines.append(f'setNOTE "{safe_note}"')
        script_lines.append('end tell')

        self._osascript(script_lines)

    def _osascript(self, lines: list) -> str:
        """
        Run a multi-line AppleScript via osascript.
        Each element of lines is passed as a separate -e argument.
        Returns stdout as a string.
        Raises RuntimeError on non-zero exit code.

        Values are passed as pre-built AppleScript string literals so
        that no user data ever touches the shell command string itself.
        Source: https://scriptingosx.com/2022/05/launching-scripts-4-applescript-from-shell-script/
        """
        import subprocess
        cmd = ["/usr/bin/osascript"]
        for line in lines:
            cmd += ["-e", line]

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

    Each backend uses args.rig_host for the host address (defaults to
    127.0.0.1) but its own well-known default port so that flrig and
    rigctld can both be registered simultaneously without conflict:
      flrig   : port 12345  (overridden by --rig-port)
      rigctld : port 4532   (fixed; rigctld has its own --rigctld-port
                             if you need to change it — see argparse below)
    """
    return {
        "mldx":    MacLoggerDXBackend(),
        "flrig":   FlrigBackend(host=args.rig_host, port=args.rig_port),
        "rigctld": RigctldBackend(host=args.rig_host, port=args.rigctld_port),
        # Add future backends here, e.g.:
        # "omnirig": OmniRigBackend(),
    }


# ════════════════════════════════════════════════════════════
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
        Used by PotaSpotHunter.html to display the version in the header
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

    def do_GET(self):
        parsed   = urlparse(self.path)
        path     = parsed.path.rstrip("/")
        qs       = parse_qs(parsed.query)

        # ── Route: /backends ────────────────────────────────
        if path == "/backends":
            self._json_response(200, {
                "backends": list(self.backends.keys())
            })
            return

        # ── Route: /version ──────────────────────────────────
        # Returns the app version from the VERSION file.
        # Called by PotaSpotHunter.html at startup to display the version
        # in the page header without duplicating it in the HTML source.
        if path == "/version":
            self._json_response(200, {"version": APP_VERSION})
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
                self._json_response(200, {
                    "ok":      True,
                    "backend": backend_name,
                    "version": version,
                })
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
                import inspect
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

    # Inject backends into the handler class (shared across all requests)
    ProxyHandler.backends = backends

    # Bind to localhost only — never expose this to the network.
    server = HTTPServer(("127.0.0.1", args.port), ProxyHandler)

    # Resolve the HTML file path relative to this script's location.
    # This works whether the script is run from its own directory or
    # from a different working directory (e.g. ~/Scripts/pota_proxy.py
    # will look for ~/Scripts/POTASpotHunter.html).
    # pathlib is imported at the top of this file (needed for VERSION too).
    script_dir = pathlib.Path(__file__).parent.resolve()
    html_path  = script_dir / "POTASpotHunter.html"

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
        import webbrowser, threading
        # Open in a background thread so it doesn't block serve_forever().
        # A short delay ensures the server's accept loop is running before
        # the browser sends its first request.
        def _open():
            import time
            time.sleep(0.5)
            url = html_path.as_uri()   # converts to file:///path/to/...
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
