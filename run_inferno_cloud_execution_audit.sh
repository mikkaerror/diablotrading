#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"
python3 inferno_cloud_execution_auditor.py "$@"
