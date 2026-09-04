#!/usr/bin/env bash
# Inferno one-shot Schwab reauthorization (with a diagnostic log).
#   ./reauth.sh
# Opens Schwab sign-in, waits at a prompt for the redirect URL, exchanges it,
# and writes a full transcript to reauth.log so failures are easy to trace.
# It never sees your password; only the one-time redirect URL you paste.
set -uo pipefail
cd "$(dirname "$0")"
LOG="reauth.log"; : > "$LOG"

BACKTEST_ROOT="${BACKTEST_ROOT:-$HOME/PycharmProjects/Backtest3.0}"
_py="$BACKTEST_ROOT/venv/bin/python"; [ -x "$_py" ] || _py="python3"
PY="${INFERNO_PYTHON:-$_py}"
{ echo "== env =="; echo "cwd: $(pwd)"; echo "python: $PY"; "$PY" --version; } >>"$LOG" 2>&1

printf '\n\033[1;33m== Step 1 · opening Schwab sign-in ==\033[0m\n'
url="$("$PY" inferno_schwab_oauth.py auth-url 2>>"$LOG" | grep -Eo 'https://[^ ]+' | tail -1)"
{ echo "== step1 auth-url =="; echo "url: ${url:-<none>}"; } >>"$LOG" 2>&1
if [ -z "$url" ]; then
  echo "Couldn't build the sign-in URL — details are in reauth.log."
  exit 1
fi
echo "Sign in here (opening your browser now):"
echo "  $url"
if command -v open >/dev/null 2>&1; then open "$url" && echo "(browser opened)"; else echo "(open that URL manually)"; fi

printf '\n\033[1;33m== Step 2 · paste the redirect URL ==\033[0m\n'
cat <<'EOF'
After you approve, the browser lands on a page that looks broken at
  https://127.0.0.1/?code=...
Copy the ENTIRE address-bar URL and paste it at the prompt below, then Enter.
(No quotes, no flags — the prompt waits for you.)

EOF
set +e
"$PY" inferno_schwab_oauth.py exchange 2> >(tee -a "$LOG" >&2)
rc=$?
set -e
echo "== step2 exchange exit: $rc ==" >>"$LOG"

printf '\n\033[1;33m== Step 3 · token status ==\033[0m\n'
"$PY" inferno_schwab_oauth.py status 2>&1 | tee -a "$LOG" | grep -iE "reauthorizationRequired|accessTokenPresent|refreshTokenPresent|lastRefreshError" || true

echo
if [ "$rc" -eq 0 ]; then
  printf '\033[1;32m✓ Reauthorized.\033[0m  Now run:  ./run_inferno_refresh.sh\n'
else
  printf '\033[1;31m✗ Exchange did not complete.\033[0m  The code may have expired between sign-in and paste.\n'
  echo "Just run  ./reauth.sh  again for a fresh URL. Full details: reauth.log"
fi
