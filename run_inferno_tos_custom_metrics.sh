#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
python3 inferno_tos_custom_metrics.py "$@"
