#!/usr/bin/env bash
PLIST="$HOME/Library/LaunchAgents/com.github.xeneon-touch.plist"
launchctl stop com.github.xeneon-touch 2>/dev/null || true
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "xeneon-touch uninstalled."
