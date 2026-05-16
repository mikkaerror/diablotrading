from __future__ import annotations

"""Cloud control-plane verifier for the Inferno desk.

This module answers one practical question: if we decide to ship the morning
pipeline to Google Cloud next week, is the operator machine actually ready to do
that work? The repo may be code-ready while the laptop is not deployment-ready.

The verifier stays read-only. It checks the local toolchain, credentials,
configuration files, and current Google Cloud control-plane state without
changing anything in the project or the cloud account.
"""

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from inferno_config import GCLOUD_BIN, LOCAL_BIN_DIR, ROOT, default_backtest_root, local_now
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


CLOUD_CONTROL_PLANE_FILE = DATA_DIR / "inferno_cloud_control_plane.json"
CLOUD_CONTROL_PLANE_TEXT_FILE = REPORTS_DIR / "cloud_control_plane_latest.txt"

GCRED_PATH = default_backtest_root() / "gcred.json"
SMTP_ENV_FILE = ROOT / ".env.smtp"

REQUIRED_APIS = (
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudscheduler.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com",
)

REQUIRED_ASSETS = (
    "Dockerfile.cloud",
    "cloudbuild.cloud.yaml",
    "requirements-cloud.txt",
    "scripts/deploy_cloud_run_job.sh",
    "scripts/run_cloud_native_local.sh",
)

DEFAULT_REGION = "us-central1"
DEFAULT_JOB_NAME = "diablotrading-dawn"
DEFAULT_STRIKE_JOB_NAME = "diablotrading-strikes"
DEFAULT_AUDIT_JOB_NAME = "diablotrading-audit"
DEFAULT_SCHEDULER_NAME = "diablotrading-dawn-6am"
DEFAULT_STRIKE_SCHEDULER_NAME = "diablotrading-strikes-745am"
DEFAULT_AUDIT_SCHEDULER_NAME = "diablotrading-audit-805am"


def text(value: Any) -> str:
    """Normalize arbitrary values into stripped text."""
    return str(value or "").strip()


def run_command(args: list[str], *, timeout_seconds: int = 30) -> dict[str, Any]:
    """Run a subprocess and capture a stable result payload."""
    env = os.environ.copy()
    env["PATH"] = f"{LOCAL_BIN_DIR}:{env.get('PATH', '')}"
    result = subprocess.run(
        args,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
        env=env,
    )
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": text(result.stdout),
        "stderr": text(result.stderr),
        "command": " ".join(args),
    }


def env_key(path: Path, key: str) -> str:
    """Read a single key from a simple dotenv-style file."""
    if not path.exists():
        return ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        current_key, value = line.split("=", 1)
        if current_key.strip() == key:
            return value.strip()
    return ""


def read_service_account_metadata(path: Path) -> dict[str, str]:
    """Read project/email hints from the Google service-account JSON when available."""
    if not path.exists():
        return {"projectId": "", "clientEmail": ""}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"projectId": "", "clientEmail": ""}
    return {
        "projectId": text(payload.get("project_id")),
        "clientEmail": text(payload.get("client_email")),
    }


def check_assets() -> dict[str, Any]:
    """Verify the deployable cloud asset set exists locally."""
    missing = [asset for asset in REQUIRED_ASSETS if not (ROOT / asset).exists()]
    ok = not missing
    return {
        "name": "assets",
        "ok": ok,
        "detail": "all required cloud assets present" if ok else f"missing: {', '.join(missing)}",
    }


def check_local_credentials() -> dict[str, Any]:
    """Verify the local non-cloud secrets/files needed for deployment exist."""
    smtp_present = SMTP_ENV_FILE.exists()
    gcred_present = GCRED_PATH.exists()
    gcred_meta = read_service_account_metadata(GCRED_PATH)
    ok = smtp_present and gcred_present
    detail = {
        "smtpEnvPresent": smtp_present,
        "googleServiceAccountJsonPresent": gcred_present,
        "gcredPath": str(GCRED_PATH),
        "gcredProjectId": gcred_meta.get("projectId"),
        "gcredClientEmail": gcred_meta.get("clientEmail"),
    }
    return {"name": "local-credentials", "ok": ok, "detail": detail}


def check_gcloud_install() -> dict[str, Any]:
    """Check whether the Google Cloud CLI is available."""
    gcloud_candidate = Path(GCLOUD_BIN).expanduser()
    if gcloud_candidate.exists():
        return {"name": "gcloud", "ok": True, "detail": str(gcloud_candidate)}
    result = run_command(["bash", "-lc", "command -v gcloud"])
    detail = result["stdout"] or result["stderr"] or "gcloud not found"
    return {"name": "gcloud", "ok": result["ok"], "detail": detail}


def check_gcloud_project() -> dict[str, Any]:
    """Check whether a default project is configured."""
    result = run_command([GCLOUD_BIN, "config", "get-value", "project"], timeout_seconds=20)
    project_id = text(result["stdout"])
    ok = result["ok"] and bool(project_id) and project_id != "(unset)"
    return {
        "name": "project",
        "ok": ok,
        "detail": project_id if ok else result["stderr"] or project_id or "gcloud project is not configured",
        "projectId": project_id,
    }


def check_gcloud_auth() -> dict[str, Any]:
    """Check whether gcloud has an active logged-in account."""
    result = run_command([GCLOUD_BIN, "auth", "list", "--format=json"], timeout_seconds=20)
    account = ""
    if result["ok"]:
        try:
            entries = json.loads(result["stdout"] or "[]")
            active = next((entry for entry in entries if entry.get("status") == "ACTIVE"), None)
            account = text((active or {}).get("account"))
        except json.JSONDecodeError:
            account = ""
    ok = result["ok"] and bool(account)
    return {
        "name": "auth",
        "ok": ok,
        "detail": account if ok else result["stderr"] or "no active gcloud auth account",
        "account": account,
    }


def check_adc(active_account: str, gcred_meta: dict[str, str]) -> dict[str, Any]:
    """Check whether Application Default Credentials are available."""
    if active_account and active_account.endswith("iam.gserviceaccount.com"):
        detail = "service-account auth active; ADC not required for gcloud deploy workflow"
        return {"name": "adc", "ok": True, "detail": detail}
    result = run_command([GCLOUD_BIN, "auth", "application-default", "print-access-token"], timeout_seconds=20)
    token = text(result["stdout"])
    ok = result["ok"] and bool(token)
    detail = "application default credentials available" if ok else result["stderr"] or "ADC token unavailable"
    return {"name": "adc", "ok": ok, "detail": detail}


def check_enabled_apis(project_id: str) -> dict[str, Any]:
    """Verify the required Google Cloud APIs are enabled for the active project."""
    result = run_command(
        [GCLOUD_BIN, "services", "list", "--enabled", "--project", project_id, "--format=value(config.name)"],
        timeout_seconds=40,
    )
    enabled = {line.strip() for line in result["stdout"].splitlines() if line.strip()}
    missing = [api for api in REQUIRED_APIS if api not in enabled]
    ok = result["ok"] and not missing
    detail = "all required APIs enabled" if ok else (result["stderr"] or f"missing APIs: {', '.join(missing)}")
    return {"name": "apis", "ok": ok, "detail": detail, "missingApis": missing}


def check_cloud_jobs(project_id: str, region: str) -> dict[str, Any]:
    """Verify that the expected Cloud Run jobs already exist."""
    result = run_command(
        [GCLOUD_BIN, "run", "jobs", "list", "--region", region, "--project", project_id, "--format=value(name)"],
        timeout_seconds=40,
    )
    jobs = {line.strip() for line in result["stdout"].splitlines() if line.strip()}
    expected = {DEFAULT_JOB_NAME, DEFAULT_STRIKE_JOB_NAME, DEFAULT_AUDIT_JOB_NAME}
    missing = sorted(expected - jobs)
    ok = result["ok"] and not missing
    detail = "cloud run jobs present" if ok else (result["stderr"] or f"missing jobs: {', '.join(missing)}")
    return {"name": "jobs", "ok": ok, "detail": detail, "missingJobs": missing}


def check_cloud_schedulers(project_id: str, region: str) -> dict[str, Any]:
    """Verify that the expected Cloud Scheduler jobs already exist."""
    result = run_command(
        [GCLOUD_BIN, "scheduler", "jobs", "list", "--location", region, "--project", project_id, "--format=value(name)"],
        timeout_seconds=40,
    )
    schedulers = {line.strip() for line in result["stdout"].splitlines() if line.strip()}
    expected = {DEFAULT_SCHEDULER_NAME, DEFAULT_STRIKE_SCHEDULER_NAME, DEFAULT_AUDIT_SCHEDULER_NAME}
    missing = sorted(expected - schedulers)
    ok = result["ok"] and not missing
    detail = "cloud scheduler jobs present" if ok else (result["stderr"] or f"missing schedulers: {', '.join(missing)}")
    return {"name": "schedulers", "ok": ok, "detail": detail, "missingSchedulers": missing}


def check_cloud_state_bucket(project_id: str) -> dict[str, Any]:
    """Verify that the persistent Cloud Run state bucket is available."""
    bucket = os.environ.get("CLOUD_STATE_BUCKET") or f"{project_id}-inferno-state"
    result = run_command(
        [GCLOUD_BIN, "storage", "buckets", "describe", f"gs://{bucket}", "--project", project_id],
        timeout_seconds=40,
    )
    ok = result["ok"]
    detail = f"state bucket present: gs://{bucket}" if ok else (result["stderr"] or f"missing bucket: gs://{bucket}")
    return {"name": "cloud-state-bucket", "ok": ok, "detail": detail, "bucket": bucket}


def determine_verdict(checks: list[dict[str, Any]]) -> tuple[str, str]:
    """Translate cloud checks into a control-plane verdict."""
    status = {check["name"]: check for check in checks}
    assets_ok = status["assets"]["ok"]
    credentials_ok = status["local-credentials"]["ok"]
    gcloud_ok = status["gcloud"]["ok"]
    project_ok = status.get("project", {}).get("ok", False)
    auth_ok = status.get("auth", {}).get("ok", False)
    adc_ok = status.get("adc", {}).get("ok", False)
    apis_ok = status.get("apis", {}).get("ok", False)
    jobs_ok = status.get("jobs", {}).get("ok", False)
    schedulers_ok = status.get("schedulers", {}).get("ok", False)
    cloud_state_ok = status.get("cloud-state-bucket", {"ok": True}).get("ok", False)

    if not assets_ok:
        return "blocked", "Required cloud deployment assets are missing from the repo."
    if not credentials_ok:
        return "blocked", "Local SMTP or Google Sheets credentials are missing for cloud deployment."
    if not gcloud_ok:
        return "repo-ready", "Cloud deployment code is ready, but gcloud is not installed on this machine."
    if not project_ok or not auth_ok or not adc_ok:
        return "operator-setup-needed", "Google Cloud CLI is present, but local auth or project setup is incomplete."
    if not apis_ok:
        return "project-setup-needed", "Google Cloud project is selected, but required APIs are not all enabled yet."
    if not jobs_ok or not schedulers_ok or not cloud_state_ok:
        return "deployable", "This machine can deploy the cloud control plane, but jobs, schedulers, or the state bucket are not fully provisioned yet."
    return "ready", "Cloud control plane is present and this machine is ready to operate it."


def build_report(*, region: str = DEFAULT_REGION) -> dict[str, Any]:
    """Build the cloud control-plane report and persist it."""
    ensure_dirs()
    local_credentials = check_local_credentials()
    checks = [check_assets(), local_credentials, check_gcloud_install()]
    gcred_meta = local_credentials.get("detail") or {}

    project_id = ""
    if checks[-1]["ok"]:
        project = check_gcloud_project()
        checks.append(project)
        project_id = text(project.get("projectId"))

        auth = check_gcloud_auth()
        checks.append(auth)

        adc = check_adc(text(auth.get("account")), gcred_meta)
        checks.append(adc)

        if project["ok"]:
            checks.append(check_enabled_apis(project_id))
            checks.append(check_cloud_jobs(project_id, region))
            checks.append(check_cloud_schedulers(project_id, region))
            checks.append(check_cloud_state_bucket(project_id))

    verdict, message = determine_verdict(checks)
    report = {
        "generatedAt": local_now().isoformat(),
        "region": region,
        "projectId": project_id,
        "verdict": verdict,
        "message": message,
        "checks": checks,
    }
    save_report(report)
    return report


def render_text(report: dict[str, Any]) -> str:
    """Render the cloud control-plane report for operators."""
    lines = [
        "Inferno Cloud Control Plane",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Region: {report.get('region')}",
        f"Project: {report.get('projectId') or 'unset'}",
        f"Verdict: {report.get('verdict')}",
        f"Message: {report.get('message')}",
        "",
        "Checks:",
    ]
    for check in report.get("checks") or []:
        marker = "PASS" if check.get("ok") else "WARN"
        lines.append(f"- [{marker}] {check.get('name')}: {check.get('detail')}")
    return "\n".join(lines).rstrip() + "\n"


def save_report(report: dict[str, Any]) -> None:
    """Persist the latest cloud control-plane JSON and text outputs."""
    ensure_dirs()
    CLOUD_CONTROL_PLANE_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    CLOUD_CONTROL_PLANE_TEXT_FILE.write_text(render_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse CLI args for the cloud control-plane checker."""
    parser = argparse.ArgumentParser(description="Verify Inferno cloud deployment readiness.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--region", default=DEFAULT_REGION, help="Google Cloud region to inspect.")
    return parser.parse_args()


def main() -> int:
    """Run or show the latest cloud control-plane report."""
    args = parse_args()
    if args.command == "status" and CLOUD_CONTROL_PLANE_TEXT_FILE.exists():
        print(CLOUD_CONTROL_PLANE_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = build_report(region=args.region)
    print(render_text(report))
    return 0 if report.get("verdict") in {"deployable", "ready"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
