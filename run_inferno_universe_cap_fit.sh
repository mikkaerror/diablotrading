#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")"
exec python3 inferno_universe_cap_fit.py "$@"
