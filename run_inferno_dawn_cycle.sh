#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

BACKTEST_ROOT="${BACKTEST_ROOT:-$HOME/PycharmProjects/Backtest3.0}"
BACKTEST_PYTHON="${BACKTEST_PYTHON:-$BACKTEST_ROOT/venv/bin/python}"

set +e
"$BACKTEST_PYTHON" inferno_dawn_pipeline.py "$@"
dawn_code=$?
# Advisory ChatGPT devil's advocate for the Desk Editor; never fails the dawn run.
"$BACKTEST_PYTHON" inferno_second_opinion.py run || true
exit $dawn_code
