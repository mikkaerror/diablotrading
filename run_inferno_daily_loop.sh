#!/bin/zsh
# Operator daily-loop wrapper.
#
# Chains the read-only diagnostics into one combined digest at
# data/inferno_daily_loop.json and reports/daily_loop_latest.txt.
#
# Safe to run on a schedule. Read-only — cannot place trades, change
# authority, or mutate the approval queue.

set -euo pipefail

cd "$(dirname "$0")"

# Mirror the dawn-cycle pattern: prefer the Backtest venv Python so Google
# Sheets / yfinance imports resolve the same way they do in cloud automation.
BACKTEST_ROOT="${BACKTEST_ROOT:-$HOME/PycharmProjects/Backtest3.0}"
BACKTEST_PYTHON="${BACKTEST_PYTHON:-$BACKTEST_ROOT/venv/bin/python}"

if [ -x "$BACKTEST_PYTHON" ]; then
    PY="$BACKTEST_PYTHON"
else
    PY="python3"
fi

"$PY" inferno_daily_loop.py "$@"
