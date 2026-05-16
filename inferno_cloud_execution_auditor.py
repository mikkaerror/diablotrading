from __future__ import annotations

"""Execution auditor for the Google Cloud Inferno automation lane.

The cloud control plane tells us whether the machine and project are configured.
This auditor answers the sharper hedge-desk question: did the scheduled jobs
actually run, emit the expected success logs, and preserve the evidence trail?

The module is intentionally read-only. It shells out to `gcloud`, extracts only
safe metadata from Cloud Run / Scheduler / Storage, and persists a concise audit
artifact locally. It never stores Cloud Run environment variables or secret
values from job definitions.
"""

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from inferno_cloud_state import DEFAULT_ARTIFACT_PATHS, DEFAULT_CLOUD_STATE_PREFIX
from inferno_config import GCLOUD_BIN, LOCAL_BIN_DIR, local_now, local_today
from server import DATA_DIR, REPORTS_DIR, SMTP_ENV_FILE, ensure_dirs, load_env_file, send_email, smtp_configured


CLOUD_EXECUTION_AUDIT_FILE = DATA_DIR / "inferno_cloud_execution_audit.json"
CLOUD_EXECUTION_AUDIT_TEXT_FILE = REPORTS_DIR / "cloud_execution_audit_latest.txt"
CLOUD_EXECUTION_ALERT_FILE = DATA_DIR / "inferno_cloud_execution_alert.json"

DEFAULT_REGION = os.environ.get("INFERNO_CLOUD_REGION", "us-central1").strip()
DEFAULT_DAWN_JOB = os.environ.get("INFERNO_DAWN_JOB", "diablotrading-dawn").strip()
DEFAULT_STRIKE_JOB = os.environ.get("INFERNO_STRIKE_JOB", "diablotrading-strikes").strip()
DEFAULT_DAWN_SCHEDULER = os.environ.get("INFERNO_DAWN_SCHEDULER", "diablotrading-dawn-6am").strip()
DEFAULT_STRIKE_SCHEDULER = os.environ.get("INFERNO_STRIKE_SCHEDULER", "diablotrading-strikes-745am").strip()

REQUIRED_STATE_ARTIFACTS = (
    "data/inferno_paper_execution_ledger.json",
    "data/inferno_shadow_evidence.json",
    "reports/paper_execution_ledger_latest.txt",
    "reports/shadow_evidence_latest.txt",
)


@dataclass(frozen=True)
class CloudJobSpec:
    """Expected proof points for one scheduled Cloud Run job."""

    key: str
    job_name: str
    scheduler_name: str
    success_log: str
    supporting_logs: tuple[str, ...]


DEFAULT_JOB_SPECS = (
    CloudJobSpec(
        key="dawn",
        job_name=DEFAULT_DAWN_JOB,
        scheduler_name=DEFAULT_DAWN_SCHEDULER,
        success_log="Email sent: yes",
        supporting_logs=("Morning inferno pipeline complete.", "Shadow evidence:"),
    ),
    CloudJobSpec(
        key="strikes",
        job_name=DEFAULT_STRIKE_JOB,
        scheduler_name=DEFAULT_STRIKE_SCHEDULER,
        success_log="Strike email sent: yes",
        supporting_logs=("Inferno Strike Plan", "Cloud state persist:"),
    ),
)


def text(value: Any) -> str:
    """Normalize arbitrary command/config values into trimmed text."""
    return str(value or "").strip()


def run_command(args: list[str], *, timeout_seconds: int = 60) -> dict[str, Any]:
    """Run a `gcloud` command and return a structured, non-throwing result."""
    env = os.environ.copy()
    env["PATH"] = f"{LOCAL_BIN_DIR}:{env.get('PATH', '')}"
    try:
        result = subprocess.run(
            args,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
            env=env,
        )
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc),
            "command": " ".join(args),
        }
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": text(result.stdout),
        "stderr": text(result.stderr),
        "command": " ".join(args),
    }


def gcloud_available() -> bool:
    """Return True when the gcloud CLI is callable from this runtime."""
    result = run_command([GCLOUD_BIN, "--version"], timeout_seconds=15)
    return result["ok"]


@lru_cache(maxsize=1)
def cloud_api_token_and_project() -> tuple[str, str]:
    """Return an access token and detected project for direct Google API calls."""
    import google.auth  # type: ignore[import-not-found]
    from google.auth.transport.requests import Request as GoogleAuthRequest  # type: ignore[import-not-found]

    credentials, detected_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(GoogleAuthRequest())
    return text(credentials.token), text(detected_project)


def cloud_api_request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Call Google APIs directly when the gcloud CLI is unavailable."""
    import requests

    token, _detected_project = cloud_api_token_and_project()
    headers = {"Authorization": f"Bearer {token}"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    response = requests.request(
        method,
        url,
        json=payload,
        headers=headers,
        timeout=timeout_seconds,
    )
    body = text(response.text)
    return {
        "ok": response.ok,
        "returncode": response.status_code,
        "stdout": body if response.ok else "",
        "stderr": "" if response.ok else body,
        "command": f"{method} {url}",
    }


def resolve_project_id(project_id: str = "") -> str:
    """Resolve the Google Cloud project without requiring a duplicated flag."""
    explicit = text(project_id) or text(os.environ.get("PROJECT_ID")) or text(os.environ.get("GOOGLE_CLOUD_PROJECT"))
    if explicit:
        return explicit
    if not gcloud_available():
        _token, detected_project = cloud_api_token_and_project()
        return detected_project
    result = run_command([GCLOUD_BIN, "config", "get-value", "project"], timeout_seconds=20)
    candidate = text(result.get("stdout"))
    return "" if candidate == "(unset)" else candidate


def parse_json_list(stdout: str) -> list[dict[str, Any]]:
    """Parse a `gcloud --format=json` list payload safely."""
    if not text(stdout):
        return []
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def parse_json_object(stdout: str) -> dict[str, Any]:
    """Parse a `gcloud --format=json` object payload safely."""
    if not text(stdout):
        return {}
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def latest_execution(executions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the newest Cloud Run execution record by creation timestamp."""
    if not executions:
        return None
    return max(
        executions,
        key=lambda item: text(
            (item.get("metadata") or {}).get("creationTimestamp")
            or item.get("createTime")
        ),
    )


def execution_name(execution: dict[str, Any] | None) -> str:
    """Return the short execution name for both v1 and v2 Cloud Run payloads."""
    if not execution:
        return ""
    metadata = execution.get("metadata") or {}
    raw_name = text(metadata.get("name") or execution.get("name"))
    return raw_name.rsplit("/", 1)[-1]


def execution_created_at(execution: dict[str, Any] | None) -> str:
    """Return the creation timestamp for both v1 and v2 execution payloads."""
    if not execution:
        return ""
    metadata = execution.get("metadata") or {}
    return text(metadata.get("creationTimestamp") or execution.get("createTime"))


def condition_status(execution: dict[str, Any], condition_type: str) -> str:
    """Extract a condition status from a Cloud Run execution payload."""
    status_conditions = ((execution.get("status") or {}).get("conditions") or [])
    flat_conditions = execution.get("conditions") or []
    for condition in [*status_conditions, *flat_conditions]:
        if condition.get("type") == condition_type:
            return text(condition.get("status") or condition.get("state"))
    return ""


def execution_completed(execution: dict[str, Any] | None) -> bool:
    """Return True when the execution reached a completed/succeeded state."""
    if not execution:
        return False
    status = execution.get("status") or {}
    succeeded = int(status.get("succeededCount") or execution.get("succeededCount") or 0)
    failed = int(status.get("failedCount") or execution.get("failedCount") or 0)
    completed_state = condition_status(execution, "Completed")
    return succeeded > 0 and failed == 0 and completed_state in {"True", "CONDITION_SUCCEEDED"}


def safe_execution_summary(execution: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only safe metadata from a Cloud Run execution record.

    Raw execution records can include container environment variables. We never
    persist the raw payload; this summary keeps only timing and outcome fields.
    """
    if not execution:
        return {
            "name": "",
            "createdAt": "",
            "startedAt": "",
            "completedAt": "",
            "succeededCount": 0,
            "failedCount": 0,
            "completed": False,
        }
    metadata = execution.get("metadata") or {}
    status = execution.get("status") or {}
    return {
        "name": execution_name(execution),
        "createdAt": execution_created_at(execution),
        "startedAt": text(status.get("startTime") or execution.get("startTime")),
        "completedAt": text(status.get("completionTime") or execution.get("completionTime")),
        "succeededCount": int(status.get("succeededCount") or execution.get("succeededCount") or 0),
        "failedCount": int(status.get("failedCount") or execution.get("failedCount") or 0),
        "completed": execution_completed(execution),
    }


def extract_log_text(entry: dict[str, Any]) -> str:
    """Extract human-readable text from a Cloud Logging entry."""
    if entry.get("textPayload"):
        return text(entry.get("textPayload"))
    json_payload = entry.get("jsonPayload")
    if isinstance(json_payload, dict):
        for key in ("message", "msg", "text"):
            if json_payload.get(key):
                return text(json_payload.get(key))
    proto_payload = entry.get("protoPayload")
    if isinstance(proto_payload, dict):
        return text(proto_payload.get("methodName") or proto_payload.get("status"))
    return ""


def logs_contain(log_text: str, needle: str) -> bool:
    """Case-sensitive proof check for a required Cloud Run log line."""
    return bool(text(needle)) and needle in log_text


def audit_verdict(checks: list[dict[str, Any]]) -> str:
    """Collapse individual checks into the desk-level audit verdict."""
    return "healthy" if checks and all(check.get("ok") for check in checks) else "needs-attention"


def failed_checks(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only unhealthy audit checks for alert payloads."""
    return [check for check in report.get("checks") or [] if not check.get("ok")]


def alert_throttle_key(report: dict[str, Any]) -> str:
    """Build a stable daily key so a broken cloud lane does not spam email."""
    failed = ",".join(sorted(text(check.get("name")) for check in failed_checks(report)))
    return f"{local_today()}|{report.get('projectId')}|{report.get('region')}|{failed}"


def should_send_failure_alert(report: dict[str, Any], alert_state: dict[str, Any] | None, *, force: bool = False) -> bool:
    """Return True when the current audit failure should email the operator."""
    if force:
        return report.get("verdict") != "healthy"
    if report.get("verdict") == "healthy":
        return False
    state = alert_state or {}
    return state.get("lastAlertKey") != alert_throttle_key(report)


def audit_alert_text(report: dict[str, Any]) -> str:
    """Render an email-safe alert brief for an unhealthy cloud execution audit."""
    lines = [
        "Inferno Cloud Execution Alert",
        "",
        "The cloud automation lane needs attention.",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Project: {report.get('projectId') or '-'}",
        f"Region: {report.get('region') or '-'}",
        f"Verdict: {report.get('verdict')}",
        "",
        "Failed checks:",
    ]
    failures = failed_checks(report)
    if failures:
        lines.extend(f"- {check.get('name')}: {check.get('detail')}" for check in failures)
    else:
        lines.append("- No individual failed checks were recorded, but the audit verdict was unhealthy.")

    lines.append("")
    lines.append("Latest job proof:")
    for job in report.get("jobs") or []:
        execution = job.get("execution") or {}
        scheduler = job.get("scheduler") or {}
        lines.append(
            "- "
            f"{job.get('key')}: execution={execution.get('name') or '-'} "
            f"completed={execution.get('completed')} "
            f"emailLog={job.get('successLogFound')} "
            f"scheduler={scheduler.get('state')}"
        )

    artifacts = report.get("stateArtifacts") or {}
    if artifacts:
        lines.extend(
            [
                "",
                "State vault:",
                f"- bucket: {artifacts.get('bucket') or '-'}",
                f"- available objects: {artifacts.get('availableCount', 0)}",
                f"- missing required: {', '.join(artifacts.get('missingRequired') or []) or 'none'}",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def load_alert_state() -> dict[str, Any]:
    """Load the daily alert throttle state if it exists."""
    if not CLOUD_EXECUTION_ALERT_FILE.exists():
        return {}
    try:
        payload = json.loads(CLOUD_EXECUTION_ALERT_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def save_alert_state(payload: dict[str, Any]) -> None:
    """Persist the latest cloud execution alert state."""
    ensure_dirs()
    CLOUD_EXECUTION_ALERT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def maybe_send_failure_alert(report: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Send one operator email when the cloud audit is unhealthy.

    Healthy audits are intentionally quiet. Unhealthy audits are throttled by a
    daily failure key, so a repeated local check does not turn into email spam.
    """
    load_env_file(SMTP_ENV_FILE)
    prior_state = load_alert_state()
    should_send = should_send_failure_alert(report, prior_state, force=force)
    payload = {
        "checkedAt": local_now().isoformat(),
        "auditGeneratedAt": report.get("generatedAt"),
        "auditVerdict": report.get("verdict"),
        "alertNeeded": report.get("verdict") != "healthy",
        "alertSentThisRun": False,
        "alertSuppressed": False,
        "alertError": None,
        "lastAlertKey": prior_state.get("lastAlertKey"),
    }
    if report.get("verdict") == "healthy":
        save_alert_state(payload)
        return payload
    if not should_send:
        payload["alertSuppressed"] = True
        save_alert_state(payload)
        return payload
    if not smtp_configured():
        payload["alertError"] = "SMTP is not configured."
        save_alert_state(payload)
        return payload

    key = alert_throttle_key(report)
    try:
        sent = send_email(
            {
                "brief": audit_alert_text(report),
                "sourceLabel": "Inferno Cloud Execution Auditor",
                "rows": [],
            },
            subject="Inferno Cloud Execution Alert",
        )
        payload["alertSentThisRun"] = bool(sent)
        payload["lastAlertKey"] = key if sent else prior_state.get("lastAlertKey")
    except Exception as exc:  # noqa: BLE001
        payload["alertError"] = str(exc)
    save_alert_state(payload)
    return payload


def list_executions(job_name: str, project_id: str, region: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fetch recent Cloud Run job executions for one job."""
    if not gcloud_available():
        result = cloud_api_request(
            "GET",
            f"https://run.googleapis.com/v2/projects/{project_id}/locations/{region}/jobs/{job_name}/executions?pageSize=5",
        )
        payload = parse_json_object(result.get("stdout", ""))
        return result, payload.get("executions") or []
    result = run_command(
        [
            GCLOUD_BIN,
            "run",
            "jobs",
            "executions",
            "list",
            "--job",
            job_name,
            "--region",
            region,
            "--project",
            project_id,
            "--limit",
            "5",
            "--format=json",
        ],
        timeout_seconds=60,
    )
    return result, parse_json_list(result.get("stdout", ""))


def fetch_execution_logs(execution_name: str, project_id: str) -> tuple[dict[str, Any], str]:
    """Fetch safe text logs for one Cloud Run execution."""
    if not execution_name:
        return {"ok": False, "stderr": "missing execution name", "stdout": "", "returncode": 1}, ""
    log_filter = (
        'resource.type="cloud_run_job" '
        f'AND labels."run.googleapis.com/execution_name"="{execution_name}"'
    )
    if not gcloud_available():
        result = cloud_api_request(
            "POST",
            "https://logging.googleapis.com/v2/entries:list",
            payload={
                "resourceNames": [f"projects/{project_id}"],
                "filter": log_filter,
                "orderBy": "timestamp desc",
                "pageSize": 250,
            },
        )
        payload = parse_json_object(result.get("stdout", ""))
        entries = payload.get("entries") or []
        lines = [line for entry in entries if (line := extract_log_text(entry))]
        return result, "\n".join(lines)
    result = run_command(
        [
            GCLOUD_BIN,
            "logging",
            "read",
            log_filter,
            "--project",
            project_id,
            "--freshness=7d",
            "--limit=250",
            "--format=json",
        ],
        timeout_seconds=60,
    )
    entries = parse_json_list(result.get("stdout", ""))
    lines = [line for entry in entries if (line := extract_log_text(entry))]
    return result, "\n".join(lines)


def scheduler_summary(scheduler_name: str, project_id: str, region: str) -> dict[str, Any]:
    """Fetch one Cloud Scheduler job and return only relevant state fields."""
    if not gcloud_available():
        result = cloud_api_request(
            "GET",
            f"https://cloudscheduler.googleapis.com/v1/projects/{project_id}/locations/{region}/jobs/{scheduler_name}",
        )
        payload = parse_json_object(result.get("stdout", ""))
        state = text(payload.get("state"))
        return {
            "ok": result["ok"] and state == "ENABLED",
            "name": scheduler_name,
            "state": state or "UNKNOWN",
            "schedule": text(payload.get("schedule")),
            "timeZone": text(payload.get("timeZone")),
            "nextScheduleTime": text(payload.get("scheduleTime") or payload.get("nextScheduleTime")),
            "error": "" if result["ok"] else result.get("stderr"),
        }
    result = run_command(
        [
            GCLOUD_BIN,
            "scheduler",
            "jobs",
            "describe",
            scheduler_name,
            "--location",
            region,
            "--project",
            project_id,
            "--format=json",
        ],
        timeout_seconds=60,
    )
    payload = parse_json_object(result.get("stdout", ""))
    state = text(payload.get("state"))
    return {
        "ok": result["ok"] and state == "ENABLED",
        "name": scheduler_name,
        "state": state or "UNKNOWN",
        "schedule": text(payload.get("schedule")),
        "timeZone": text(payload.get("timeZone")),
        "nextScheduleTime": text(payload.get("scheduleTime") or payload.get("nextScheduleTime")),
        "error": "" if result["ok"] else result.get("stderr"),
    }


def state_bucket_name(project_id: str) -> str:
    """Resolve the expected GCS state bucket name for cloud evidence."""
    return (
        text(os.environ.get("INFERNO_CLOUD_STATE_BUCKET"))
        or text(os.environ.get("CLOUD_STATE_BUCKET"))
        or f"{project_id}-inferno-state"
    )


def normalize_gcs_artifact(line: str, bucket: str, prefix: str) -> str:
    """Convert a `gcloud storage ls` line into a repo-relative artifact path."""
    cleaned = text(line).rstrip("/")
    marker = f"gs://{bucket}/{prefix.strip('/')}/"
    if cleaned.startswith(marker):
        return cleaned[len(marker) :]
    return cleaned


def state_artifact_audit(project_id: str, bucket: str, prefix: str) -> dict[str, Any]:
    """Verify the persistent GCS state vault contains expected desk artifacts."""
    if not gcloud_available():
        from google.cloud import storage  # type: ignore[import-not-found]

        client = storage.Client(project=project_id)
        blobs = client.list_blobs(bucket, prefix=f"{prefix.strip('/')}/")
        available = {
            normalize_gcs_artifact(f"gs://{bucket}/{blob.name}", bucket, prefix)
            for blob in blobs
        }
        missing_required = [artifact for artifact in REQUIRED_STATE_ARTIFACTS if artifact not in available]
        optional_missing = [artifact for artifact in DEFAULT_ARTIFACT_PATHS if artifact not in available]
        return {
            "ok": not missing_required,
            "bucket": bucket,
            "prefix": prefix,
            "availableCount": len(available),
            "requiredCount": len(REQUIRED_STATE_ARTIFACTS),
            "missingRequired": missing_required,
            "optionalMissing": optional_missing,
            "error": "",
        }
    result = run_command(
        [
            GCLOUD_BIN,
            "storage",
            "ls",
            "-r",
            f"gs://{bucket}/{prefix.strip('/')}/**",
            "--project",
            project_id,
        ],
        timeout_seconds=60,
    )
    available = {
        normalize_gcs_artifact(line, bucket, prefix)
        for line in result.get("stdout", "").splitlines()
        if line.strip() and not line.endswith(":")
    }
    missing_required = [artifact for artifact in REQUIRED_STATE_ARTIFACTS if artifact not in available]
    optional_missing = [artifact for artifact in DEFAULT_ARTIFACT_PATHS if artifact not in available]
    return {
        "ok": result["ok"] and not missing_required,
        "bucket": bucket,
        "prefix": prefix,
        "availableCount": len(available),
        "requiredCount": len(REQUIRED_STATE_ARTIFACTS),
        "missingRequired": missing_required,
        "optionalMissing": optional_missing,
        "error": "" if result["ok"] else result.get("stderr"),
    }


def audit_cloud_job(spec: CloudJobSpec, project_id: str, region: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Audit execution, logs, and scheduler state for one Cloud Run job."""
    checks: list[dict[str, Any]] = []
    execution_result, executions = list_executions(spec.job_name, project_id, region)
    latest = latest_execution(executions)
    execution = safe_execution_summary(latest)
    execution_ok = execution_result["ok"] and execution_completed(latest)
    checks.append(
        {
            "name": f"{spec.key}-latest-execution",
            "ok": execution_ok,
            "detail": execution["name"] if execution_ok else execution_result.get("stderr") or "no completed execution",
        }
    )

    logs_result, log_text = fetch_execution_logs(execution["name"], project_id)
    success_log_found = logs_result["ok"] and logs_contain(log_text, spec.success_log)
    supporting_log_status = {needle: logs_contain(log_text, needle) for needle in spec.supporting_logs}
    checks.append(
        {
            "name": f"{spec.key}-success-log",
            "ok": success_log_found,
            "detail": spec.success_log if success_log_found else logs_result.get("stderr") or "success log missing",
        }
    )

    scheduler = scheduler_summary(spec.scheduler_name, project_id, region)
    checks.append(
        {
            "name": f"{spec.key}-scheduler",
            "ok": scheduler["ok"],
            "detail": f"{scheduler['state']} | {scheduler.get('schedule')} | {scheduler.get('timeZone')}",
        }
    )

    return (
        {
            "key": spec.key,
            "jobName": spec.job_name,
            "schedulerName": spec.scheduler_name,
            "execution": execution,
            "successLog": spec.success_log,
            "successLogFound": success_log_found,
            "supportingLogs": supporting_log_status,
            "scheduler": scheduler,
        },
        checks,
    )


def build_audit(*, project_id: str = "", region: str = DEFAULT_REGION) -> dict[str, Any]:
    """Build the full cloud execution audit report."""
    ensure_dirs()
    resolved_project = resolve_project_id(project_id)
    checks: list[dict[str, Any]] = []

    if not resolved_project:
        checks.append({"name": "project", "ok": False, "detail": "Google Cloud project is not configured"})
        report = {
            "generatedAt": local_now().isoformat(),
            "projectId": "",
            "region": region,
            "verdict": audit_verdict(checks),
            "checks": checks,
            "jobs": [],
            "stateArtifacts": {},
        }
        save_audit_report(report)
        return report

    jobs: list[dict[str, Any]] = []
    for spec in DEFAULT_JOB_SPECS:
        job_report, job_checks = audit_cloud_job(spec, resolved_project, region)
        jobs.append(job_report)
        checks.extend(job_checks)

    bucket = state_bucket_name(resolved_project)
    prefix = text(os.environ.get("INFERNO_CLOUD_STATE_PREFIX")) or DEFAULT_CLOUD_STATE_PREFIX
    artifacts = state_artifact_audit(resolved_project, bucket, prefix)
    checks.append(
        {
            "name": "cloud-state-artifacts",
            "ok": artifacts["ok"],
            "detail": (
                f"{artifacts['availableCount']} objects available"
                if artifacts["ok"]
                else artifacts.get("error") or f"missing: {', '.join(artifacts['missingRequired'])}"
            ),
        }
    )

    report = {
        "generatedAt": local_now().isoformat(),
        "projectId": resolved_project,
        "region": region,
        "verdict": audit_verdict(checks),
        "checks": checks,
        "jobs": jobs,
        "stateArtifacts": artifacts,
    }
    save_audit_report(report)
    return report


def audit_report_text(report: dict[str, Any]) -> str:
    """Render the cloud execution audit into an operator-facing report."""
    lines = [
        "Inferno Cloud Execution Audit",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Project: {report.get('projectId') or '-'}",
        f"Region: {report.get('region') or '-'}",
        f"Verdict: {report.get('verdict')}",
        "",
        "Jobs:",
    ]
    for job in report.get("jobs") or []:
        execution = job.get("execution") or {}
        scheduler = job.get("scheduler") or {}
        lines.extend(
            [
                f"- {job.get('key')} / {job.get('jobName')}",
                f"  execution: {execution.get('name') or '-'} | completed={execution.get('completed')}",
                f"  email-log: {job.get('successLogFound')} | {job.get('successLog')}",
                f"  scheduler: {scheduler.get('state')} | {scheduler.get('schedule')} | {scheduler.get('timeZone')}",
                f"  next: {scheduler.get('nextScheduleTime') or '-'}",
            ]
        )
    artifacts = report.get("stateArtifacts") or {}
    lines.extend(
        [
            "",
            "State vault:",
            f"- bucket: {artifacts.get('bucket') or '-'}",
            f"- prefix: {artifacts.get('prefix') or '-'}",
            f"- available objects: {artifacts.get('availableCount', 0)}",
            f"- missing required: {', '.join(artifacts.get('missingRequired') or []) or 'none'}",
            "",
            "Checks:",
        ]
    )
    for check in report.get("checks") or []:
        marker = "PASS" if check.get("ok") else "WARN"
        lines.append(f"- [{marker}] {check.get('name')}: {check.get('detail')}")
    return "\n".join(lines).rstrip() + "\n"


def save_audit_report(report: dict[str, Any]) -> None:
    """Persist the cloud execution audit JSON and text reports."""
    ensure_dirs()
    CLOUD_EXECUTION_AUDIT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    CLOUD_EXECUTION_AUDIT_TEXT_FILE.write_text(audit_report_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the cloud execution auditor."""
    parser = argparse.ArgumentParser(description="Audit Cloud Run/Scheduler execution proof for the Inferno desk.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--project-id", default="", help="Google Cloud project id; defaults to gcloud config")
    parser.add_argument("--region", default=DEFAULT_REGION, help="Cloud Run/Scheduler region")
    parser.add_argument(
        "--alert-on-failure",
        action="store_true",
        help="Send one SMTP alert per day when the cloud audit is unhealthy.",
    )
    parser.add_argument(
        "--force-alert",
        action="store_true",
        help="Send an unhealthy-audit alert even if today's failure key was already sent.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the audit or print the most recent audit report."""
    args = parse_args()
    if args.command == "status" and CLOUD_EXECUTION_AUDIT_TEXT_FILE.exists():
        print(CLOUD_EXECUTION_AUDIT_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = build_audit(project_id=args.project_id, region=args.region)
    if args.alert_on_failure or args.force_alert:
        alert = maybe_send_failure_alert(report, force=args.force_alert)
        report["alert"] = alert
        save_audit_report(report)
    print(audit_report_text(report))
    if report.get("alert"):
        print(f"Alert status: {json.dumps(report['alert'], sort_keys=True)}")
    return 0 if report.get("verdict") == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
