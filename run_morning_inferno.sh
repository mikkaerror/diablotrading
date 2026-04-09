#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

# Backward-compatible shim. The canonical entrypoint is run_inferno_dawn_cycle.sh.
exec ./run_inferno_dawn_cycle.sh "$@"
