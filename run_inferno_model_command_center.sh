#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
python3 inferno_model_command_center.py "$@"
