#!/usr/bin/env bash
# Sync hassai_bridge version fields from the root VERSION file.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAW="$(tr -d '[:space:]' < "$ROOT/VERSION")"
RAW="${RAW#v}"
TAG="v${RAW}"

if [[ ! "$RAW" =~ ^[0-9] ]]; then
  echo "Invalid VERSION: $RAW" >&2
  exit 1
fi

# config.yaml version field
sed -i -E "s/^(version: ).*/\\1\"${RAW}\"/" "$ROOT/hassai_bridge/config.yaml"

# Dockerfile default ref
sed -i -E "s|^(ARG HASSAI_REF=).*|\\1${TAG}|" "$ROOT/hassai_bridge/Dockerfile"

# build.yaml args
if grep -q 'HASSAI_REF:' "$ROOT/hassai_bridge/build.yaml"; then
  sed -i -E "s|^(  HASSAI_REF: ).*|\\1${TAG}|" "$ROOT/hassai_bridge/build.yaml"
else
  # replace empty args: {}
  sed -i "s|^args: {}|args:\n  HASSAI_REF: ${TAG}|" "$ROOT/hassai_bridge/build.yaml"
fi

echo "Synced add-on + Docker to ${RAW} (git ref ${TAG})"
echo "App UI will show v${RAW} via core.config.VERSION"
