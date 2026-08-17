#!/usr/bin/env bash
# Copy app sources into hassai_bridge/app/ so the HA add-on image
# builds from this folder (Supervisor build context is the add-on dir only).
# Git-cloning main at image-build time was cached and shipped stale v0.2.0-beta.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/hassai_bridge/app"

rm -rf "$DEST"
mkdir -p "$DEST"

copy_tree() {
  local src="$1" dest="$2"
  mkdir -p "$dest"
  tar -C "$src" --exclude='__pycache__' --exclude='*.pyc' -cf - . | tar -C "$dest" -xf -
}

cp "$ROOT/main.py" "$ROOT/config.py" "$ROOT/database.py" "$ROOT/requirements.txt" "$ROOT/VERSION" "$DEST/"
copy_tree "$ROOT/core" "$DEST/core"
copy_tree "$ROOT/routers" "$DEST/routers"
copy_tree "$ROOT/services" "$DEST/services"
copy_tree "$ROOT/static" "$DEST/static"
mkdir -p "$DEST/data/skills/generated"
copy_tree "$ROOT/data/skills" "$DEST/data/skills"
# Keep generated as a package, drop any accidental user files
find "$DEST/data/skills/generated" -type f ! -name '__init__.py' -delete 2>/dev/null || true

# Marker so we never confuse this tree with a live data dir
printf '%s\n' "vendored by scripts/sync_addon_app.sh — do not edit" > "$DEST/VENDORED.txt"

echo "Vendored app into hassai_bridge/app ($(cat "$ROOT/VERSION"))"
