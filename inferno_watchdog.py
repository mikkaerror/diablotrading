from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from server import LOG_FILE, OPS_STATUS_FILE, ROOT, WATCHDOG_STATUS_FILE, load_json_file, send_email, smtp_configured


STDOUT_LOG = ROOT / "logs" / "inferno_dawn.stdout.log"
STDERR_LOG = ROOT / "logs" / "inferno_dawn.stderr.log"


def local_today() -> str:
    return datetime.now().astimezone().date().isoformat()


def build_failure_reasons(ops_status: dict | None) -> list[str]:
    if not ops_status:
        return ["no operations status file exists yet"]

    reasons: list[str] = []
    generated_at = str(ops_status.get("generatedAt", ""))
    if not generated_at.startswith(local_today()):
        reasons.append(f"no dawn-cycle run is recorded for {local_today()}")

    if not ops_status.get("ok", False):
        reasons.append(ops_status.get("error", "dawn cycle marked failed"))
    if not ops_status.get("emailSent", False):
        reasons.append("morning brief email did not send")

    failed_jobs = [entry.get("script") for entry in ops_status.get("updaterScripts", []) if not entry.get("ok")]
    if failed_jobs:
        reasons.append(f"failed jobs: {', '.join(failed_jobs)}")

    return reasons


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


def send_watchdog_alert(reasons: list[str], ops_status: dict | None) -> bool:
    if not smtp_configured():
        return False

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
    return send_email(payload, subject="Inferno Watchdog Alert")


def main() -> int:
    ops_status = load_json_file(OPS_STATUS_FILE)
    reasons = build_failure_reasons(ops_status)

    prior_status = load_json_file(WATCHDOG_STATUS_FILE) or {}
    alert_date = prior_status.get("lastAlertDate")
    alert_sent = False

    ok = not reasons
    if reasons and smtp_configured() and alert_date != local_today():
        alert_sent = send_watchdog_alert(reasons, ops_status)
        if alert_sent:
            alert_date = local_today()

    status_payload = {
        "checkedAt": datetime.now().astimezone().isoformat(),
        "ok": ok,
        "reasons": reasons,
        "lastAlertDate": alert_date,
        "alertSentThisRun": alert_sent,
        "opsGeneratedAt": ops_status.get("generatedAt") if ops_status else None,
    }
    WATCHDOG_STATUS_FILE.write_text(json.dumps(status_payload, indent=2), encoding="utf-8")

    if ok:
        print("Inferno watchdog check passed.")
        return 0

    print("Inferno watchdog detected issues:")
    for reason in reasons:
        print(f"- {reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
