#!/usr/bin/env bash
#
# ovpanel-client-connect.sh
# OpenVPN `client-connect` hook that enforces a per-config (per-CN)
# simultaneous-connection limit set by ov-panel.
#
# Policy: REJECT the new connection when the limit is already reached.
#         (Existing sessions keep running.)
#
# OpenVPN runs this for every new session BEFORE the client is added to the
# active list. Exit 0 = allow, exit non-zero = reject.
#
# How the active count is determined
# ----------------------------------
# We count the client's CURRENT sessions from OpenVPN's status log
# (/var/log/openvpn-status.log). This is the source of truth and is immune to
# OpenVPN restarts: ov-node restarts the OpenVPN service on activate/deactivate
# and on settings changes, during which a persistent counter would drift and
# wrongly block clients. Reading the live status avoids that entirely.
#
# Because client-connect runs BEFORE the new client is added to the status
# list, the number we read is the count of *already established* sessions, so
# "current >= limit" is the correct rejection test.
#
# Limit source: /etc/openvpn/limits/<common_name>  (a single integer)
#               0      = unlimited
#               missing/empty = DEFAULT_LIMIT
#
set -euo pipefail

LIMITS_DIR="/etc/openvpn/limits"
STATUS_FILE="${OVPANEL_STATUS_FILE:-/var/log/openvpn-status.log}"
DEFAULT_LIMIT=1
LOG_TAG="ovpanel-mlogin"

cn="${common_name:-${1:-}}"

log() { logger -t "$LOG_TAG" "$*" 2>/dev/null || echo "$LOG_TAG: $*" >&2; }

# No CN -> don't block; let OpenVPN handle it.
if [[ -z "$cn" ]]; then
    log "no common_name provided; allowing"
    exit 0
fi

# --- read configured limit ---------------------------------------------------
limit="$DEFAULT_LIMIT"
limit_file="${LIMITS_DIR}/${cn}"
if [[ -f "$limit_file" ]]; then
    raw="$(tr -dc '0-9' < "$limit_file" || true)"
    [[ -n "$raw" ]] && limit="$raw"
fi

# 0 == unlimited -> always allow.
if [[ "$limit" -eq 0 ]]; then
    log "CN=$cn limit=unlimited; allow"
    exit 0
fi

# --- count this CN's current sessions from the status log --------------------
# Status log lines look like:  CLIENT_LIST,<CommonName>,<real ip>,...
# Match the exact common name in field 2 only.
cur=0
if [[ -f "$STATUS_FILE" ]]; then
    cur="$(awk -F',' -v cn="$cn" \
        '$1 == "CLIENT_LIST" && $2 == cn { c++ } END { print c+0 }' \
        "$STATUS_FILE" 2>/dev/null || echo 0)"
fi

if (( cur >= limit )); then
    log "CN=$cn limit=$limit active=$cur; REJECT (limit reached)"
    exit 1
fi

log "CN=$cn limit=$limit active=$cur; allow"
exit 0
