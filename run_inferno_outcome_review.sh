#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"
python3 inferno_outcome_reviewer.py review "$@"
