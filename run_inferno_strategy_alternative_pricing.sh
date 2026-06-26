#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
if [[ "${1:-run}" != "status" ]]; then
  python3 inferno_paper_variant_scanner.py run >/dev/null
fi
python3 inferno_strategy_alternative_pricing.py "$@"
