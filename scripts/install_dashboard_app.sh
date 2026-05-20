#!/bin/bash
set -euo pipefail

SOURCE_APP="${1:-/Volumes/Bob/www/ghostfrog-centaur/apps/Centaur Dashboard.app}"
TARGET_DIR="${2:-$HOME/Applications}"
APP_NAME="$(basename "$SOURCE_APP")"
TARGET_APP="$TARGET_DIR/$APP_NAME"

mkdir -p "$TARGET_DIR"
rm -rf "$TARGET_APP"
cp -R "$SOURCE_APP" "$TARGET_APP"
find "$TARGET_APP/Contents/MacOS" -type f -exec chmod +x {} \;

echo "Installed app to:"
echo "  $TARGET_APP"
