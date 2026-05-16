#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"
python3 inferno_capital_allocator.py "$@"
