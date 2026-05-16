#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"
python3 inferno_tos_sandbox.py build "$@"
