#!/usr/bin/env bash
set -e

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="$INSTALL_DIR/launchd/com.github.xeneon-touch.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.github.xeneon-touch.plist"
LABEL="com.github.xeneon-touch"
UID_NUM="$(id -u)"

echo "=== xeneon-touch installer ==="
echo ""

# ── Dependencies ─────────────────────────────────────────────────────────────
echo "→ Checking dependencies…"
if ! command -v brew &>/dev/null; then
    echo "  ERROR: Homebrew not found. Install from https://brew.sh"
    exit 1
fi
brew list hidapi &>/dev/null || brew install hidapi

# Resolve the python3 that has the deps to its REAL, fully-dereferenced binary
# (e.g. /opt/homebrew/Cellar/python@3.12/.../bin/python3.12), not the
# /opt/homebrew/bin/python3 symlink. macOS TCC permissions (Input Monitoring /
# Accessibility) attach to the concrete binary; pinning the symlink means a
# `brew upgrade python` that repoints it silently voids the grants and touch
# dies with no error. Pinning the versioned binary survives that — at the cost
# of needing a re-run of this installer + re-grant after a deliberate Python
# version bump (3.12 -> 3.13).
PYTHON_RAW="$(command -v python3)"
if [ -z "$PYTHON_RAW" ]; then
    echo "  ERROR: python3 not found on PATH."
    exit 1
fi
PYTHON_BIN="$("$PYTHON_RAW" -c 'import os, sys; print(os.path.realpath(sys.executable))')"
if [ ! -x "$PYTHON_BIN" ]; then
    echo "  WARN: could not resolve real python path; falling back to $PYTHON_RAW"
    PYTHON_BIN="$PYTHON_RAW"
fi
echo "  Using python (pinned): $PYTHON_BIN"
"$PYTHON_BIN" -m pip install hid pyobjc-framework-Quartz pyobjc-framework-ApplicationServices \
    --break-system-packages -q

# ── Install / reload the LaunchAgent ─────────────────────────────────────────
echo "→ Installing LaunchAgent…"
mkdir -p "$HOME/Library/LaunchAgents"

# Render the template (substitute both placeholders).
sed -e "s|INSTALL_DIR|$INSTALL_DIR|g" \
    -e "s|PYTHON_BIN|$PYTHON_BIN|g" \
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
