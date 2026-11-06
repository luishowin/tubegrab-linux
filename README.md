<p align="center">
  <img src="tubegrab/assets/tubegrab.svg" width="112" height="112" alt="TubeGrab logo">
</p>

# TubeGrab

TubeGrab is a small, native-feeling Linux desktop utility for downloading video and audio with
[yt-dlp](https://github.com/yt-dlp/yt-dlp) and FFmpeg. It keeps the original Tkinter/ttk toolkit
used by the original project, adds an Apple-inspired light/dark interface, a sequential download
queue, and a metadata preview, and installs entirely in your home directory.

Use it only for content you own, have permission to download, or are otherwise legally entitled
to save. Respect the source site's terms and applicable copyright law.

## Features

- Apple-inspired light/dark interface that follows the GNOME color scheme, with antialiased
  rounded surfaces, a gray-and-blue palette, a segmented format picker, and keyboard-accessible
  custom controls.
- Compact responsive layout: the native title bar is the only header, Preview always matches the
  Options card height, and narrow windows stack the URL actions and cards instead of clipping.
- Explicit metadata preview: title, thumbnail, duration, uploader/channel, resolutions, and audio
  formats (no video download is performed for previews).
- Sequential download queue: add more links while one is downloading, cancel the active item,
  retry failed/cancelled items (resume or start over), remove queued/completed items, and clear
  finished rows.
- Video quality selection: best available, 2160p, 1440p, 1080p, 720p, 480p, 360p, 240p, or 144p. The selector
  always falls back to the best format at or below the selected height.
- Separate best video/audio streams are merged into MKV without re-encoding. A combined source
  stream keeps its own compatible container.
- Audio can be kept in its original source format (typically Opus or AAC, no lossy conversion), or
  converted to high-quality MP3 V0 VBR (~245 kbps).
- Download folder picker, remembered destination, and an **Open folder** action.
- Readable Unicode filenames, no silent overwrites, and clear handling of already-downloaded files.
- Background workers for metadata, downloads, conversion, and thumbnails; the interface never
  blocks on those operations.
- Cancellation terminates the whole yt-dlp/FFmpeg process group, not just the parent process.
- Concise user-facing errors with full diagnostics in a rotating log file.
- Per-user GNOME application launcher and icon.

## Project status

- Version **1.2.0** on `main`.
- 63 automated tests; the GUI smoke tests run when a display is available.
- Fedora `noarch` RPM is built with `./packaging/build-rpm.sh`.
- Larger design/build notes: [PROJECT_STATE.md](PROJECT_STATE.md) and [BUILD-NOTES.txt](BUILD-NOTES.txt).

## Requirements

TubeGrab targets Fedora Workstation/GNOME on Linux, but it should work on other Linux desktops with
Tkinter.

Required:

- Python 3 with Tkinter
- yt-dlp
- FFmpeg (including FFprobe for some yt-dlp operations)

On Fedora:

```bash
sudo dnf install python3-tkinter yt-dlp ffmpeg-free
```

Notes:

- `python3-tkinter` provides Tkinter for Fedora's system Python. If you use a pyenv/mise/conda
  Python instead, make sure that interpreter can import `tkinter`; the installer looks for a working
  interpreter automatically and prefers one whose Tk uses Xft, so text is antialiased. You can point
  it at a specific interpreter with `TUBEGRAB_PYTHON`.
- Fedora's `ffmpeg-free` build is sufficient for normal merging and MP3 conversion. If a particular
  codec is unavailable, install the full FFmpeg package from a trusted repository such as RPM Fusion.
- yt-dlp changes frequently. Update it with `sudo dnf upgrade yt-dlp` (or however you installed it).
  A JavaScript runtime (Node.js, Deno, or Bun) is optional but recommended for YouTube extraction;
  TubeGrab auto-detects one and passes it to yt-dlp.

## Install

From the project directory:

```bash
cd /path/to/tubegrab-linux
./install.sh
```

The installer is per-user and does **not** use sudo. It installs:

- application code: `~/.local/share/tubegrab/` (or `$XDG_DATA_HOME/tubegrab/`)
- command: `~/.local/bin/tubegrab`
- desktop entry: `~/.local/share/applications/tubegrab.desktop`
- icons: `~/.local/share/icons/hicolor/.../apps/tubegrab.*`

Make sure `~/.local/bin` is on your `PATH` for the terminal command; the GNOME application grid does
not require it. Launch TubeGrab from the application grid or run:

```bash
tubegrab
```

You can also run it directly from the project during development:

```bash
python3 tubegrab.py
# or
python3 -m tubegrab
```

If the installer cannot find a Tk-capable Python:

```bash
sudo dnf install python3-tkinter
./install.sh
```

or select an interpreter explicitly:

```bash
TUBEGRAB_PYTHON=/path/to/python3 ./install.sh
```

### Fedora RPM

A system-wide `noarch` RPM can be built from the project directory:

```bash
sudo dnf install rpm-build
./packaging/build-rpm.sh
sudo dnf install dist/tubegrab-1.2.0-1.fc44.noarch.rpm
```

The RPM installs the application under `/usr/share/tubegrab`, the `tubegrab` command in
`/usr/bin`, and the desktop entry and icons system-wide. It pulls in `python3-tkinter`, `yt-dlp`,
and FFmpeg as dependencies. Remove it with `sudo dnf remove tubegrab`. Use `install.sh` instead if
you prefer a per-user installation without root.

## Use

1. Paste an http:// or https:// link and press **Download**, or press **Preview** first to inspect
   the video. Enter in the link field downloads; Ctrl+Enter previews.
2. Choose **Video**, **Audio · original**, or **Audio · MP3**.
3. For video, choose the maximum quality. The best available format at or below that height is used
   when the requested height is unavailable.
4. Choose a destination folder, then add more links if desired. Downloads run one at a time.
5. Use row buttons to cancel, retry, remove, or open the destination.

### Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| Enter | Download the link / add it to the queue |
| Ctrl+Enter | Fetch preview metadata |
| Ctrl+L | Focus the link field |
| Ctrl+O | Choose the download folder |
| Escape | Cancel the active download |
| Ctrl+Q | Quit (asks before cancelling an active download) |

### Audio choices

- **Audio · original** downloads the best available audio-only stream and extracts it without a
  lossy conversion. The source may be Opus (`.opus`) or AAC (`.m4a`).
- **Audio · MP3** converts the source audio to MP3 V0 variable bitrate. This is a lossy conversion;
  the conversion quality is distinct from the source stream quality.
- **Video** downloads separate best-quality video/audio streams when available and merges them using
  FFmpeg. MKV is used when merging so modern codecs can be combined without re-encoding. A single
  combined stream is left in its original container.

### Duplicate and existing files

The output filename is based on the video title plus the yt-dlp video ID, so different videos do not
collide. Existing files are not overwritten: if the target already exists, TubeGrab reports that it
was left untouched. Use a different folder if you intentionally want a second copy.

## Configuration and logs

- Settings: `~/.config/tubegrab/config.json` (or `$XDG_CONFIG_HOME/tubegrab/config.json`)
  - remembered destination, download mode, video quality, window size
  - no cookies, passwords, or authentication data are stored
- Logs: `~/.local/state/tubegrab/tubegrab.log` (rotated; or `$XDG_STATE_HOME/...`)
- Thumbnail cache: `~/.cache/tubegrab/thumbnails/` (or `$XDG_CACHE_HOME/...`)

The rotating log at `~/.local/state/tubegrab/tubegrab.log` contains more verbose yt-dlp output
useful for bug reports.

## Update

Replace the source files with the newer version, then rerun the installer:

```bash
cd /path/to/tubegrab-linux
./install.sh
```

If you keep the project in git:

```bash
git pull
./install.sh
```

Reinstalling updates the installed code, desktop entry, and icons while preserving your settings.
You can also keep using `python3 tubegrab.py` from the source directory without installing.

If you installed the RPM, build the newer version and upgrade it:

```bash
./packaging/build-rpm.sh
sudo dnf upgrade dist/tubegrab-<version>-1.fc44.noarch.rpm
```

## Uninstall

```bash
./uninstall.sh
```

This removes only TubeGrab's installed launcher, application code, desktop entry, and icons. Settings,
logs, caches, and downloaded media are kept. To remove the settings/log/cache directories too:

```bash
./uninstall.sh --purge
```

Downloads are never deleted. Use the same `PREFIX`/`XDG_DATA_HOME` as during installation if you
customized them.

## Tests

No third-party test runner is required:

```bash
python3 -m compileall -q tubegrab.py tubegrab tests
python3 -m unittest discover -s tests -v
```

The GUI smoke tests run when a display is available and are skipped otherwise. Network tests are not
part of the automated suite; metadata and download behavior depends on the source site.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| `yt-dlp was not found` | `sudo dnf install yt-dlp`, then restart TubeGrab. |
| `FFmpeg was not found` | `sudo dnf install ffmpeg-free`. Video merging and MP3 conversion need it. Original audio may still work. |
| Private, age-restricted, or "confirm you're not a bot" | TubeGrab does not bypass sign-in, age gates, DRM, or bot checks. Use a lawful source you can access. |
| Unsupported URL | The site is not supported by the installed yt-dlp version. Update yt-dlp or use a supported source. |
| Network or timeout errors | Check your connection and retry the queue item. Partial files from failed attempts are kept for **Retry**; use **Start over** to discard a corrupt partial and download again. Cancelled items are cleaned up. |
| MP3 or a codec conversion fails | Your FFmpeg build may lack the codec. Try full FFmpeg from a trusted third-party repository, or choose **Audio · original**. |
| yt-dlp warns about a missing JavaScript runtime | See the current yt-dlp documentation. Some YouTube formats may be unavailable without a supported JS runtime; TubeGrab passes yt-dlp's normal options and does not bypass access controls. |
| App does not appear in the GNOME grid | Run `./install.sh` again, check `~/.local/share/applications/tubegrab.desktop`, and make sure the desktop database refresh tools are available. Log out and back in if necessary. |
| Need diagnostics | Inspect `~/.local/state/tubegrab/tubegrab.log`. |

## Project layout

```
tubegrab.py              development launcher
tubegrab/
  __main__.py            CLI entry point and logging startup
  app.py                 Tkinter interface and queue rendering
  downloader.py          yt-dlp commands, metadata, progress, cancellation
  queue.py               sequential queue state machine
  config.py              XDG paths and atomic settings
  theme.py               light/dark palettes, font selection, ttk styles
  widgets.py             canvas-drawn rounded controls and layout helpers
  utils.py               URL, filename, format, and desktop helpers
  assets/                SVG icon, PNG sizes, and UI icons
desktop/tubegrab.desktop.in
packaging/
  tubegrab.spec          Fedora RPM spec
  build-rpm.sh           builds dist/tubegrab-<version>.rpm
install.sh
uninstall.sh
tests/
PROJECT_STATE.md
BUILD-NOTES.txt
LICENSE
```

## Known limitations

- Downloads are processed one at a time; there is no concurrent-download setting.
- Playlist URLs are intentionally limited to one item (the first video).
- Cookie import, browser authentication, DRM circumvention, and age/bot-check bypass are not
  supported.
- Dependency installation is not automatic; Fedora commands are documented and shown in the app.
- The interface uses Tkinter, so it follows the system's available Tk fonts and X11/Wayland window
  decorations rather than drawing its own custom title bar.
- Text antialiasing requires a Tk build with Xft. The installer prefers one; a Python whose Tk was
  built without Xft falls back to un-antialiased core fonts.
- Tk Canvas cannot render CSS-style shadows or backdrop blur; cards use antialiased corner tiles,
  hairline borders, and subtle flat depth instead.
