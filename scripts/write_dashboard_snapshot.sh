#!/bin/bash
set -euo pipefail

PROJECT_ROOT="/Volumes/Bob/www/ghostfrog-centaur"
OUTPUT_DIR="$PROJECT_ROOT/var"
OUTPUT_FILE="$OUTPUT_DIR/dashboard_snapshot.json"
TEMP_FILE="$OUTPUT_DIR/dashboard_snapshot.tmp.json"

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

mkdir -p "$OUTPUT_DIR"
PYTHON_BIN="$(resolve_python_bin)"
cd "$PROJECT_ROOT"
"$PYTHON_BIN" "$PROJECT_ROOT/scripts/dashboard_snapshot.py" --output "$TEMP_FILE"
mv "$TEMP_FILE" "$OUTPUT_FILE"
