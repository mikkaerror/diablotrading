#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
python3 inferno_evidence_goal_loop.py "$@"
