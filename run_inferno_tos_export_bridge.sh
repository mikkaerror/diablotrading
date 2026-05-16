#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"
python3 inferno_tos_export_bridge.py run "$@"
