#!/bin/sh
# TubeGrab per-user installer.  No sudo and no system-wide files.
set -eu

APP_NAME="TubeGrab"

if [ "$(id -u)" -eq 0 ]; then
    echo "Do not run this installer as root. TubeGrab installs for the current user." >&2
    exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SOURCE_DIR="$SCRIPT_DIR"

if [ ! -d "$SOURCE_DIR/tubegrab" ] || [ ! -f "$SOURCE_DIR/tubegrab/__main__.py" ]; then
    echo "The TubeGrab source package was not found next to install.sh." >&2
    exit 1
fi

# Pick a Python interpreter that can actually import Tkinter.  The launcher has
# to use an absolute interpreter path because GNOME's launch environment does
# not necessarily have a developer's pyenv/mise shims on PATH.
PYTHON="${TUBEGRAB_PYTHON:-}"
if [ -z "$PYTHON" ]; then
    for candidate in \
        "$(command -v python3 2>/dev/null || true)" \
        /usr/bin/python3 \
        /usr/local/bin/python3 \
        "$(command -v python3.14 2>/dev/null || true)" \
        "$(command -v python3.13 2>/dev/null || true)" \
        "$(command -v python3.12 2>/dev/null || true)"
    do
        [ -n "$candidate" ] || continue
        [ -x "$candidate" ] || continue
        if "$candidate" -c 'import tkinter' >/dev/null 2>&1; then
            PYTHON="$candidate"
            break
        fi
    done
fi

if [ -z "$PYTHON" ] || ! "$PYTHON" -c 'import tkinter' >/dev/null 2>&1; then
    echo "No Python installation with Tkinter was found." >&2
    echo "On Fedora, install the system toolkit, then run this installer again:" >&2
    echo "  sudo dnf install python3-tkinter" >&2
    echo "If you use pyenv/mise, set TUBEGRAB_PYTHON to a Python with Tkinter." >&2
    exit 1
fi
PYTHON=$(readlink -f "$PYTHON" 2>/dev/null || printf '%s' "$PYTHON")

PREFIX="${PREFIX:-$HOME/.local}"
BIN_DIR="$PREFIX/bin"
DATA_HOME="${XDG_DATA_HOME:-$PREFIX/share}"
APP_DIR="$DATA_HOME/tubegrab"
DESKTOP_DIR="$DATA_HOME/applications"
ICON_BASE="$DATA_HOME/icons/hicolor"
LAUNCHER="$BIN_DIR/tubegrab"
DESKTOP_FILE="$DESKTOP_DIR/tubegrab.desktop"

case "$APP_DIR" in
    */tubegrab) ;;
    *)
        echo "Refusing to use an unexpected install directory: $APP_DIR" >&2
        exit 1
        ;;
esac

echo "Installing $APP_NAME"
echo "  Python:  $PYTHON"
echo "  App:     $APP_DIR"
echo "  Command: $LAUNCHER"

mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR" \
    "$ICON_BASE/scalable/apps" \
    "$ICON_BASE/16x16/apps" "$ICON_BASE/24x24/apps" "$ICON_BASE/32x32/apps" \
    "$ICON_BASE/48x48/apps" "$ICON_BASE/64x64/apps" "$ICON_BASE/128x128/apps" \
    "$ICON_BASE/256x256/apps"

rm -rf "$APP_DIR/tubegrab"
cp -a "$SOURCE_DIR/tubegrab" "$APP_DIR/tubegrab"
find "$APP_DIR/tubegrab" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$APP_DIR/tubegrab" -type f -name '*.pyc' -delete
[ -f "$SOURCE_DIR/README.md" ] && cp "$SOURCE_DIR/README.md" "$APP_DIR/README.md"

# Generate a small POSIX launcher.  Paths are quoted by Python so spaces and
# apostrophes in HOME/XDG directories remain safe.
"$PYTHON" - "$PYTHON" "$APP_DIR" "$LAUNCHER" <<'PY'
import os
import shlex
import sys

python, app_dir, launcher = sys.argv[1:4]
content = f"""#!/bin/sh
# TubeGrab launcher (installed by install.sh). Remove with uninstall.sh.
PYTHON={shlex.quote(python)}
APP_DIR={shlex.quote(app_dir)}
if [ ! -x "$PYTHON" ] || ! "$PYTHON" -c 'import tkinter' >/dev/null 2>&1; then
    for candidate in python3 /usr/bin/python3 /usr/local/bin/python3 python3.14 python3.13 python3.12; do
        resolved=$(command -v "$candidate" 2>/dev/null || true)
        if [ -n "$resolved" ] && "$resolved" -c 'import tkinter' >/dev/null 2>&1; then
            PYTHON=$resolved
            break
        fi
    done
fi
if [ ! -x "$PYTHON" ] || ! "$PYTHON" -c 'import tkinter' >/dev/null 2>&1; then
    echo "TubeGrab: no Python with Tkinter was found. Install python3-tkinter or reinstall TubeGrab." >&2
    exit 1
fi
export PYTHONPATH="$APP_DIR${{PYTHONPATH:+:$PYTHONPATH}}"
exec "$PYTHON" -m tubegrab "$@"
"""
with open(launcher, "w", encoding="utf-8") as handle:
    handle.write(content)
os.chmod(launcher, 0o755)
PY

cp "$SOURCE_DIR/tubegrab/assets/tubegrab.svg" "$ICON_BASE/scalable/apps/tubegrab.svg"
for size in 16 24 32 48 64 128 256; do
    cp "$SOURCE_DIR/tubegrab/assets/icon-$size.png" "$ICON_BASE/${size}x${size}/apps/tubegrab.png"
done

# Desktop Exec paths need desktop-entry quoting, which is not shell quoting.
"$PYTHON" - "$SOURCE_DIR/desktop/tubegrab.desktop.in" "$DESKTOP_FILE" "$LAUNCHER" <<'PY'
import sys

template_path, output_path, launcher = sys.argv[1:4]
reserved = set(' \t\n"\'\\`$><~|&;$*?#()')
exec_path = launcher.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
if any(char in reserved for char in launcher) or "%" in launcher:
    exec_value = f'"{exec_path}"'
else:
    exec_value = exec_path
with open(template_path, encoding="utf-8") as handle:
    content = handle.read()
content = content.replace("@EXEC@", exec_value)
with open(output_path, "w", encoding="utf-8") as handle:
    handle.write(content)
PY

if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$DESKTOP_FILE" || {
        echo "The installed desktop file did not validate." >&2
        exit 1
    }
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$ICON_BASE" >/dev/null 2>&1 || true
fi

echo
echo "$APP_NAME installed successfully."
echo "Launch it from the GNOME application grid, or run: tubegrab"
echo "If 'tubegrab' is not on your PATH, use: $LAUNCHER"
