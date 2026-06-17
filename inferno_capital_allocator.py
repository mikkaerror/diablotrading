from __future__ import annotations

"""Capital sleeve allocator for the Inferno desk.

This layer translates research, evidence, and authority into a cleaner portfolio
plan. The goal is not to promise alpha. It is to stop mixing short-horizon
options catalysts with long-horizon accumulation ideas and give each lane an
explicit daily mandate.
"""

import argparse
from typing import Any

from inferno_config import MAX_DAILY_TICKET_DOLLARS, MAX_SINGLE_TICKET_DOLLARS, local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


EDGE_RESEARCH_FILE = DATA_DIR / "inferno_edge_research.json"
EXECUTION_QUEUE_FILE = DATA_DIR / "inferno_execution_queue.json"
STRATEGY_LAB_FILE = DATA_DIR / "inferno_strategy_lab.json"
AUTHORITY_MANIFEST_FILE = DATA_DIR / "inferno_authority_manifest.json"
EXPOSURE_ANALYTICS_FILE = DATA_DIR / "inferno_exposure_analytics.json"
CAPITAL_ALLOCATOR_FILE = DATA_DIR / "inferno_capital_allocator.json"
CAPITAL_ALLOCATOR_TEXT_FILE = REPORTS_DIR / "capital_allocator_latest.txt"


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp a fractional allocation into a stable range."""
    return max(low, min(high, value))


def number(value: Any, default: float = 0.0) -> float:
    """Safely coerce loosely typed values into floats."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_sleeves(options: float, long_term: float, cash: float) -> dict[str, float]:
    """Normalize sleeve weights so they sum to 1.0."""
    total = max(options + long_term + cash, 0.0001)
    return {
        "options": round(options / total, 4),
        "longTerm": round(long_term / total, 4),
        "cash": round(cash / total, 4),
    }


def build_sleeves(
    authority: dict[str, Any],
    strategy_lab: dict[str, Any],
    exposure: dict[str, Any],
    edge_research: dict[str, Any],
) -> dict[str, float]:
    """Build sleeve weights from authority, regime, and opportunity mix."""
    options = 0.35
    long_term = 0.40
    cash = 0.25

    authority_level = str((authority.get("decision") or {}).get("authorityLevel") or "")
    strategy_level = str((strategy_lab.get("deskVerdict") or {}).get("level") or "")
    market_risk = str((exposure.get("marketRegime") or {}).get("riskLevel") or "")
    catalyst_count = len(edge_research.get("topCatalystTrades") or [])
    shovel_count = len(edge_research.get("topLongTermShovels") or [])

    if authority_level == "halted":
        # In a hard stop, keep tactical options dry and reserve the desk for
        # deliberate long-term buying only if conviction names are on sale.
        options = 0.0
        long_term = 0.35 if shovel_count else 0.15
        cash = 1.0 - long_term
        return normalize_sleeves(options, long_term, cash)

    if market_risk == "high":
        options -= 0.15
        long_term -= 0.05
        cash += 0.20
    elif market_risk == "low":
        options += 0.05
        cash -= 0.05

    if strategy_level == "promotable":
        options += 0.10
        cash -= 0.05
        long_term -= 0.05
    elif strategy_level in {"cooldown", "insufficient-data"}:
        options -= 0.10
        cash += 0.10

    if catalyst_count >= 4:
        options += 0.05
        cash -= 0.05
    elif catalyst_count == 0:
        options -= 0.10
        if shovel_count:
            # No catalyst lane means do not force options; use the freed budget
            # for long-term candidates when they exist instead of over-reserving.
            long_term += 0.10
        else:
            cash += 0.10

    if shovel_count >= 4:
        long_term += 0.05
        cash -= 0.05
    elif shovel_count == 0:
        long_term -= 0.10
        cash += 0.10

    return normalize_sleeves(
        clamp(options),
        clamp(long_term),
        clamp(cash),
    )


def build_options_lane(
    edge_research: dict[str, Any],
    execution_queue: dict[str, Any],
    sleeves: dict[str, float],
    *,
    deployable_cash_dollars: float | None = None,
) -> dict[str, Any]:
    """Build the event-driven options lane plan."""
    ready_by_ticker = {
        str(item.get("ticker") or "").upper(): item
        for item in execution_queue.get("items") or []
        if item.get("ticker")
    }
    catalyst_candidates: list[dict[str, Any]] = []
    for candidate in edge_research.get("topCatalystTrades") or []:
        ticker = str(candidate.get("ticker") or "").upper()
        intent = ready_by_ticker.get(ticker, {})
        catalyst_candidates.append(
            {
                "ticker": ticker,
                "category": candidate.get("category"),
                "edgeScore": candidate.get("edgeScore"),
                "timingScore": (candidate.get("scores") or {}).get("timingScore"),
                "qualityScore": (candidate.get("scores") or {}).get("qualityScore"),
                "setupRec": intent.get("setupRec") or candidate.get("setupRec"),
                "intentStatus": intent.get("intentStatus") or "research-only",
                "riskUnits": intent.get("riskUnits"),
                "daysUntilEarnings": candidate.get("daysUntilEarnings"),
                "thesis": candidate.get("thesis"),
            }
        )

    capital_base = number(deployable_cash_dollars, MAX_DAILY_TICKET_DOLLARS) if deployable_cash_dollars is not None else MAX_DAILY_TICKET_DOLLARS
    deploy_budget = round(capital_base * sleeves["options"], 2)
    staged_count = max(1, min(3, len(catalyst_candidates)))
    starter_cap = round(min(MAX_SINGLE_TICKET_DOLLARS, deploy_budget / staged_count), 2)
    return {
        "sleeveWeight": sleeves["options"],
        "capitalBaseDollars": round(capital_base, 2),
        "dailyBudgetDollars": deploy_budget,
        "maxStarterTicketDollars": starter_cap,
        "recommendedTicketCount": staged_count if catalyst_candidates else 0,
        "topCandidates": catalyst_candidates[:5],
        "playbook": [
            "Only press names that clear trigger, approval, and strike-quality gates.",
            "Use the post-open strike cycle for contracts; do not trust 6 AM option quotes.",
            "If no candidate is approval-ready, preserve the sleeve in cash instead of forcing a trade.",
        ],
    }


def build_long_term_lane(
    edge_research: dict[str, Any],
    sleeves: dict[str, float],
    *,
    deployable_cash_dollars: float | None = None,
) -> dict[str, Any]:
    """Build the long-horizon accumulation lane plan."""
    long_term_candidates: list[dict[str, Any]] = []
    for candidate in edge_research.get("topLongTermShovels") or []:
        long_term_candidates.append(
            {
                "ticker": candidate.get("ticker"),
                "category": candidate.get("category"),
                "edgeScore": candidate.get("edgeScore"),
                "qualityScore": (candidate.get("scores") or {}).get("qualityScore"),
                "valuationRiskScore": (candidate.get("scores") or {}).get("valuationRiskScore"),
                "longTermScore": candidate.get("longTermScore"),
                "thesis": candidate.get("thesis"),
            }
        )

    tranche_weights = [0.40, 0.35, 0.25]
    capital_base = number(deployable_cash_dollars, MAX_DAILY_TICKET_DOLLARS) if deployable_cash_dollars is not None else MAX_DAILY_TICKET_DOLLARS
    sleeve_budget = round(capital_base * sleeves["longTerm"], 2)
    return {
        "sleeveWeight": sleeves["longTerm"],
        "capitalBaseDollars": round(capital_base, 2),
        "sleeveBudgetDollars": sleeve_budget,
        "tranchePlan": [
            {"name": "starter", "weight": tranche_weights[0], "dollars": round(sleeve_budget * tranche_weights[0], 2)},
            {"name": "add-on weakness", "weight": tranche_weights[1], "dollars": round(sleeve_budget * tranche_weights[1], 2)},
            {"name": "deep-discount add", "weight": tranche_weights[2], "dollars": round(sleeve_budget * tranche_weights[2], 2)},
        ],
        "topCandidates": long_term_candidates[:5],
        "playbook": [
            "Use three tranches instead of one all-in decision.",
            "Only accumulate names that still fit the shovel thesis after the excitement fades.",
            "Do not re-label a bad options trade as a long-term investment just to avoid taking the lesson.",
        ],
    }


def allocator_verdict(
    authority: dict[str, Any],
    strategy_lab: dict[str, Any],
    options_lane: dict[str, Any],
    long_term_lane: dict[str, Any],
) -> dict[str, Any]:
    """Build a plain-English allocator verdict."""
    authority_level = str((authority.get("decision") or {}).get("authorityLevel") or "")
    strategy_level = str((strategy_lab.get("deskVerdict") or {}).get("level") or "")

    blockers: list[str] = []
    warnings: list[str] = []
    if authority_level == "halted":
        blockers.append("authority manifest is halted")
    if strategy_level in {"cooldown", "insufficient-data"}:
        warnings.append(f"strategy evidence lane is {strategy_level}")
    if not options_lane.get("topCandidates"):
        warnings.append("no strong catalyst lane candidates right now")
    if not long_term_lane.get("topCandidates"):
        warnings.append("no strong long-term accumulation candidates right now")

    if blockers:
        level = "defensive"
        message = "Hold tactical firepower in reserve and only build long-term conviction in careful tranches."
    elif strategy_level == "promotable" and options_lane.get("topCandidates"):
        level = "balanced-attack"
        message = "Catalyst lane is usable, but only through paper-validated, risk-capped structures."
    else:
        level = "measured"
        message = "Favor deliberate accumulation and only deploy options capital when the trigger stack is undeniable."
    return {
        "level": level,
        "message": message,
        "blockers": blockers,
        "warnings": warnings,
    }


def build_capital_allocator(*, deployable_cash_dollars: float | None = None) -> dict[str, Any]:
    """Build the full capital allocator artifact."""
    edge_research = load_json_file(EDGE_RESEARCH_FILE) or {}
    execution_queue = load_json_file(EXECUTION_QUEUE_FILE) or {}
    strategy_lab = load_json_file(STRATEGY_LAB_FILE) or {}
    authority = load_json_file(AUTHORITY_MANIFEST_FILE) or {}
    exposure = load_json_file(EXPOSURE_ANALYTICS_FILE) or {}

    sleeves = build_sleeves(authority, strategy_lab, exposure, edge_research)
    options_lane = build_options_lane(
        edge_research,
        execution_queue,
        sleeves,
        deployable_cash_dollars=deployable_cash_dollars,
    )
    long_term_lane = build_long_term_lane(
        edge_research,
        sleeves,
        deployable_cash_dollars=deployable_cash_dollars,
    )
    verdict = allocator_verdict(authority, strategy_lab, options_lane, long_term_lane)
    capital_base = number(deployable_cash_dollars, MAX_DAILY_TICKET_DOLLARS) if deployable_cash_dollars is not None else MAX_DAILY_TICKET_DOLLARS

    return {
        "generatedAt": local_now().isoformat(),
        "stage": "capital-allocator",
        "inputs": {
            "deployableCashDollars": round(capital_base, 2),
            "authorityLevel": (authority.get("decision") or {}).get("authorityLevel"),
            "strategyDeskVerdict": (strategy_lab.get("deskVerdict") or {}).get("level"),
            "marketRiskLevel": (exposure.get("marketRegime") or {}).get("riskLevel"),
            "catalystCount": len(edge_research.get("topCatalystTrades") or []),
            "longTermCount": len(edge_research.get("topLongTermShovels") or []),
        },
        "sleeves": sleeves,
        "reserveCashDollars": round(capital_base * sleeves["cash"], 2),
        "optionsLane": options_lane,
        "longTermLane": long_term_lane,
        "verdict": verdict,
        "principles": [
            "Do not confuse short-term catalyst risk with long-term conviction inventory.",
            "Preserve cash when evidence is thin instead of manufacturing activity.",
            "Only let the options sleeve expand when strategy evidence and authority both agree.",
        ],
    }


def allocator_text(report: dict[str, Any]) -> str:
    """Render the allocator as a readable desk memo."""
    tranche_plan_text = ", ".join(
        f"{item.get('name')} {round(number(item.get('weight')) * 100, 1)}%"
        for item in (report.get("longTermLane") or {}).get("tranchePlan", [])
    ) or "none"
    lines = [
        "Inferno Capital Allocator",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Verdict: {(report.get('verdict') or {}).get('level')} | {(report.get('verdict') or {}).get('message')}",
        f"Deployable cash base: ${number((report.get('inputs') or {}).get('deployableCashDollars')):.2f}",
        "",
        "Sleeves:",
        f"- options catalyst sleeve: {round(number((report.get('sleeves') or {}).get('options')) * 100, 1)}%",
        f"- long-term accumulation sleeve: {round(number((report.get('sleeves') or {}).get('longTerm')) * 100, 1)}%",
        f"- reserve cash sleeve: {round(number((report.get('sleeves') or {}).get('cash')) * 100, 1)}%",
        f"- reserve cash dollars: ${number(report.get('reserveCashDollars')):.2f}",
        "",
        "Options lane:",
        f"- daily budget: ${(report.get('optionsLane') or {}).get('dailyBudgetDollars', 0):.2f}",
        f"- starter ticket cap: ${(report.get('optionsLane') or {}).get('maxStarterTicketDollars', 0):.2f}",
        f"- recommended ticket count: {(report.get('optionsLane') or {}).get('recommendedTicketCount', 0)}",
    ]
    for index, candidate in enumerate((report.get("optionsLane") or {}).get("topCandidates", []), start=1):
        lines.append(
            f"  {index}. {candidate.get('ticker')} | {candidate.get('setupRec') or 'setup wait'} | "
            f"edge {candidate.get('edgeScore')} | status {candidate.get('intentStatus')}"
        )

    lines.extend(
        [
            "",
            "Long-term lane:",
            f"- sleeve budget: ${number((report.get('longTermLane') or {}).get('sleeveBudgetDollars')):.2f}",
            f"- tranche plan: {tranche_plan_text}",
        ]
    )
    for index, candidate in enumerate((report.get("longTermLane") or {}).get("topCandidates", []), start=1):
        lines.append(
            f"  {index}. {candidate.get('ticker')} | {candidate.get('category')} | "
            f"edge {candidate.get('edgeScore')} | long-term {candidate.get('longTermScore')}"
        )

    if (report.get("verdict") or {}).get("warnings"):
        lines.extend(["", "Warnings:"])
        for warning in (report.get("verdict") or {}).get("warnings", []):
            lines.append(f"- {warning}")
    if report.get("principles"):
        lines.extend(["", "Principles:"])
        for principle in report.get("principles", []):
            lines.append(f"- {principle}")
    return "\n".join(lines).rstrip() + "\n"


def save_capital_allocator(report: dict[str, Any]) -> None:
    """Persist JSON and text copies of the allocator."""
    ensure_dirs()
    atomic_write_json(CAPITAL_ALLOCATOR_FILE, report)
    atomic_write_text(CAPITAL_ALLOCATOR_TEXT_FILE, allocator_text(report))


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Build the Inferno capital allocator.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    parser.add_argument(
        "--deployable-cash",
        type=float,
        default=None,
        help="Optional cash amount to size sleeves against for the current deployment window.",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    if args.command == "status" and CAPITAL_ALLOCATOR_TEXT_FILE.exists():
        print(CAPITAL_ALLOCATOR_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = build_capital_allocator(deployable_cash_dollars=args.deployable_cash)
    save_capital_allocator(report)
    print(allocator_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
