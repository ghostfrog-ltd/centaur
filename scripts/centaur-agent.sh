#!/bin/bash
set -euo pipefail

PLIST="$HOME/Library/LaunchAgents/com.ghostfrog.centaur.control.plist"
LABEL="$(/usr/bin/defaults read "$PLIST" Label 2>/dev/null || echo 'com.ghostfrog.centaur.control')"
DOMAIN="gui/$(id -u)"
WRAPPER_LOG="$HOME/centaur_control_wrapper.log"
RUNTIME_LOG="$HOME/.centaur/runtime/control_tick.log"
PROJECT_ROOT="/Volumes/Bob/www/ghostfrog-centaur"

resolve_python_bin() {
  local candidates=(
    "$PROJECT_ROOT/.venv-mac/bin/python"
    "$PROJECT_ROOT/.venv/bin/python"
    "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
    "/opt/homebrew/opt/python@3.13/bin/python3.13"
    "/opt/homebrew/opt/python@3.12/bin/python3.12"
    "/opt/homebrew/bin/python3"
    "/usr/local/bin/python3"
    "/usr/bin/python3"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -x "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done

  command -v python3
}

case "${1:-}" in
  start)
    echo "Starting Centaur..."
    launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null || true
    launchctl enable "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl kickstart -k "$DOMAIN/$LABEL"
    ;;

  stop)
    echo "Stopping Centaur..."
    launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
    ;;

  restart)
    echo "Restarting Centaur..."
    launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    launchctl enable "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl kickstart -k "$DOMAIN/$LABEL"
    ;;

  dashboard)
    echo "Starting DDEV-routed Centaur dashboard..."
    ddev start
    echo "Dashboard URL: https://ghostfrog-centaur.ddev.site"
    echo "Live API source: http://host.docker.internal:8788/api/snapshot"
    ;;

  status)
    echo "Status for $LABEL in $DOMAIN"
    echo "Note: timer-based agents often show 'state = not running' between scheduled launches."
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      launchctl print "$DOMAIN/$LABEL" | head -n 20
    else
      echo "Not loaded in $DOMAIN"
    fi

    if [ -f "$WRAPPER_LOG" ]; then
      echo
      echo "Last wrapper log lines:"
      tail -n 20 "$WRAPPER_LOG"
    fi

    if [ -f "$RUNTIME_LOG" ]; then
      echo
      echo "Last runtime log lines:"
      tail -n 20 "$RUNTIME_LOG"
    fi

    echo
    echo "Centaur summary:"
    "$(resolve_python_bin)" "$PROJECT_ROOT/main.py" --status || true
    ;;

  *)
    echo "Usage: centaur-agent {start|stop|restart|status|dashboard}"
    exit 1
    ;;
esac
