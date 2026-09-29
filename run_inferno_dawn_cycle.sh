#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

BACKTEST_ROOT="${BACKTEST_ROOT:-$HOME/PycharmProjects/Backtest3.0}"
BACKTEST_PYTHON="${BACKTEST_PYTHON:-$BACKTEST_ROOT/venv/bin/python}"

# inferno_dawn_pipeline.py runs the advisory follow-ups (second opinion,
# Desk Editor email) itself, so launchd and this wrapper behave the same.
exec "$BACKTEST_PYTHON" inferno_dawn_pipeline.py "$@"
