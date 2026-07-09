#!/bin/zsh
# Build the low-context handoff packet for Codex/Claude/operator sessions.

set -euo pipefail
cd "$(dirname "$0")"

exec ./inferno usage "$@"
