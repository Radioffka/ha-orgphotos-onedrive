#!/usr/bin/with-contenv bash
# ---------------------------------------------
#  OrgPhotos-OneDrive  – startovací skript
# ---------------------------------------------
set -euo pipefail
source /usr/lib/bashio/bashio.sh

# ---------- načtení voleb z /data/options.json ----------
# Najeďme proměnné a exportujme je, aby je Python viděl
export SOURCE_DIR="$(bashio::config 'source_dir')"
export TARGET_DIR="$(bashio::config 'target_dir')"
export ONEDRIVE_CLIENT_ID="$(bashio::config 'onedrive_client_id')"
export ONEDRIVE_TENANT_ID="$(bashio::config 'onedrive_tenant_id')"
export DEBOUNCE_SECS="$(bashio::config 'debounce_secs')"
export LOG_LEVEL="$(bashio::config 'log_level')"

# ---------- fallbacky, pokud uživatel nic nenastavil ----------
# (pokud chcete, můžete sem přidat fallbacky; v původním run.sh byly prázdné)

# ---------- refresh-token ----------
REF_FILE="/data/refresh_token"
if [[ ! -f "$REF_FILE" ]]; then
    [[ -f /share/onedrive_refresh_token ]] && cp /share/onedrive_refresh_token "$REF_FILE"
fi

if [[ ! -f "$REF_FILE" ]]; then
    bashio::exit.nok "Refresh token not found in /data/refresh_token"
fi
export ONEDRIVE_REFRESH_FILE="$REF_FILE"

# ---------- spuštění Pythonu ----------
exec python3 -u /addon/OrgPhotos.py

