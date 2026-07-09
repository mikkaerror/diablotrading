from __future__ import annotations

"""Central supervisor command for the Inferno desk.

This is the single top-level operator and model entrypoint for the desk's
shared brain. It centralizes three things:

1. refresh the maintenance sweep
2. refresh the shared multi-model command center
3. summarize doctor health into one compact supervisor artifact

It stays read-only with respect to broker authority and never places trades.
"""

import argparse
import json
import plistlib
import re
import subprocess
from pathlib import Path
from typing import Any

from inferno_config import ROOT, default_backtest_root, local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_model_command_center import (
    ACTIVE_MISSIONS_FILE,
    MODEL_COMMAND_CENTER_FILE,
    MODEL_NOTES_FILE,
    add_mission,
    append_note,
    build_command_center,
    onboard_digest,
    parse_tags,
    update_mission,
)
from inferno_ops_maintenance import run_maintenance
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


CENTRAL_COMMAND_FILE = DATA_DIR / "inferno_central_command.json"
CENTRAL_COMMAND_TEXT_FILE = REPORTS_DIR / "central_command_latest.txt"

CONTROL_ENTRYPOINT = "./inferno"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
CODEX_AUTOMATIONS_DIR = Path.home() / ".codex" / "automations"
WEEKDAY_LABELS = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
CONTROL_COMMANDS: tuple[dict[str, str], ...] = (
    {"command": "status", "description": "show the latest command-center state"},
    {"command": "sync", "description": "run the full daily model refresh now"},
    {"command": "today", "description": "open the one-letter operator decision screen"},
    {"command": "doctor", "description": "run the full health check"},
    {"command": "preflight", "description": "check reporting readiness without refreshing data"},
    {"command": "usage", "description": "build the low-context handoff packet"},
    {"command": "oauth", "description": "run Schwab OAuth status, refresh, or restart from one place"},
    {"command": "daily-ops", "description": "refresh the Schwab daily options operations tape"},
    {"command": "action-pulse", "description": "build the tactical action pulse; no email unless --send is passed"},
    {"command": "deposit-plan", "description": "show recurring deposit forecast separate from broker cash"},
    {"command": "cash-ledger", "description": "reconcile broker cash changes without inferring trading profit"},
    {"command": "ticket-cap", "description": "show construction cap, simulated paper budget, and call-options posture"},
    {"command": "capital-check", "description": "run the capital launch check; defaults to deployable cash 0"},
    {"command": "strike-cycle", "description": "run the strike cycle; defaults to deployable cash 0"},
    {"command": "approvals", "description": "show approval queue status only"},
    {"command": "schedule", "description": "show launchd and Codex automation schedules"},
    {"command": "onboard", "description": "print the compact handoff packet"},
)
LAUNCH_AGENT_SCHEDULES: tuple[tuple[str, str], ...] = (
    ("io.diablotrading.inferno-daily-model-refresh", "full sync"),
    ("io.diablotrading.inferno-daily-loop", "digest"),
    ("io.diablotrading.inferno-nightly-optimize", "nightly research"),
)
CODEX_AUTOMATIONS: tuple[str, ...] = (
    "schwab-oauth-early-warning",
    "morning-conviction-brief",
)


def run_command(args: list[str], *, timeout_seconds: int = 300) -> dict[str, Any]:
    """Run a subprocess and capture a structured result."""
    result = subprocess.run(
        args,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
        cwd=str(ROOT),
    )
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": str(result.stdout or "").strip(),
        "stderr": str(result.stderr or "").strip(),
        "command": " ".join(args),
    }


def run_passthrough_command(args: list[str], *, timeout_seconds: int = 3600) -> dict[str, Any]:
    """Run an operator command with inherited stdout/stderr."""
    result = subprocess.run(
        args,
        text=True,
        check=False,
        timeout=timeout_seconds,
        cwd=str(ROOT),
    )
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "command": " ".join(args),
    }


def _hhmm(hour: int | str | None, minute: int | str | None) -> str:
    try:
        return f"{int(hour):02d}:{int(minute):02d}"
    except (TypeError, ValueError):
        return "unknown"


def _format_calendar_intervals(intervals: Any) -> str:
    if isinstance(intervals, dict):
        intervals = [intervals]
    if not isinstance(intervals, list) or not intervals:
        return "not scheduled"
    times = sorted({_hhmm(item.get("Hour"), item.get("Minute")) for item in intervals if isinstance(item, dict)})
    weekdays = sorted(
        {
            int(item["Weekday"])
            for item in intervals
            if isinstance(item, dict) and str(item.get("Weekday", "")).isdigit()
        }
    )
    weekday_label = ",".join(WEEKDAY_LABELS.get(day, str(day)) for day in weekdays) if weekdays else "all days"
    return f"{weekday_label} at {', '.join(times)}"


def _read_launch_agent(label: str, purpose: str) -> dict[str, Any]:
    path = LAUNCH_AGENTS_DIR / f"{label}.plist"
    if not path.exists():
        return {"id": label, "kind": "launchagent", "purpose": purpose, "status": "missing", "path": str(path)}
    try:
        with path.open("rb") as handle:
            payload = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        return {
            "id": label,
            "kind": "launchagent",
            "purpose": purpose,
            "status": "unreadable",
            "path": str(path),
            "error": str(exc),
        }
    return {
        "id": label,
        "kind": "launchagent",
        "purpose": purpose,
        "status": "configured",
        "path": str(path),
        "program": " ".join(str(item) for item in payload.get("ProgramArguments", [])),
        "schedule": _format_calendar_intervals(payload.get("StartCalendarInterval")),
    }


def _toml_string(body: str, key: str) -> str | None:
    match = re.search(rf'^{re.escape(key)}\s*=\s*"([^"]*)"', body, flags=re.MULTILINE)
    return match.group(1) if match else None


def _describe_rrule(rrule: str | None) -> str:
    if not rrule:
        return "not scheduled"
    parts: dict[str, str] = {}
    for chunk in rrule.split(";"):
        if "=" in chunk:
            key, value = chunk.split("=", 1)
            parts[key] = value
    time_label = _hhmm(parts.get("BYHOUR"), parts.get("BYMINUTE"))
    days = parts.get("BYDAY")
    freq = parts.get("FREQ", "").lower()
    if days:
        return f"{days} at {time_label}"
    if freq:
        return f"{freq} at {time_label}"
    return rrule


def _read_codex_automation(automation_id: str) -> dict[str, Any]:
    path = CODEX_AUTOMATIONS_DIR / automation_id / "automation.toml"
    if not path.exists():
        return {"id": automation_id, "kind": "codex-automation", "status": "missing", "path": str(path)}
    try:
        body = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {
            "id": automation_id,
            "kind": "codex-automation",
            "status": "unreadable",
            "path": str(path),
            "error": str(exc),
        }
    rrule = _toml_string(body, "rrule")
    return {
        "id": _toml_string(body, "id") or automation_id,
        "kind": _toml_string(body, "kind") or "codex-automation",
        "name": _toml_string(body, "name") or automation_id,
        "status": _toml_string(body, "status") or "unknown",
        "path": str(path),
        "rrule": rrule,
        "schedule": _describe_rrule(rrule),
    }


def _codex_automation_ids() -> list[str]:
    """Return known and locally discovered Codex automation ids."""
    ids = set(CODEX_AUTOMATIONS)
    if CODEX_AUTOMATIONS_DIR.exists():
        for path in CODEX_AUTOMATIONS_DIR.glob("*/automation.toml"):
            ids.add(path.parent.name)
    return sorted(ids)


def build_schedule_status() -> dict[str, Any]:
    """Return the desk's local automation schedule in one shape."""
    launch_agents = [_read_launch_agent(label, purpose) for label, purpose in LAUNCH_AGENT_SCHEDULES]
    codex_automations = [_read_codex_automation(automation_id) for automation_id in _codex_automation_ids()]
    configured = sum(1 for item in launch_agents + codex_automations if item.get("status") in {"configured", "ACTIVE"})
    return {
        "generatedAt": local_now().isoformat(),
        "entrypoint": CONTROL_ENTRYPOINT,
        "configuredCount": configured,
        "launchAgents": launch_agents,
        "codexAutomations": codex_automations,
    }


def render_schedule_status(payload: dict[str, Any]) -> str:
    """Render launchd and Codex automation state as one operator-facing schedule."""
    lines = [
        "Inferno Schedule",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Entrypoint: {payload.get('entrypoint')}",
        "",
        "LaunchAgents:",
    ]
    for item in payload.get("launchAgents") or []:
        lines.append(
            f"- {item.get('purpose')}: {item.get('status')} | {item.get('schedule')} | {item.get('id')}"
        )
    lines.extend(["", "Codex automations:"])
    for item in payload.get("codexAutomations") or []:
        lines.append(
            f"- {item.get('name')}: {item.get('status')} | {item.get('schedule')} | {item.get('id')}"
        )
    lines.extend(
        [
            "",
            "Unified commands:",
            *[
                f"- {CONTROL_ENTRYPOINT} {item['command']} - {item['description']}"
                for item in CONTROL_COMMANDS
            ],
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def doctor_summary() -> dict[str, Any]:
    """Collect the current doctor verdict without duplicating doctor logic."""
    result = run_command(["python3", "inferno_doctor.py"])
    output = result["stdout"] or result["stderr"]
    final_line = next(
        (line.strip() for line in reversed(output.splitlines()) if line.strip().startswith("Desk status:")),
        "Desk status: unknown",
    )
    verdict = final_line.split("Desk status:", 1)[-1].strip() if "Desk status:" in final_line else "unknown"
    return {
        "ok": result["ok"],
        "verdict": verdict,
        "detail": final_line,
        "command": result["command"],
        "returncode": result["returncode"],
    }


def cached_doctor_summary() -> dict[str, Any]:
    """Read the latest persisted doctor verdict without rerunning doctor."""
    path = REPORTS_DIR / "doctor_latest.txt"
    if not path.exists():
        return {
            "ok": False,
            "verdict": "missing",
            "detail": "Desk status: missing",
            "command": "cached doctor report",
            "returncode": None,
        }
    try:
        body = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {
            "ok": False,
            "verdict": "unreadable",
            "detail": str(exc),
            "command": "cached doctor report",
            "returncode": None,
        }
    final_line = next(
        (line.strip() for line in reversed(body.splitlines()) if line.strip().startswith("Desk status:")),
        "Desk status: unknown",
    )
    verdict = final_line.split("Desk status:", 1)[-1].strip() if "Desk status:" in final_line else "unknown"
    return {
        "ok": verdict == "healthy",
        "verdict": verdict,
        "detail": final_line,
        "command": "cached doctor report",
        "returncode": 0 if verdict == "healthy" else 1,
    }


def cached_maintenance_summary() -> dict[str, Any]:
    """Read the latest persisted ops-maintenance result without rerunning it."""
    report = load_json_file(DATA_DIR / "inferno_ops_maintenance.json") or {}
    return {
        "ok": bool(report.get("ok")),
        "generatedAt": report.get("generatedAt"),
    }


def display_metric(value: Any) -> str:
    """Render missing values without hiding numeric zero."""
    if value is None:
        return "-"
    if isinstance(value, str) and not value.strip():
        return "-"
    return str(value)


def money_metric(value: Any) -> str:
    """Render money-like headline metrics consistently."""
    if value is None:
        return "-"
    try:
        parsed = float(value)
        prefix = "-$" if parsed < 0 else "$"
        return f"{prefix}{abs(parsed):,.2f}"
    except (TypeError, ValueError):
        text = str(value).strip()
        return text if text.startswith("$") else f"${text}" if text else "-"


def render_central_command_text(payload: dict[str, Any]) -> str:
    """Render the central supervisor payload into a compact briefing."""
    maintenance = payload.get("opsMaintenance") or {}
    command_center = payload.get("modelCommandCenter") or {}
    doctor = payload.get("doctor") or {}
    control = payload.get("controlPlane") or {}
    schedules = control.get("schedules") or {}
    metrics = (command_center.get("headlineMetrics") or {})
    lines = [
        "Inferno Central Command",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Supervisor verdict: {payload.get('verdict')}",
        f"Unified entrypoint: {control.get('entrypoint', CONTROL_ENTRYPOINT)}",
        "",
        "Core lanes:",
        f"- Ops maintenance: {maintenance.get('status')}",
        f"- Model command center: {command_center.get('status')} | missions {command_center.get('missionCount', 0)} | notes {command_center.get('noteCount', 0)}",
        f"- Doctor: {doctor.get('verdict')}",
        "",
        "Unified commands:",
        *[
            f"- {control.get('entrypoint', CONTROL_ENTRYPOINT)} {item.get('command')} - {item.get('description')}"
            for item in control.get("commands", [])
        ],
        "",
        "Automation schedule:",
        *[
            f"- {item.get('purpose')}: {item.get('status')} | {item.get('schedule')}"
            for item in schedules.get("launchAgents", [])
        ],
        *[
            f"- {item.get('name')}: {item.get('status')} | {item.get('schedule')}"
            for item in schedules.get("codexAutomations", [])
        ],
        "",
        "Headline metrics:",
        (
            f"- Deposit plan: {money_metric(metrics.get('depositAmountDollars'))} every "
            f"{display_metric(metrics.get('depositIntervalDays'))} day(s) | "
            f"next {display_metric(metrics.get('depositNextDate'))} | "
            f"30d {money_metric(metrics.get('depositForecast30Days'))} planned | "
            f"broker cash {money_metric(metrics.get('accountTotalCash'))}"
        ),
        (
            f"- Cash attribution: {display_metric(metrics.get('cashAttributionVerdict'))} | "
            f"latest delta {money_metric(metrics.get('cashAttributionLatestDelta'))} | "
            f"{display_metric(metrics.get('cashAttributionClassification'))}"
        ),
        (
            f"- Ticket cap policy: {display_metric(metrics.get('ticketCapVerdict'))} | "
            f"construction {money_metric(metrics.get('ticketCapConstructionMinTarget'))}-"
            f"{money_metric(metrics.get('ticketCapConstructionHardCap'))} | "
            f"paper cap {money_metric(metrics.get('ticketCapHardCap'))} | "
            f"live cap {money_metric(metrics.get('ticketCapLiveHardCap'))} | "
            f"call posture {display_metric(metrics.get('ticketCapCallPosture'))}"
        ),
        f"- Live supported: {metrics.get('liveSupported', 0)}",
        f"- Live fragile: {metrics.get('liveFragile', 0)}",
        f"- Paper auto-selected: {metrics.get('paperAutoSelected', 0)}",
        f"- Paper research-selected: {metrics.get('paperResearchSelected', 0)} "
        f"({metrics.get('paperResearchEvents', 0)} distinct event(s))",
        f"- Paper approval-only: {metrics.get('paperApprovalOnly', 0)}",
        f"- Paper construction-watch: {metrics.get('paperConstructionWatch', 0)}",
        f"- Fast-paper backlog: {metrics.get('fastPaperBacklog', 0)}",
        f"- Promotion gap: {metrics.get('paperRemainingForPromotion', 0)}",
        "",
        "Quick files:",
        f"- {MODEL_COMMAND_CENTER_FILE}",
        f"- {ACTIVE_MISSIONS_FILE}",
        f"- {MODEL_NOTES_FILE}",
        "",
        "Recommended next move:",
        f"- {payload.get('recommendedNextMove')}",
    ]
    return "\n".join(lines).rstrip() + "\n"


def save_central_command(payload: dict[str, Any]) -> None:
    """Persist the central supervisor artifact."""
    ensure_dirs()
    atomic_write_json(CENTRAL_COMMAND_FILE, payload)
    atomic_write_text(CENTRAL_COMMAND_TEXT_FILE, render_central_command_text(payload))


def build_central_command(
    *,
    backtest_root: Path,
    sheet_name: str,
    cloud_region: str,
    force_email: bool = False,
    refresh_lanes: bool = True,
) -> dict[str, Any]:
    """Run the central supervisor refresh and persist the result."""
    if refresh_lanes:
        maintenance = run_maintenance(
            backtest_root=backtest_root,
            sheet_name=sheet_name,
            force_email=force_email,
            cloud_region=cloud_region,
        )
        doctor = doctor_summary()
    else:
        maintenance = cached_maintenance_summary()
        doctor = cached_doctor_summary()
    command_center = build_command_center()
    schedule_status = build_schedule_status()

    headline_metrics = command_center.get("headlineMetrics") or {}
    next_actions = command_center.get("nextActions") or []
    payload = {
        "generatedAt": local_now().isoformat(),
        "verdict": "healthy" if maintenance.get("ok") and doctor.get("ok") else "attention",
        "opsMaintenance": {
            "ok": bool(maintenance.get("ok")),
            "status": "healthy" if maintenance.get("ok") else "attention",
            "generatedAt": maintenance.get("generatedAt"),
        },
        "modelCommandCenter": {
            "ok": True,
            "status": "ready",
            "generatedAt": command_center.get("generatedAt"),
            "missionCount": len(command_center.get("activeMissions") or []),
            "noteCount": len(command_center.get("recentNotes") or []),
            "headlineMetrics": headline_metrics,
        },
        "doctor": doctor,
        "controlPlane": {
            "entrypoint": CONTROL_ENTRYPOINT,
            "commands": list(CONTROL_COMMANDS),
            "schedules": schedule_status,
        },
        "recommendedNextMove": next_actions[0] if next_actions else "Review reports/model_command_center_latest.txt",
        "shortcutCommands": [
            'cd "<repo-root>"',
            f"{CONTROL_ENTRYPOINT} status",
            f"{CONTROL_ENTRYPOINT} sync",
            f"{CONTROL_ENTRYPOINT} today",
            f"{CONTROL_ENTRYPOINT} doctor",
            f"{CONTROL_ENTRYPOINT} preflight",
            f"{CONTROL_ENTRYPOINT} usage",
            f"{CONTROL_ENTRYPOINT} oauth",
            f"{CONTROL_ENTRYPOINT} daily-ops",
            f"{CONTROL_ENTRYPOINT} action-pulse",
            f"{CONTROL_ENTRYPOINT} deposit-plan",
            f"{CONTROL_ENTRYPOINT} cash-ledger",
            f"{CONTROL_ENTRYPOINT} ticket-cap",
            f"{CONTROL_ENTRYPOINT} capital-check",
            f"{CONTROL_ENTRYPOINT} strike-cycle",
            f"{CONTROL_ENTRYPOINT} approvals",
            f"{CONTROL_ENTRYPOINT} schedule",
        ],
    }
    save_central_command(payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser for the central supervisor command."""
    parser = argparse.ArgumentParser(description="Central supervisor command for the Inferno desk.")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("run")
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--refresh", action="store_true")
    subparsers.add_parser("onboard")
    subparsers.add_parser("doctor")
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--max-age-hours", type=float)

    usage_parser = subparsers.add_parser("usage")
    usage_parser.add_argument("usage_action", nargs="?", choices=("build", "status"), default="build")
    subparsers.add_parser("schedule")
    subparsers.add_parser("approvals")

    oauth_parser = subparsers.add_parser("oauth")
    oauth_parser.add_argument("oauth_action", nargs="?", default="status", choices=("auth-url", "exchange", "restart", "refresh", "ensure", "status"))
    oauth_parser.add_argument("--code")

    daily_ops_parser = subparsers.add_parser("daily-ops")
    daily_ops_parser.add_argument("symbols", nargs="*")
    daily_ops_parser.add_argument("--fixture")
    daily_ops_parser.add_argument("--skip-refresh", action="store_true")
    daily_ops_parser.add_argument("--json", action="store_true")
    daily_ops_parser.add_argument("--quiet", action="store_true")

    action_pulse_parser = subparsers.add_parser("action-pulse")
    action_pulse_parser.add_argument("action_pulse_action", nargs="?", choices=("run", "status"))
    action_pulse_parser.add_argument("--phase", choices=("manual", "open", "preclose"), default="manual")
    action_pulse_parser.add_argument("--deployable-cash", default="0")
    action_pulse_parser.add_argument("--send", action="store_true")
    action_pulse_parser.add_argument("--force-send", action="store_true")
    action_pulse_parser.add_argument("--skip-maintenance", action="store_true")
    action_pulse_parser.add_argument("--refresh-live-sync", action="store_true")
    action_pulse_parser.add_argument("--fast", action="store_true")
    action_pulse_parser.add_argument("--full", action="store_true")

    deposit_plan_parser = subparsers.add_parser("deposit-plan")
    deposit_plan_parser.add_argument("deposit_action", nargs="?", choices=("run", "status", "configure"), default="run")
    deposit_plan_parser.add_argument("--amount", type=float, default=250.0)
    deposit_plan_parser.add_argument("--interval-days", type=int, default=14)
    deposit_plan_parser.add_argument("--first-date")

    cash_ledger_parser = subparsers.add_parser("cash-ledger")
    cash_ledger_parser.add_argument("cash_ledger_action", nargs="?", choices=("run", "status"), default="run")

    ticket_cap_parser = subparsers.add_parser("ticket-cap")
    ticket_cap_parser.add_argument("ticket_cap_action", nargs="?", choices=("run", "status", "configure"), default="run")
    ticket_cap_parser.add_argument("--min-ticket", type=float)
    ticket_cap_parser.add_argument("--max-ticket", type=float)
    ticket_cap_parser.add_argument("--target-ticket", type=float)
    ticket_cap_parser.add_argument(
        "--call-posture",
        choices=("aggressive-defined-risk", "call-debit-biased", "balanced-defined-risk"),
    )

    capital_check_parser = subparsers.add_parser("capital-check")
    capital_check_parser.add_argument("--deployable-cash", default="0")
    capital_check_parser.add_argument("--for-date")
    capital_check_parser.add_argument("--refresh-live-sync", action="store_true")

    strike_cycle_parser = subparsers.add_parser("strike-cycle")
    strike_cycle_parser.add_argument("--deployable-cash", default="0")
    strike_cycle_parser.add_argument("--limit")
    strike_cycle_parser.add_argument("--email", action="store_true")

    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("--skip-tracker", action="store_true")

    today_parser = subparsers.add_parser("today")
    today_parser.add_argument("--quiet", action="store_true")

    note_parser = subparsers.add_parser("note")
    note_parser.add_argument("--author", required=True)
    note_parser.add_argument("--title", required=True)
    note_parser.add_argument("--body", required=True)
    note_parser.add_argument("--priority", default="normal")
    note_parser.add_argument("--tags", default="")

    mission_add = subparsers.add_parser("mission-add")
    mission_add.add_argument("--title", required=True)
    mission_add.add_argument("--body", required=True)
    mission_add.add_argument("--owner", default="shared")
    mission_add.add_argument("--status", default="pending")
    mission_add.add_argument("--priority", default="normal")
    mission_add.add_argument("--tags", default="")

    mission_update = subparsers.add_parser("mission-update")
    mission_update.add_argument("--id", required=True)
    mission_update.add_argument("--title")
    mission_update.add_argument("--body")
    mission_update.add_argument("--owner")
    mission_update.add_argument("--status")
    mission_update.add_argument("--priority")
    mission_update.add_argument("--tags")

    parser.add_argument("--backtest-root", default=str(default_backtest_root()))
    parser.add_argument("--sheet-name", default="Earnings Tracker")
    parser.add_argument("--cloud-region", default="us-central1")
    parser.add_argument("--force-email", action="store_true")
    return parser


def main() -> int:
    """Run the central command CLI."""
    parser = build_parser()
    args = parser.parse_args()
    command = args.command or "run"

    if command == "run":
        payload = build_central_command(
            backtest_root=Path(args.backtest_root).expanduser().resolve(),
            sheet_name=args.sheet_name,
            cloud_region=args.cloud_region,
            force_email=args.force_email,
        )
        print(render_central_command_text(payload))
        return 0 if payload.get("verdict") == "healthy" else 1

    if command == "status":
        payload = build_central_command(
            backtest_root=Path(args.backtest_root).expanduser().resolve(),
            sheet_name=args.sheet_name,
            cloud_region=args.cloud_region,
            force_email=args.force_email,
            refresh_lanes=args.refresh,
        )
        print(render_central_command_text(payload))
        return 0

    if command == "onboard":
        payload = build_command_center()
        print(onboard_digest(payload))
        return 0

    if command == "schedule":
        print(render_schedule_status(build_schedule_status()))
        return 0

    if command == "doctor":
        result = run_passthrough_command(["python3", "inferno_doctor.py"], timeout_seconds=600)
        return int(result["returncode"])

    if command == "preflight":
        command_args = ["python3", "inferno_reporting_preflight.py"]
        if args.max_age_hours is not None:
            command_args.extend(["--max-age-hours", str(args.max_age_hours)])
        result = run_passthrough_command(command_args, timeout_seconds=600)
        return int(result["returncode"])

    if command == "usage":
        command_args = ["python3", "inferno_usage_optimizer.py"]
        if args.usage_action:
            command_args.append(args.usage_action)
        result = run_passthrough_command(command_args, timeout_seconds=600)
        return int(result["returncode"])

    if command == "oauth":
        oauth_args = [args.oauth_action]
        if args.code:
            oauth_args.extend(["--code", args.code])
        result = run_passthrough_command(["python3", "inferno_schwab_oauth.py", *oauth_args], timeout_seconds=900)
        return int(result["returncode"])

    if command == "daily-ops":
        command_args = ["./run_inferno_schwab_daily_ops.sh"]
        if args.fixture:
            command_args.extend(["--fixture", args.fixture])
        if args.skip_refresh:
            command_args.append("--skip-refresh")
        if args.json:
            command_args.append("--json")
        if args.quiet:
            command_args.append("--quiet")
        command_args.extend(args.symbols or [])
        result = run_passthrough_command(command_args, timeout_seconds=1800)
        return int(result["returncode"])

    if command == "action-pulse":
        command_args = ["./run_inferno_action_pulse.sh"]
        if args.action_pulse_action:
            command_args.append(args.action_pulse_action)
        command_args.extend(["--phase", args.phase, "--deployable-cash", str(args.deployable_cash)])
        if args.send:
            command_args.append("--send")
        if args.force_send:
            command_args.append("--force-send")
        if args.skip_maintenance:
            command_args.append("--skip-maintenance")
        if args.refresh_live_sync:
            command_args.append("--refresh-live-sync")
        if args.fast or not args.full:
            command_args.append("--fast")
        result = run_passthrough_command(command_args, timeout_seconds=1800)
        return int(result["returncode"])

    if command == "deposit-plan":
        command_args = ["python3", "inferno_deposit_plan.py", args.deposit_action]
        if args.deposit_action == "configure":
            command_args.extend(["--amount", str(args.amount), "--interval-days", str(args.interval_days)])
            if args.first_date:
                command_args.extend(["--first-date", args.first_date])
        result = run_passthrough_command(command_args, timeout_seconds=600)
        return int(result["returncode"])

    if command == "cash-ledger":
        result = run_passthrough_command(
            ["python3", "inferno_cash_attribution.py", args.cash_ledger_action],
            timeout_seconds=600,
        )
        return int(result["returncode"])

    if command == "ticket-cap":
        command_args = ["python3", "inferno_ticket_cap_policy.py", args.ticket_cap_action]
        if args.ticket_cap_action == "configure":
            if args.min_ticket is not None:
                command_args.extend(["--min-ticket", str(args.min_ticket)])
            if args.max_ticket is not None:
                command_args.extend(["--max-ticket", str(args.max_ticket)])
            if args.target_ticket is not None:
                command_args.extend(["--target-ticket", str(args.target_ticket)])
            if args.call_posture is not None:
                command_args.extend(["--call-posture", args.call_posture])
        result = run_passthrough_command(command_args, timeout_seconds=600)
        return int(result["returncode"])

    if command == "capital-check":
        capital_check_args = ["--deployable-cash", str(args.deployable_cash)]
        if args.for_date:
            capital_check_args.extend(["--for-date", args.for_date])
        if args.refresh_live_sync:
            capital_check_args.append("--refresh-live-sync")
        result = run_passthrough_command(
            ["./run_inferno_capital_launch_check.sh", *capital_check_args],
            timeout_seconds=1800,
        )
        return int(result["returncode"])

    if command == "strike-cycle":
        strike_cycle_args = ["--deployable-cash", str(args.deployable_cash)]
        if args.limit:
            strike_cycle_args.extend(["--limit", str(args.limit)])
        if args.email:
            strike_cycle_args.append("--email")
        result = run_passthrough_command(["./run_inferno_strike_cycle.sh", *strike_cycle_args], timeout_seconds=1800)
        return int(result["returncode"])

    if command == "approvals":
        result = run_passthrough_command(["python3", "inferno_approval_queue.py", "status"], timeout_seconds=600)
        return int(result["returncode"])

    if command == "today":
        command_args = ["python3", "today.py"]
        if args.quiet:
            command_args.append("--quiet")
        result = run_passthrough_command(command_args, timeout_seconds=600)
        return int(result["returncode"])

    if command == "sync":
        command_args = ["./run_inferno_daily_model_refresh.sh"]
        if args.skip_tracker:
            command_args.append("--skip-tracker")
        result = run_passthrough_command(command_args, timeout_seconds=7200)
        payload = build_central_command(
            backtest_root=Path(args.backtest_root).expanduser().resolve(),
            sheet_name=args.sheet_name,
            cloud_region=args.cloud_region,
            force_email=args.force_email,
            refresh_lanes=False,
        )
        print(render_central_command_text(payload))
        return int(result["returncode"])

    if command == "note":
        note = append_note(
            author=args.author,
            title=args.title,
            body=args.body,
            priority=args.priority,
            tags=parse_tags(args.tags),
        )
        payload = build_central_command(
            backtest_root=Path(args.backtest_root).expanduser().resolve(),
            sheet_name=args.sheet_name,
            cloud_region=args.cloud_region,
            force_email=args.force_email,
            refresh_lanes=False,
        )
        print(json.dumps({"note": note, "centralCommandGeneratedAt": payload.get("generatedAt")}, indent=2))
        return 0

    if command == "mission-add":
        mission = add_mission(
            title=args.title,
            body=args.body,
            owner=args.owner,
            status=args.status,
            priority=args.priority,
            tags=parse_tags(args.tags),
        )
        payload = build_central_command(
            backtest_root=Path(args.backtest_root).expanduser().resolve(),
            sheet_name=args.sheet_name,
            cloud_region=args.cloud_region,
            force_email=args.force_email,
            refresh_lanes=False,
        )
        print(json.dumps({"mission": mission, "centralCommandGeneratedAt": payload.get("generatedAt")}, indent=2))
        return 0

    if command == "mission-update":
        mission = update_mission(
            args.id,
            title=args.title,
            body=args.body,
            owner=args.owner,
            status=args.status,
            priority=args.priority,
            tags=parse_tags(args.tags) if args.tags is not None else None,
        )
        payload = build_central_command(
            backtest_root=Path(args.backtest_root).expanduser().resolve(),
            sheet_name=args.sheet_name,
            cloud_region=args.cloud_region,
            force_email=args.force_email,
            refresh_lanes=False,
        )
        print(json.dumps({"mission": mission, "centralCommandGeneratedAt": payload.get("generatedAt")}, indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
