#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

BACKTEST_ROOT="${BACKTEST_ROOT:-$HOME/PycharmProjects/Backtest3.0}"
BACKTEST_PYTHON="${BACKTEST_PYTHON:-$BACKTEST_ROOT/venv/bin/python}"

"$BACKTEST_PYTHON" inferno_dawn_pipeline.py "$@"
