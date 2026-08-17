#!/usr/bin/with-contenv bashio
# ==============================================================================
# HASSAI Bridge add-on entrypoint
# ==============================================================================
set -euo pipefail

LOG_LEVEL=$(bashio::config 'log_level' 'info')
bashio::log.level "${LOG_LEVEL}"
bashio::log.info "Starting HASSAI Bridge..."

mkdir -p /data/hassai

# Point app data dir at persistent add-on storage
if [[ -L /opt/hassai-bridge/data ]]; then
  :
elif [[ -d /opt/hassai-bridge/data ]]; then
  cp -a /opt/hassai-bridge/data/. /data/hassai/ 2>/dev/null || true
  rm -rf /opt/hassai-bridge/data
  ln -sfn /data/hassai /opt/hassai-bridge/data
else
  ln -sfn /data/hassai /opt/hassai-bridge/data
fi

export HASSAI_DATA_DIR="/data/hassai"
export SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"

cd /opt/hassai-bridge
exec python3 -m uvicorn main:app --host 0.0.0.0 --port 8899 --proxy-headers --forwarded-allow-ips='*'
