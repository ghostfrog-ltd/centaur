#!/bin/zsh

set -eu

PROJECT_ROOT="/Volumes/Bob/www/ghostfrog-centaur"
LOCK_DIR="/tmp/ghostfrog-centaur-control.lock"
LOG_FILE="$PROJECT_ROOT/logs/control_tick.log"
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

mkdir -p "$PROJECT_ROOT/logs"
export PATH="/Library/Frameworks/Python.framework/Versions/Current/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

timestamp() {
  date '+%Y-%m-%d %H:%M:%S %Z'
}

resolve_python_bin() {
  local candidate
  for candidate in "${PYTHON_CANDIDATES[@]}"; do
    if [[ -x "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done

  command -v python3
}

if [[ ! -t 1 ]]; then
  exec >>"$LOG_FILE" 2>&1
fi

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "[$(timestamp)] Skip: previous control tick is still running."
  exit 0
fi

cleanup() {
  rmdir "$LOCK_DIR"
}

trap cleanup EXIT INT TERM

cd "$PROJECT_ROOT"
PYTHON_BIN="$(resolve_python_bin)"
echo "[$(timestamp)] Control tick start | python=$PYTHON_BIN"
set +e
"$PYTHON_BIN" "$PROJECT_ROOT/main.py"
status=$?
set -e
echo "[$(timestamp)] Control tick end"
exit "$status"
