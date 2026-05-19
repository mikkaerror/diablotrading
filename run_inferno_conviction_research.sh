#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
python3 inferno_conviction_research.py "$@"
