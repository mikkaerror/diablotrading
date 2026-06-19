from __future__ import annotations

"""Build a research-only account growth and risk optimization brief.

The brief stress-tests ambitious return targets against the current Schwab
account, contribution scenarios, concentration, and contract-sized options
risk. It never changes authority, stages orders, or submits trades.
"""

import argparse
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


ACCOUNT_OPTIMIZATION_FILE = DATA_DIR / "inferno_account_optimization.json"
ACCOUNT_OPTIMIZATION_TEXT_FILE = REPORTS_DIR / "account_optimization_latest.txt"
LIVE_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_live_account_sync.json"
CAPITAL_ALLOCATOR_FILE = DATA_DIR / "inferno_capital_allocator.json"
STRATEGY_LAB_FILE = DATA_DIR / "inferno_strategy_lab.json"
FAST_PAPER_COHORT_FILE = DATA_DIR / "inferno_fast_paper_cohort.json"

ACCOUNT_OPTIMIZATION_STAGE = "account-optimization-research-only"
TARGET_MONTHLY_RETURN = 0.10
SCENARIO_MONTHLY_RETURNS = (0.0, 0.01, 0.02, 0.05, 0.10)
SCENARIO_MONTHLY_CONTRIBUTIONS = (0.0, 250.0, 500.0, 1000.0)
MILESTONES = (5000.0, 7500.0, 15000.0, 25000.0, 100000.0)
RISK_FRACTIONS = (0.005, 0.01, 0.02, 0.05)


def number(value: Any, default: float = 0.0) -> float:
    """Coerce loose artifact values into floats."""
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value or "").replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return default


def monthly_to_annual(monthly_return: float) -> float:
    """Return the compounded annual return for a monthly rate."""
    return (1.0 + monthly_return) ** 12 - 1.0


def future_value(
    starting_balance: float,
    monthly_return: float,
    monthly_contribution: float,
    months: int = 12,
) -> float:
    """Compound a balance with end-of-month contributions."""
    if months <= 0:
        return starting_balance
    if monthly_return == 0:
        return starting_balance + monthly_contribution * months
    growth = (1.0 + monthly_return) ** months
    contribution_growth = monthly_contribution * (growth - 1.0) / monthly_return
    return starting_balance * growth + contribution_growth


def months_to_target(
    starting_balance: float,
    target_balance: float,
    monthly_return: float,
    monthly_contribution: float,
    *,
    max_months: int = 600,
) -> int | None:
    """Return months needed to cross a target under a deterministic scenario."""
    if starting_balance >= target_balance:
        return 0
    if monthly_return <= 0 and monthly_contribution <= 0:
        return None
    balance = starting_balance
    for month in range(1, max_months + 1):
        balance = balance * (1.0 + monthly_return) + monthly_contribution
        if balance >= target_balance:
            return month
    return None


def load_inputs() -> dict[str, dict[str, Any]]:
    """Load the canonical account, allocation, evidence, and paper artifacts."""
    return {
        "liveAccount": load_json_file(LIVE_ACCOUNT_SYNC_FILE) or {},
        "allocator": load_json_file(CAPITAL_ALLOCATOR_FILE) or {},
        "strategyLab": load_json_file(STRATEGY_LAB_FILE) or {},
        "fastPaper": load_json_file(FAST_PAPER_COHORT_FILE) or {},
    }


def position_concentration(live_account: dict[str, Any], nlv: float) -> dict[str, Any]:
    """Summarize position and cash concentration from broker truth."""
    rows: list[dict[str, Any]] = []
    for position in live_account.get("positions") or []:
        market_value = number(position.get("markValue"))
        weight = number(position.get("weightPct"))
        if weight <= 0 and nlv > 0:
            weight = market_value / nlv * 100.0
        rows.append(
            {
                "symbol": str(position.get("symbol") or "").upper(),
                "marketValue": round(market_value, 2),
                "weightPct": round(weight, 2),
                "plPercent": round(number(position.get("plPercent")), 2),
                "riskFlags": list(position.get("riskFlags") or []),
            }
        )
    rows.sort(key=lambda item: item["weightPct"], reverse=True)
    invested = sum(item["marketValue"] for item in rows)
    return {
        "positionCount": len(rows),
        "investedDollars": round(invested, 2),
        "investedPct": round(invested / nlv * 100.0, 2) if nlv > 0 else 0.0,
        "topPositionPct": round(rows[0]["weightPct"], 2) if rows else 0.0,
        "topTwoPct": round(sum(item["weightPct"] for item in rows[:2]), 2),
        "fragileAlignmentCount": sum(
            1 for item in rows if "fragile-alignment" in item["riskFlags"]
        ),
        "positions": rows,
    }


def growth_scenarios(nlv: float) -> list[dict[str, Any]]:
    """Build a twelve-month return and contribution stress-test grid."""
    rows: list[dict[str, Any]] = []
    for monthly_return in SCENARIO_MONTHLY_RETURNS:
        for contribution in SCENARIO_MONTHLY_CONTRIBUTIONS:
            ending = future_value(nlv, monthly_return, contribution)
            rows.append(
                {
                    "monthlyReturnPct": round(monthly_return * 100.0, 2),
                    "annualizedReturnPct": round(monthly_to_annual(monthly_return) * 100.0, 2),
                    "monthlyContribution": contribution,
                    "endingBalance12Months": round(ending, 2),
                    "netGrowth12Months": round(ending - nlv, 2),
                }
            )
    return rows


def affordability_table(ticket_dollars: float, nlv: float) -> list[dict[str, Any]]:
    """Show how large one contract-sized ticket is at several risk bands."""
    rows: list[dict[str, Any]] = []
    for fraction in RISK_FRACTIONS:
        rows.append(
            {
                "riskPct": round(fraction * 100.0, 2),
                "currentRiskBudgetDollars": round(nlv * fraction, 2),
                "requiredNlvForReferenceTicket": (
                    round(ticket_dollars / fraction, 2) if ticket_dollars > 0 else None
                ),
            }
        )
    return rows


def milestone_table(nlv: float) -> list[dict[str, Any]]:
    """Show contribution-sensitive timelines under a demanding 2% scenario."""
    rows: list[dict[str, Any]] = []
    for target in MILESTONES:
        rows.append(
            {
                "targetBalance": target,
                "monthsAt2PctWith250Contribution": months_to_target(nlv, target, 0.02, 250.0),
                "monthsAt2PctWith500Contribution": months_to_target(nlv, target, 0.02, 500.0),
                "monthsAt10PctWithoutContribution": months_to_target(nlv, target, 0.10, 0.0),
            }
        )
    return rows


def build_account_optimization(
    inputs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the current account optimization plan."""
    artifacts = inputs or load_inputs()
    live_account = artifacts.get("liveAccount") or {}
    allocator = artifacts.get("allocator") or {}
    strategy_lab = artifacts.get("strategyLab") or {}
    fast_paper = artifacts.get("fastPaper") or {}

    nlv = number(live_account.get("netLiquidatingValue"))
    cash = number(live_account.get("totalCash"))
    options_lane = allocator.get("optionsLane") or {}
    reference_ticket = number(options_lane.get("maxStarterTicketDollars"))
    overall = strategy_lab.get("overall") or {}
    strategy_verdict = overall.get("verdict") or {}
    strategy_promotable = bool(strategy_verdict.get("promotable"))
    strategy_risk_cap = number(overall.get("riskUnitCap"))
    concentration = position_concentration(live_account, nlv)
    reference_ticket_pct = reference_ticket / nlv * 100.0 if nlv > 0 else 0.0
    three_ticket_drawdown = reference_ticket * 3.0 / nlv if nlv > 0 else 0.0

    blockers: list[str] = []
    if nlv <= 0:
        blockers.append("live Schwab NLV is unavailable")
    if not strategy_promotable:
        blockers.append("strategy evidence is not promotable")
    if reference_ticket_pct > 2.0:
        blockers.append(
            f"one ${reference_ticket:,.2f} starter ticket is {reference_ticket_pct:.2f}% of NLV"
        )
    if concentration["topPositionPct"] > 20.0:
        blockers.append(
            f"largest holding is {concentration['topPositionPct']:.2f}% of NLV"
        )

    fast_counts = fast_paper.get("counts") or {}
    fast_open = int(number(fast_counts.get("open")))
    simulation_label = "simulation" if fast_open == 1 else "simulations"
    fast_action = (
        f"Close and score the {fast_open} fast-paper {simulation_label} at the first eligible "
        "later-session quote, then open the next diversified cohort."
        if fast_open
        else "Open the next diversified fast-paper cohort when the market-data lane is ready."
    )
    actions = [
        "Keep live options max-loss authority at $0 until the strategy lab becomes promotable.",
        fast_action,
        "Use new deposits to reduce concentration through qualified, less-correlated long-term holdings; do not automatically add to the largest current position.",
        "Preserve cash when no long-term or options candidate clears its gates.",
        "Reconcile broker transaction history so realized options profit can be harvested into shares without double counting deposits.",
        "Reassess one-contract live options only when both evidence is promotable and the contract max loss is no more than 2% of NLV.",
    ]

    return {
        "generatedAt": local_now().isoformat(),
        "stage": ACCOUNT_OPTIMIZATION_STAGE,
        "verdict": "protect-and-prove" if blockers else "eligible-for-manual-sizing-review",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "account": {
            "source": live_account.get("accountDataSource"),
            "suffix": live_account.get("matchedSuffix"),
            "netLiquidatingValue": round(nlv, 2),
            "cash": round(cash, 2),
            "cashPct": round(cash / nlv * 100.0, 2) if nlv > 0 else 0.0,
        },
        "targetStressTest": {
            "targetMonthlyReturnPct": TARGET_MONTHLY_RETURN * 100.0,
            "compoundedAnnualReturnPct": round(
                monthly_to_annual(TARGET_MONTHLY_RETURN) * 100.0, 2
            ),
            "endingBalanceWithoutContributions": round(
                future_value(nlv, TARGET_MONTHLY_RETURN, 0.0), 2
            ),
            "classification": "stretch hypothesis, not an operating baseline",
        },
        "concentration": concentration,
        "optionsAffordability": {
            "referenceStarterTicketDollars": round(reference_ticket, 2),
            "referenceTicketPctOfNlv": round(reference_ticket_pct, 2),
            "strategyLabPromotable": strategy_promotable,
            "strategyLabRiskUnitCap": strategy_risk_cap,
            "edgeAdjustedLiveOptionsMaxLossDollars": 0.0 if not strategy_promotable else round(
                min(reference_ticket, nlv * 0.02), 2
            ),
            "threeReferenceTicketDrawdownPct": round(three_ticket_drawdown * 100.0, 2),
            "gainRequiredToRecoverThreeTicketDrawdownPct": (
                round(three_ticket_drawdown / (1.0 - three_ticket_drawdown) * 100.0, 2)
                if 0.0 < three_ticket_drawdown < 1.0
                else None
            ),
            "riskBands": affordability_table(reference_ticket, nlv),
        },
        "evidence": {
            "strategyScoredCount": int(number(overall.get("scoredCount"))),
            "strategyRemainingForPromotion": max(
                0, 30 - int(number(overall.get("scoredCount")))
            ),
            "fastPaperOpen": int(number(fast_counts.get("open"))),
            "fastPaperClosedLifetime": int(number(fast_counts.get("closedLifetime"))),
        },
        "growthScenarios": growth_scenarios(nlv),
        "milestones": milestone_table(nlv),
        "blockers": blockers,
        "nextActions": actions,
        "operatorRule": (
            "This is a research and sizing brief. It does not recommend a specific security, "
            "change authority, or authorize an order."
        ),
    }


def money(value: Any) -> str:
    """Render a dollar value."""
    return f"${number(value):,.2f}"


def render_account_optimization(payload: dict[str, Any]) -> str:
    """Render the optimization plan as an operator-facing memo."""
    account = payload.get("account") or {}
    target = payload.get("targetStressTest") or {}
    concentration = payload.get("concentration") or {}
    affordability = payload.get("optionsAffordability") or {}
    evidence = payload.get("evidence") or {}
    lines = [
        "Inferno Account Optimization",
        "=" * 28,
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Operator rule: {payload.get('operatorRule')}",
        "",
        "Current account truth",
        f"- NLV: {money(account.get('netLiquidatingValue'))}",
        f"- Cash: {money(account.get('cash'))} ({number(account.get('cashPct')):.2f}%)",
        f"- Invested: {money(concentration.get('investedDollars'))} ({number(concentration.get('investedPct')):.2f}%)",
        f"- Largest position: {number(concentration.get('topPositionPct')):.2f}%",
        f"- Top two positions: {number(concentration.get('topTwoPct')):.2f}%",
        f"- Fragile-alignment positions: {concentration.get('fragileAlignmentCount', 0)}",
        "",
        "10% monthly stress test",
        f"- Annualized compound return: {number(target.get('compoundedAnnualReturnPct')):.2f}%",
        f"- 12-month balance without deposits: {money(target.get('endingBalanceWithoutContributions'))}",
        f"- Classification: {target.get('classification')}",
        "",
        "Options affordability",
        f"- Reference starter ticket: {money(affordability.get('referenceStarterTicketDollars'))}",
        f"- Reference ticket / NLV: {number(affordability.get('referenceTicketPctOfNlv')):.2f}%",
        f"- Evidence-adjusted live max loss now: {money(affordability.get('edgeAdjustedLiveOptionsMaxLossDollars'))}",
        f"- Three-ticket max-loss drawdown: {number(affordability.get('threeReferenceTicketDrawdownPct')):.2f}%",
        f"- Recovery gain after that drawdown: {number(affordability.get('gainRequiredToRecoverThreeTicketDrawdownPct')):.2f}%",
        "",
        "Contract-size thresholds",
    ]
    for row in affordability.get("riskBands") or []:
        lines.append(
            f"- {number(row.get('riskPct')):.2f}% risk: current budget "
            f"{money(row.get('currentRiskBudgetDollars'))}; "
            f"NLV needed for this ticket {money(row.get('requiredNlvForReferenceTicket'))}"
        )

    lines.extend(
        [
            "",
            "Evidence",
            f"- Strategy scored outcomes: {evidence.get('strategyScoredCount', 0)}",
            f"- Remaining promotion outcomes: {evidence.get('strategyRemainingForPromotion', 0)}",
            f"- Fast-paper open / closed: {evidence.get('fastPaperOpen', 0)} / {evidence.get('fastPaperClosedLifetime', 0)}",
            "",
            "Twelve-month scenarios",
        ]
    )
    for row in payload.get("growthScenarios") or []:
        if number(row.get("monthlyContribution")) not in {0.0, 500.0}:
            continue
        lines.append(
            f"- {number(row.get('monthlyReturnPct')):.0f}% monthly + "
            f"{money(row.get('monthlyContribution'))}/month -> "
            f"{money(row.get('endingBalance12Months'))}"
        )

    lines.extend(["", "Current blockers"])
    lines.extend(f"- {item}" for item in payload.get("blockers") or ["none"])
    lines.extend(["", "Next actions"])
    lines.extend(f"{index}. {item}" for index, item in enumerate(payload.get("nextActions") or [], 1))
    return "\n".join(lines).rstrip() + "\n"


def save_account_optimization(payload: dict[str, Any]) -> None:
    """Persist JSON and text optimization artifacts."""
    ensure_dirs()
    atomic_write_json(ACCOUNT_OPTIMIZATION_FILE, payload)
    atomic_write_text(ACCOUNT_OPTIMIZATION_TEXT_FILE, render_account_optimization(payload))


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Build the research-only account optimization brief.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    if args.command == "status" and ACCOUNT_OPTIMIZATION_TEXT_FILE.exists():
        print(ACCOUNT_OPTIMIZATION_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_account_optimization()
    save_account_optimization(payload)
    print(render_account_optimization(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
