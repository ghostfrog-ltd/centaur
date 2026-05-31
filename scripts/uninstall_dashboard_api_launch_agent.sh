#!/bin/bash

set -euo pipefail

PLIST_TARGET="$HOME/Library/LaunchAgents/com.ghostfrog.centaur.dashboard-api.plist"

launchctl bootout "gui/$(id -u)" "$PLIST_TARGET" >/dev/null 2>&1 || true
rm -f "$PLIST_TARGET"

echo "Uninstalled dashboard API launch agent: $PLIST_TARGET"
