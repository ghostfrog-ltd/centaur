#!/bin/bash

set -euo pipefail

PROJECT_ROOT="/Volumes/Bob/www/ghostfrog-centaur"
PLIST_SOURCE="$PROJECT_ROOT/ops/com.ghostfrog.centaur.dashboard-snapshot.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_TARGET="$LAUNCH_AGENTS_DIR/com.ghostfrog.centaur.dashboard-snapshot.plist"
WRAPPER_DIR="$HOME/.centaur"
WRAPPER_TARGET="$WRAPPER_DIR/write_dashboard_snapshot.sh"
WRAPPER_LOG="$WRAPPER_DIR/runtime/dashboard_snapshot.log"
LOCK_DIR="/tmp/ghostfrog-centaur-dashboard-snapshot.lock"

mkdir -p "$LAUNCH_AGENTS_DIR"
mkdir -p "$WRAPPER_DIR"
mkdir -p "$WRAPPER_DIR/runtime"

cat > "$WRAPPER_TARGET" <<'EOF'
#!/bin/bash
set -euo pipefail

PROJECT_ROOT="/Volumes/Bob/www/ghostfrog-centaur"
RUNTIME_DIR="$HOME/.centaur/runtime"
LOGFILE="$RUNTIME_DIR/dashboard_snapshot.log"
LOCK_DIR="/tmp/ghostfrog-centaur-dashboard-snapshot.lock"
OUTPUT_DIR="$PROJECT_ROOT/var"
OUTPUT_FILE="$OUTPUT_DIR/dashboard_snapshot.json"

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

mkdir -p "$RUNTIME_DIR"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "[$(date)] Skip: previous dashboard snapshot refresh is still running." >> "$LOGFILE"
  exit 0
fi

cleanup() {
  rmdir "$LOCK_DIR"
}

trap cleanup EXIT INT TERM

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

echo "[$(date)] Refreshing Centaur dashboard snapshot..." >> "$LOGFILE"
mkdir -p "$OUTPUT_DIR"
set +e
"$TARGET" "$PROJECT_ROOT/scripts/dashboard_snapshot.py" --output "$OUTPUT_FILE" >> "$LOGFILE" 2>&1
status=$?
set -e
echo "[$(date)] Dashboard snapshot refresh exited with status $status" >> "$LOGFILE"
exit "$status"
EOF

chmod +x "$WRAPPER_TARGET"
cp "$PLIST_SOURCE" "$PLIST_TARGET"

launchctl bootout "gui/$(id -u)" "$PLIST_TARGET" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_TARGET"
launchctl enable "gui/$(id -u)/com.ghostfrog.centaur.dashboard-snapshot"
launchctl kickstart -k "gui/$(id -u)/com.ghostfrog.centaur.dashboard-snapshot"

echo "Installed launch agent: $PLIST_TARGET"
echo "Installed wrapper: $WRAPPER_TARGET"
echo "Snapshot log: $WRAPPER_LOG"
