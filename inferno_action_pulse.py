from __future__ import annotations

"""Twice-daily action pulse for the Inferno desk.

The morning brief tells the operator what the desk saw at dawn. This pulse is
the easy-access tactical layer: one email near the open and one before the
close that says whether anything needs attention now.

Safety contract:
- read-only diagnostics only
- no approval mutation beyond the existing ops maintenance inbox sweep
- no broker submit, no order routing, no authority promotion
- deduplicates one sent email per phase/day unless forced by the operator
"""

import argparse
import html
import json
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from inferno_capital_launch_check import build_capital_launch_check
from inferno_config import DEFAULT_SHEET_NAME, default_backtest_root, local_now, local_today
from inferno_daily_loop import build_daily_loop, save_daily_loop
from inferno_io import atomic_write_json, atomic_write_text
from inferno_ops_maintenance import run_maintenance
from server import (
    DATA_DIR,
    REPORTS_DIR,
    SMTP_ENV_FILE,
    ensure_dirs,
    load_env_file,
    load_json_file,
    smtp_configured,
    smtp_settings,
)


ACTION_PULSE_FILE = DATA_DIR / "inferno_action_pulse.json"
ACTION_PULSE_TEXT_FILE = REPORTS_DIR / "action_pulse_latest.txt"
ACTION_PULSE_STATE_FILE = DATA_DIR / "inferno_action_pulse_state.json"
SCHWAB_DAILY_OPS_FILE = DATA_DIR / "inferno_schwab_daily_ops.json"

PHASE_LABELS = {
    "open": "Open Watch",
    "preclose": "Pre-Close Watch",
    "manual": "Manual Check",
}


def text(value: Any, default: str = "") -> str:
    """Normalize loose artifact values into concise report text."""
    if value is None:
        return default
    rendered = str(value).strip()
    return rendered or default


def number(value: Any, default: float = 0.0) -> float:
    """Parse a numeric value from JSON/report strings."""
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = text(value).replace("$", "").replace(",", "").replace("%", "")
    try:
        return float(cleaned)
    except ValueError:
        return default


def command_cash_arg(value: Any) -> str:
    """Render deployable cash for copy/paste-safe operator commands."""
    cash = number(value)
    if cash.is_integer():
        return str(int(cash))
    return f"{cash:.2f}"


def load_state() -> dict[str, Any]:
    """Load the send-dedupe state file."""
    if not ACTION_PULSE_STATE_FILE.exists():
        return {"sentByKey": {}}
    try:
        payload = json.loads(ACTION_PULSE_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"sentByKey": {}}
    if not isinstance(payload, dict):
        return {"sentByKey": {}}
    payload.setdefault("sentByKey", {})
    return payload


def save_state(payload: dict[str, Any]) -> None:
    """Persist the send-dedupe state file."""
    ensure_dirs()
    atomic_write_json(ACTION_PULSE_STATE_FILE, payload)


def sent_key(phase: str, day: str | None = None) -> str:
    """Return the dedupe key for one phase/day."""
    return f"{day or local_today()}:{phase}"


def phase_label(phase: str) -> str:
    """Return a presentation label for the action-pulse phase."""
    return PHASE_LABELS.get(phase, phase.title())


def summarize_decisions(launch: dict[str, Any]) -> list[str]:
    """Summarize the live-book decisions that matter right now."""
    decisions = ((launch.get("liveBook") or {}).get("requiredHumanDecisions") or [])
    if not decisions:
        return ["No live-book human decision is blocking the launch check."]
    lines: list[str] = []
    for item in decisions[:6]:
        lines.append(
            f"{item.get('symbol')}: {item.get('unlockEffect')} | "
            f"heat={item.get('reviewHeat')} | days={item.get('daysUntilEarnings')} | "
            f"support cushion={item.get('supportCushionPct')}% | "
            f"resistance room={item.get('resistanceHeadroomPct')}%"
        )
    return lines


def summarize_warnings(launch: dict[str, Any]) -> list[str]:
    """Return the most actionable blocker/warning lines from launch artifacts."""
    readiness = launch.get("capitalReadiness") or {}
    warnings = list(readiness.get("blockers") or []) + list(readiness.get("warnings") or [])
    risk = launch.get("riskGateAudit") or {}
    warning_gates = [row.get("name") for row in risk.get("warningGates") or [] if row.get("name")]
    if warning_gates:
        warnings.append("Risk-gate warnings: " + ", ".join(text(name) for name in warning_gates))
    return [text(item) for item in warnings[:8] if text(item)] or ["No blockers or warnings were reported."]


def summarize_schwab_daily_ops(report: dict[str, Any]) -> dict[str, Any]:
    """Compress the Schwab options tape for twice-daily operator emails."""
    rows = report.get("rows") or []
    tradable = [row.get("symbol") for row in rows if row.get("lane") == "tradable-research"]
    paper_ready = [row.get("symbol") for row in rows if row.get("lane") == "paper-ready"]
    avoid = [row.get("symbol") for row in rows if row.get("lane") == "avoid-chain"]
    lines = []
    for row in rows[:6]:
        move = row.get("atmImpliedMovePct")
        move_text = f"{number(move) * 100:.2f}%" if move is not None else "-"
        lines.append(
            f"{row.get('symbol')}: {row.get('lane')} | "
            f"Q {number(row.get('quoteQualityScore')):.0f}/{text(row.get('quoteQualityLabel'), 'unknown')} | "
            f"spread {text(row.get('atmSpreadQuality'), 'unknown')} | "
            f"liq {number(row.get('atmLiquidityScore')):.0f} | move {move_text}"
        )
    return {
        "available": bool(report),
        "generatedAt": report.get("generatedAt"),
        "sourceStatus": report.get("sourceStatus"),
        "laneCounts": report.get("laneCounts") or {},
        "tradableResearch": [ticker for ticker in tradable if ticker],
        "paperReady": [ticker for ticker in paper_ready if ticker],
        "avoidChain": [ticker for ticker in avoid if ticker],
        "summaryLines": lines,
    }


def build_action_pulse(
    *,
    phase: str,
    deployable_cash: float = 1000.0,
    skip_maintenance: bool = False,
    refresh_live_sync: bool = False,
) -> dict[str, Any]:
    """Build the action pulse payload and supporting reports."""
    ensure_dirs()
    load_env_file(SMTP_ENV_FILE)

    maintenance: dict[str, Any] | None = None
    if not skip_maintenance:
        maintenance = run_maintenance(
            backtest_root=default_backtest_root(),
            sheet_name=DEFAULT_SHEET_NAME,
            force_email=False,
        )

    daily_loop = build_daily_loop()
    save_daily_loop(daily_loop)

    launch = build_capital_launch_check(
        deployable_cash=deployable_cash,
        refresh_live_sync=refresh_live_sync,
    )
    schwab_daily_ops = summarize_schwab_daily_ops(load_json_file(SCHWAB_DAILY_OPS_FILE) or {})
    cash_arg = command_cash_arg(deployable_cash)

    payload = {
        "generatedAt": local_now().isoformat(),
        "stage": "action-pulse",
        "phase": phase,
        "phaseLabel": phase_label(phase),
        "diagnosticOnly": True,
        "deployableCash": deployable_cash,
        "verdict": launch.get("verdict"),
        "message": launch.get("message"),
        "manualDeploymentAllowed": launch.get("manualDeploymentAllowed"),
        "autoLiveAllowed": False,
        "maintenanceStatus": (maintenance or {}).get("ok") if maintenance is not None else "skipped",
        "dailyLoop": {
            "deskVerdict": daily_loop.get("deskVerdict"),
            "decideTodayTickers": daily_loop.get("decideTodayTickers") or [],
            "failedCount": daily_loop.get("failedCount"),
            "okCount": daily_loop.get("okCount"),
            "stepCount": daily_loop.get("stepCount"),
            "narrative": daily_loop.get("narrative"),
        },
        "capitalLaunch": launch,
        "schwabDailyOps": schwab_daily_ops,
        "decisionSummary": summarize_decisions(launch),
        "warningSummary": summarize_warnings(launch),
        "operatorCommands": [
            "./run_inferno_schwab_daily_ops.sh",
            f'./run_inferno_action_pulse.sh --phase manual --deployable-cash {cash_arg} --send --force-send',
            f'./run_inferno_capital_launch_check.sh --deployable-cash {cash_arg}',
            f'./run_inferno_strike_cycle.sh --deployable-cash {cash_arg}',
            'python3 inferno_approval_queue.py status',
        ],
        "operatorRule": "If this says blocked, do not deploy fresh capital. Real orders still require explicit final confirmation.",
    }
    save_action_pulse(payload)
    return payload


def subject_for_pulse(payload: dict[str, Any]) -> str:
    """Build the concise email subject."""
    phase = text(payload.get("phaseLabel"), "Action Pulse").upper()
    verdict = text(payload.get("verdict"), "unknown").upper()
    return f"[Inferno Action Pulse] {phase}: {verdict}"


def render_action_pulse(payload: dict[str, Any]) -> str:
    """Render the pulse as an email-friendly plain-text memo."""
    launch = payload.get("capitalLaunch") or {}
    guardrails = ((launch.get("capitalReadiness") or {}).get("guardrails") or {})
    daily = payload.get("dailyLoop") or {}
    lines = [
        "Inferno Action Pulse",
        "=" * 21,
        f"Generated: {payload.get('generatedAt')}",
        f"Phase: {payload.get('phaseLabel')}",
        f"Verdict: {payload.get('verdict')}",
        f"Message: {payload.get('message')}",
        "",
        "Safety locks",
        f"- Manual deployment allowed: {payload.get('manualDeploymentAllowed')}",
        f"- Auto live trading allowed: {payload.get('autoLiveAllowed')}",
        "",
        "Capital guardrails",
        f"- Deployable cash: ${number(payload.get('deployableCash')):,.2f}",
        f"- Max options risk: ${number(guardrails.get('maxOptionsRisk')):,.2f}",
        f"- Max starter ticket: ${number(guardrails.get('maxStarterTicket')):,.2f}",
        f"- Max long-term buy: ${number(guardrails.get('maxLongTermBuy')):,.2f}",
        f"- Reserve cash: ${number(guardrails.get('reserveCash')):,.2f}",
        "",
        "Act-now queue",
    ]
    decide = daily.get("decideTodayTickers") or []
    lines.extend([f"- {ticker}" for ticker in decide] or ["- none"])
    schwab = payload.get("schwabDailyOps") or {}
    lines.extend(["", "Schwab options tape"])
    if schwab.get("available"):
        counts = schwab.get("laneCounts") or {}
        lines.append(
            "- Lanes: "
            f"tradable={counts.get('tradable-research', 0)} | "
            f"paper={counts.get('paper-ready', 0)} | "
            f"manual={counts.get('manual-review', 0)} | "
            f"avoid={counts.get('avoid-chain', 0)}"
        )
        lines.extend(f"- {item}" for item in schwab.get("summaryLines") or ["No Schwab rows summarized."])
    else:
        lines.append("- No Schwab daily ops report yet. Run ./run_inferno_schwab_daily_ops.sh.")
    lines.extend(["", "Human decisions"])
    lines.extend(f"- {item}" for item in payload.get("decisionSummary") or [])
    lines.extend(["", "Warnings / blockers"])
    lines.extend(f"- {item}" for item in payload.get("warningSummary") or [])
    narrative = text(daily.get("narrative"))
    if narrative:
        lines.extend(["", "Desk narrative", narrative])
    lines.extend(["", "Operator commands"])
    lines.extend(f"- {item}" for item in payload.get("operatorCommands") or [])
    lines.extend(["", f"Rule: {payload.get('operatorRule')}"])
    return "\n".join(lines).rstrip() + "\n"


def render_action_pulse_html(payload: dict[str, Any]) -> str:
    """Render a lightweight HTML email version of the pulse."""
    plain = html.escape(render_action_pulse(payload))
    verdict = html.escape(text(payload.get("verdict"), "unknown"))
    return f"""<!doctype html>
<html lang="en">
  <body style="background:#120707;color:#f6e5d1;font-family:Georgia,serif;padding:24px;">
    <h1 style="color:#ffb074;margin:0 0 8px;">Inferno Action Pulse</h1>
    <p style="margin:0 0 16px;color:#d6b399;">Verdict: <strong>{verdict}</strong></p>
    <pre style="white-space:pre-wrap;background:#1a0907;border:1px solid #6f2a19;padding:16px;color:#f6e5d1;">{plain}</pre>
  </body>
</html>"""


def save_action_pulse(payload: dict[str, Any]) -> None:
    """Persist JSON and text copies of the latest action pulse."""
    atomic_write_json(ACTION_PULSE_FILE, payload)
    atomic_write_text(ACTION_PULSE_TEXT_FILE, render_action_pulse(payload))


def send_action_pulse(payload: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Send one action-pulse email with phase/day dedupe."""
    load_env_file(SMTP_ENV_FILE)
    state = load_state()
    key = sent_key(text(payload.get("phase"), "manual"))
    if key in state.get("sentByKey", {}) and not force:
        return {
            "attempted": False,
            "sent": False,
            "status": "already-sent",
            "key": key,
        }
    if not smtp_configured():
        return {
            "attempted": False,
            "sent": False,
            "status": "smtp-not-configured",
            "key": key,
        }

    settings = smtp_settings()
    message = EmailMessage()
    message["Subject"] = subject_for_pulse(payload)
    message["From"] = settings["from_addr"]
    message["To"] = settings["to_addr"]
    message.set_content(render_action_pulse(payload))
    message.add_alternative(render_action_pulse_html(payload), subtype="html")

    if settings["use_ssl"]:
        with smtplib.SMTP_SSL(settings["host"], settings["port"]) as smtp:
            if settings["username"]:
                smtp.login(settings["username"], settings["password"])
            smtp.send_message(message)
    else:
        with smtplib.SMTP(settings["host"], settings["port"]) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            if settings["username"]:
                smtp.login(settings["username"], settings["password"])
            smtp.send_message(message)

    state.setdefault("sentByKey", {})[key] = {
        "sentAt": local_now().isoformat(),
        "phase": payload.get("phase"),
        "subject": message["Subject"],
        "verdict": payload.get("verdict"),
    }
    save_state(state)
    return {
        "attempted": True,
        "sent": True,
        "status": "sent",
        "key": key,
        "subject": message["Subject"],
    }


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Build and optionally send the Inferno action pulse.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--phase", choices=sorted(PHASE_LABELS), default="manual")
    parser.add_argument("--deployable-cash", type=float, default=1000.0)
    parser.add_argument("--send", action="store_true", help="Send the action pulse via SMTP.")
    parser.add_argument("--force-send", action="store_true", help="Send even if this phase already sent today.")
    parser.add_argument("--skip-maintenance", action="store_true", help="Skip ops maintenance before building the pulse.")
    parser.add_argument("--refresh-live-sync", action="store_true", help="Refresh live sync before launch check.")
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    if args.command == "status" and ACTION_PULSE_TEXT_FILE.exists():
        print(ACTION_PULSE_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_action_pulse(
        phase=args.phase,
        deployable_cash=args.deployable_cash,
        skip_maintenance=args.skip_maintenance,
        refresh_live_sync=args.refresh_live_sync,
    )
    delivery = {"sent": False, "status": "not-requested"}
    if args.send:
        delivery = send_action_pulse(payload, force=args.force_send)
    payload["delivery"] = delivery
    save_action_pulse(payload)
    print(render_action_pulse(payload))
    print(f"Delivery: {delivery.get('status')}")
    if args.send and delivery.get("status") in {"smtp-not-configured"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
