#!/usr/bin/env bash
PLIST="$HOME/Library/LaunchAgents/com.github.xeneon-touch.plist"
LABEL="com.github.xeneon-touch"
UID_NUM="$(id -u)"

launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "xeneon-touch uninstalled (LaunchAgent removed)."
echo "Note: Input Monitoring / Accessibility grants for python remain in"
echo "System Settings; remove them there manually if you want a clean slate."
