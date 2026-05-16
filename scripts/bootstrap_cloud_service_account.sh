#!/bin/zsh
set -euo pipefail

MODE="${1:-activate}"
GCRED_PATH="${GCRED_PATH:-$HOME/PycharmProjects/Backtest3.0/gcred.json}"
LOCAL_GCLOUD_BIN="${GCLOUD_BIN:-$HOME/.local/bin/gcloud}"

if [ -x "$LOCAL_GCLOUD_BIN" ]; then
  export PATH="$(dirname "$LOCAL_GCLOUD_BIN"):$PATH"
fi

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud is not installed. Run ./scripts/bootstrap_cloud_operator.sh install first." >&2
  exit 1
fi

if [ ! -f "$GCRED_PATH" ]; then
  echo "Google service-account JSON not found: $GCRED_PATH" >&2
  exit 1
fi

PROJECT_ID="$(python3 - <<'PY' "$GCRED_PATH"
import json, sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text())
print(payload.get("project_id", ""))
PY
)"

CLIENT_EMAIL="$(python3 - <<'PY' "$GCRED_PATH"
import json, sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text())
print(payload.get("client_email", ""))
PY
)"

if [ -z "$PROJECT_ID" ] || [ -z "$CLIENT_EMAIL" ]; then
  echo "Could not read project_id/client_email from $GCRED_PATH" >&2
  exit 1
fi

case "$MODE" in
  status)
    echo "gcloud: $(command -v gcloud)"
    echo "project_id: $PROJECT_ID"
    echo "client_email: $CLIENT_EMAIL"
    echo "active account:"
    gcloud config get-value account 2>/dev/null || true
    echo "configured project:"
    gcloud config get-value project 2>/dev/null || true
    ;;
  activate)
    gcloud auth activate-service-account "$CLIENT_EMAIL" --key-file="$GCRED_PATH" --project="$PROJECT_ID"
    gcloud config set project "$PROJECT_ID"
    echo "Service account activated for project $PROJECT_ID"
    ;;
  *)
    echo "Usage: $0 [status|activate]" >&2
    exit 1
    ;;
esac
