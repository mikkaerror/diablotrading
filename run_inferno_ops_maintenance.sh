#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
python3 inferno_ops_maintenance.py "$@"
