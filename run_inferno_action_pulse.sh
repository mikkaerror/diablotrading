#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

set +e
python3 inferno_schwab_daily_ops.py --quiet
schwab_status=$?
set -e
if [[ "$schwab_status" -ne 0 ]]; then
  echo "Warning: Schwab daily ops refresh did not complete; continuing action pulse with latest saved data." >&2
fi

python3 inferno_action_pulse.py "$@"
