#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"
python3 inferno_paper_evidence_loop.py "$@"
