#!/usr/bin/env bash
set -e

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="$INSTALL_DIR/launchd/com.github.xeneon-touch.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.github.xeneon-touch.plist"

echo "=== xeneon-touch installer ==="
echo ""

# Dependencies
echo "→ Checking dependencies…"
if ! command -v brew &>/dev/null; then
    echo "  ERROR: Homebrew not found. Install from https://brew.sh"
    exit 1
fi
brew list hidapi &>/dev/null || brew install hidapi
pip3 install hid pyobjc-framework-Quartz pyobjc-framework-ApplicationServices --break-system-packages -q

# Install launchd plist
echo "→ Installing launchd agent…"
sed "s|INSTALL_DIR|$INSTALL_DIR|g" "$PLIST_SRC" > "$PLIST_DEST"
launchctl load "$PLIST_DEST" 2>/dev/null || true
launchctl start com.github.xeneon-touch 2>/dev/null || true

echo ""
echo "✓ Installed. xeneon-touch will start on login."
echo ""
echo "IMPORTANT: Grant Accessibility permission when prompted, or go to:"
echo "  System Settings → Privacy & Security → Accessibility"
echo "  and enable your terminal / Python."
echo ""
echo "Logs: tail -f /tmp/xeneon-touch.log"
