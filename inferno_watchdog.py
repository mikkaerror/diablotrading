from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from inferno_io import atomic_write_json
from inferno_config import (
    AUTOMATION_ALLOWED_WEEKDAYS,
    AUTOMATION_WINDOW_START,
    SERVICE_HOUR,
    WATCHDOG_WINDOW_END,
    ROOT,
    in_time_window,
    local_now,
    local_today,
)
from inferno_heartbeat import record_heartbeat
from server import LOG_FILE, OPS_STATUS_FILE, WATCHDOG_STATUS_FILE, load_json_file, send_email, smtp_configured


STDOUT_LOG = ROOT / "logs" / "inferno_dawn.stdout.log"
STDERR_LOG = ROOT / "logs" / "inferno_dawn.stderr.log"
DESKTOP_AUTOMATION_FILE = ROOT / "data" / "inferno_desktop_automation.json"


def cycle_reference_day() -> str:
    """Return the service-cycle day the watchdog should expect."""
    now = local_now()
    if now.hour < SERVICE_HOUR:
        return (now.date() - timedelta(days=1)).isoformat()
    return local_today()


def automation_skip_reason(window_start: str, window_end: str) -> str | None:
    now = local_now()
    if now.weekday() not in AUTOMATION_ALLOWED_WEEKDAYS:
        return "Skipping automated watchdog: Saturday automation is disabled."
    if not in_time_window(now, window_start, window_end):
        return (
            "Skipping automated watchdog: "
            f"{now.strftime('%H:%M')} is outside the {window_start}-{window_end} mountain-time window."
        )
    return None


def build_failure_reasons(ops_status: dict | None) -> list[str]:
    if not ops_status:
        return ["no operations status file exists yet"]

    reasons: list[str] = []
    generated_at = str(ops_status.get("generatedAt", ""))
    reference_day = cycle_reference_day()
    if not generated_at.startswith(reference_day):
        reasons.append(f"no dawn-cycle run is recorded for {reference_day}")

    if not ops_status.get("ok", False):
        reasons.append(ops_status.get("error", "dawn cycle marked failed"))
    if not ops_status.get("emailSent", False):
        reasons.append("morning brief email did not send")

    failed_jobs = [entry.get("script") for entry in ops_status.get("updaterScripts", []) if not entry.get("ok")]
    if failed_jobs:
        reasons.append(f"failed jobs: {', '.join(failed_jobs)}")

    return reasons


def should_attempt_rescue(reasons: list[str]) -> bool:
    if not reasons:
        return False
    now = local_now()
    if now.weekday() not in AUTOMATION_ALLOWED_WEEKDAYS:
        return False
    if not in_time_window(now, AUTOMATION_WINDOW_START, WATCHDOG_WINDOW_END):
        return False
    return any(
        reason.startswith("no dawn-cycle run is recorded")
        or reason == "morning brief email did not send"
        for reason in reasons
    )


def attempt_rescue_run() -> dict[str, object]:
    command = [
        sys.executable,
        str(ROOT / "inferno_dawn_pipeline.py"),
        "--automation",
        "--quiet-skip",
        "--window-start",
        AUTOMATION_WINDOW_START,
        "--window-end",
        WATCHDOG_WINDOW_END,
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return {
        "attemptedAt": local_now().isoformat(),
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def tail_lines(path: Path, count: int = 8) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-count:]


def build_diagnostics(ops_status: dict | None) -> list[str]:
    lines = ["Diagnostics:"]
    if ops_status:
        lines.append(f"- Last recorded run: {ops_status.get('generatedAt', 'unknown')}")
        lines.append(f"- Source: {ops_status.get('sourceLabel', 'unknown')}")
        lines.append(f"- Email sent: {ops_status.get('emailSent', 'unknown')}")
        lines.append(f"- Eligible count: {ops_status.get('eligibleCount', 'unknown')}")
        lines.append(f"- Top tickers: {', '.join(ops_status.get('topTickers', [])[:5]) or 'none'}")
        failed_jobs = [entry.get("script") for entry in ops_status.get("updaterScripts", []) if not entry.get("ok")]
        lines.append(f"- Failed jobs: {', '.join(failed_jobs) if failed_jobs else 'none'}")
        repair = ops_status.get("repair") or {}
        if repair:
            lines.append(f"- R repair summary: {json.dumps(repair)}")
        formula_sync = ops_status.get("formulaSync") or {}
        if formula_sync:
            lines.append(f"- Score formula sync: {json.dumps(formula_sync)}")
    else:
        lines.append("- No ops status file is available yet.")

    desktop_status = load_json_file(DESKTOP_AUTOMATION_FILE) or {}
    if desktop_status:
        lines.append(
            "- Desktop automation: "
            f"{desktop_status.get('verdict', 'unknown')} | "
            f"{desktop_status.get('message', 'no message')}"
        )

    stderr_tail = tail_lines(STDERR_LOG)
    stdout_tail = tail_lines(STDOUT_LOG)
    brief_tail = tail_lines(LOG_FILE)

    if stderr_tail:
        lines.append("")
        lines.append("Dawn stderr tail:")
        lines.extend([f"> {line}" for line in stderr_tail])
    if stdout_tail:
        lines.append("")
        lines.append("Dawn stdout tail:")
        lines.extend([f"> {line}" for line in stdout_tail])
    if brief_tail:
        lines.append("")
        lines.append("Recent brief log tail:")
        lines.extend([f"> {line}" for line in brief_tail[-3:]])

    return lines


def send_watchdog_alert(reasons: list[str], ops_status: dict | None) -> tuple[bool, str | None]:
    if not smtp_configured():
        return False, "SMTP is not configured."

    lines = [
        "Inferno Watchdog Alert",
        "",
        "The automated dawn cycle needs attention.",
        "",
        "Reasons:",
    ]
    lines.extend([f"- {reason}" for reason in reasons])

    if ops_status:
        lines.append("")
        lines.extend(build_diagnostics(ops_status))
    else:
        lines.append("")
        lines.extend(build_diagnostics(None))

    payload = {
        "brief": "\n".join(lines),
        "sourceLabel": "Inferno Watchdog",
        "rows": [],
    }
    try:
        return send_email(payload, subject="Inferno Watchdog Alert"), None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def run_watchdog_check(*, send_alerts: bool = True) -> tuple[dict[str, object], int]:
    """Run one watchdog evaluation and persist the latest status artifact."""
    ops_status = load_json_file(OPS_STATUS_FILE)
    reasons = build_failure_reasons(ops_status)
    rescue_result = None

    if should_attempt_rescue(reasons):
        rescue_result = attempt_rescue_run()
        ops_status = load_json_file(OPS_STATUS_FILE)
        reasons = build_failure_reasons(ops_status)

    prior_status = load_json_file(WATCHDOG_STATUS_FILE) or {}
    alert_date = prior_status.get("lastAlertDate")
    alert_sent = False
    alert_error = None

    ok = not reasons
    if reasons and send_alerts and smtp_configured() and alert_date != local_today():
        alert_sent, alert_error = send_watchdog_alert(reasons, ops_status)
        if alert_sent:
            alert_date = local_today()

    status_payload = {
        "checkedAt": datetime.now().astimezone().isoformat(),
        "ok": ok,
        "reasons": reasons,
        "lastAlertDate": alert_date,
        "alertSentThisRun": alert_sent,
        "alertError": alert_error,
        "opsGeneratedAt": ops_status.get("generatedAt") if ops_status else None,
        "rescueAttempted": bool(rescue_result),
        "rescueResult": rescue_result,
    }
    atomic_write_json(WATCHDOG_STATUS_FILE, status_payload)
    record_heartbeat(
        "watchdog",
        status="ok" if ok else "fail",
        summary="watchdog check passed" if ok else "watchdog detected issues",
        detail={
            "reasonCount": len(reasons),
            "rescueAttempted": bool(rescue_result),
            "alertSentThisRun": alert_sent,
        },
    )
    return status_payload, 0 if ok else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the dawn cycle, attempt a rescue run, and alert if the desk is stale.")
    parser.add_argument(
        "--automation",
        action="store_true",
        help="Run only during the configured automation window.",
    )
    parser.add_argument(
        "--quiet-skip",
        action="store_true",
        help="Exit silently when automation mode decides the check should be skipped.",
    )
    parser.add_argument(
        "--no-alert",
        action="store_true",
        help="Update watchdog status without sending an alert email.",
    )
    parser.add_argument("--window-start", default=AUTOMATION_WINDOW_START, help="Local HH:MM start for automation mode")
    parser.add_argument("--window-end", default=WATCHDOG_WINDOW_END, help="Local HH:MM end for automation mode")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.automation:
        try:
            skip_reason = automation_skip_reason(args.window_start, args.window_end)
        except ValueError as exc:
            print(f"Automation window is invalid: {exc}", file=sys.stderr)
            return 1
        if skip_reason:
            if not args.quiet_skip:
                print(skip_reason)
            return 0

    status_payload, exit_code = run_watchdog_check(send_alerts=not args.no_alert)

    if exit_code == 0:
        print("Inferno watchdog check passed.")
        return 0

    print("Inferno watchdog detected issues:")
    for reason in status_payload.get("reasons", []):
        print(f"- {reason}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
