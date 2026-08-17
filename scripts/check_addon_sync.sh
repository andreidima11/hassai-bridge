#!/usr/bin/env bash
# Fail if hassai_bridge/app is stale vs the root app (add-on image would ship old UI).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Vendor into a temp dir using the same script, then diff against committed app/
ORIG_DEST="$ROOT/hassai_bridge/app"
export ROOT
# Reimplement copy into TMP to avoid deleting the real dest
mkdir -p "$TMP/app"
cp "$ROOT/main.py" "$ROOT/config.py" "$ROOT/database.py" "$ROOT/requirements.txt" "$ROOT/VERSION" "$TMP/app/"
copy_tree() {
  mkdir -p "$2"
  tar -C "$1" --exclude='__pycache__' --exclude='*.pyc' -cf - . | tar -C "$2" -xf -
}
copy_tree "$ROOT/core" "$TMP/app/core"
copy_tree "$ROOT/routers" "$TMP/app/routers"
copy_tree "$ROOT/services" "$TMP/app/services"
copy_tree "$ROOT/static" "$TMP/app/static"
mkdir -p "$TMP/app/data/skills/generated"
copy_tree "$ROOT/data/skills" "$TMP/app/data/skills"
find "$TMP/app/data/skills/generated" -type f ! -name '__init__.py' -delete 2>/dev/null || true
printf '%s\n' "vendored by scripts/sync_addon_app.sh — do not edit" > "$TMP/app/VENDORED.txt"

if ! diff -rq -x '__pycache__' -x '*.pyc' "$TMP/app" "$ORIG_DEST" >"$TMP/diff.txt"; then
  echo "hassai_bridge/app is out of sync with the root app. Run: bash scripts/sync_version.sh" >&2
  cat "$TMP/diff.txt" >&2
  exit 1
fi

ADDON_VER="$(sed -nE 's/^version: "(.*)"/\1/p' "$ROOT/hassai_bridge/config.yaml" | head -1)"
APP_VER="$(tr -d '[:space:]' < "$ROOT/VERSION")"
APP_VER="${APP_VER#v}"
if [[ "$ADDON_VER" != "$APP_VER" ]]; then
  echo "config.yaml version ($ADDON_VER) != VERSION ($APP_VER)" >&2
  exit 1
fi

echo "Add-on vendor matches root app ($APP_VER)"
