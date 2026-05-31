#!/bin/bash

set -euo pipefail

PROJECT_ROOT="/Volumes/Bob/www/ghostfrog-centaur"
PLIST_SOURCE="$PROJECT_ROOT/ops/com.ghostfrog.centaur.dashboard-api.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_TARGET="$LAUNCH_AGENTS_DIR/com.ghostfrog.centaur.dashboard-api.plist"
WRAPPER_DIR="$HOME/.centaur"
WRAPPER_TARGET="$WRAPPER_DIR/run_dashboard_api.sh"
WRAPPER_LOG="$WRAPPER_DIR/runtime/dashboard_api.log"
OLD_PLIST_TARGET="$LAUNCH_AGENTS_DIR/com.ghostfrog.centaur.dashboard-snapshot.plist"

mkdir -p "$LAUNCH_AGENTS_DIR"
mkdir -p "$WRAPPER_DIR"
mkdir -p "$WRAPPER_DIR/runtime"

cat > "$WRAPPER_TARGET" <<'EOF'
#!/bin/bash
set -euo pipefail

PROJECT_ROOT="/Volumes/Bob/www/ghostfrog-centaur"
RUNTIME_DIR="$HOME/.centaur/runtime"
LOGFILE="$RUNTIME_DIR/dashboard_api.log"
HOST="0.0.0.0"
PORT="8788"

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

TARGET=""
for candidate in "${PYTHON_CANDIDATES[@]}"; do
  if [ -x "$candidate" ]; then
    TARGET="$candidate"
    break
  fi
done

if [ -z "$TARGET" ]; then
  echo "[$(date)] ERROR: no python3 binary found for dashboard API" >> "$LOGFILE"
  exit 78
fi

echo "[$(date)] Starting Centaur dashboard API on ${HOST}:${PORT}" >> "$LOGFILE"
exec "$TARGET" "$PROJECT_ROOT/main.py" --dashboard --host "$HOST" --port "$PORT" >> "$LOGFILE" 2>&1
EOF

chmod +x "$WRAPPER_TARGET"
cp "$PLIST_SOURCE" "$PLIST_TARGET"

launchctl bootout "gui/$(id -u)" "$OLD_PLIST_TARGET" >/dev/null 2>&1 || true
rm -f "$OLD_PLIST_TARGET"

launchctl bootout "gui/$(id -u)" "$PLIST_TARGET" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_TARGET"
launchctl enable "gui/$(id -u)/com.ghostfrog.centaur.dashboard-api"
launchctl kickstart -k "gui/$(id -u)/com.ghostfrog.centaur.dashboard-api"

echo "Installed dashboard API launch agent: $PLIST_TARGET"
echo "Installed wrapper: $WRAPPER_TARGET"
echo "Dashboard API log: $WRAPPER_LOG"
