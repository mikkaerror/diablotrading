#!/usr/bin/env bash
# One-letter entry point. Run from anywhere inside the project.
set -euo pipefail
cd "$(dirname "$0")"
exec python3 today.py "$@"
