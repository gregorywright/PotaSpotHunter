#!/usr/bin/env python3
"""
build.py — developer utility for PotaSpotHunter

Usage:
  python3 build.py test    — run the test suite
  python3 build.py         — run with no args to see this help
"""
import sys
import subprocess


def run_tests():
    # Try python3 -m pytest first (works with venv / pip-installed pytest),
    # then fall back to the pytest binary on PATH (works with brew-installed pytest).
    import shutil
    use_module = False
    try:
        import pytest
        use_module = True
    except ImportError:
        if not shutil.which('pytest'):
            print("pytest is not installed. Install it with one of:")
            print("  brew install pytest          # macOS with Homebrew")
            print("  pip install -r requirements-dev.txt")
            sys.exit(1)

    cmd = [sys.executable, '-m', 'pytest'] if use_module else ['pytest']
    result = subprocess.run(cmd + ['tests/', '-v'], cwd=sys.path[0] or '.')
    sys.exit(result.returncode)


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else None
    if cmd == 'test':
        run_tests()
    else:
        print(__doc__)
