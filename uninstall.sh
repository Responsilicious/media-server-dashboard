#!/bin/sh
# Stops the dashboard and removes it from login items. Your files in this folder are left alone.
LABEL="local.media-server-dashboard"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Stopped and removed from startup."
