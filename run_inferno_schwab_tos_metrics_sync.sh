#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
python3 inferno_schwab_tos_metrics_sync.py "$@"
