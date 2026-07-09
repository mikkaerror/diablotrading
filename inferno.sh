#!/usr/bin/env bash
# INFERNO - one command, one screen.
#
#   ./inferno.sh                 refresh the desk, then open the dashboard
#   ./inferno.sh --skip-tracker  refresh but skip the Google-Sheet tracker pull
#   ./inferno.sh --no-refresh    just (re)open the dashboard, no refresh
#
# This is a THIN front door. It only runs existing desk scripts and serves the
# read-only dashboard. It never places a trade, changes authority, or edits risk
# constants. liveTradingAllowed / brokerSubmitAllowed stay off.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1
PORT="${INFERNO_DASHBOARD_PORT:-8787}"

DO_REFRESH=1
ARGS=()
for a in "$@"; do
  if [ "$a" = "--no-refresh" ]; then DO_REFRESH=0; else ARGS+=("$a"); fi
done

echo "INFERNO - one command"

if [ "$DO_REFRESH" = "1" ]; then
  echo "Refreshing the desk (Schwab -> metrics -> evidence -> reports)..."
  echo "If Schwab asks for re-auth, run: ./inferno oauth restart"
  echo ""
  if [ "${#ARGS[@]}" -gt 0 ]; then
    ./inferno sync "${ARGS[@]}" || echo "(refresh finished with advisory warnings - expected while OAuth/data is thin)"
  else
    ./inferno sync || echo "(refresh finished with advisory warnings - expected while OAuth/data is thin)"
  fi
  echo ""
else
  echo "Skipping refresh (--no-refresh); opening the last-known screen."
fi

# Serve the repo over localhost so the dashboard can read data/*.json (file://
# fetch is blocked by browsers). Reuse an existing server if the port is up.
URL="http://localhost:${PORT}/inferno_dashboard.html"
if ! curl -s "http://localhost:${PORT}/" >/dev/null 2>&1; then
  ( python3 -m http.server "${PORT}" >/dev/null 2>&1 & )
  sleep 1
fi

echo "One screen -> ${URL}"
if command -v open >/dev/null 2>&1; then
  open "${URL}"
fi
echo "Leave it open - it self-refreshes every 5 minutes. Re-run ./inferno.sh to pull fresh data."
