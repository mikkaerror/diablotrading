#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")/.."

LOCAL_GCLOUD_BIN="${GCLOUD_BIN:-$HOME/.local/bin/gcloud}"
if [ -x "$LOCAL_GCLOUD_BIN" ]; then
  export PATH="$(dirname "$LOCAL_GCLOUD_BIN"):$PATH"
fi
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"

PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-us-central1}"
REPOSITORY="${REPOSITORY:-diablotrading}"
JOB_NAME="${JOB_NAME:-diablotrading-dawn}"
SCHEDULER_NAME="${SCHEDULER_NAME:-diablotrading-dawn-6am}"
STRIKE_JOB_NAME="${STRIKE_JOB_NAME:-diablotrading-strikes}"
STRIKE_SCHEDULER_NAME="${STRIKE_SCHEDULER_NAME:-diablotrading-strikes-745am}"
AUDIT_JOB_NAME="${AUDIT_JOB_NAME:-diablotrading-audit}"
AUDIT_SCHEDULER_NAME="${AUDIT_SCHEDULER_NAME:-diablotrading-audit-805am}"
TIME_ZONE="${TIME_ZONE:-America/Denver}"
SCHEDULE="${SCHEDULE:-0 6 * * SUN,MON,TUE,WED,THU,FRI}"
STRIKE_SCHEDULE="${STRIKE_SCHEDULE:-45 7 * * SUN,MON,TUE,WED,THU,FRI}"
AUDIT_SCHEDULE="${AUDIT_SCHEDULE:-5 8 * * SUN,MON,TUE,WED,THU,FRI}"
GCRED_PATH="${GCRED_PATH:-$HOME/PycharmProjects/Backtest3.0/gcred.json}"
SERVICE_ACCOUNT_NAME="${SERVICE_ACCOUNT_NAME:-diablotrading-scheduler}"
RUNNER_SERVICE_ACCOUNT_NAME="${RUNNER_SERVICE_ACCOUNT_NAME:-diablotrading-runner}"
SECRET_DELIVERY_MODE="${SECRET_DELIVERY_MODE:-auto}"
MEMORY="${MEMORY:-1Gi}"
CLOUD_STATE_BUCKET="${CLOUD_STATE_BUCKET:-${PROJECT_ID:+${PROJECT_ID}-inferno-state}}"
CLOUD_STATE_PREFIX="${CLOUD_STATE_PREFIX:-diablotrading-state}"

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud is not installed. Run ./scripts/bootstrap_cloud_operator.sh install, then rerun this script." >&2
  exit 1
fi

if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
  echo "python3 is required but was not found on PATH." >&2
  exit 1
fi

if [ -z "$PROJECT_ID" ]; then
  PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
fi

if [ -z "$PROJECT_ID" ]; then
  echo "PROJECT_ID is required. Run: gcloud config set project <project-id>" >&2
  exit 1
fi

SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
RUNNER_SERVICE_ACCOUNT_EMAIL="${RUNNER_SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
GCRED_CLIENT_EMAIL="$("$PYTHON_BIN" - "$GCRED_PATH" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(str(payload.get("client_email", "")).strip())
PY
)"
DEFAULT_RUN_JOB_SERVICE_ACCOUNT_EMAIL="${GCRED_CLIENT_EMAIL:-$RUNNER_SERVICE_ACCOUNT_EMAIL}"
RUN_JOB_SERVICE_ACCOUNT_EMAIL="${RUN_JOB_SERVICE_ACCOUNT_EMAIL:-$DEFAULT_RUN_JOB_SERVICE_ACCOUNT_EMAIL}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${JOB_NAME}:latest"
ACTIVE_GCLOUD_ACCOUNT="$(gcloud auth list --format='value(account)' --filter='status:ACTIVE' 2>/dev/null | head -n 1)"
SCHEDULER_CALLER_SERVICE_ACCOUNT_EMAIL="$SERVICE_ACCOUNT_EMAIL"

if [ ! -f "$GCRED_PATH" ]; then
  echo "Google service-account JSON not found: $GCRED_PATH" >&2
  exit 1
fi

if [ ! -f ".env.smtp" ]; then
  echo ".env.smtp not found. Run python3 setup_smtp.py first." >&2
  exit 1
fi

load_env_value() {
  local key="$1"
  "$PYTHON_BIN" - "$key" <<'PY'
import sys
from pathlib import Path
key = sys.argv[1]
for raw in Path(".env.smtp").read_text(encoding="utf-8").splitlines():
    if not raw or raw.lstrip().startswith("#") or "=" not in raw:
        continue
    k, v = raw.split("=", 1)
    if k == key:
        print(v)
        break
PY
}

write_env_file() {
  local path="$1"
  local include_inline_secrets="$2"
  "$PYTHON_BIN" - "$path" "$include_inline_secrets" <<'PY'
import os
import sys
import json
from pathlib import Path

path = Path(sys.argv[1])
include_inline_secrets = sys.argv[2] == "true"

payload = {
    "PROJECT_ID": os.environ["PROJECT_ID"],
    "TZ": os.environ["TIME_ZONE"],
    "SMTP_HOST": os.environ["SMTP_HOST"],
    "SMTP_PORT": os.environ["SMTP_PORT"],
    "SMTP_FROM": os.environ["SMTP_FROM"],
    "SMTP_TO": os.environ["SMTP_TO"],
    "SMTP_USERNAME": os.environ["SMTP_USERNAME"],
    "SMTP_USE_SSL": os.environ["SMTP_USE_SSL"],
    "INFERNO_CLOUD_STATE_BUCKET": os.environ.get("CLOUD_STATE_BUCKET", ""),
    "INFERNO_CLOUD_STATE_PREFIX": os.environ.get("CLOUD_STATE_PREFIX", "diablotrading-state"),
}

if include_inline_secrets:
    payload["SMTP_PASSWORD"] = os.environ["SMTP_PASSWORD"]
    if os.environ.get("INLINE_GOOGLE_SERVICE_ACCOUNT_JSON", "false") == "true":
        payload["GOOGLE_SERVICE_ACCOUNT_JSON_B64"] = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON_B64"]

path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
PY
}

SMTP_HOST="$(load_env_value SMTP_HOST)"
SMTP_PORT="$(load_env_value SMTP_PORT)"
SMTP_FROM="$(load_env_value SMTP_FROM)"
SMTP_TO="$(load_env_value SMTP_TO)"
SMTP_USERNAME="$(load_env_value SMTP_USERNAME)"
SMTP_PASSWORD="$(load_env_value SMTP_PASSWORD)"
SMTP_USE_SSL="$(load_env_value SMTP_USE_SSL)"
GOOGLE_SERVICE_ACCOUNT_JSON_B64="$("$PYTHON_BIN" - "$GCRED_PATH" <<'PY'
import base64
import sys
from pathlib import Path
print(base64.b64encode(Path(sys.argv[1]).read_bytes()).decode("ascii"))
PY
)"

INLINE_GOOGLE_SERVICE_ACCOUNT_JSON="true"
if [ -n "$GCRED_CLIENT_EMAIL" ] && [ "$RUN_JOB_SERVICE_ACCOUNT_EMAIL" = "$GCRED_CLIENT_EMAIL" ]; then
  INLINE_GOOGLE_SERVICE_ACCOUNT_JSON="false"
fi

if [ -z "$CLOUD_STATE_BUCKET" ]; then
  CLOUD_STATE_BUCKET="${PROJECT_ID}-inferno-state"
fi

export TIME_ZONE SMTP_HOST SMTP_PORT SMTP_FROM SMTP_TO SMTP_USERNAME SMTP_PASSWORD SMTP_USE_SSL GOOGLE_SERVICE_ACCOUNT_JSON_B64 INLINE_GOOGLE_SERVICE_ACCOUNT_JSON CLOUD_STATE_BUCKET CLOUD_STATE_PREFIX
export PROJECT_ID

EFFECTIVE_SECRET_DELIVERY_MODE="$SECRET_DELIVERY_MODE"
if [[ "$EFFECTIVE_SECRET_DELIVERY_MODE" != "auto" && "$EFFECTIVE_SECRET_DELIVERY_MODE" != "secret-manager" && "$EFFECTIVE_SECRET_DELIVERY_MODE" != "plain-env" ]]; then
  echo "SECRET_DELIVERY_MODE must be one of: auto, secret-manager, plain-env" >&2
  exit 1
fi

ENV_FILE="$(mktemp -t diablotrading-cloud-env.XXXXXX)"
trap 'rm -f "$ENV_FILE"' EXIT

if [ -z "$SMTP_PASSWORD" ]; then
  echo "SMTP_PASSWORD is missing in .env.smtp" >&2
  exit 1
fi

echo "Enabling required Google Cloud APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  iam.googleapis.com \
  --project "$PROJECT_ID"

echo "Ensuring Artifact Registry repository exists..."
gcloud artifacts repositories describe "$REPOSITORY" \
  --location "$REGION" \
  --project "$PROJECT_ID" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "$REPOSITORY" \
    --repository-format docker \
    --location "$REGION" \
    --description "Diablo Trading container images" \
    --project "$PROJECT_ID"

echo "Ensuring Cloud state bucket exists..."
if ! gcloud storage buckets describe "gs://${CLOUD_STATE_BUCKET}" --project "$PROJECT_ID" >/dev/null 2>&1; then
  if ! gcloud storage buckets create "gs://${CLOUD_STATE_BUCKET}" \
    --location "$REGION" \
    --uniform-bucket-level-access \
    --project "$PROJECT_ID"; then
    echo "Could not create ${CLOUD_STATE_BUCKET}; falling back to ${PROJECT_ID}_cloudbuild for state artifacts." >&2
    CLOUD_STATE_BUCKET="${PROJECT_ID}_cloudbuild"
    export CLOUD_STATE_BUCKET
  fi
fi

echo "Granting runner access to Cloud state bucket..."
gcloud storage buckets add-iam-policy-binding "gs://${CLOUD_STATE_BUCKET}" \
  --member "serviceAccount:${RUN_JOB_SERVICE_ACCOUNT_EMAIL}" \
  --role "roles/storage.objectAdmin" \
  --project "$PROJECT_ID" >/dev/null 2>&1 \
  || echo "Could not update bucket IAM; continuing because the runner may already have storage access." >&2

upsert_secret() {
  local secret_name="$1"
  local secret_value="$2"
  if ! gcloud secrets describe "$secret_name" --project "$PROJECT_ID" >/dev/null 2>&1; then
    gcloud secrets create "$secret_name" --replication-policy automatic --project "$PROJECT_ID"
  fi
  printf "%s" "$secret_value" | gcloud secrets versions add "$secret_name" --data-file=- --project "$PROJECT_ID" >/dev/null
}

configure_secret_manager_mode() {
  JOB_SECRET_SPEC="SMTP_PASSWORD=diablotrading-smtp-password:latest"
  local grants_ok="true"
  echo "Uploading secrets to Secret Manager..."
  upsert_secret "diablotrading-smtp-password" "$SMTP_PASSWORD"
  if [ "$INLINE_GOOGLE_SERVICE_ACCOUNT_JSON" = "true" ]; then
    upsert_secret "diablotrading-google-service-account-json" "$(cat "$GCRED_PATH")"
  else
    echo "Using Cloud Run ambient service-account auth for Google Sheets."
  fi

  echo "Granting the runner access to required secrets..."
  if ! gcloud secrets add-iam-policy-binding "diablotrading-smtp-password" \
    --member "serviceAccount:${RUN_JOB_SERVICE_ACCOUNT_EMAIL}" \
    --role "roles/secretmanager.secretAccessor" \
    --project "$PROJECT_ID" >/dev/null; then
    grants_ok="false"
  fi
  if [ "$INLINE_GOOGLE_SERVICE_ACCOUNT_JSON" = "true" ]; then
    if ! gcloud secrets add-iam-policy-binding "diablotrading-google-service-account-json" \
      --member "serviceAccount:${RUN_JOB_SERVICE_ACCOUNT_EMAIL}" \
      --role "roles/secretmanager.secretAccessor" \
      --project "$PROJECT_ID" >/dev/null; then
      grants_ok="false"
    fi
    JOB_SECRET_SPEC="GOOGLE_SERVICE_ACCOUNT_JSON=diablotrading-google-service-account-json:latest,${JOB_SECRET_SPEC}"
  fi

  if [ "$grants_ok" != "true" ]; then
    return 1
  fi

  write_env_file "$ENV_FILE" "false"
}

configure_plain_env_mode() {
  echo "Using inline Cloud Run env fallback for SMTP and Google Sheets credentials."
  echo "This bypasses Secret Manager IAM friction, but the secrets will live in the job config."
  write_env_file "$ENV_FILE" "true"
}

clear_existing_job_secrets() {
  local job_name="$1"
  if gcloud run jobs describe "$job_name" --region "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
    echo "Clearing stale secret bindings from ${job_name} before inline-env deploy..."
    gcloud run jobs update "$job_name" \
      --region "$REGION" \
      --project "$PROJECT_ID" \
      --clear-secrets >/dev/null
  fi
}

grant_scheduler_invoker_access() {
  gcloud run jobs add-iam-policy-binding "$JOB_NAME" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --member "serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role "roles/run.invoker" >/dev/null

  gcloud run jobs add-iam-policy-binding "$STRIKE_JOB_NAME" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --member "serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role "roles/run.invoker" >/dev/null

  gcloud run jobs add-iam-policy-binding "$AUDIT_JOB_NAME" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --member "serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role "roles/run.invoker" >/dev/null
}

echo "Building cloud image..."
gcloud builds submit \
  --config cloudbuild.cloud.yaml \
  --substitutions "_IMAGE=${IMAGE}" \
  --project "$PROJECT_ID" \
  .

echo "Ensuring scheduler service account exists..."
gcloud iam service-accounts describe "$SERVICE_ACCOUNT_EMAIL" --project "$PROJECT_ID" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "$SERVICE_ACCOUNT_NAME" \
    --display-name "Diablo Trading Scheduler" \
    --project "$PROJECT_ID"

if [ "$RUN_JOB_SERVICE_ACCOUNT_EMAIL" = "$RUNNER_SERVICE_ACCOUNT_EMAIL" ]; then
  echo "Ensuring Cloud Run runner service account exists..."
  gcloud iam service-accounts describe "$RUNNER_SERVICE_ACCOUNT_EMAIL" --project "$PROJECT_ID" >/dev/null 2>&1 \
    || gcloud iam service-accounts create "$RUNNER_SERVICE_ACCOUNT_NAME" \
      --display-name "Diablo Trading Cloud Run Runner" \
      --project "$PROJECT_ID"
else
  echo "Using existing Cloud Run job service account: ${RUN_JOB_SERVICE_ACCOUNT_EMAIL}"
fi

if [ "$EFFECTIVE_SECRET_DELIVERY_MODE" = "auto" ]; then
  if configure_secret_manager_mode; then
    EFFECTIVE_SECRET_DELIVERY_MODE="secret-manager"
  else
    echo "Secret Manager IAM grant failed. Falling back to inline job env delivery." >&2
    EFFECTIVE_SECRET_DELIVERY_MODE="plain-env"
    configure_plain_env_mode
  fi
elif [ "$EFFECTIVE_SECRET_DELIVERY_MODE" = "secret-manager" ]; then
  configure_secret_manager_mode
else
  configure_plain_env_mode
fi

JOB_SECRET_FLAGS=()
if [ "$EFFECTIVE_SECRET_DELIVERY_MODE" = "secret-manager" ]; then
  JOB_SECRET_FLAGS=(
    --set-secrets
    "$JOB_SECRET_SPEC"
  )
else
  clear_existing_job_secrets "$JOB_NAME"
  clear_existing_job_secrets "$STRIKE_JOB_NAME"
  clear_existing_job_secrets "$AUDIT_JOB_NAME"
fi

echo "Deploying Cloud Run Job..."
gcloud run jobs deploy "$JOB_NAME" \
  --image "$IMAGE" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --service-account "$RUN_JOB_SERVICE_ACCOUNT_EMAIL" \
  --tasks 1 \
  --max-retries 1 \
  --task-timeout 3600 \
  --memory "$MEMORY" \
  --env-vars-file "$ENV_FILE" \
  "${JOB_SECRET_FLAGS[@]}" \
  --command python \
  --args "morning_inferno_pipeline.py,--cloud-native"

echo "Deploying Cloud Run strike-selection job..."
gcloud run jobs deploy "$STRIKE_JOB_NAME" \
  --image "$IMAGE" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --service-account "$RUN_JOB_SERVICE_ACCOUNT_EMAIL" \
  --tasks 1 \
  --max-retries 1 \
  --task-timeout 3600 \
  --memory "$MEMORY" \
  --env-vars-file "$ENV_FILE" \
  "${JOB_SECRET_FLAGS[@]}" \
  --command python \
  --args "cloud_strike_cycle.py"

echo "Deploying Cloud Run execution-audit job..."
gcloud run jobs deploy "$AUDIT_JOB_NAME" \
  --image "$IMAGE" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --service-account "$RUN_JOB_SERVICE_ACCOUNT_EMAIL" \
  --tasks 1 \
  --max-retries 1 \
  --task-timeout 3600 \
  --memory "$MEMORY" \
  --env-vars-file "$ENV_FILE" \
  "${JOB_SECRET_FLAGS[@]}" \
  --command python \
  --args "inferno_cloud_execution_auditor.py,--alert-on-failure"

echo "Granting scheduler least-privilege permission to execute the job..."
if grant_scheduler_invoker_access; then
  echo "Dedicated scheduler service account can invoke both jobs."
elif [[ "$ACTIVE_GCLOUD_ACCOUNT" == *"iam.gserviceaccount.com" ]]; then
  SCHEDULER_CALLER_SERVICE_ACCOUNT_EMAIL="$ACTIVE_GCLOUD_ACCOUNT"
  echo "Job IAM policy could not be updated. Falling back to active deploy service account for scheduler calls:"
  echo "  ${SCHEDULER_CALLER_SERVICE_ACCOUNT_EMAIL}"
else
  echo "Unable to grant scheduler invoker permissions and no service-account fallback is available." >&2
  exit 1
fi

SCHEDULER_URI="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB_NAME}:run"
STRIKE_SCHEDULER_URI="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${STRIKE_JOB_NAME}:run"
AUDIT_SCHEDULER_URI="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${AUDIT_JOB_NAME}:run"

echo "Creating or updating Cloud Scheduler trigger..."
if gcloud scheduler jobs describe "$SCHEDULER_NAME" --location "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$SCHEDULER_NAME" \
    --location "$REGION" \
    --schedule "$SCHEDULE" \
    --time-zone "$TIME_ZONE" \
    --uri "$SCHEDULER_URI" \
    --http-method POST \
    --oauth-service-account-email "$SCHEDULER_CALLER_SERVICE_ACCOUNT_EMAIL" \
    --project "$PROJECT_ID"
else
  gcloud scheduler jobs create http "$SCHEDULER_NAME" \
    --location "$REGION" \
    --schedule "$SCHEDULE" \
    --time-zone "$TIME_ZONE" \
    --uri "$SCHEDULER_URI" \
    --http-method POST \
    --oauth-service-account-email "$SCHEDULER_CALLER_SERVICE_ACCOUNT_EMAIL" \
    --project "$PROJECT_ID"
fi

echo "Creating or updating Cloud Scheduler strike trigger..."
if gcloud scheduler jobs describe "$STRIKE_SCHEDULER_NAME" --location "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$STRIKE_SCHEDULER_NAME" \
    --location "$REGION" \
    --schedule "$STRIKE_SCHEDULE" \
    --time-zone "$TIME_ZONE" \
    --uri "$STRIKE_SCHEDULER_URI" \
    --http-method POST \
    --oauth-service-account-email "$SCHEDULER_CALLER_SERVICE_ACCOUNT_EMAIL" \
    --project "$PROJECT_ID"
else
  gcloud scheduler jobs create http "$STRIKE_SCHEDULER_NAME" \
    --location "$REGION" \
    --schedule "$STRIKE_SCHEDULE" \
    --time-zone "$TIME_ZONE" \
    --uri "$STRIKE_SCHEDULER_URI" \
    --http-method POST \
    --oauth-service-account-email "$SCHEDULER_CALLER_SERVICE_ACCOUNT_EMAIL" \
    --project "$PROJECT_ID"
fi

echo "Creating or updating Cloud Scheduler audit trigger..."
if gcloud scheduler jobs describe "$AUDIT_SCHEDULER_NAME" --location "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$AUDIT_SCHEDULER_NAME" \
    --location "$REGION" \
    --schedule "$AUDIT_SCHEDULE" \
    --time-zone "$TIME_ZONE" \
    --uri "$AUDIT_SCHEDULER_URI" \
    --http-method POST \
    --oauth-service-account-email "$SCHEDULER_CALLER_SERVICE_ACCOUNT_EMAIL" \
    --project "$PROJECT_ID"
else
  gcloud scheduler jobs create http "$AUDIT_SCHEDULER_NAME" \
    --location "$REGION" \
    --schedule "$AUDIT_SCHEDULE" \
    --time-zone "$TIME_ZONE" \
    --uri "$AUDIT_SCHEDULER_URI" \
    --http-method POST \
    --oauth-service-account-email "$SCHEDULER_CALLER_SERVICE_ACCOUNT_EMAIL" \
    --project "$PROJECT_ID"
fi

echo "Cloud automation deployed."
echo "Secret delivery mode: ${EFFECTIVE_SECRET_DELIVERY_MODE}"
echo "Cloud Run job service account: ${RUN_JOB_SERVICE_ACCOUNT_EMAIL}"
echo "Scheduler caller identity: ${SCHEDULER_CALLER_SERVICE_ACCOUNT_EMAIL}"
echo "Test it with:"
echo "  gcloud run jobs execute ${JOB_NAME} --region ${REGION} --project ${PROJECT_ID} --wait"
echo "  gcloud run jobs execute ${STRIKE_JOB_NAME} --region ${REGION} --project ${PROJECT_ID} --wait"
echo "  gcloud run jobs execute ${AUDIT_JOB_NAME} --region ${REGION} --project ${PROJECT_ID} --wait"
