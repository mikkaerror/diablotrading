from __future__ import annotations

"""Read-only reporting preflight for the next-week Inferno operating cadence.

The preflight answers one boring question before the desk sends or trusts a
brief: are the reporting inputs fresh enough, are SMTP/Schwab configured, is
TOS in an attach-only safe state, and did the doctor recently report healthy or
only advisory attention items? When it is blocked, it also produces an ordered
recovery plan that separates a human-only broker reauthorization from the
read-only refreshes that must wait for it.

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
    """Return True when fresh Schwab account truth removes the TOS dependency."""
    live_sync = load_json_file(LIVE_ACCOUNT_SYNC_FILE) or {}
    live_age = age_hours(artifact_generated_at(LIVE_ACCOUNT_SYNC_FILE))
    live_ready = (
        bool(live_sync.get("ok"))
        and live_sync.get("accountDataSource") == "schwab-account-api"
        and live_sync.get("tosRequiredForAccountSync") is False
        and live_age is not None
        and live_age <= 8
    )
    schwab_sync = load_json_file(SCHWAB_ACCOUNT_SYNC_FILE) or {}
    schwab_age = age_hours(artifact_generated_at(SCHWAB_ACCOUNT_SYNC_FILE))
    schwab_ready = (
        bool(schwab_sync.get("ok"))
        and schwab_sync.get("verdict") == "healthy"
        and bool(schwab_sync.get("brokerReadOnly"))
        and schwab_sync.get("orderEndpointsAllowed") is False
        and schwab_age is not None
        and schwab_age <= 8
    )
    return live_ready or schwab_ready


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


def _live_account_sync_check() -> dict[str, Any]:
    """Check live account sync only when Schwab account truth is not fresh enough."""
    if _account_api_source_ready():
        return {
            "name": "live account sync",
            "ok": True,
            "severity": "pass",
            "detail": "covered by fresh Schwab account API sync",
        }
    return _artifact_check("live account sync", LIVE_ACCOUNT_SYNC_FILE, max_age_hours=8)


def build_recovery_plan(checks: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify failed preflight checks without attempting any remediation.

    The plan intentionally never invokes OAuth, opens thinkorswim, refreshes
    data, stages paper tickets, or changes authority. Its job is to prevent a
    stale quote tape from looking like a reason to bypass the human-owned OAuth
    step that safely unlocks the ordinary read-only refresh path.
    """
    failed = [check for check in checks if check.get("severity") == "fail"]
    by_name = {str(check.get("name")): check for check in failed}
    token_detail = (by_name.get("schwab token") or {}).get("detail")
    reauthorization_required = isinstance(token_detail, dict) and bool(
        token_detail.get("reauthorizationRequired")
    )
    steps: list[dict[str, Any]] = []

    if reauthorization_required:
        steps.append(
            {
                "id": "schwab-reauthorization",
                "kind": "human-required",
                "status": "blocked",
                "action": (
                    "Account owner: run ./inferno oauth restart and complete the broker authorization flow. "
                    "Do not submit orders or change authority."
                ),
                "reason": "The configured Schwab refresh token can no longer refresh the read-only tape.",
                "verify": "After the owner completes reauthorization, run ./inferno daily-ops, then ./inferno preflight.",
            }
        )
    elif "schwab token" in by_name:
        steps.append(
            {
                "id": "schwab-oauth-configuration",
                "kind": "human-required",
                "status": "blocked",
                "action": "Account owner: inspect the local Schwab OAuth configuration without exposing or replacing secrets.",
                "reason": "The read-only Schwab OAuth prerequisites are incomplete or invalid.",
                "verify": "Run ./inferno oauth status, then ./inferno preflight after the configuration is repaired.",
            }
        )

    deferred_artifacts = {
        "Schwab options tape",
        "Schwab daily ops",
        "Schwab account sync",
        "live account sync",
    }
    for name in sorted(deferred_artifacts.intersection(by_name)):
        if reauthorization_required:
            steps.append(
                {
                    "id": f"deferred-{name.lower().replace(' ', '-')}",
                    "kind": "deferred-read-only",
                    "status": "waiting-on-reauthorization",
                    "action": f"Do not force-refresh {name}; resume its normal read-only refresh only after Schwab reauthorization succeeds.",
                    "reason": "Refreshing now would repeat the known authentication failure and cannot improve evidence freshness.",
                    "verify": "Confirm the artifact is fresh in ./inferno preflight.",
                }
            )
        else:
            steps.append(
                {
                    "id": f"refresh-{name.lower().replace(' ', '-')}",
                    "kind": "read-only-follow-up",
                    "status": "ready-after-prerequisites",
                    "action": f"Run the normal read-only refresh that produces {name}.",
                    "reason": "The artifact is absent or stale after its prerequisites passed.",
                    "verify": "Confirm the artifact is fresh in ./inferno preflight.",
                }
            )

    tos_check = by_name.get("tos attach-only")
    if tos_check:
        steps.append(
            {
                "id": "tos-attach-only",
                "kind": "supervised-desktop-only",
                "status": "blocked",
                "action": (
                    "Do not launch a new thinkorswim window. If TOS evidence is truly needed, use only the already-open "
                    "window in a supervised session and then rerun ./inferno preflight."
                ),
                "reason": str(tos_check.get("detail") or "The attach-only TOS check did not pass."),
                "verify": "The preflight must report an attach-only-safe TOS state; no ticket or broker action is implied.",
            }
        )

    handled = {"schwab token", *deferred_artifacts, "tos attach-only"}
    for name in sorted(set(by_name).difference(handled)):
        check = by_name[name]
        steps.append(
            {
                "id": f"inspect-{name.lower().replace(' ', '-')}",
                "kind": "inspect",
                "status": "blocked",
                "action": f"Inspect the failed {name} check before changing any configuration or workflow.",
                "reason": str(check.get("detail") or "The preflight check failed."),
                "verify": "Rerun ./inferno preflight and confirm this check passes.",
            }
        )

    if not steps:
        return {
            "verdict": "no-recovery-needed",
            "humanActionRequired": False,
            "authorityChanged": False,
            "brokerSubmitAllowed": False,
            "steps": [],
        }
    return {
        "verdict": "human-reauthorization-required" if reauthorization_required else "recovery-actions-required",
        "humanActionRequired": any(step["kind"] == "human-required" for step in steps),
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "steps": steps,
    }


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
        _live_account_sync_check(),
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
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "ok": not hard_failures,
        "verdict": "ready" if not hard_failures else "blocked",
        "hardFailureCount": len(hard_failures),
        "warningCount": len(warnings),
        "checks": checks,
        "freshnessPanel": build_freshness_panel(),
        "tosVisibility": build_tos_visibility_summary(),
        "nextActions": [],
    }
    payload["recoveryPlan"] = build_recovery_plan(checks)
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
    recovery = payload.get("recoveryPlan") or {}
    lines.extend(
        [
            "",
            "Recovery plan:",
            f"- Verdict: {recovery.get('verdict', 'unavailable')}",
            "- Safety: diagnostic only; this plan never refreshes credentials, launches TOS, stages tickets, or submits orders.",
        ]
    )
    if not recovery.get("steps"):
        lines.append("- No failed check requires a recovery action.")
    for step in recovery.get("steps") or []:
        lines.extend(
            [
                f"- [{step.get('kind')}] {step.get('action')}",
                f"  Reason: {step.get('reason')}",
                f"  Verify: {step.get('verify')}",
            ]
        )
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
