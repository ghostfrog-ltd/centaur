#!/bin/bash

set -euo pipefail

PROJECT_ROOT="/Volumes/Bob/www/ghostfrog-centaur"
PLIST_SOURCE="$PROJECT_ROOT/ops/com.ghostfrog.centaur.test-monitor.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_TARGET="$LAUNCH_AGENTS_DIR/com.ghostfrog.centaur.test-monitor.plist"
WRAPPER_DIR="$HOME/.centaur"
WRAPPER_TARGET="$WRAPPER_DIR/run_test_monitor.sh"
WRAPPER_LOG="$HOME/centaur_test_monitor_wrapper.log"
RUNTIME_DIR="$WRAPPER_DIR/runtime"

mkdir -p "$LAUNCH_AGENTS_DIR"
mkdir -p "$WRAPPER_DIR"
mkdir -p "$RUNTIME_DIR"

cat > "$WRAPPER_TARGET" <<'EOF'
#!/bin/bash
set -euo pipefail

LOGFILE="$HOME/centaur_test_monitor_wrapper.log"
PROJECT_ROOT="/Volumes/Bob/www/ghostfrog-centaur"
LOCK_DIR="/tmp/ghostfrog-centaur-test-monitor.lock"

PYTHON_CANDIDATES=(
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

TARGET=""
for candidate in "${PYTHON_CANDIDATES[@]}"; do
  if [ -x "$candidate" ]; then
    TARGET="$candidate"
    break
  fi
done

if [ -z "$TARGET" ]; then
  echo "[$(date)] ERROR: no python3 binary found, exiting 78" >> "$LOGFILE"
  exit 78
fi

if [ ! -d "$PROJECT_ROOT" ]; then
  echo "[$(date)] ERROR: project root $PROJECT_ROOT not available, exiting 78" >> "$LOGFILE"
  exit 78
fi

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "[$(date)] Skip: previous test monitor run is still active." >> "$LOGFILE"
  exit 0
fi

cleanup() {
  rmdir "$LOCK_DIR"
}

trap cleanup EXIT INT TERM

cd "$PROJECT_ROOT"
export PATH="/Library/Frameworks/Python.framework/Versions/Current/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1

echo "[$(date)] Test monitor start | python=$TARGET" >> "$LOGFILE"
set +e
"$TARGET" "$PROJECT_ROOT/scripts/run_test_monitor.py" >> "$LOGFILE" 2>&1
status=$?
set -e
echo "[$(date)] Test monitor end | status=$status" >> "$LOGFILE"
exit 0
EOF
chmod +x "$WRAPPER_TARGET"

cp "$PLIST_SOURCE" "$PLIST_TARGET"

launchctl bootout "gui/$(id -u)" "$PLIST_TARGET" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_TARGET"
launchctl enable "gui/$(id -u)/com.ghostfrog.centaur.test-monitor"
launchctl kickstart -k "gui/$(id -u)/com.ghostfrog.centaur.test-monitor"

echo "Installed launch agent: $PLIST_TARGET"
echo "Installed wrapper: $WRAPPER_TARGET"
echo "Wrapper log: $WRAPPER_LOG"
echo "Monitor log: $PROJECT_ROOT/logs/test_monitor.log"
echo "Monitor state: $PROJECT_ROOT/.runtime/test_monitor_state.json"
