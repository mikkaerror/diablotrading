#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

BACKTEST_ROOT="${BACKTEST_ROOT:-$HOME/PycharmProjects/Backtest3.0}"
BACKTEST_PYTHON="${BACKTEST_PYTHON:-$BACKTEST_ROOT/venv/bin/python}"

set +e
"$BACKTEST_PYTHON" inferno_schwab_daily_ops.py --quiet
schwab_status=$?
set -e
if [[ "$schwab_status" -ne 0 ]]; then
  echo "Warning: Schwab daily ops refresh did not complete; continuing action pulse with latest saved data." >&2
fi

"$BACKTEST_PYTHON" inferno_action_pulse.py "$@"
