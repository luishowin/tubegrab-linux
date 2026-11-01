#!/bin/sh
# Remove only the files installed by TubeGrab's install.sh.
set -eu

PURGE=0
for arg in "$@"; do
    case "$arg" in
        --purge) PURGE=1 ;;
        -h|--help)
            echo "Usage: ./uninstall.sh [--purge]"
            echo "  --purge  also remove TubeGrab configuration, state, and thumbnail cache"
            exit 0
            ;;
        *)
            echo "Unknown option: $arg" >&2
            exit 2
            ;;
    esac
done

if [ "$(id -u)" -eq 0 ]; then
    echo "Do not run this uninstaller as root." >&2
    exit 1
fi

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
        echo "Refusing to use an unexpected application directory: $APP_DIR" >&2
        exit 1
        ;;
esac

removed=0

if [ -d "$APP_DIR/tubegrab" ] && grep -q 'APP_NAME = "TubeGrab"' "$APP_DIR/tubegrab/__init__.py" 2>/dev/null; then
    rm -rf "$APP_DIR/tubegrab"
    rm -f "$APP_DIR/README.md"
    rmdir "$APP_DIR" 2>/dev/null || true
    removed=1
elif [ -e "$APP_DIR" ]; then
    echo "Skipping $APP_DIR: it does not look like a TubeGrab installation." >&2
fi

if [ -f "$LAUNCHER" ] && grep -q 'TubeGrab launcher' "$LAUNCHER" 2>/dev/null; then
    rm -f "$LAUNCHER"
    removed=1
fi

if [ -f "$DESKTOP_FILE" ] && grep -q '^X-TubeGrab-Managed=true$' "$DESKTOP_FILE" 2>/dev/null; then
    rm -f "$DESKTOP_FILE"
    removed=1
fi

for icon in \
    "$ICON_BASE/scalable/apps/tubegrab.svg" \
    "$ICON_BASE/16x16/apps/tubegrab.png" \
    "$ICON_BASE/24x24/apps/tubegrab.png" \
    "$ICON_BASE/32x32/apps/tubegrab.png" \
    "$ICON_BASE/48x48/apps/tubegrab.png" \
    "$ICON_BASE/64x64/apps/tubegrab.png" \
    "$ICON_BASE/128x128/apps/tubegrab.png" \
    "$ICON_BASE/256x256/apps/tubegrab.png"
do
    if [ -f "$icon" ]; then
        rm -f "$icon"
        removed=1
    fi
done

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$ICON_BASE" >/dev/null 2>&1 || true
fi

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/tubegrab"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/tubegrab"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/tubegrab"

if [ "$PURGE" -eq 1 ]; then
    rm -rf "$CONFIG_DIR" "$STATE_DIR" "$CACHE_DIR"
    echo "Removed TubeGrab configuration, logs, and thumbnail cache."
else
    echo "Kept your settings, logs, and downloaded media."
    echo "  Settings: $CONFIG_DIR"
    echo "  Logs:     $STATE_DIR"
    echo "  Cache:    $CACHE_DIR"
    echo "Use ./uninstall.sh --purge to remove those directories too."
fi

if [ "$removed" -eq 1 ]; then
    echo "TubeGrab was uninstalled."
else
    echo "No TubeGrab installation files were found in the standard per-user locations."
fi
