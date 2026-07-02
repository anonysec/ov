#!/usr/bin/env bash
# ov-panel multi-login enforcement for OpenVPN client-connect.
#
# Enforces /etc/openvpn/limits/<common_name> immediately, even when multiple
# devices connect before OpenVPN's status log refreshes. Uses a small active
# session registry protected by flock; client-disconnect removes the session.

set -euo pipefail

LIMITS_DIR="/etc/openvpn/limits"
ACTIVE_DIR="/etc/openvpn/ovpanel-active"
LOCK_FILE="${ACTIVE_DIR}/.lock"
STATUS_FILE="${OVPANEL_STATUS_FILE:-/var/log/openvpn-status.log}"
DEFAULT_LIMIT=1
LOG_TAG="ovpanel-mlogin"

cn="${common_name:-${1:-}}"

log() { logger -t "$LOG_TAG" "$*" 2>/dev/null || echo "$LOG_TAG: $*" >&2; }

sanitize() {
    printf '%s' "$1" | sed 's/[^A-Za-z0-9_.-]/_/g'
}

if [[ -z "$cn" ]]; then
    log "no common_name provided; allowing"
    exit 0
fi

safe_cn="$(sanitize "$cn")"
mkdir -p "$LIMITS_DIR" "$ACTIVE_DIR"
chmod 755 "$ACTIVE_DIR" 2>/dev/null || true

limit="$DEFAULT_LIMIT"
limit_file="${LIMITS_DIR}/${cn}"
if [[ -f "$limit_file" ]]; then
    raw="$(tr -dc '0-9' < "$limit_file" || true)"
    [[ -n "$raw" ]] && limit="$raw"
fi

if [[ "$limit" -eq 0 ]]; then
    log "CN=$cn limit=unlimited; allow"
    exit 0
fi

trusted_ip_s="$(sanitize "${trusted_ip:-unknown}")"
trusted_port_s="$(sanitize "${trusted_port:-unknown}")"
pool_ip_s="$(sanitize "${ifconfig_pool_remote_ip:-noip}")"
time_s="$(date +%s)"
session_key="${safe_cn}.${trusted_ip_s}.${trusted_port_s}.${pool_ip_s}"
session_file="${ACTIVE_DIR}/${session_key}"

# Everything below is atomic so two simultaneous connects cannot both pass.
exec 9>"$LOCK_FILE"
flock -x 9

# Remove very old stale records. Normal disconnect removes records immediately;
# this is only protection against crashes where OpenVPN never calls disconnect.
find "$ACTIVE_DIR" -type f -name "${safe_cn}.*" -mmin +1440 -delete 2>/dev/null || true

# Count active records written by this hook. This catches fast second connects
# before the OpenVPN status file has refreshed.
active_files="$(find "$ACTIVE_DIR" -type f -name "${safe_cn}.*" 2>/dev/null | wc -l | tr -d ' ')"

# Also count OpenVPN's status log when available, in case the active registry was
# cleared while sessions are still up.
status_count=0
if [[ -f "$STATUS_FILE" ]]; then
    status_count="$(awk -v cn="$cn" '
        BEGIN { FS="[,\t]" }
        $1 == "CLIENT_LIST" && $2 == cn { c++ }
        END { print c+0 }
    ' "$STATUS_FILE" 2>/dev/null || echo 0)"
fi

cur="$active_files"
if [[ "$status_count" -gt "$cur" ]]; then
    cur="$status_count"
fi

if (( cur >= limit )); then
    log "CN=$cn limit=$limit active_files=$active_files status=$status_count; REJECT"
    exit 1
fi

cat > "$session_file" <<EOF
common_name=$cn
trusted_ip=${trusted_ip:-}
trusted_port=${trusted_port:-}
ifconfig_pool_remote_ip=${ifconfig_pool_remote_ip:-}
created=$time_s
EOF
chmod 600 "$session_file" 2>/dev/null || true

log "CN=$cn limit=$limit active_files=$active_files status=$status_count; allow session=$session_key"
exit 0
