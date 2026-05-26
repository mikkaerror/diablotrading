#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ "$#" -eq 0 ]; then
  python3 inferno_live_account_sync.py --refresh-schwab
else
  python3 inferno_live_account_sync.py "$@"
fi
