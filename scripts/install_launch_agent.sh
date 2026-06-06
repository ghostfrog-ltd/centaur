#!/bin/bash

set -euo pipefail

PROJECT_ROOT="/Volumes/Bob/www/ghostfrog-centaur"
PLIST_SOURCE="$PROJECT_ROOT/ops/com.ghostfrog.centaur.control.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_TARGET="$LAUNCH_AGENTS_DIR/com.ghostfrog.centaur.control.plist"
WRAPPER_DIR="$HOME/.centaur"
WRAPPER_TARGET="$WRAPPER_DIR/run_control_tick.sh"
WRAPPER_LOG="$HOME/centaur_control_wrapper.log"
RUNTIME_DIR="$WRAPPER_DIR/runtime"
HEARTBEAT_INTERVAL_SECONDS="${CENTAUR_HEARTBEAT_INTERVAL_SECONDS:-10}"

mkdir -p "$LAUNCH_AGENTS_DIR"
mkdir -p "$WRAPPER_DIR"
mkdir -p "$RUNTIME_DIR"

cat > "$WRAPPER_TARGET" <<'EOF'
#!/bin/bash
set -euo pipefail

LOGFILE="$HOME/centaur_control_wrapper.log"
echo "[$(date)] Wrapper starting..." >> "$LOGFILE"

PROJECT_ROOT="/Volumes/Bob/www/ghostfrog-centaur"
RUNTIME_DIR="$HOME/.centaur/runtime"
HEARTBEAT_INTERVAL_SECONDS="${CENTAUR_HEARTBEAT_INTERVAL_SECONDS:-10}"
PROJECT_LOG="$RUNTIME_DIR/control_tick.log"
PROJECT_ENV_FILE="$PROJECT_ROOT/.env"
LOCK_DIR="/tmp/ghostfrog-centaur-control.lock"
LOCK_PID_FILE="$LOCK_DIR/pid"
WAIT_RETRIES=30
WAIT_SECONDS=2

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

mkdir -p "$RUNTIME_DIR" || {
  echo "[$(date)] ERROR: failed to create runtime dir at $RUNTIME_DIR" >> "$LOGFILE"
  exit 1
}

for ((i=1; i<=WAIT_RETRIES; i++)); do
  if [ -d "$PROJECT_ROOT" ]; then
    echo "[$(date)] Project root available at $PROJECT_ROOT" >> "$LOGFILE"
    break
  fi
  echo "[$(date)] Waiting for project root $PROJECT_ROOT, retry $i..." >> "$LOGFILE"
  sleep "$WAIT_SECONDS"
done

if [ ! -d "$PROJECT_ROOT" ]; then
  echo "[$(date)] ERROR: project root $PROJECT_ROOT not available after retries, exiting 78" >> "$LOGFILE"
  exit 78
fi

if [ ! -r "$PROJECT_ROOT/main.py" ]; then
  echo "[$(date)] ERROR: cannot read $PROJECT_ROOT/main.py" >> "$LOGFILE"
  exit 1
fi

touch "$PROJECT_LOG" || {
  echo "[$(date)] ERROR: failed to open runtime log at $PROJECT_LOG" >> "$LOGFILE"
  exit 1
}

cd "$PROJECT_ROOT" || {
  echo "[$(date)] ERROR: failed to cd to $PROJECT_ROOT" >> "$LOGFILE"
  exit 1
}

export PATH="/Library/Frameworks/Python.framework/Versions/Current/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  if [ -r "$LOCK_PID_FILE" ]; then
    existing_pid="$(cat "$LOCK_PID_FILE" 2>/dev/null || true)"
    if [ -n "$existing_pid" ] && kill -0 "$existing_pid" 2>/dev/null; then
      echo "[$(date)] Existing Centaur heartbeat service is still running with pid $existing_pid." >> "$LOGFILE"
      exit 0
    fi
  fi
  echo "[$(date)] Removing stale Centaur heartbeat lock at $LOCK_DIR." >> "$LOGFILE"
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR"
fi
echo "$$" > "$LOCK_PID_FILE"

cleanup() {
  rm -f "$LOCK_PID_FILE"
  rmdir "$LOCK_DIR" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

echo "[$(date)] Found $TARGET, starting Centaur heartbeat service interval=${HEARTBEAT_INTERVAL_SECONDS}s with runtime log $PROJECT_LOG..." >> "$LOGFILE"
echo "[$(date)] Working directory=$PROJECT_ROOT | dotenv_path=$PROJECT_ENV_FILE | dotenv_loaded_by=python_startup" >> "$LOGFILE"
set +e
"$TARGET" "$PROJECT_ROOT/main.py" --heartbeat-service --interval-seconds "$HEARTBEAT_INTERVAL_SECONDS" >> "$PROJECT_LOG" 2>> "$LOGFILE"
status=$?
set -e
echo "[$(date)] Centaur heartbeat service exited with status $status" >> "$LOGFILE"
exit "$status"
EOF
chmod +x "$WRAPPER_TARGET"

cp "$PLIST_SOURCE" "$PLIST_TARGET"

launchctl bootout "gui/$(id -u)" "$PLIST_TARGET" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_TARGET"
launchctl enable "gui/$(id -u)/com.ghostfrog.centaur.control"
launchctl kickstart -k "gui/$(id -u)/com.ghostfrog.centaur.control"

echo "Installed launch agent: $PLIST_TARGET"
echo "Installed wrapper: $WRAPPER_TARGET"
echo "Heartbeat interval: ${HEARTBEAT_INTERVAL_SECONDS}s"
echo "Wrapper log: $WRAPPER_LOG"
echo "Runtime log: $RUNTIME_DIR/control_tick.log"
