#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 inferno_dte_policy_analysis.py "$@"
