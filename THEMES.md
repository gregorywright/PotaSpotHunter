# POTA Spot Hunter — Theme Guide

Themes control the colors, map tile appearance, and visual effects of the app.
The built-in `the-matrix` theme is hardcoded in the app (pure black, digital rain green). All other themes
live as `.json` files in the `themes/` directory and are loaded automatically
at startup.

---

## Installing a theme

Drop a `.json` file into the `themes/` folder alongside `PotaProxy.py`.
Restart the proxy (or just reload the page) — the theme will appear in the
🎨 dropdown in the header.

---

## Creating a theme

A theme file is a JSON object with CSS variable names as keys. Every variable
must be present — partial themes are not supported (missing variables bleed
from the previously active theme).

### Minimal example

```json
{
  "name": "my-theme",
  "description": "A brief description shown nowhere yet, but good practice",
  "--bg": "#1a1a2e",
  "--surface": "#16213e",
  "--surface2": "#0f3460",
  "--border": "#533483",
  "--green": "#e94560",
  "--green-dim": "#7a1a2a",
  "--green-faint": "#2a0a10",
  "--amber": "#f5a623",
  "--amber-dim": "#7a5010",
  "--red": "#ff4444",
  "--text": "#e0e0e0",
  "--text-dim": "#888888",
  "--text-bright": "#ffffff",
  "--tooltip-bg": "#0f3460",
  "--tooltip-text": "#e0e0e0",
  "--scanline": "transparent",
  "--map-filter": "none"
}
```

### Variable reference

| Variable | Role | Example values |
|---|---|---|
| `--bg` | Page background | `#0d0f0e` |
| `--surface` | Elevated surfaces (header, toolbar) | `#141714` |
| `--surface2` | Hover/active surface | `#1a1d1a` |
| `--border` | Borders and dividers | `#2a2e2a` |
| `--green` | Primary accent — logo, active states, links | `#39ff6a` |
| `--green-dim` | Dimmed accent | `#1a7a35` |
| `--green-faint` | Very faint accent — active row background | `#0d3319` |
| `--amber` | Secondary highlight — frequency, scan bar, tooltip border | `#ffb830` |
| `--amber-dim` | Dimmed highlight | `#7a5010` |
| `--red` | Errors and warnings | `#ff4444` |
| `--text` | Body text | `#c8d4c8` |
| `--text-dim` | Muted/secondary text | `#5a6b5a` |
| `--text-bright` | High-emphasis text | `#e8f4e8` |
| `--tooltip-bg` | Tooltip background | `#1e1a0e` |
| `--tooltip-text` | Tooltip text | `#e8f4e8` |
| `--scanline` | CRT scanline overlay color | `rgba(0,0,0,0.09)` or `transparent` |
| `--map-filter` | CSS filter applied to map tiles | `none`, `brightness(0.7)`, `invert(1) hue-rotate(180deg)`, `sepia(0.5)` |

### Tips

- **Dark themes** — set `--scanline` to `rgba(0,0,0,0.07)` for a subtle CRT
  effect, or `transparent` to disable it.
- **Light themes** — always set `--scanline: transparent`. Set `--tooltip-bg`
  to a light color and `--tooltip-text` to a dark color so tooltips match
  the page.
- **Map filter** — `invert(1) hue-rotate(180deg)` creates a dark map from
  OSM's light tiles. `sepia(0.5)` gives a warm antique look. `none` leaves
  tiles unchanged.
- **Naming** — the filename (without `.json`) is used as the theme name in
  the dropdown. Use lowercase with hyphens: `my-theme.json`.

### Bundled themes

| File | Description |
|---|---|
| `delta-loop.json` | Purple-tinted dark, inverted map tiles |
| `firefly-browncoats.json` | Dusty frontier western-in-space, sepia map |
| `green-terminal-crt.json` | Classic ham radio terminal with CRT scanlines |
| `locutus-of-borg.json` | Dark metallic Borg green, resistance is futile |
| `mr-clean.json` | Sparkling white, high contrast |
| `solarized-light.json` | Warm cream, sepia map tiles |

---

## Sharing themes

Theme files are self-contained JSON — share them by posting the file.
Others install it by dropping it into their `themes/` folder.
