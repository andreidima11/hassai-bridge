#!/usr/bin/env bash
# Sync hassai_bridge version fields from the root VERSION file
# and vendor app sources into the add-on build context.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAW="$(tr -d '[:space:]' < "$ROOT/VERSION")"
RAW="${RAW#v}"

if [[ ! "$RAW" =~ ^[0-9] ]]; then
  echo "Invalid VERSION: $RAW" >&2
  exit 1
fi

sed -i -E "s/^(version: ).*/\\1\"${RAW}\"/" "$ROOT/hassai_bridge/config.yaml"
bash "$ROOT/scripts/sync_addon_app.sh"

echo "Synced add-on to ${RAW} (app vendored into hassai_bridge/app)"
echo "App UI will show v${RAW} via core.config.VERSION"
