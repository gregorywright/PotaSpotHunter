# Contributing to POTA Spot Hunter

Thanks for your interest in contributing!

## Project structure

| File | Purpose |
|------|---------|
| `www/index.html` | HTML shell — served by proxy |
| `www/style.css` | All CSS styles |
| `www/app.js` | All JavaScript |
| `PotaProxy.py` | Local Python proxy server |
| `tests/` | Unit tests for the proxy |
| `build.py` | Developer utility (run tests, future: build HTML from source) |
| `requirements-dev.txt` | Dev dependencies (pytest) |

## Running the app

```bash
python3 PotaProxy.py
```

This starts the proxy on `localhost:8080` and opens the browser automatically.
No build step required — edit files in `www/` and reload the browser.

## Running the tests

First, install the dev dependencies. Choose the method that matches your setup:

**macOS with Homebrew (recommended on macOS):**
```bash
brew install pytest
```

**Anywhere else (Linux, Windows, non-Homebrew macOS):**
```bash
pip install -r requirements-dev.txt
```

**Using a virtual environment (if pip is blocked system-wide):**
```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

Then run the tests:
```bash
python3 build.py test
```

## Notes

- `PotaProxy.py` has no runtime dependencies — only the Python standard library.
- Tests mock all external calls (osascript, sockets) — no radio software needed.
- The `tests/` directory and `build.py` are excluded from the release ZIP.
