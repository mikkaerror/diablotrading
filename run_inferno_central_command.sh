#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
python3 inferno_central_command.py "$@"
