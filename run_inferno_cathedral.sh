#!/bin/bash
# Inferno Command Cathedral — read-only illuminated operating picture.
# Regenerates reports/cathedral_command_center.html from existing desk artifacts.
# Research-only: touches no authority, tickets, risk constants, or broker state.
set -euo pipefail
cd "$(dirname "$0")"
python3 inferno_cathedral_command.py --root . "$@"
