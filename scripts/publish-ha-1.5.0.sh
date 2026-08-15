#!/usr/bin/env bash
# Publish hassai-bridge-ha v1.5.1 from your Mac (Cursor bot has no write access to that repo).
set -euo pipefail

REPO_DIR="${1:-$HOME/hassai-bridge-ha}"
ZIP_URL="https://github.com/andreidima11/hassai-bridge/releases/download/v0.1.9.5-beta/hassai-bridge-ha-1.5.1.zip"
WORKDIR=$(mktemp -d)

cleanup() { rm -rf "$WORKDIR"; }
trap cleanup EXIT

echo "Downloading integration pack..."
curl -fsSL "$ZIP_URL" -o "$WORKDIR/ha.zip"
unzip -q "$WORKDIR/ha.zip" -d "$WORKDIR/pack"

if [[ ! -d "$REPO_DIR/.git" ]]; then
  echo "Cloning hassai-bridge-ha..."
  git clone https://github.com/andreidima11/hassai-bridge-ha.git "$REPO_DIR"
fi

cd "$REPO_DIR"
git checkout main
git pull --ff-only origin main || true

# Replace custom component
rm -rf custom_components/hassai_bridge
mkdir -p custom_components
cp -a "$WORKDIR/pack/custom_components/hassai_bridge" custom_components/
cp "$WORKDIR/pack/README.md" README.md

git add -A
git commit -m "Release v1.5.1: automation tools + sensor coordinator fix" || echo "Nothing to commit"
git push origin main

git tag -a v1.5.1 -m "v1.5.1" || true
git push origin v1.5.1

gh release create v1.5.1 \
  --title "v1.5.1 — Automations + sensor fix" \
  --notes "$(cat <<'EOF'
## HASSAI Bridge HA Integration v1.5.1

### Fixes
- Sensors no longer stuck on Unknown/unavailable (DataUpdateCoordinator + better fallbacks)

### Features
- Automation tools for Assist:
  - `list_automations`
  - `get_automation`
  - `create_automation` (requires confirm=true)
  - `update_automation` (requires confirm=true)
  - `delete_automation` (requires confirm=true)
  - `toggle_automation`

Requires HASSAI Bridge **v0.1.9.5-beta+**.
EOF
)" \
  --latest

echo "Done: https://github.com/andreidima11/hassai-bridge-ha/releases/tag/v1.5.1"
