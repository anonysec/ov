#!/usr/bin/env bash
#
# ovpanel-client-disconnect.sh
# Matching `client-disconnect` hook for ovpanel-client-connect.sh.
#
# The connection limit is enforced by counting live sessions from OpenVPN's
# status log at connect time, so no per-CN counter has to be maintained here.
# This hook is intentionally a no-op (kept so server.conf's client-disconnect
# directive points at a valid script and for future use / logging).
#
set -euo pipefail

LOG_TAG="ovpanel-mlogin"
cn="${common_name:-${1:-}}"

logger -t "$LOG_TAG" "CN=${cn:-?} disconnect" 2>/dev/null || true
exit 0
