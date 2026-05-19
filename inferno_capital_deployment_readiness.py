"""Build a capital deployment readiness brief for the Inferno desk.

This module is intentionally conservative. It does not trade, route orders, or
touch thinkorswim. It reads the desk artifacts we already produce, verifies the
important guardrails, and writes a compact readiness brief for manual review.
"""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path
from typing import Any

from inferno_capital_allocator import build_capital_allocator, save_capital_allocator
from inferno_config import account_suffix_allowed, approved_account_scope, local_now, local_today
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


AUTHORITY_MANIFEST_FILE = DATA_DIR / "inferno_authority_manifest.json"
CAPITAL_ALLOCATOR_FILE = DATA_DIR / "inferno_capital_allocator.json"
CAPITAL_DEPLOYMENT_READINESS_FILE = DATA_DIR / "inferno_capital_deployment_readiness.json"
CAPITAL_DEPLOYMENT_READINESS_TEXT_FILE = REPORTS_DIR / "capital_deployment_readiness_latest.txt"
LIVE_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_live_account_sync.json"
LIVE_POSITION_REVIEW_FILE = DATA_DIR / "inferno_live_position_review.json"
PAPER_EVIDENCE_LOOP_FILE = DATA_DIR / "inferno_paper_evidence_loop.json"
PAPER_TEST_DIRECTOR_FILE = DATA_DIR / "inferno_paper_test_director.json"
STRATEGY_LAB_FILE = DATA_DIR / "inferno_strategy_lab.json"
DATA_READINESS_AUDIT_FILE = DATA_DIR / "inferno_data_readiness_audit.json"
TICKER_UNIVERSE_AUDIT_FILE = DATA_DIR / "inferno_ticker_universe_audit.json"
OPS_MAINTENANCE_FILE = DATA_DIR / "inferno_ops_maintenance.json"


def text(value: Any, default: str = "") -> str:
    """Return a stripped string for stable report rendering."""
    if value is None:
        return default
    rendered = str(value).strip()
    return rendered or default


def number(value: Any, default: float = 0.0) -> float:
    """Parse a number from broker/report text without throwing."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return default


def truthy(value: Any) -> bool:
    """Interpret common string/number booleans from JSON artifacts."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"true", "yes", "y", "1", "enabled"}


def nested(payload: dict[str, Any], path: tuple[str, ...], default: Any = None) -> Any:
    """Safely read a nested dictionary path."""
    current: Any = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def first_present(*values: Any, default: Any = None) -> Any:
    """Return the first non-empty value from a set of possible artifact fields."""
    for value in values:
        if value not in (None, ""):
            return value
    return default


def load_artifacts() -> dict[str, dict[str, Any]]:
    """Load every desk artifact needed for the deployment preflight."""
    return {
        "authority": load_json_file(AUTHORITY_MANIFEST_FILE) or {},
        "allocator": load_json_file(CAPITAL_ALLOCATOR_FILE) or {},
        "liveSync": load_json_file(LIVE_ACCOUNT_SYNC_FILE) or {},
        "liveReview": load_json_file(LIVE_POSITION_REVIEW_FILE) or {},
        "paperLoop": load_json_file(PAPER_EVIDENCE_LOOP_FILE) or {},
        "paperDirector": load_json_file(PAPER_TEST_DIRECTOR_FILE) or {},
        "strategyLab": load_json_file(STRATEGY_LAB_FILE) or {},
        "dataReadiness": load_json_file(DATA_READINESS_AUDIT_FILE) or {},
        "tickerAudit": load_json_file(TICKER_UNIVERSE_AUDIT_FILE) or {},
        "opsMaintenance": load_json_file(OPS_MAINTENANCE_FILE) or {},
    }


def is_generated_today(payload: dict[str, Any]) -> bool:
    """Return true when an artifact appears to have been refreshed today."""
    generated_at = text(first_present(payload.get("generatedAt"), payload.get("updatedAt")))
    return generated_at.startswith(local_today())


def artifact_verdict(payload: dict[str, Any]) -> str:
    """Extract the most common verdict/status field from an artifact."""
    return text(
        first_present(
            payload.get("verdict"),
            payload.get("status"),
            nested(payload, ("deskVerdict", "level")),
            nested(payload, ("summary", "verdict")),
        ),
        "missing",
    )


def infer_cash_from_live_sync(live_sync: dict[str, Any]) -> float:
    """Infer deployable cash from the live sync artifact when possible."""
    return number(
        first_present(
            live_sync.get("stockBuyingPower"),
            live_sync.get("buyingPower"),
            live_sync.get("availableFundsForTrading"),
            nested(live_sync, ("accountSummary", "Stock Buying Power")),
            nested(live_sync, ("accountSummary", "Available Funds For Trading")),
            nested(live_sync, ("balances", "stockBuyingPower")),
        )
    )


def build_guardrail_summary(allocator: dict[str, Any]) -> dict[str, Any]:
    """Normalize allocator values into a compact capital plan."""
    return {
        "deployableCash": number(
            first_present(
                allocator.get("deployableCash"),
                nested(allocator, ("inputs", "deployableCashDollars")),
                nested(allocator, ("capital", "deployableCash")),
                nested(allocator, ("summary", "deployableCash")),
            )
        ),
        "maxOptionsRisk": number(
            first_present(
                allocator.get("maxOptionsRisk"),
                nested(allocator, ("optionsLane", "dailyBudgetDollars")),
                nested(allocator, ("guardrails", "maxOptionsRisk")),
                nested(allocator, ("capital", "maxOptionsRisk")),
            )
        ),
        "maxStarterTicket": number(
            first_present(
                allocator.get("maxStarterTicket"),
                nested(allocator, ("optionsLane", "maxStarterTicketDollars")),
                nested(allocator, ("guardrails", "maxStarterTicket")),
            )
        ),
        "maxLongTermBuy": number(
            first_present(
                allocator.get("maxLongTermBuy"),
                nested(allocator, ("longTermLane", "sleeveBudgetDollars")),
                nested(allocator, ("guardrails", "maxLongTermBuy")),
                nested(allocator, ("capital", "maxLongTermBuy")),
            )
        ),
        "reserveCash": number(
            first_present(
                allocator.get("reserveCash"),
                allocator.get("reserveCashDollars"),
                nested(allocator, ("guardrails", "reserveCash")),
                nested(allocator, ("capital", "reserveCash")),
            )
        ),
    }


def evaluate_readiness(
    artifacts: dict[str, dict[str, Any]],
    allocator: dict[str, Any],
    deployment_date: str,
) -> dict[str, Any]:
    """Evaluate tomorrow's manual deployment readiness from desk artifacts."""
    blockers: list[str] = []
    warnings: list[str] = []
    next_actions: list[str] = []

    authority = artifacts["authority"]
    authority_level = text(
        first_present(
            nested(authority, ("decision", "authorityLevel")),
            authority.get("authorityLevel"),
        ),
        "missing",
    )
    broker_submit_allowed = truthy(
        first_present(
            nested(authority, ("decision", "brokerSubmitAllowed")),
            authority.get("brokerSubmitAllowed"),
            False,
        )
    )
    live_trading_allowed = truthy(
        first_present(
            nested(authority, ("decision", "liveTradingAllowed")),
            authority.get("liveTradingAllowed"),
            False,
        )
    )
    if broker_submit_allowed or live_trading_allowed:
        blockers.append("Authority manifest allows live or broker submit. Lock it back to manual review before proceeding.")
    if authority_level in {"missing", "halted"}:
        blockers.append("Authority manifest is missing or halted. Refresh authority before sizing capital.")

    live_sync = artifacts["liveSync"]
    live_suffix = text(first_present(live_sync.get("matchedSuffix"), live_sync.get("accountSuffix")))
    live_verdict = artifact_verdict(live_sync)
    if live_verdict not in {"healthy", "matched", "ok"}:
        blockers.append(f"Live account sync is not healthy: {live_verdict}.")
    if live_suffix and not account_suffix_allowed(live_suffix):
        blockers.append(f"Live account suffix is {live_suffix}, expected {approved_account_scope()}.")
    if not live_suffix:
        warnings.append(f"Live account suffix was not found in the sync artifact. Confirm {approved_account_scope()} manually.")

    data_verdict = artifact_verdict(artifacts["dataReadiness"])
    if not (data_verdict.startswith("ready") or data_verdict in {"healthy", "ok"}):
        blockers.append(f"Tracker data readiness is not green: {data_verdict}.")

    ticker_verdict = artifact_verdict(artifacts["tickerAudit"])
    ticker_critical = number(
        first_present(
            artifacts["tickerAudit"].get("criticalCount"),
            nested(artifacts["tickerAudit"], ("counts", "critical")),
            nested(artifacts["tickerAudit"], ("summary", "critical")),
        )
    )
    if ticker_verdict not in {"healthy", "ok", "missing"} and ticker_critical > 0:
        blockers.append(f"Ticker universe audit has {int(ticker_critical)} critical issue(s).")

    live_review_counts = artifacts["liveReview"].get("counts") or {}
    live_review_needed = number(live_review_counts.get("review"))
    live_fragile = number(live_review_counts.get("fragile"))
    if live_fragile:
        blockers.append(f"Live position review has {int(live_fragile)} fragile holding(s).")
    if live_review_needed:
        warnings.append(f"Live position review has {int(live_review_needed)} holding(s) needing review before adding exposure.")

    paper_remaining = number(
        first_present(
            nested(artifacts["paperLoop"], ("counts", "remainingForPromotion")),
            artifacts["paperLoop"].get("remainingForPromotion"),
        )
    )
    if paper_remaining:
        warnings.append(f"Paper evidence loop still needs {int(paper_remaining)} closed paper trade(s) for automation promotion.")

    paper_stageable = number(
        first_present(
            nested(artifacts["paperDirector"], ("counts", "stageableNow")),
            artifacts["paperDirector"].get("stageableNow"),
        )
    )
    paper_approval = number(
        first_present(
            nested(artifacts["paperDirector"], ("counts", "approvalOnly")),
            artifacts["paperDirector"].get("approvalOnly"),
        )
    )
    paper_auto = number(
        first_present(
            nested(artifacts["paperDirector"], ("counts", "autoPaperSelected")),
            artifacts["paperDirector"].get("autoPaperSelected"),
        )
    )
    if paper_stageable <= 0 and paper_auto <= 0 and paper_approval <= 0:
        warnings.append("Paper test director has no stageable, auto-selected, or approval-only candidates.")

    strategy_verdict = artifact_verdict(artifacts["strategyLab"])
    if strategy_verdict in {"insufficient-data", "missing"}:
        warnings.append("Strategy lab still has insufficient closed evidence. Manual conviction only.")

    ops_verdict = artifact_verdict(artifacts["opsMaintenance"])
    if ops_verdict not in {"healthy", "ok", "missing"}:
        warnings.append(f"Ops maintenance artifact is not clean: {ops_verdict}.")

    for name in ("liveSync", "dataReadiness", "tickerAudit"):
        payload = artifacts[name]
        if payload and not is_generated_today(payload):
            warnings.append(f"{name} artifact is not stamped today. Refresh before deployment window.")

    guardrails = build_guardrail_summary(allocator)
    if guardrails["deployableCash"] <= 0:
        warnings.append("Capital allocator has no deployable cash. Rebuild with expected cash before sizing.")

    next_actions.extend(
        [
            "Run inferno_doctor.py and require a healthy desk before market open.",
            "Refresh tracker data, live account sync, and paper evidence artifacts.",
            "Use this brief for sizing only. Orders still require explicit user confirmation.",
            f"Confirm every order is under {approved_account_scope()} before any final submit.",
        ]
    )

    if blockers:
        verdict = "not-ready"
        message = "Do not deploy new capital until blockers are cleared."
    elif warnings:
        verdict = "manual-ready-with-warnings"
        message = "Manual deployment can be reviewed, but automation remains locked."
    else:
        verdict = "manual-ready"
        message = "Manual review is clean. Automation remains locked by policy."

    return {
        "generatedAt": local_now().isoformat(),
        "deploymentDate": deployment_date,
        "verdict": verdict,
        "message": message,
        "manualDeploymentAllowed": not blockers,
        "autoLiveAllowed": False,
        "liveAccountScopeRequired": approved_account_scope(),
        "authorityLevel": authority_level,
        "guardrails": guardrails,
        "blockers": blockers,
        "warnings": warnings,
        "nextActions": next_actions,
        "artifactVerdicts": {
            key: artifact_verdict(value)
            for key, value in artifacts.items()
        },
    }


def render_readiness_text(readiness: dict[str, Any]) -> str:
    """Render the deployment readiness artifact as a terminal-friendly brief."""
    guardrails = readiness.get("guardrails") or {}
    lines = [
        "Inferno Capital Deployment Readiness",
        "=" * 42,
        f"Generated: {text(readiness.get('generatedAt'))}",
        f"Deployment date: {text(readiness.get('deploymentDate'))}",
        f"Verdict: {text(readiness.get('verdict'))}",
        f"Message: {text(readiness.get('message'))}",
        "",
        "Capital guardrails",
        f"- Deployable cash: ${number(guardrails.get('deployableCash')):,.2f}",
        f"- Max options risk: ${number(guardrails.get('maxOptionsRisk')):,.2f}",
        f"- Max starter ticket: ${number(guardrails.get('maxStarterTicket')):,.2f}",
        f"- Max long-term buy: ${number(guardrails.get('maxLongTermBuy')):,.2f}",
        f"- Reserve cash: ${number(guardrails.get('reserveCash')):,.2f}",
        "",
        "Safety locks",
        f"- Manual deployment allowed: {readiness.get('manualDeploymentAllowed')}",
        f"- Auto live trading allowed: {readiness.get('autoLiveAllowed')}",
        f"- Required account scope: {text(first_present(readiness.get('liveAccountScopeRequired'), readiness.get('liveAccountSuffixRequired')))}",
        f"- Authority level: {text(readiness.get('authorityLevel'))}",
        "",
        "Blockers",
    ]
    blockers = readiness.get("blockers") or []
    lines.extend([f"- {item}" for item in blockers] or ["- none"])
    lines.append("")
    lines.append("Warnings")
    warnings = readiness.get("warnings") or []
    lines.extend([f"- {item}" for item in warnings] or ["- none"])
    lines.append("")
    lines.append("Next actions")
    lines.extend(f"- {item}" for item in readiness.get("nextActions") or [])
    return "\n".join(lines) + "\n"


def build_capital_deployment_readiness(
    deployable_cash: float | None = None,
    for_date: str | None = None,
) -> dict[str, Any]:
    """Build and persist the capital deployment readiness brief."""
    ensure_dirs()
    deployment_date = for_date or (local_now().date() + timedelta(days=1)).isoformat()

    allocator = build_capital_allocator(deployable_cash_dollars=deployable_cash)
    save_capital_allocator(allocator)

    artifacts = load_artifacts()
    artifacts["allocator"] = allocator
    readiness = evaluate_readiness(artifacts, allocator, deployment_date)
    atomic_write_json(CAPITAL_DEPLOYMENT_READINESS_FILE, readiness)
    atomic_write_text(CAPITAL_DEPLOYMENT_READINESS_TEXT_FILE, render_readiness_text(readiness))
    return readiness


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the readiness builder."""
    parser = argparse.ArgumentParser(description="Build capital deployment readiness brief.")
    parser.add_argument(
        "--deployable-cash",
        type=float,
        default=None,
        help="Expected cash to size against. If omitted, allocator defaults are used.",
    )
    parser.add_argument(
        "--for-date",
        default=None,
        help="Deployment date to print in the brief. Defaults to tomorrow.",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    readiness = build_capital_deployment_readiness(
        deployable_cash=args.deployable_cash,
        for_date=args.for_date,
    )
    print(render_readiness_text(readiness))
    return 0 if readiness.get("verdict") != "not-ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
