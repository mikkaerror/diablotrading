#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 inferno_expectancy_ledger.py "$@"
