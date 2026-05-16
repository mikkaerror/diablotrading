#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"
python3 inferno_deploy_preflight.py "$@"
