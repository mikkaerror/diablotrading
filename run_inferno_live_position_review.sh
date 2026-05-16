#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
python3 inferno_live_position_review.py "$@"
