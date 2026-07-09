from __future__ import annotations

"""One-command capital launch preflight for the Inferno desk.

This module is the operator cockpit before any real cash is deployed. It
refreshes the existing read-only safety artifacts, sizes the desk against the
cash the operator expects to have available, and renders a concise go/no-go
brief. It never submits orders, never opens thinkorswim, and never widens
authority.
"""

import argparse
from typing import Any

from inferno_capital_deployment_readiness import build_capital_deployment_readiness
from inferno_cash_attribution import build_cash_attribution
from inferno_config import approved_account_scope, local_now
from inferno_deposit_plan import build_deposit_plan
from inferno_io import atomic_write_json, atomic_write_text
from inferno_live_account_sync import build_live_account_sync
from inferno_live_book_review_packet import build_review_packet
from inferno_live_position_review import build_live_position_review
from inferno_model_command_center import build_command_center
from inferno_risk_gate_audit import build_risk_gate_audit
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


CAPITAL_LAUNCH_CHECK_FILE = DATA_DIR / "inferno_capital_launch_check.json"
CAPITAL_LAUNCH_CHECK_TEXT_FILE = REPORTS_DIR / "capital_launch_check_latest.txt"


def text(value: Any, default: str = "") -> str:
    """Normalize loose artifact values into concise display text."""
    if value is None:
        return default
    rendered = str(value).strip()
    return rendered or default


def number(value: Any, default: float = 0.0) -> float:
    """Parse broker/report numbers without throwing on blanks or symbols."""
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = text(value).replace("$", "").replace(",", "").replace("%", "")
    try:
        return float(cleaned)
    except ValueError:
        return default


def money(value: Any) -> str:
    """Render money values with conventional negative formatting."""
    parsed = number(value)
    prefix = "-$" if parsed < 0 else "$"
    return f"{prefix}{abs(parsed):,.2f}"


def truthy(value: Any) -> bool:
    """Interpret common boolean-like artifact values."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return text(value).lower() in {"true", "yes", "y", "1", "enabled"}


def gate_rows(risk_gate_audit: dict[str, Any], statuses: set[str]) -> list[dict[str, Any]]:
    """Return risk-gate rows matching the requested statuses."""
    return [
        row
        for row in risk_gate_audit.get("gates") or []
        if text(row.get("status")).lower() in statuses
    ]


def required_human_decisions(live_book_packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract live-book decisions that must be resolved before new capital."""
    decisions: list[dict[str, Any]] = []
    for row in live_book_packet.get("positions") or []:
        effect = text(row.get("unlockEffect"))
        if effect == "does-not-block":
            continue
        math_block = row.get("math") or {}
        decisions.append(
            {
                "symbol": text(row.get("symbol")).upper(),
                "unlockEffect": effect,
                "reviewHeat": number(row.get("reviewHeat")),
                "posture": text(row.get("posture")),
                "daysUntilEarnings": math_block.get("daysUntilEarnings"),
                "supportCushionPct": math_block.get("supportCushionPct"),
                "resistanceHeadroomPct": math_block.get("resistanceHeadroomPct"),
                "prompts": row.get("reviewPrompts") or [],
            }
        )
    return decisions


def launch_verdict(
    readiness: dict[str, Any],
    risk_gate_audit: dict[str, Any],
    live_book_packet: dict[str, Any],
) -> dict[str, Any]:
    """Collapse readiness, risk, and live-book state into one launch verdict."""
    readiness_verdict = text(readiness.get("verdict"), "missing")
    risk_verdict = text(risk_gate_audit.get("verdict"), "missing")
    live_counts = live_book_packet.get("counts") or {}
    hard_blockers = int(number(live_counts.get("hardBlockers")))
    hard_fails = int(number((risk_gate_audit.get("summary") or {}).get("hardFails")))

    if hard_blockers or hard_fails or readiness_verdict == "not-ready" or risk_verdict == "blocked":
        return {
            "verdict": "blocked",
            "message": "Do not deploy fresh capital until hard blockers are cleared.",
            "manualDeploymentAllowed": False,
        }

    if readiness_verdict == "manual-ready" and risk_verdict == "clear":
        return {
            "verdict": "manual-ready",
            "message": "Manual execution review is clean; live automation remains locked.",
            "manualDeploymentAllowed": True,
        }

    return {
        "verdict": "manual-ready-with-warnings",
        "message": "Manual execution can be reviewed, but warnings must be accepted explicitly.",
        "manualDeploymentAllowed": truthy(readiness.get("manualDeploymentAllowed")),
    }


def build_execution_process(verdict: str) -> list[str]:
    """Return the concise human process for moving from signal to real order."""
    if verdict == "blocked":
        opening = "Clear hard blockers first; do not size new orders yet."
    else:
        opening = "Review the candidates and size only inside the guardrails below."
    return [
        opening,
        "Run this launch check again after any position exit, tracker update, or cash change.",
        "Approve one candidate from the approval queue; reject anything you cannot explain in one sentence.",
        "Run ./inferno strike-cycle after options markets are open for current strikes.",
        "Review reports/strike_plan_latest.txt and any broker preview before touching TOS.",
        f"Enter orders manually in {approved_account_scope()} only; final submit requires your explicit confirmation.",
        "After fills, run capture/ingest and rebuild the command center so evidence stays current.",
    ]


def build_capital_launch_check(
    *,
    deployable_cash: float | None = None,
    for_date: str | None = None,
    refresh_live_sync: bool = False,
) -> dict[str, Any]:
    """Refresh launch-critical artifacts and build the capital launch brief."""
    ensure_dirs()

    # Keep this read-only. ``refresh_live_sync`` may use an existing artifact or
    # Schwab account API, but none of these builders has submit power.
    live_sync = build_live_account_sync(refresh_schwab=refresh_live_sync, refresh_statement=False)
    live_review = build_live_position_review(refresh_live_sync=False)
    readiness = build_capital_deployment_readiness(
        deployable_cash=deployable_cash,
        for_date=for_date,
    )
    live_book_packet = build_review_packet()
    risk_gate_audit = build_risk_gate_audit()
    deposit_plan = build_deposit_plan()
    cash_attribution = build_cash_attribution()
    command_center = build_command_center()

    verdict_block = launch_verdict(readiness, risk_gate_audit, live_book_packet)
    failed_gates = gate_rows(risk_gate_audit, {"fail"})
    warning_gates = gate_rows(risk_gate_audit, {"warn"})
    decisions = required_human_decisions(live_book_packet)
    guardrails = readiness.get("guardrails") or {}
    effective_deployable_cash = number(guardrails.get("deployableCash"), number(deployable_cash))

    payload = {
        "generatedAt": local_now().isoformat(),
        "stage": "capital-launch-check",
        "deployableCash": effective_deployable_cash,
        "deployableCashSource": readiness.get("deployableCashSource"),
        "deploymentDate": readiness.get("deploymentDate"),
        "verdict": verdict_block["verdict"],
        "message": verdict_block["message"],
        "manualDeploymentAllowed": verdict_block["manualDeploymentAllowed"],
        "autoLiveAllowed": False,
        "liveAccountScopeRequired": approved_account_scope(),
        "liveAccountSync": {
            "verdict": live_sync.get("verdict"),
            "matchedSuffix": live_sync.get("matchedSuffix") or live_sync.get("accountSuffix"),
            "generatedAt": live_sync.get("generatedAt"),
        },
        "livePositionReview": {
            "verdict": live_review.get("verdict"),
            "counts": live_review.get("counts") or {},
            "generatedAt": live_review.get("generatedAt"),
        },
        "capitalReadiness": {
            "verdict": readiness.get("verdict"),
            "message": readiness.get("message"),
            "guardrails": readiness.get("guardrails") or {},
            "blockers": readiness.get("blockers") or [],
            "warnings": readiness.get("warnings") or [],
        },
        "depositPlan": {
            "verdict": deposit_plan.get("verdict"),
            "message": deposit_plan.get("message"),
            "plan": deposit_plan.get("plan") or {},
            "schedule": deposit_plan.get("schedule") or {},
            "forecastWindows": deposit_plan.get("forecastWindows") or {},
            "capitalTreatment": deposit_plan.get("capitalTreatment") or {},
            "brokerCashSnapshot": deposit_plan.get("brokerCashSnapshot") or {},
        },
        "cashAttribution": {
            "verdict": cash_attribution.get("verdict"),
            "message": cash_attribution.get("message"),
            "brokerCash": cash_attribution.get("brokerCash") or {},
            "latestCashChange": cash_attribution.get("latestCashChange") or {},
            "latestCashClassification": cash_attribution.get("latestCashClassification") or {},
            "realizedOptionsProfit": cash_attribution.get("realizedOptionsProfit") or {},
            "capitalTreatment": cash_attribution.get("capitalTreatment") or {},
        },
        "riskGateAudit": {
            "verdict": risk_gate_audit.get("verdict"),
            "message": risk_gate_audit.get("message"),
            "summary": risk_gate_audit.get("summary") or {},
            "failedGates": failed_gates,
            "warningGates": warning_gates,
        },
        "liveBook": {
            "verdict": live_book_packet.get("verdict"),
            "counts": live_book_packet.get("counts") or {},
            "unlockChecklist": live_book_packet.get("unlockChecklist") or [],
            "requiredHumanDecisions": decisions,
        },
        "commandCenterGeneratedAt": command_center.get("generatedAt"),
        "executionProcess": build_execution_process(verdict_block["verdict"]),
        "operatorRule": "No broker submit, no live order, and no authority promotion without explicit user confirmation.",
    }
    save_capital_launch_check(payload)
    return payload


def render_capital_launch_check(payload: dict[str, Any]) -> str:
    """Render the launch check as a concise operator-facing briefing."""
    readiness = payload.get("capitalReadiness") or {}
    guardrails = readiness.get("guardrails") or {}
    deposit = payload.get("depositPlan") or {}
    deposit_plan = deposit.get("plan") or {}
    deposit_schedule = deposit.get("schedule") or {}
    deposit_forecast = deposit.get("forecastWindows") or {}
    deposit_broker = deposit.get("brokerCashSnapshot") or {}
    cash_attribution = payload.get("cashAttribution") or {}
    cash_classification = cash_attribution.get("latestCashClassification") or {}
    cash_change = cash_attribution.get("latestCashChange") or {}
    realized_options = cash_attribution.get("realizedOptionsProfit") or {}
    risk = payload.get("riskGateAudit") or {}
    live_book = payload.get("liveBook") or {}
    live_counts = live_book.get("counts") or {}

    lines = [
        "Inferno Capital Launch Check",
        "=" * 29,
        f"Generated: {payload.get('generatedAt')}",
        f"Deployment date: {payload.get('deploymentDate')}",
        f"Verdict: {payload.get('verdict')}",
        f"Message: {payload.get('message')}",
        "",
        "Safety locks",
        f"- Manual deployment allowed: {payload.get('manualDeploymentAllowed')}",
        f"- Auto live trading allowed: {payload.get('autoLiveAllowed')}",
        f"- Required account scope: {payload.get('liveAccountScopeRequired') or payload.get('liveAccountSuffixRequired')}",
        "",
        "Capital guardrails",
        f"- Deployable cash: ${number(payload.get('deployableCash')):,.2f}",
        f"- Deployable cash source: {payload.get('deployableCashSource') or '-'}",
        f"- Max options risk: ${number(guardrails.get('maxOptionsRisk')):,.2f}",
        f"- Max starter ticket: ${number(guardrails.get('maxStarterTicket')):,.2f}",
        f"- Max long-term buy: ${number(guardrails.get('maxLongTermBuy')):,.2f}",
        f"- Reserve cash: ${number(guardrails.get('reserveCash')):,.2f}",
        "",
        "Deposit plan",
        f"- Recurring deposit: ${number(deposit_plan.get('amountDollars')):,.2f} every {int(number(deposit_plan.get('intervalDays')))} day(s)",
        f"- Next expected deposit: {deposit_schedule.get('nextDepositDate')} ({deposit_schedule.get('daysUntilNextDeposit')} day(s))",
        f"- 30-day planned deposits: ${number((deposit_forecast.get('30Days') or {}).get('grossDeposits')):,.2f}",
        f"- Broker-confirmed cash: ${number(deposit_broker.get('cash')):,.2f}",
        "- Treatment: planned deposits are not deployable until broker cash confirms.",
        "",
        "Cash attribution",
        f"- Verdict: {cash_attribution.get('verdict')}",
        f"- Latest cash delta: {money(cash_change.get('deltaCash'))}",
        f"- Classification: {cash_classification.get('classification') or '-'}",
        f"- Realized options profit known: {realized_options.get('known')}",
        "- Treatment: cash changes are not option profit without a broker transaction ledger.",
        "",
        "Live book",
        f"- Verdict: {live_book.get('verdict')}",
        f"- Hard blockers: {live_counts.get('hardBlockers', 0)}",
        f"- Warnings: {live_counts.get('warnings', 0)}",
        "",
        "Risk gates",
        f"- Verdict: {risk.get('verdict')}",
        f"- Summary: {(risk.get('summary') or {}).get('passed', 0)}/{(risk.get('summary') or {}).get('total', 0)} pass",
        "",
        "Required human decisions",
    ]

    decisions = live_book.get("requiredHumanDecisions") or []
    if decisions:
        for item in decisions:
            lines.append(
                "- "
                f"{item.get('symbol')}: {item.get('unlockEffect')} | "
                f"heat={item.get('reviewHeat')} | days={item.get('daysUntilEarnings')} | "
                f"support cushion={item.get('supportCushionPct')}% | "
                f"resistance room={item.get('resistanceHeadroomPct')}%"
            )
    else:
        lines.append("- none")

    lines.extend(["", "Blockers"])
    blockers = readiness.get("blockers") or []
    lines.extend([f"- {item}" for item in blockers] or ["- none"])

    lines.extend(["", "Warnings"])
    warnings = readiness.get("warnings") or []
    warning_gates = [row.get("name") for row in risk.get("warningGates") or []]
    lines.extend([f"- {item}" for item in warnings] or ["- none"])
    if warning_gates:
        lines.append(f"- Risk-gate warnings: {', '.join(text(name) for name in warning_gates)}")

    lines.extend(["", "Execution process"])
    lines.extend(f"{index}. {step}" for index, step in enumerate(payload.get("executionProcess") or [], 1))
    return "\n".join(lines).rstrip() + "\n"


def save_capital_launch_check(payload: dict[str, Any]) -> None:
    """Persist JSON and text copies of the launch check."""
    atomic_write_json(CAPITAL_LAUNCH_CHECK_FILE, payload)
    atomic_write_text(CAPITAL_LAUNCH_CHECK_TEXT_FILE, render_capital_launch_check(payload))


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Build the Inferno capital launch check.")
    parser.add_argument(
        "--deployable-cash",
        type=float,
        default=None,
        help="Expected cash available for the next deployment window. If omitted, live account sync cash is used.",
    )
    parser.add_argument(
        "--for-date",
        default=None,
        help="Deployment date to stamp in the brief. Defaults to the readiness module date.",
    )
    parser.add_argument(
        "--refresh-live-sync",
        action="store_true",
        help="Refresh live account sync from the existing read-only lane before checking.",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    payload = build_capital_launch_check(
        deployable_cash=args.deployable_cash,
        for_date=args.for_date,
        refresh_live_sync=args.refresh_live_sync,
    )
    print(render_capital_launch_check(payload))
    return 0 if payload.get("verdict") != "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
