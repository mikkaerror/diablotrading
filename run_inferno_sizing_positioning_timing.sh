#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec "${INFERNO_PYTHON:-python3}" inferno_sizing_positioning_timing.py "$@"
