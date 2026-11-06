# TubeGrab project state

_Last updated: 2026-11-06_

## Current state

- Branch: `main` (merged from `feature/apple-ui`)
- Version: `1.2.0`
- Base: `main` at the 1.1.1 release commit
- Interface: Apple-inspired light/dark Tkinter UI with antialiased canvas surfaces
- Palette: light/dark grays plus one blue accent; red is reserved for errors
- Downloads: sequential queue with resume/retry, **Start over**, JS runtime detection, and RPM packaging

## Completed in this branch

- Replaced the original dark ttk layout with a custom Apple-like interface.
- Added `tubegrab/widgets.py`:
  - Canvas-drawn rounded cards, buttons, fields, segmented control, popup select, progress bar,
    status controls, and scroll frame
  - antialiased corner-tile renderer with per-surface background blending
- Added light/dark palettes following GNOME `color-scheme`.
- Added compact responsive layout:
  - native title bar only (no in-app header)
  - Preview always equal in height to Options
  - URL actions stack below the field on narrow windows
  - Options/Preview stack vertically below ~820px content width
- Reworked the quality popup into a custom dropdown that closes on outside click, `Escape`,
  selection, and application focus loss.
- Removed all custom cursors and the green accent; disabled Download is now neutral gray.
- Replaced the application icon with the new YouTube-down-arrow mark and regenerated every PNG size.
- Fixed the Tk 9 scroll-region centering bug that collapsed the page margin after resizing.
- Removed the bottom “Open Folder”/“Details” links and separator; diagnostics remain in the rotating log.
- Removed the bottom “Ready” state; status text appears only while downloading or after an error.
- Fixed accidental page overscroll when content fits.
- Improved download recovery:
  - auto-detected Node/Deno/Bun runtime passed to yt-dlp
  - retries raised to 10
  - **Start over** uses `--no-continue` to discard corrupt partial files
  - clearer interrupted-transfer error message
- Antialiased text now requires and prefers an Xft Tk build; `install.sh` probes for one.

## Open items

- No RPM binary is committed; `dist/` stays local and git-ignored.
- The existing corrupt `.part` file in `~/Videos` must be discarded via **Start over** or manually.
- Native GNOME title bar is intentionally retained; no custom traffic lights.
- Tk Canvas has no backdrop blur or CSS shadows; the visual treatment is an approximation.

## Verification

```bash
python3 -m compileall -q tubegrab.py tubegrab tests
python3 -m unittest discover -s tests
/usr/bin/python3 -m unittest discover -s tests
```

Current result: **63 tests pass** under both the mise Python and system Python.

Manual checks:

- light and dark at 1040x700, 900x620, 800x620, and 640x600
- Preview/Options equal height
- quality popup dismisses on outside click, focus loss, `Escape`, and selection
- no page scrollbar when content fits
- disabled Download is gray; enabled is blue
- no green in normal/success UI

## Vitals

Measured 2026-11-02:

| Item | Value |
| --- | --- |
| Idle app RSS | 45.3 MiB (stable over 25 s) |
| Bare Tk RSS | 31.9 MiB |
| Source tree | 292 KiB |
| Assets | 76 KiB |
| Installed app | 308 KiB |
| RPM | 78 KiB |

## Build and install

```bash
./install.sh                 # per-user install, prefers an Xft Tk
./packaging/build-rpm.sh     # Fedora noarch RPM in dist/
~/.local/bin/tubegrab        # launch installed app
```

RPM output:

```text
dist/tubegrab-1.2.0-1.fc44.noarch.rpm
```
