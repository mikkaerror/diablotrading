#!/bin/zsh
# Build the low-context handoff packet for Codex/Claude/operator sessions.

set -euo pipefail
cd "$(dirname "$0")"

python3 inferno_usage_optimizer.py "$@"
