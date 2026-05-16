#!/usr/bin/env bash
# Inferno backup helper.
#
# Usage:
#   scripts/inferno_backup.sh <file> [file ...]
#
# Copies each target into _backups/YYYY-MM-DD/<basename>.<HHMMSS> and prints
# the snapshot path. Use this before any code edit so a recovery copy exists
# locally even when git status is mid-flight.

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "usage: scripts/inferno_backup.sh <file> [file ...]" >&2
    exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATE_DIR="$ROOT/_backups/$(date +%Y-%m-%d)"
mkdir -p "$DATE_DIR"

for target in "$@"; do
    if [ ! -e "$target" ]; then
        echo "skip (does not exist): $target" >&2
        continue
    fi
    if [ ! -f "$target" ]; then
        echo "skip (not a regular file): $target" >&2
        continue
    fi
    base="$(basename "$target")"
    stamp="$(date +%H%M%S)"
    dest="$DATE_DIR/${base}.${stamp}"
    cp "$target" "$dest"
    echo "$dest"
done
