#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
python3 inferno_ticker_universe_audit.py "$@"
