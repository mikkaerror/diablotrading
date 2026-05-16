#!/bin/zsh
set -euo pipefail

MODE="${1:-status}"
LOCAL_GCLOUD_BIN="${GCLOUD_BIN:-$HOME/.local/bin/gcloud}"

if [ -x "$LOCAL_GCLOUD_BIN" ]; then
  export PATH="$(dirname "$LOCAL_GCLOUD_BIN"):$PATH"
fi

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud is not installed. Run ./scripts/bootstrap_cloud_operator.sh install first." >&2
  exit 1
fi

case "$MODE" in
  status)
    echo "gcloud: $(command -v gcloud)"
    echo "project:"
    gcloud config get-value project 2>/dev/null || true
    echo ""
    echo "active auth accounts:"
    gcloud auth list --format="table(account,status)"
    echo ""
    echo "ADC check:"
    if gcloud auth application-default print-access-token >/dev/null 2>&1; then
      echo "application default credentials available"
    else
      echo "application default credentials missing"
    fi
    ;;
  login)
    echo "Launching gcloud auth login..."
    gcloud auth login
    ;;
  adc)
    echo "Launching application-default login..."
    gcloud auth application-default login
    ;;
  all)
    echo "Launching auth login..."
    gcloud auth login
    echo "Launching application-default login..."
    gcloud auth application-default login
    ;;
  *)
    echo "Usage: $0 [status|login|adc|all]" >&2
    exit 1
    ;;
esac
