#!/usr/bin/env bash
# Keep add-on config / Docker ARG in sync with hassai_bridge/app/VERSION.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VER_FILE="$ROOT/hassai_bridge/app/VERSION"
RAW="$(tr -d '[:space:]' < "$VER_FILE")"
RAW="${RAW#v}"

if [[ ! "$RAW" =~ ^[0-9] ]]; then
  echo "Invalid VERSION: $RAW" >&2
  exit 1
fi

sed -i -E "s/^(version: ).*/\\1\"${RAW}\"/" "$ROOT/hassai_bridge/config.yaml"
sed -i -E "s/^(ARG HASSAI_VERSION=).*/\\1${RAW}/" "$ROOT/hassai_bridge/Dockerfile"
if grep -q 'HASSAI_VERSION:' "$ROOT/hassai_bridge/build.yaml"; then
  sed -i -E "s/^(  HASSAI_VERSION: ).*/\\1${RAW}/" "$ROOT/hassai_bridge/build.yaml"
fi

echo "Add-on version synced to ${RAW}"
