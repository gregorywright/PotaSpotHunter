#!/usr/bin/env python3
"""
udp_sniff.py — MLDX UDP log report sniffer

Run this while PotaProxy.py is STOPPED (both can't bind port 9932 at once).
Log a QSO in MacLoggerDX. If MLDX sends UDP broadcasts you'll see them here.

Usage:
    python3 udp_sniff.py
"""
import socket

PORT = 9932

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock.bind(('', PORT))
except OSError as e:
    print(f"ERROR: Cannot bind port {PORT}: {e}")
    print("Is PotaProxy.py running? Stop it first, then run this script.")
    raise SystemExit(1)

print(f"Listening on UDP port {PORT} — log a QSO in MacLoggerDX now...")
print("Press Ctrl+C to stop.\n")

try:
    while True:
        data, addr = sock.recvfrom(4096)
        msg = data.decode('utf-8', errors='replace')
        print(f"--- Packet from {addr[0]}:{addr[1]} ---")
        print(repr(msg))
        print()
except KeyboardInterrupt:
    print("\nStopped.")
finally:
    sock.close()
