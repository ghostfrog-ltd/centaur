#!/bin/bash

set -euo pipefail

PLIST_TARGET="$HOME/Library/LaunchAgents/com.ghostfrog.centaur.test-monitor.plist"
WRAPPER_TARGET="$HOME/.centaur/run_test_monitor.sh"
WRAPPER_LOG="$HOME/centaur_test_monitor_wrapper.log"

if [[ -f "$PLIST_TARGET" ]]; then
  launchctl bootout "gui/$(id -u)" "$PLIST_TARGET" >/dev/null 2>&1 || true
  rm -f "$PLIST_TARGET"
  echo "Removed launch agent: $PLIST_TARGET"
else
  echo "Launch agent not installed: $PLIST_TARGET"
fi

if [[ -f "$WRAPPER_TARGET" ]]; then
  rm -f "$WRAPPER_TARGET"
  echo "Removed wrapper: $WRAPPER_TARGET"
fi

if [[ -f "$WRAPPER_LOG" ]]; then
  echo "Wrapper log retained at: $WRAPPER_LOG"
fi
