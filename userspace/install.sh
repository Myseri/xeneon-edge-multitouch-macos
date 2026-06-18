#!/usr/bin/env bash
set -e

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="$INSTALL_DIR/launchd/com.github.xeneon-touch.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.github.xeneon-touch.plist"
LABEL="com.github.xeneon-touch"
UID_NUM="$(id -u)"

echo "=== xeneon-touch installer ==="
echo ""

# ── Python (pinned to the real, fully-dereferenced binary) ───────────────────
# macOS TCC permissions (Input Monitoring / Accessibility) attach to the
# concrete on-disk binary, so pin the versioned executable (e.g.
# .../Versions/3.14/bin/python3.14), not a `python3` symlink that a version
# upgrade would repoint — that would silently void the grants and kill touch.
echo "→ Resolving Python…"
PYTHON_RAW="$(command -v python3)"
if [ -z "$PYTHON_RAW" ]; then
    echo "  ERROR: python3 not found on PATH."
    exit 1
fi
PYTHON_BIN="$("$PYTHON_RAW" -c 'import os, sys; print(os.path.realpath(sys.executable))')"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN="$PYTHON_RAW"
PY_ARCH="$("$PYTHON_BIN" -c 'import platform; print(platform.machine())')"
echo "  Using python (pinned): $PYTHON_BIN  [$PY_ARCH]"

# ── Homebrew (arch-matched to the interpreter) ───────────────────────────────
# libhidapi must be the SAME architecture as the python that dlopen()s it. On
# Apple Silicon an Intel/Rosetta brew at /usr/local builds an x86_64 dylib that
# an arm64 python cannot load (and vice-versa). Pick the brew matching PY_ARCH.
echo "→ Checking hidapi (arch-matched)…"
case "$PY_ARCH" in
    arm64)  BREW=/opt/homebrew/bin/brew ;;
    x86_64) BREW=/usr/local/bin/brew ;;
    *)      BREW="$(command -v brew)" ;;
esac
[ -x "$BREW" ] || BREW="$(command -v brew)"
if [ -z "$BREW" ] || [ ! -x "$BREW" ]; then
    echo "  ERROR: no Homebrew found for arch '$PY_ARCH'. Install from https://brew.sh"
    exit 1
fi
echo "  Using brew: $BREW"
"$BREW" list hidapi &>/dev/null || "$BREW" install hidapi
HIDAPI_LIB_DIR="$("$BREW" --prefix hidapi)/lib"
if [ ! -e "$HIDAPI_LIB_DIR/libhidapi.dylib" ]; then
    echo "  ERROR: libhidapi.dylib not found in $HIDAPI_LIB_DIR"
    exit 1
fi
echo "  hidapi lib: $HIDAPI_LIB_DIR"

# ── Python packages ──────────────────────────────────────────────────────────
# The code does `import hid` expecting the CYTHON 'hidapi' package
# (hid.device(), dev.open()). The identically-imported 'hid' (pyhidapi) package
# exposes a different API (hid.Device) and breaks it — remove it if present.
echo "→ Installing Python packages…"
"$PYTHON_BIN" -m pip uninstall -y hid >/dev/null 2>&1 || true
"$PYTHON_BIN" -m pip install hidapi pyobjc-framework-Quartz pyobjc-framework-ApplicationServices \
    --break-system-packages -q

# ── Install / reload the LaunchAgent ─────────────────────────────────────────
echo "→ Installing LaunchAgent…"
mkdir -p "$HOME/Library/LaunchAgents"

# Render the template (substitute all placeholders).
sed -e "s|INSTALL_DIR|$INSTALL_DIR|g" \
    -e "s|PYTHON_BIN|$PYTHON_BIN|g" \
    -e "s|HIDAPI_LIB_DIR|$HIDAPI_LIB_DIR|g" \
    "$PLIST_SRC" > "$PLIST_DEST"

# Tear down any previous instance, then load fresh. Prefer modern bootstrap,
# fall back to legacy load on older macOS.
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
launchctl unload "$PLIST_DEST" 2>/dev/null || true
if ! launchctl bootstrap "gui/$UID_NUM" "$PLIST_DEST" 2>/dev/null; then
    launchctl load "$PLIST_DEST"
fi
launchctl kickstart -k "gui/$UID_NUM/$LABEL" 2>/dev/null || true

echo ""
echo "✓ Installed. xeneon-touch now starts at login and restarts itself"
echo "  automatically (including when you re-plug the monitor)."
echo ""
echo "── ONE-TIME PERMISSIONS (required) ──────────────────────────────────────"
echo "macOS will block touch injection until you grant two permissions to:"
echo "  $PYTHON_BIN"
echo ""
echo "  System Settings → Privacy & Security →"
echo "     • Input Monitoring   → add/enable the python above"
echo "     • Accessibility      → add/enable the python above"
echo ""
echo "  After granting, restart the agent:"
echo "     launchctl kickstart -k gui/$UID_NUM/$LABEL"
echo ""
echo "Logs:  tail -f /tmp/xeneon-touch.log"
echo "Stop:  ./uninstall.sh"
echo ""
echo "Note: the agent is pinned to the exact Python binary above. After a"
echo "deliberate Python version upgrade (e.g. brew upgrade python@3.x), rerun"
echo "./install.sh and re-grant the two permissions to the new binary."
