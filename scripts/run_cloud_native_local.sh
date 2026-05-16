#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f ".env.smtp" ]; then
  set -a
  source ".env.smtp"
  set +a
fi

if [ -z "${GOOGLE_SERVICE_ACCOUNT_JSON:-}" ]; then
  GCRED_PATH="${GOOGLE_APPLICATION_CREDENTIALS:-$HOME/PycharmProjects/Backtest3.0/gcred.json}"
  if [ -f "$GCRED_PATH" ]; then
    export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat "$GCRED_PATH")"
  fi
fi

python3 morning_inferno_pipeline.py --cloud-native "$@"
