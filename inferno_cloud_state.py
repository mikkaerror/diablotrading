from __future__ import annotations

"""Google Cloud Storage artifact vault for Cloud Run jobs.

Cloud Run Jobs are intentionally stateless: every execution starts with a clean
container filesystem. That is great for reliability, but terrible for learning
loops if paper ledgers and shadow evidence vanish after each run. This module
adds an optional GCS-backed state vault. When `INFERNO_CLOUD_STATE_BUCKET` is
set, cloud jobs restore known artifacts at startup and persist them after
successful runs.

The vault never stores broker credentials or SMTP secrets. It only moves desk
artifacts such as paper ledgers, shadow evidence, analytics, and authority
reports between the ephemeral container and a private bucket.
"""

import json
import os
from pathlib import Path
from typing import Any

from inferno_config import local_now
from server import DATA_DIR, REPORTS_DIR, ROOT, ensure_dirs


CLOUD_STATE_FILE = DATA_DIR / "inferno_cloud_state.json"
CLOUD_STATE_TEXT_FILE = REPORTS_DIR / "cloud_state_latest.txt"

DEFAULT_CLOUD_STATE_PREFIX = "diablotrading-state"
DEFAULT_ARTIFACT_PATHS = [
    "data/inferno_paper_execution_ledger.json",
    "data/inferno_fast_paper_cohort.json",
    "data/inferno_fast_paper_ledger.json",
    "data/inferno_shadow_evidence.json",
    "data/inferno_performance_analytics.json",
    "data/inferno_strategy_lab.json",
    "data/inferno_exposure_analytics.json",
    "data/inferno_broker_preview.json",
    "data/inferno_authority_manifest.json",
    "data/inferno_tos_sandbox_session.json",
    "reports/paper_execution_ledger_latest.txt",
    "reports/fast_paper_cohort_latest.txt",
    "reports/shadow_evidence_latest.txt",
    "reports/performance_analytics_latest.txt",
    "reports/strategy_lab_latest.txt",
    "reports/exposure_analytics_latest.txt",
    "reports/broker_preview_latest.txt",
    "reports/authority_manifest_latest.txt",
    "reports/tos_sandbox_session_latest.txt",
]


def cloud_state_bucket_name() -> str:
    """Return the configured GCS bucket name, if cloud persistence is enabled."""
    return os.environ.get("INFERNO_CLOUD_STATE_BUCKET", "").strip()


def cloud_state_prefix() -> str:
    """Return the object prefix used inside the state bucket."""
    return os.environ.get("INFERNO_CLOUD_STATE_PREFIX", DEFAULT_CLOUD_STATE_PREFIX).strip().strip("/")


def cloud_state_enabled() -> bool:
    """Return True when the cloud state vault has enough config to run."""
    return bool(cloud_state_bucket_name())


def artifact_path(path: str | Path) -> Path:
    """Resolve an artifact path under the repository root."""
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def object_name(path: str | Path) -> str:
    """Return the GCS object name for a repo-relative artifact path."""
    relative = artifact_path(path).relative_to(ROOT).as_posix()
    prefix = cloud_state_prefix()
    return f"{prefix}/{relative}" if prefix else relative


def storage_bucket() -> Any:
    """Build a GCS bucket handle lazily so local runs do not need the package."""
    from google.cloud import storage  # type: ignore[import-not-found]

    client = storage.Client()
    return client.bucket(cloud_state_bucket_name())


def cloud_state_report_text(report: dict[str, Any]) -> str:
    """Render cloud state activity as an operator-readable report."""
    lines = [
        "Inferno Cloud State Vault",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Mode: {report.get('mode')}",
        f"Enabled: {report.get('enabled')}",
        f"Bucket: {report.get('bucket') or 'not configured'}",
        f"Prefix: {report.get('prefix') or '-'}",
        f"OK: {report.get('ok')}",
        "",
        f"Restored: {len(report.get('restored', []))}",
        f"Persisted: {len(report.get('persisted', []))}",
        f"Missing: {len(report.get('missing', []))}",
        f"Errors: {len(report.get('errors', []))}",
    ]
    if report.get("errors"):
        lines.append("")
        lines.append("Errors:")
        lines.extend(f"- {item}" for item in report["errors"])
    return "\n".join(lines).rstrip() + "\n"


def save_cloud_state_report(report: dict[str, Any]) -> None:
    """Persist the latest cloud state report locally for doctor/preflight use."""
    ensure_dirs()
    CLOUD_STATE_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    CLOUD_STATE_TEXT_FILE.write_text(cloud_state_report_text(report), encoding="utf-8")


def base_report(mode: str) -> dict[str, Any]:
    """Build a standard report shell for restore/persist operations."""
    return {
        "generatedAt": local_now().isoformat(),
        "mode": mode,
        "enabled": cloud_state_enabled(),
        "bucket": cloud_state_bucket_name(),
        "prefix": cloud_state_prefix(),
        "ok": True,
        "restored": [],
        "persisted": [],
        "missing": [],
        "errors": [],
    }


def restore_cloud_artifacts(paths: list[str] | None = None) -> dict[str, Any]:
    """Restore cloud artifacts into the local data/report directories."""
    report = base_report("restore")
    paths = paths or DEFAULT_ARTIFACT_PATHS
    if not cloud_state_enabled():
        save_cloud_state_report(report)
        return report

    try:
        bucket = storage_bucket()
        for path in paths:
            local_path = artifact_path(path)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            blob = bucket.blob(object_name(path))
            if not blob.exists():
                report["missing"].append(path)
                continue
            blob.download_to_filename(str(local_path))
            report["restored"].append(path)
    except Exception as exc:  # noqa: BLE001
        report["ok"] = False
        report["errors"].append(str(exc))

    save_cloud_state_report(report)
    return report


def persist_cloud_artifacts(paths: list[str] | None = None) -> dict[str, Any]:
    """Persist local data/report artifacts into the configured cloud vault."""
    report = base_report("persist")
    paths = paths or DEFAULT_ARTIFACT_PATHS
    if not cloud_state_enabled():
        save_cloud_state_report(report)
        return report

    try:
        bucket = storage_bucket()
        for path in paths:
            local_path = artifact_path(path)
            if not local_path.exists():
                report["missing"].append(path)
                continue
            blob = bucket.blob(object_name(path))
            blob.upload_from_filename(str(local_path))
            report["persisted"].append(path)
    except Exception as exc:  # noqa: BLE001
        report["ok"] = False
        report["errors"].append(str(exc))

    save_cloud_state_report(report)
    return report
