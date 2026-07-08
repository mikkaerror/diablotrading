from __future__ import annotations

"""Operator ticket-cap policy for paper/research construction.

This lane records the desk's current sizing posture without changing the
operator-owned risk constants in ``inferno_config.py``. The hard ceiling still
comes from the central risk policy. This artifact describes the target band and
call-options posture the research lanes should use when choosing what to price.
"""

import argparse
import os
from typing import Any

from inferno_config import MAX_SINGLE_TICKET_DOLLARS, PAPER_TICKET_BUDGET_DOLLARS, local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


TICKET_CAP_POLICY_STAGE = "ticket-cap-policy-research-only"
TICKET_CAP_POLICY_CONFIG_FILE = DATA_DIR / "operator_ticket_cap_policy.json"
TICKET_CAP_POLICY_FILE = DATA_DIR / "inferno_ticket_cap_policy.json"
TICKET_CAP_POLICY_TEXT_FILE = REPORTS_DIR / "ticket_cap_policy_latest.txt"

DEFAULT_MIN_TICKET_DOLLARS = float(os.environ.get("INFERNO_TICKET_MIN_DOLLARS", "250"))
DEFAULT_MAX_TICKET_DOLLARS = float(os.environ.get("INFERNO_TICKET_MAX_DOLLARS", "500"))
DEFAULT_TARGET_TICKET_DOLLARS = float(os.environ.get("INFERNO_TICKET_TARGET_DOLLARS", "250"))
DEFAULT_CALL_POSTURE = os.environ.get("INFERNO_CALL_POSTURE", "aggressive-defined-risk")


def text(value: Any, default: str = "") -> str:
    """Return compact display text."""
    if value is None:
        return default
    rendered = str(value).strip()
    return rendered or default


def number(value: Any, default: float = 0.0) -> float:
    """Parse artifact numbers without trusting formatting."""
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = text(value).replace("$", "").replace(",", "").replace("%", "")
    try:
        return float(cleaned)
    except ValueError:
        return default


def _normalized_band(
    *,
    min_ticket: float,
    max_ticket: float,
    target_ticket: float,
) -> dict[str, float]:
    """Normalize the operator sizing band into a consistent order."""
    floor = max(0.0, float(min_ticket))
    ceiling = max(0.0, float(max_ticket))
    if ceiling and floor > ceiling:
        floor, ceiling = ceiling, floor
    if ceiling <= 0:
        ceiling = float(MAX_SINGLE_TICKET_DOLLARS)
    target = max(0.0, float(target_ticket))
    if target <= 0:
        target = floor or ceiling
    if floor:
        target = max(target, floor)
    target = min(target, ceiling)
    return {
        "minTicketDollars": round(floor, 2),
        "maxTicketDollars": round(ceiling, 2),
        "targetTicketDollars": round(target, 2),
    }


def load_policy_config() -> tuple[dict[str, Any], bool]:
    """Load the saved operator ticket-cap policy or return default assumptions."""
    payload = load_json_file(TICKET_CAP_POLICY_CONFIG_FILE) or {}
    if payload:
        return payload, True
    return {
        "minTicketDollars": DEFAULT_MIN_TICKET_DOLLARS,
        "maxTicketDollars": DEFAULT_MAX_TICKET_DOLLARS,
        "targetTicketDollars": DEFAULT_TARGET_TICKET_DOLLARS,
        "callOptionsPosture": DEFAULT_CALL_POSTURE,
        "source": "default-assumption",
    }, False


def save_policy_config(
    *,
    min_ticket_dollars: float,
    max_ticket_dollars: float,
    target_ticket_dollars: float | None = None,
    call_options_posture: str = DEFAULT_CALL_POSTURE,
    source: str = "operator-assumption",
) -> dict[str, Any]:
    """Persist the operator's target ticket band and call posture."""
    ensure_dirs()
    band = _normalized_band(
        min_ticket=min_ticket_dollars,
        max_ticket=max_ticket_dollars,
        target_ticket=target_ticket_dollars if target_ticket_dollars is not None else min_ticket_dollars,
    )
    payload = {
        "updatedAt": local_now().isoformat(),
        **band,
        "callOptionsPosture": text(call_options_posture, DEFAULT_CALL_POSTURE),
        "source": source,
    }
    atomic_write_json(TICKET_CAP_POLICY_CONFIG_FILE, payload)
    return payload


def current_risk_cap() -> dict[str, Any]:
    """Resolve the active risk-policy cap without making this module mandatory."""
    try:
        from inferno_risk_policy import current_single_ticket_cap

        cap = current_single_ticket_cap() or {}
    except Exception:
        cap = {
            "effectiveCap": float(MAX_SINGLE_TICKET_DOLLARS),
            "source": "risk-policy-unavailable",
            "recommendedCap": None,
            "ackedCap": None,
            "verdict": None,
            "shouldUseRecommendation": False,
        }
    effective = max(0.0, number(cap.get("effectiveCap"), float(MAX_SINGLE_TICKET_DOLLARS)))
    return {
        **cap,
        "effectiveCap": round(effective, 2),
    }


def build_ticket_cap_policy() -> dict[str, Any]:
    """Build the current ticket-cap policy artifact."""
    ensure_dirs()
    config, configured = load_policy_config()
    requested = _normalized_band(
        min_ticket=number(config.get("minTicketDollars"), DEFAULT_MIN_TICKET_DOLLARS),
        max_ticket=number(config.get("maxTicketDollars"), DEFAULT_MAX_TICKET_DOLLARS),
        target_ticket=number(config.get("targetTicketDollars"), DEFAULT_TARGET_TICKET_DOLLARS),
    )
    cap_info = current_risk_cap()
    live_hard_cap = max(0.0, number(cap_info.get("effectiveCap"), DEFAULT_MAX_TICKET_DOLLARS))
    paper_budget_cap = max(0.0, round(float(PAPER_TICKET_BUDGET_DOLLARS), 2))
    construction_hard_cap = min(requested["maxTicketDollars"], float(MAX_SINGLE_TICKET_DOLLARS))
    construction_hard_cap = max(0.0, round(construction_hard_cap, 2))
    construction_floor = min(requested["minTicketDollars"], construction_hard_cap) if construction_hard_cap else 0.0
    construction_target = (
        min(max(requested["targetTicketDollars"], construction_floor), construction_hard_cap)
        if construction_hard_cap
        else 0.0
    )
    paper_hard_cap = max(0.0, round(paper_budget_cap, 2))
    target_floor = min(requested["minTicketDollars"], paper_hard_cap) if paper_hard_cap else 0.0
    effective_target = (
        min(max(requested["targetTicketDollars"], target_floor), paper_hard_cap)
        if paper_hard_cap
        else 0.0
    )
    if paper_hard_cap < requested["minTicketDollars"]:
        verdict = "paper-budget-below-target-band"
    elif paper_hard_cap < requested["maxTicketDollars"]:
        verdict = "clamped-to-paper-budget"
    else:
        verdict = "active"
    call_posture = text(config.get("callOptionsPosture"), DEFAULT_CALL_POSTURE)
    payload = {
        "generatedAt": local_now().isoformat(),
        "stage": TICKET_CAP_POLICY_STAGE,
        "verdict": verdict,
        "message": (
            f"Target paper/research ticket band ${requested['minTicketDollars']:.0f}-"
            f"${requested['maxTicketDollars']:.0f}; construction ceiling ${construction_hard_cap:.0f}; "
            f"simulated paper risk budget ${paper_hard_cap:.0f}; live capital ceiling ${live_hard_cap:.0f}."
        ),
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "configured": configured,
        "requestedBand": requested,
        "constructionBand": {
            "minTargetDollars": round(construction_floor, 2),
            "targetTicketDollars": round(construction_target, 2),
            "hardCapDollars": construction_hard_cap,
            "source": "operator-ticket-cap-policy",
            "note": "Research construction/search cap only; simulated paper and live capital gates remain separate.",
        },
        "effectiveBand": {
            "minTargetDollars": round(target_floor, 2),
            "targetTicketDollars": round(effective_target, 2),
            "hardCapDollars": paper_hard_cap,
            "constructionConstrainedHardCapDollars": construction_hard_cap,
            "sourceRiskCapDollars": paper_budget_cap,
            "sourceRiskCapSource": "paper-budget",
            "sourceRiskCapVerdict": "paper-budget",
            "paperBudgetDollars": paper_budget_cap,
            "drawdownLevel": None,
            "drawdownCapMultiplier": None,
            "newEntriesAllowed": True,
            "note": "Simulated paper risk budget; independent of construction search caps and the live drawdown stepper.",
        },
        "liveCapitalBand": {
            "hardCapDollars": live_hard_cap,
            "sourceRiskCapSource": cap_info.get("source"),
            "sourceRiskCapVerdict": cap_info.get("verdict"),
            "ackedCap": cap_info.get("ackedCap"),
            "recommendedCap": cap_info.get("recommendedCap"),
            "drawdownLevel": cap_info.get("drawdownLevel"),
            "drawdownCapMultiplier": cap_info.get("drawdownCapMultiplier"),
            "newEntriesAllowed": cap_info.get("newEntriesAllowed"),
            "note": "Live capital cap only; paper mode ignores this cap for simulated staging.",
        },
        "sizingRules": [
            "The max ticket is a hard ceiling for paper/research construction.",
            "The min ticket is a target band floor, not a command to force risk into weak setups.",
            "Tickets below the target floor may still be valid when no clean larger structure exists.",
            "The policy never changes broker-submit or live-trading authority.",
        ],
        "callOptionsPosture": {
            "mode": call_posture,
            "aggressiveCallResearchEnabled": call_posture in {"aggressive-defined-risk", "call-debit-biased"},
            "allowedPaperResearchStructures": ["CALL_DEBIT_SPREAD"],
            "blockedStructures": ["undefined-risk-call", "naked-short-call", "broker-submitted-call-order"],
            "optimizerBias": "price defined-risk bullish call debit spreads when market context supports a call thesis",
        },
        "citations": [
            "inferno_config.PAPER_TICKET_BUDGET_DOLLARS",
            "inferno_risk_policy.current_single_ticket_cap",
            "data/operator_ticket_cap_policy.json",
            "data/inferno_capital_scaling.json",
        ],
    }
    return payload


def current_ticket_cap_policy() -> dict[str, Any]:
    """Return the fresh policy payload for callers that need the effective cap."""
    return build_ticket_cap_policy()


def ticket_cap_policy_text(payload: dict[str, Any]) -> str:
    """Render the ticket-cap policy into an operator-facing memo."""
    requested = payload.get("requestedBand") or {}
    construction = payload.get("constructionBand") or {}
    effective = payload.get("effectiveBand") or {}
    live = payload.get("liveCapitalBand") or {}
    posture = payload.get("callOptionsPosture") or {}
    lines = [
        "Inferno Ticket Cap Policy",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Verdict: {payload.get('verdict')}",
        f"Message: {payload.get('message')}",
        "Authority: research-only; brokerSubmitAllowed=False; liveTradingAllowed=False",
        "",
        "Requested band:",
        f"- Min target: ${number(requested.get('minTicketDollars')):,.2f}",
        f"- Target: ${number(requested.get('targetTicketDollars')):,.2f}",
        f"- Max cap: ${number(requested.get('maxTicketDollars')):,.2f}",
        "",
        "Research construction band:",
        f"- Min target: ${number(construction.get('minTargetDollars')):,.2f}",
        f"- Target: ${number(construction.get('targetTicketDollars')):,.2f}",
        f"- Hard cap: ${number(construction.get('hardCapDollars')):,.2f}",
        f"- Note: {construction.get('note')}",
        "",
        "Simulated paper budget band:",
        f"- Min target: ${number(effective.get('minTargetDollars')):,.2f}",
        f"- Target: ${number(effective.get('targetTicketDollars')):,.2f}",
        f"- Hard cap: ${number(effective.get('hardCapDollars')):,.2f}",
        f"- Source: {effective.get('sourceRiskCapSource')} | verdict {effective.get('sourceRiskCapVerdict')}",
        f"- Note: {effective.get('note')}",
        "",
        "Live capital cap:",
        f"- Hard cap: ${number(live.get('hardCapDollars')):,.2f}",
        f"- Risk source: {live.get('sourceRiskCapSource')} | verdict {live.get('sourceRiskCapVerdict')}",
        f"- Drawdown: {live.get('drawdownLevel') or 'n/a'} | new entries allowed {live.get('newEntriesAllowed')}",
        "",
        "Call options posture:",
        f"- Mode: {posture.get('mode')}",
        f"- Aggressive call research: {posture.get('aggressiveCallResearchEnabled')}",
        f"- Allowed structures: {', '.join(posture.get('allowedPaperResearchStructures') or [])}",
        "",
        "Sizing rules:",
    ]
    lines.extend(f"- {item}" for item in payload.get("sizingRules") or [])
    return "\n".join(lines).rstrip() + "\n"


def save_ticket_cap_policy(payload: dict[str, Any]) -> None:
    """Persist JSON and text copies of the ticket-cap policy."""
    ensure_dirs()
    atomic_write_json(TICKET_CAP_POLICY_FILE, payload)
    atomic_write_text(TICKET_CAP_POLICY_TEXT_FILE, ticket_cap_policy_text(payload))


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Build or configure the Inferno ticket-cap policy.")
    parser.add_argument("action", nargs="?", choices=("run", "status", "configure"), default="run")
    parser.add_argument("--min-ticket", type=float)
    parser.add_argument("--max-ticket", type=float)
    parser.add_argument("--target-ticket", type=float)
    parser.add_argument(
        "--call-posture",
        choices=("aggressive-defined-risk", "call-debit-biased", "balanced-defined-risk"),
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    if args.action == "configure":
        current_config, _configured = load_policy_config()
        save_policy_config(
            min_ticket_dollars=number(current_config.get("minTicketDollars"), DEFAULT_MIN_TICKET_DOLLARS)
            if args.min_ticket is None
            else args.min_ticket,
            max_ticket_dollars=number(current_config.get("maxTicketDollars"), DEFAULT_MAX_TICKET_DOLLARS)
            if args.max_ticket is None
            else args.max_ticket,
            target_ticket_dollars=number(current_config.get("targetTicketDollars"), DEFAULT_TARGET_TICKET_DOLLARS)
            if args.target_ticket is None
            else args.target_ticket,
            call_options_posture=text(current_config.get("callOptionsPosture"), DEFAULT_CALL_POSTURE)
            if args.call_posture is None
            else args.call_posture,
        )
    elif args.action == "status" and TICKET_CAP_POLICY_TEXT_FILE.exists():
        print(TICKET_CAP_POLICY_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_ticket_cap_policy()
    save_ticket_cap_policy(payload)
    print(ticket_cap_policy_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
