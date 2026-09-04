#!/usr/bin/env bash
# Inferno Refresh Runner — safe, ordered data refresh to unblock paper staging.
#
# Research-only. It refreshes market data and rebuilds report artifacts, then
# regenerates the operator screens. It NEVER touches authority, tickets, risk
# constants, promotion state, or broker order submission, and it NEVER handles
# your Schwab password or authorization code — it stops at the one manual step
# (Schwab reauthorization) and hands it back to you.
#
# Run this on the Mac where the desk's Python environment lives.
set -uo pipefail
cd "$(dirname "$0")"

say(){ printf '\n\033[1;33m== %s ==\033[0m\n' "$1"; }

# Prefer the desk's heavy Python (the Backtest venv the dawn pipeline uses, which
# has yfinance + the option stack); fall back to bare python3. Override with
# INFERNO_PYTHON=/path/to/python if your environment differs.
BACKTEST_ROOT="${BACKTEST_ROOT:-$HOME/PycharmProjects/Backtest3.0}"
_default_py="$BACKTEST_ROOT/venv/bin/python"
[ -x "$_default_py" ] || _default_py="python3"
PY="${INFERNO_PYTHON:-$_default_py}"
echo "Using Python: $PY"

say "1/5  Schwab OAuth status"
status_out="$("$PY" inferno_central_command.py oauth status 2>&1 || true)"
printf '%s\n' "$status_out"

if printf '%s\n' "$status_out" | grep -qE 'reauthorizationRequired:[[:space:]]*True'; then
  say "ACTION NEEDED — Schwab reauthorization (only you can do this)"
  echo "Open this URL, sign in to Schwab, and approve access:"
  "$PY" inferno_central_command.py oauth auth-url 2>&1 || true
  cat <<'EOF'

Finish the handshake yourself — no password or code goes through this script:
  1) Open the URL above, sign in to Schwab, and approve.
  2) Copy the FULL redirect URL from the browser address bar. It looks like
       https://127.0.0.1/?code=...&session=...
     (the page itself will look broken — that is expected.)
  3) RIGHT AWAY (the code expires in under a minute) run the exchange. Note the
     --code flag and the SINGLE quotes — the single quotes protect the & in the
     URL, which is what caused the earlier "parse error near &":
       ./inferno oauth exchange --code 'PASTE_THE_FULL_URL_HERE'
     Do not type the angle brackets < >. If the code expired, just re-run this
     script to get a fresh URL and try again.
  4) Re-run: ./run_inferno_refresh.sh

Stopping here until Schwab is reauthorized.
EOF
  exit 2
fi

say "2/5  Refresh access token"
"$PY" inferno_central_command.py oauth ensure || true

say "3/5  Refresh Schwab option tape + account (read-only)"
if [ -x ./run_inferno_schwab_daily_ops.sh ]; then ./run_inferno_schwab_daily_ops.sh || true
else "$PY" inferno_central_command.py daily-ops || true; fi
[ -x ./run_inferno_schwab_account_sync.sh ] && ./run_inferno_schwab_account_sync.sh || true

say "4/5  Full model refresh (tracker, research, strike, paper director, doctor)"
"$PY" inferno_central_command.py sync || true

say "5/5  Rebuild operator screens"
[ -f inferno_staging_board.py ] && "$PY" inferno_staging_board.py --root . || true
[ -f inferno_cathedral_command.py ] && "$PY" inferno_cathedral_command.py --root . || true

say "Done"
echo "Open:  reports/staging_board.html"
echo "       reports/cathedral_command_center.html"
echo
echo "If candidates now price, route the clean ones into paperMoney and record"
echo "real fills with:   ./inferno paper-capture"
