from __future__ import annotations

"""Read-only reporting preflight for the next-week Inferno operating cadence.

The preflight answers one boring question before the desk sends or trusts a
brief: are the reporting inputs fresh enough, are SMTP/Schwab configured, is
TOS in an attach-only safe state, and did the doctor recently report healthy or
only advisory attention items?

It does not launch thinkorswim, send email, refresh the tracker, place orders,
or mutate any authority flags. It only writes its own JSON/text artifact.
"""

import argparse
from pathlib import Path
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_reporting_summary import (
    ACTION_PULSE_FILE,
    DOCTOR_TEXT_FILE,
    LIVE_ACCOUNT_SYNC_FILE,
    MORNING_BRIEF_TEXT_FILE,
    SCHWAB_ACCOUNT_SYNC_FILE,
    SCHWAB_DAILY_OPS_FILE,
    SCHWAB_OPTIONS_FILE,
    TOS_SESSION_PROBE_FILE,
    TRACKER_SNAPSHOT_FILE,
    age_hours,
    artifact_generated_at,
    build_freshness_panel,
    build_tos_visibility_summary,
    render_freshness_lines,
    render_tos_visibility_line,
    parse_timestamp,
)
from inferno_schwab_oauth import load_config as load_schwab_config
from inferno_schwab_oauth import token_status as schwab_token_status
from server import DATA_DIR, REPORTS_DIR, SMTP_ENV_FILE, ensure_dirs, load_env_file, load_json_file, smtp_configured


REPORTING_PREFLIGHT_FILE = DATA_DIR / "inferno_reporting_preflight.json"
REPORTING_PREFLIGHT_TEXT_FILE = REPORTS_DIR / "reporting_preflight_latest.txt"
DEPOSIT_PLAN_FILE = DATA_DIR / "inferno_deposit_plan.json"
CASH_ATTRIBUTION_FILE = DATA_DIR / "inferno_cash_attribution.json"
TICKET_CAP_POLICY_FILE = DATA_DIR / "inferno_ticket_cap_policy.json"


def _artifact_check(label: str, path: Path, *, max_age_hours: float) -> dict[str, Any]:
    """Check one required artifact for presence and freshness."""
    generated_at = artifact_generated_at(path)
    age = age_hours(generated_at)
    ok = age is not None and age <= max_age_hours
    return {
        "name": label,
        "ok": ok,
        "severity": "fail" if not ok else "pass",
        "generatedAt": generated_at,
        "ageHours": round(age, 2) if age is not None else None,
        "detail": str(path),
    }


def _doctor_check() -> dict[str, Any]:
    """Check the latest doctor text without rerunning the doctor."""
    if not DOCTOR_TEXT_FILE.exists():
        return {"name": "doctor", "ok": False, "severity": "fail", "detail": "doctor report missing"}
    try:
        body = DOCTOR_TEXT_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        return {"name": "doctor", "ok": False, "severity": "fail", "detail": str(exc)}
    healthy = "Desk status: healthy" in body
    attention = "Desk status:" in body and "need attention" in body
    explicit_fail = "[FAIL]" in body
    generated_at = artifact_generated_at(DOCTOR_TEXT_FILE)
    age = age_hours(generated_at)
    fresh = age is not None and age <= 8
    if not fresh:
        severity = "fail"
        ok = False
        detail = "doctor report is stale or missing timestamp"
    elif explicit_fail:
        severity = "fail"
        ok = False
        detail = "doctor report has explicit failed checks"
    elif healthy:
        severity = "pass"
        ok = True
        detail = "Desk status: healthy and fresh"
    elif attention:
        severity = "warn"
        ok = True
        detail = "doctor report is fresh with advisory attention items"
    else:
        severity = "fail"
        ok = False
        detail = "doctor report has an unrecognized status"
    return {
        "name": "doctor",
        "ok": ok,
        "severity": severity,
        "generatedAt": generated_at,
        "ageHours": round(age, 2) if age is not None else None,
        "detail": detail,
    }


def _smtp_check() -> dict[str, Any]:
    """Check SMTP configuration without sending an email."""
    load_env_file(SMTP_ENV_FILE)
    ok = smtp_configured()
    return {
        "name": "smtp",
        "ok": ok,
        "severity": "pass" if ok else "fail",
        "detail": "SMTP configured" if ok else "SMTP not configured",
    }


def _schwab_check() -> dict[str, Any]:
    """Check Schwab local OAuth readiness without exposing secrets."""
    status = schwab_token_status(load_schwab_config())
    configured = all(
        bool(status.get(key))
        for key in (
            "envFileExists",
            "clientIdConfigured",
            "clientSecretConfigured",
            "tokenFileExists",
            "accessTokenPresent",
            "refreshTokenPresent",
        )
    )
    expiry = parse_timestamp(status.get("accessTokenExpiresAt"))
    access_token_fresh = expiry is not None and expiry > local_now()
    reauthorization_required = bool(status.get("reauthorizationRequired"))
    # Schwab access tokens are short-lived; a stored refresh token keeps the
    # desk operational, but the preflight should still surface that the next
    # tape pull may need to refresh first.
    severity = (
        "fail"
        if reauthorization_required or not configured
        else "pass"
        if access_token_fresh
        else "warn"
    )
    return {
        "name": "schwab token",
        "ok": configured and not reauthorization_required,
        "severity": severity,
        "detail": {
            "envFileExists": status.get("envFileExists"),
            "clientIdConfigured": status.get("clientIdConfigured"),
            "clientSecretConfigured": status.get("clientSecretConfigured"),
            "tokenFileExists": status.get("tokenFileExists"),
            "accessTokenPresent": status.get("accessTokenPresent"),
            "refreshTokenPresent": status.get("refreshTokenPresent"),
            "reauthorizationRequired": reauthorization_required,
            "accessTokenFresh": access_token_fresh,
            "accessTokenExpiresAt": status.get("accessTokenExpiresAt"),
            "refreshTokenExpiresAt": status.get("refreshTokenExpiresAt"),
            "lastRefreshErrorAt": status.get("lastRefreshErrorAt"),
        },
    }


def _account_api_source_ready() -> bool:
    """Return True when live account sync is already sourced from Schwab."""
    live_sync = load_json_file(LIVE_ACCOUNT_SYNC_FILE) or {}
    return (
        bool(live_sync.get("ok"))
        and live_sync.get("accountDataSource") == "schwab-account-api"
        and live_sync.get("tosRequiredForAccountSync") is False
    )


def _tos_check() -> dict[str, Any]:
    """Check TOS attach-only state without opening or focusing the app."""
    summary = build_tos_visibility_summary()
    account_api_source = _account_api_source_ready()
    level = summary.get("level")
    ok = account_api_source or level in {"visible", "running-not-visible"}
    severity = (
        "pass"
        if account_api_source or level == "visible"
        else "warn"
        if level == "running-not-visible"
        else "fail"
    )
    detail = render_tos_visibility_line(summary)
    if account_api_source:
        detail += " | not required for Schwab account API sync"
    return {
        "name": "tos attach-only",
        "ok": ok,
        "severity": severity,
        "level": level,
        "detail": detail,
    }


def _tos_session_probe_check() -> dict[str, Any]:
    """Check TOS probe freshness only when TOS is required for account sync."""
    if _account_api_source_ready():
        return {
            "name": "TOS session probe",
            "ok": True,
            "severity": "pass",
            "detail": "not required for Schwab account API sync",
        }
    return _artifact_check("TOS session probe", TOS_SESSION_PROBE_FILE, max_age_hours=8)


def build_reporting_preflight(*, max_age_hours: float = 24.0) -> dict[str, Any]:
    """Build the read-only reporting preflight artifact."""
    ensure_dirs()
    checks = [
        _smtp_check(),
        _schwab_check(),
        _tos_check(),
        _doctor_check(),
        _artifact_check("tracker snapshot", TRACKER_SNAPSHOT_FILE, max_age_hours=18),
        _artifact_check("Schwab options tape", SCHWAB_OPTIONS_FILE, max_age_hours=max_age_hours),
        _artifact_check("Schwab daily ops", SCHWAB_DAILY_OPS_FILE, max_age_hours=max_age_hours),
        _artifact_check("Schwab account sync", SCHWAB_ACCOUNT_SYNC_FILE, max_age_hours=8),
        _artifact_check("live account sync", LIVE_ACCOUNT_SYNC_FILE, max_age_hours=8),
        _tos_session_probe_check(),
        _artifact_check("morning brief", MORNING_BRIEF_TEXT_FILE, max_age_hours=30),
        _artifact_check("action pulse", ACTION_PULSE_FILE, max_age_hours=8),
        _artifact_check("deposit plan", DEPOSIT_PLAN_FILE, max_age_hours=30),
        _artifact_check("cash attribution", CASH_ATTRIBUTION_FILE, max_age_hours=30),
        _artifact_check("ticket cap policy", TICKET_CAP_POLICY_FILE, max_age_hours=30),
    ]
    hard_failures = [check for check in checks if check.get("severity") == "fail"]
    warnings = [check for check in checks if check.get("severity") == "warn"]
    payload = {
        "generatedAt": local_now().isoformat(),
        "stage": "reporting-preflight",
        "ok": not hard_failures,
        "verdict": "ready" if not hard_failures else "blocked",
        "hardFailureCount": len(hard_failures),
        "warningCount": len(warnings),
        "checks": checks,
        "freshnessPanel": build_freshness_panel(),
        "tosVisibility": build_tos_visibility_summary(),
        "nextActions": [],
    }
    if hard_failures:
        payload["nextActions"].append("Fix failed preflight checks before trusting or sending next-week reports.")
    if warnings:
        payload["nextActions"].append("Warnings are allowed; reveal TOS only when a supervised desktop capture is needed.")
    if not hard_failures and not warnings:
        payload["nextActions"].append("Reporting preflight is clean; proceed with the normal operating cadence.")
    save_reporting_preflight(payload)
    return payload


def render_reporting_preflight(payload: dict[str, Any]) -> str:
    """Render the reporting preflight into an operator-friendly memo."""
    lines = [
        "Inferno Reporting Preflight",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Hard failures: {payload.get('hardFailureCount')}",
        f"Warnings: {payload.get('warningCount')}",
        f"TOS: {render_tos_visibility_line(payload.get('tosVisibility') or {})}",
        "",
        "Checks:",
    ]
    for check in payload.get("checks") or []:
        lines.append(f"- {check.get('severity')}: {check.get('name')} | {check.get('detail')}")
    lines.extend(["", "Freshness panel:"])
    lines.extend(f"- {item}" for item in render_freshness_lines(payload.get("freshnessPanel") or {}))
    lines.extend(["", "Next actions:"])
    lines.extend(f"- {item}" for item in payload.get("nextActions") or [])
    return "\n".join(lines).rstrip() + "\n"


def save_reporting_preflight(payload: dict[str, Any]) -> None:
    """Persist JSON and text reports for the latest preflight."""
    atomic_write_json(REPORTING_PREFLIGHT_FILE, payload)
    atomic_write_text(REPORTING_PREFLIGHT_TEXT_FILE, render_reporting_preflight(payload))


def parse_args() -> argparse.Namespace:
    """Parse CLI flags."""
    parser = argparse.ArgumentParser(description="Run the read-only Inferno reporting preflight.")
    parser.add_argument("--max-age-hours", type=float, default=24.0)
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    payload = build_reporting_preflight(max_age_hours=args.max_age_hours)
    print(render_reporting_preflight(payload))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
