#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"
python3 inferno_exposure_analytics.py build "$@"
