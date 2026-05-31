#!/bin/bash

set -euo pipefail

PLIST_TARGET="$HOME/Library/LaunchAgents/com.ghostfrog.centaur.dashboard-snapshot.plist"

launchctl bootout "gui/$(id -u)" "$PLIST_TARGET" >/dev/null 2>&1 || true
rm -f "$PLIST_TARGET"

echo "Uninstalled dashboard snapshot launch agent: $PLIST_TARGET"
