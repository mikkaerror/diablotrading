#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"
python3 inferno_tos_session_probe.py "$@"
