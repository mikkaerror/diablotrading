from __future__ import annotations

"""Deployment readiness preflight for the Inferno desk.

This command gives us one honest deployment readout before we try to ship:

- core code health
- local automation test coverage
- cloud-native morning pipeline smoke run
- local desktop broker-lane status

It is intentionally conservative. A broken desktop thinkorswim window should
not hide cloud readiness, and a healthy cloud lane should not be mistaken for
broker automation readiness.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from inferno_config import local_now
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


DEPLOY_PREFLIGHT_FILE = DATA_DIR / "inferno_deploy_preflight.json"
DEPLOY_PREFLIGHT_TEXT_FILE = REPORTS_DIR / "deploy_preflight_latest.txt"

CORE_PYTHON_FILES = [
    "inferno_config.py",
    "morning_inferno_pipeline.py",
    "inferno_doctor.py",
    "inferno_tos_session_probe.py",
    "inferno_tos_ui_route.py",
    "inferno_tos_export_bridge.py",
    "inferno_tos_export_verifier.py",
    "inferno_cloud_state.py",
    "inferno_cloud_execution_auditor.py",
    "inferno_data_readiness_audit.py",
    "inferno_ops_maintenance.py",
    "inferno_ticker_universe_audit.py",
    "inferno_paper_evidence_loop.py",
    "cloud_strike_cycle.py",
    "inferno_shadow_evidence.py",
    "inferno_strategy_lab.py",
    "inferno_secret_hygiene.py",
    "inferno_research_cycle.py",
]

SHELL_FILES = [
    "run_inferno_dawn_cycle.sh",
    "run_inferno_shadow_evidence.sh",
    "run_inferno_strategy_lab.sh",
    "run_inferno_research_cycle.sh",
    "run_inferno_strike_cycle.sh",
    "run_inferno_paper_evidence_loop.sh",
    "run_inferno_ops_maintenance.sh",
    "run_inferno_ticker_universe_audit.sh",
    "run_inferno_tos_session_probe.sh",
    "run_inferno_tos_ui_route.sh",
    "run_inferno_tos_export_bridge.sh",
    "run_inferno_tos_export_verifier.sh",
    "run_inferno_cloud_control_plane.sh",
    "run_inferno_cloud_execution_audit.sh",
    "scripts/run_cloud_native_local.sh",
    "scripts/bootstrap_cloud_operator.sh",
    "scripts/bootstrap_cloud_auth.sh",
    "scripts/bootstrap_cloud_service_account.sh",
    "scripts/deploy_cloud_run_job.sh",
]

ASSET_FILES = [
    "Dockerfile.cloud",
    "cloudbuild.cloud.yaml",
    "requirements-cloud.txt",
    ".github/workflows/deploy-pages.yml",
    ".github/workflows/inferno-ci.yml",
]

PREFLIGHT_PROFILES = {"local", "ci", "cloud", "desktop"}


def text(value: Any) -> str:
    """Normalize arbitrary values into trimmed text."""
    return str(value or "").strip()


def run_command(args: list[str], *, timeout_seconds: int = 900) -> dict[str, Any]:
    """Run a subprocess and return a structured result payload."""
    result = subprocess.run(
        args,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )
    stdout = text(result.stdout)
    stderr = text(result.stderr)
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "command": " ".join(args),
    }


def run_check(name: str, args: list[str], *, timeout_seconds: int = 900) -> dict[str, Any]:
    """Wrap a subprocess into a human-readable preflight check record."""
    result = run_command(args, timeout_seconds=timeout_seconds)
    if result["stdout"]:
        detail = result["stdout"]
    elif result["stderr"]:
        detail = result["stderr"]
    elif result["ok"]:
        detail = "ok"
    else:
        # A silent non-zero return code is still actionable. Make the failure
        # explicit so preflight does not pretend a broken lane returned "ok".
        detail = f"command exited {result['returncode']} with no output"
    return {
        "name": name,
        "ok": result["ok"],
        "detail": detail,
        "command": result["command"],
        "returncode": result["returncode"],
    }


def snapshot_artifact_state(*roots: Path) -> tuple[Path, dict[str, set[Path]]]:
    """Copy the current desk artifacts into a temp snapshot for safe restoration.

    The local preflight should not pollute the operator-facing desk state. We
    snapshot the current artifact trees before a mutating smoke run, then put
    them back exactly as they were afterward.
    """
    snapshot_dir = Path(tempfile.mkdtemp(prefix="inferno-preflight-artifacts-"))
    manifests: dict[str, set[Path]] = {}
    for root in roots:
        saved_files: set[Path] = set()
        if root.exists():
            for source in root.rglob("*"):
                if not source.is_file():
                    continue
                rel_path = source.relative_to(root)
                target = snapshot_dir / root.name / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                saved_files.add(rel_path)
        manifests[str(root)] = saved_files
    return snapshot_dir, manifests


def restore_artifact_state(snapshot_dir: Path, manifests: dict[str, set[Path]]) -> None:
    """Restore desk artifacts after an isolated smoke run.

    Files created only by the smoke run are removed, and original files are
    copied back in place. This keeps preflight honest without degrading the
    live operating state.
    """
    for root_text, original_files in manifests.items():
        root = Path(root_text)
        root.mkdir(parents=True, exist_ok=True)
        current_files = {path.relative_to(root) for path in root.rglob("*") if path.is_file()}
        backup_root = snapshot_dir / root.name
        backup_files = {path.relative_to(backup_root) for path in backup_root.rglob("*") if path.is_file()} if backup_root.exists() else set()

        for extra_path in current_files - original_files:
            try:
                (root / extra_path).unlink()
            except FileNotFoundError:
                pass

        for rel_path in backup_files:
            source = backup_root / rel_path
            target = root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    shutil.rmtree(snapshot_dir, ignore_errors=True)


def run_isolated_check(name: str, args: list[str], *, timeout_seconds: int = 900) -> dict[str, Any]:
    """Run a mutating smoke check without leaving side effects behind."""
    snapshot_dir, manifests = snapshot_artifact_state(DATA_DIR, REPORTS_DIR)
    try:
        return run_check(name, args, timeout_seconds=timeout_seconds)
    finally:
        restore_artifact_state(snapshot_dir, manifests)


def doctor_summary(stdout: str) -> tuple[bool, str]:
    """Extract the final doctor verdict from raw output."""
    match = re.search(r"Desk status:\s*(.+)", stdout)
    if not match:
        return False, "doctor output missing final desk status"
    status = match.group(1).strip()
    return status.lower() == "healthy", status


def determine_verdict(report: dict[str, Any]) -> tuple[str, str]:
    """Translate detailed checks into one deploy-facing verdict."""
    profile = report.get("profile") or "local"
    core_ok = report["coreReady"]
    cloud_ok = report["cloudReady"]
    broker_ready = report["brokerDesktopReady"]

    if profile == "ci":
        if core_ok:
            return "ready-for-ci", "CI-safe deployment gates are clean."
        return "blocked", "CI-safe deployment gates are not clean enough to merge."
    if profile == "cloud":
        if core_ok and cloud_ok:
            return "ready-for-cloud-pilot", "Core and cloud lanes are healthy."
        if core_ok and not cloud_ok:
            return "core-only", "Core automation is healthy, but the cloud deployment lane still needs attention."
        return "blocked", "Core deployment gates are not clean enough to ship yet."
    if profile == "desktop":
        if core_ok and broker_ready:
            return "ready-for-desktop-pilot", "Core and desktop broker lanes are healthy."
        if core_ok and not broker_ready:
            return "desktop-blocked", "Core automation is healthy, but the desktop broker lane still needs attention."
        return "blocked", "Core deployment gates are not clean enough to ship yet."

    if core_ok and cloud_ok and broker_ready:
        return "ready-for-pilot", "Core, cloud, and broker-desktop lanes are all healthy."
    if core_ok and cloud_ok and not broker_ready:
        return (
            "ready-for-cloud-pilot",
            "Core and cloud lanes are healthy; desktop broker automation still needs a visible thinkorswim window.",
        )
    if core_ok and not cloud_ok:
        return "core-only", "Core automation is healthy, but the cloud deployment lane still needs attention."
    return "blocked", "Core deployment gates are not clean enough to ship yet."


def required_check_names(profile: str) -> set[str]:
    """Return the checks that must pass for a given preflight profile."""
    names = {"python-compile", "unit-tests", "deploy-assets", "secret-hygiene", "research-cycle"}
    names.update({f"shell:{path}" for path in SHELL_FILES})

    if profile in {"local", "cloud", "desktop"}:
        names.add("doctor")
    if profile in {"local", "cloud"}:
        names.add("cloud-smoke")
    if profile in {"local", "desktop"}:
        names.update({"tos-session-probe", "tos-ui-route-dry-run", "tos-export-verifier"})
    return names


def should_run_check(name: str, profile: str) -> bool:
    """Tell the runner whether a check belongs to the requested preflight profile."""
    return name in required_check_names(profile)


def summarize_lane(checks: list[dict[str, Any]], names: set[str]) -> bool:
    """Return True when all required checks for a lane passed."""
    relevant = [check for check in checks if check["name"] in names]
    return bool(relevant) and all(check["ok"] for check in relevant)


def run_preflight(*, timeout_seconds: int = 900, profile: str = "local") -> dict[str, Any]:
    """Run the deployment readiness preflight and persist the result."""
    ensure_dirs()

    checks: list[dict[str, Any]] = []

    if should_run_check("python-compile", profile):
        checks.append(
            run_check(
                "python-compile",
                ["python3", "-m", "py_compile", *CORE_PYTHON_FILES],
                timeout_seconds=timeout_seconds,
            )
        )
    if should_run_check("unit-tests", profile):
        checks.append(
            run_check(
                "unit-tests",
                ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
                timeout_seconds=timeout_seconds,
            )
        )

    for shell_file in SHELL_FILES:
        name = f"shell:{shell_file}"
        if should_run_check(name, profile):
            checks.append(run_check(name, ["bash", "-n", shell_file], timeout_seconds=timeout_seconds))

    missing_assets = [path for path in ASSET_FILES if not Path(path).exists()]
    if should_run_check("deploy-assets", profile):
        checks.append(
            {
                "name": "deploy-assets",
                "ok": not missing_assets,
                "detail": "all required deployment assets present" if not missing_assets else ", ".join(missing_assets),
                "command": "asset existence check",
                "returncode": 0 if not missing_assets else 1,
            }
        )

    if should_run_check("cloud-smoke", profile):
        checks.append(
            run_isolated_check(
                "cloud-smoke",
                ["python3", "morning_inferno_pipeline.py", "--cloud-native", "--skip-updates", "--skip-email"],
                timeout_seconds=timeout_seconds,
            )
        )

    if should_run_check("doctor", profile):
        doctor = run_check("doctor", ["python3", "inferno_doctor.py"], timeout_seconds=timeout_seconds)
        doctor_ok, doctor_status = doctor_summary(doctor["detail"])
        doctor["ok"] = doctor_ok
        doctor["detail"] = doctor_status
        checks.append(doctor)

    if should_run_check("secret-hygiene", profile):
        checks.append(
            run_check(
                "secret-hygiene",
                ["python3", "inferno_secret_hygiene.py"],
                timeout_seconds=timeout_seconds,
            )
        )
    if should_run_check("research-cycle", profile):
        checks.append(
            run_check(
                "research-cycle",
                ["python3", "inferno_research_cycle.py"],
                timeout_seconds=timeout_seconds,
            )
        )

    if should_run_check("tos-session-probe", profile):
        checks.append(
            run_check("tos-session-probe", ["python3", "inferno_tos_session_probe.py"], timeout_seconds=timeout_seconds)
        )
    if should_run_check("tos-ui-route-dry-run", profile):
        checks.append(
            run_check(
                "tos-ui-route-dry-run",
                ["python3", "inferno_tos_ui_route.py", "--dry-run"],
                timeout_seconds=timeout_seconds,
            )
        )
    if should_run_check("tos-export-verifier", profile):
        checks.append(
            run_check(
                "tos-export-verifier",
                ["python3", "inferno_tos_export_verifier.py"],
                timeout_seconds=timeout_seconds,
            )
        )

    core_names = required_check_names(profile) & (
        {"python-compile", "unit-tests", "doctor", "deploy-assets", "secret-hygiene", "research-cycle"}
        | {f"shell:{path}" for path in SHELL_FILES}
    )
    core_ready = summarize_lane(checks, core_names)
    cloud_ready = summarize_lane(checks, {"cloud-smoke"}) if profile in {"local", "cloud"} else False
    broker_ready = (
        summarize_lane(checks, {"tos-session-probe", "tos-ui-route-dry-run", "tos-export-verifier"})
        if profile in {"local", "desktop"}
        else False
    )

    verdict, message = determine_verdict(
        {
            "profile": profile,
            "coreReady": core_ready,
            "cloudReady": cloud_ready,
            "brokerDesktopReady": broker_ready,
        }
    )

    report = {
        "generatedAt": local_now().isoformat(),
        "profile": profile,
        "checks": checks,
        "coreReady": core_ready,
        "cloudReady": cloud_ready,
        "brokerDesktopReady": broker_ready,
        "verdict": verdict,
        "message": message,
    }
    save_preflight_report(report)
    return report


def preflight_report_text(report: dict[str, Any]) -> str:
    """Render the deploy preflight into an operator-facing summary."""
    lines = [
        "Inferno Deploy Preflight",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Profile: {report.get('profile')}",
        f"Verdict: {report.get('verdict')}",
        f"Message: {report.get('message')}",
        f"Core ready: {report.get('coreReady')}",
        f"Cloud ready: {report.get('cloudReady')}",
        f"Broker desktop ready: {report.get('brokerDesktopReady')}",
        "",
        "Checks:",
    ]
    for check in report.get("checks") or []:
        marker = "PASS" if check.get("ok") else "WARN"
        lines.append(f"- [{marker}] {check.get('name')}: {check.get('detail')}")
    return "\n".join(lines).rstrip() + "\n"


def save_preflight_report(report: dict[str, Any]) -> None:
    """Persist the latest deploy preflight JSON and text reports."""
    ensure_dirs()
    from inferno_io import atomic_write_json, atomic_write_text

    atomic_write_json(DEPLOY_PREFLIGHT_FILE, report)
    atomic_write_text(DEPLOY_PREFLIGHT_TEXT_FILE, preflight_report_text(report))


def parse_args() -> argparse.Namespace:
    """Parse CLI args for the deploy preflight."""
    parser = argparse.ArgumentParser(description="Run the Inferno deployment readiness preflight.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--timeout-seconds", type=int, default=900, help="Per-check timeout in seconds")
    parser.add_argument(
        "--profile",
        choices=sorted(PREFLIGHT_PROFILES),
        default="local",
        help="Choose which readiness lane to validate.",
    )
    return parser.parse_args()


def main() -> int:
    """Run or show the latest deploy preflight."""
    args = parse_args()
    if args.command == "status" and DEPLOY_PREFLIGHT_TEXT_FILE.exists():
        print(DEPLOY_PREFLIGHT_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = run_preflight(timeout_seconds=args.timeout_seconds, profile=args.profile)
    print(preflight_report_text(report))
    return 0 if report.get("coreReady") else 1


if __name__ == "__main__":
    raise SystemExit(main())
