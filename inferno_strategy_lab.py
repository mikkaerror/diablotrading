from __future__ import annotations

"""Conservative strategy-evidence lab for the Inferno desk.

The performance analytics module tells us what happened. This lab asks the
harder promotion question: "Is the evidence strong enough to let automation do
more tomorrow?" It uses lower-confidence bounds, drawdown checks, and capped
Kelly sizing so a hot streak does not accidentally become a license to gamble.
"""

import argparse
import json
import math
from collections import Counter, defaultdict
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_math_config import MIN_WILSON_LOWER_FOR_EDGE
from inferno_paper_execution import load_ledger
from inferno_performance_analytics import (
    estimated_pnl,
    max_loss,
    outcome_status,
    return_on_risk,
    strategy_key,
)
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


STRATEGY_LAB_FILE = DATA_DIR / "inferno_strategy_lab.json"
STRATEGY_LAB_TEXT_FILE = REPORTS_DIR / "strategy_lab_latest.txt"

CONFIDENCE_Z = 1.96
MIN_SCORED_TRADES_FOR_PROMOTION = 30
MIN_WIN_RATE_LOWER_BOUND = MIN_WILSON_LOWER_FOR_EDGE
WIN_RATE_BREAKEVEN_MARGIN = 0.03
MIN_EXPECTANCY_LOWER_BOUND = 0.0
MIN_PROFIT_FACTOR = 1.25
MAX_FALSE_POSITIVE_RATE = 0.45
MAX_DRAWDOWN_RISK_UNITS = -6.0
MAX_RISK_UNIT_CAP = 1.0


def number(value: Any, default: float = 0.0) -> float:
    """Safely coerce loose ledger values into floats."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def wilson_lower_bound(wins: int, total: int, z_score: float = CONFIDENCE_Z) -> float | None:
    """Return the Wilson lower confidence bound for a binomial win rate.

    Wilson is deliberately used instead of raw win rate because tiny samples lie.
    A 4/4 streak is not treated as a 100% strategy; the lower bound keeps the
    desk in evidence-building mode until enough trades have survived contact
    with the market.
    """
    if total <= 0:
        return None
    phat = wins / total
    denominator = 1 + (z_score**2 / total)
    centre = phat + (z_score**2 / (2 * total))
    spread = z_score * math.sqrt((phat * (1 - phat) + (z_score**2 / (4 * total))) / total)
    return round(max(0.0, (centre - spread) / denominator), 4)


def sample_mean(values: list[float]) -> float | None:
    """Return a mean value while preserving None for missing samples."""
    if not values:
        return None
    return sum(values) / len(values)


def sample_std(values: list[float]) -> float | None:
    """Return sample standard deviation for trade return samples."""
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    variance = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def confidence_interval(values: list[float], z_score: float = CONFIDENCE_Z) -> dict[str, float | None]:
    """Return a conservative normal-approximation confidence interval.

    This is not pretending to be institutional-grade statistics. It is a stable,
    deterministic safety rail that forces automation to pass a lower-bound check
    before risk authority increases.
    """
    avg = sample_mean(values)
    if avg is None:
        return {"mean": None, "lower": None, "upper": None, "std": None}
    std = sample_std(values)
    if std is None:
        rounded = round(avg, 6)
        return {"mean": rounded, "lower": rounded, "upper": rounded, "std": None}
    margin = z_score * std / math.sqrt(len(values))
    return {
        "mean": round(avg, 6),
        "lower": round(avg - margin, 6),
        "upper": round(avg + margin, 6),
        "std": round(std, 6),
    }


def profit_factor(values: list[float]) -> float | None:
    """Return gross profit divided by gross loss for return-on-risk samples."""
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_loss = abs(sum(losses))
    if not gross_loss:
        return round(sum(wins), 4) if wins else None
    return round(sum(wins) / gross_loss, 4)


def max_drawdown(values: list[float]) -> float | None:
    """Return peak-to-trough drawdown on cumulative return-on-risk equity."""
    if not values:
        return None
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return round(worst, 6)


def payoff_ratio(wins: list[float], losses: list[float]) -> float | None:
    """Return average win divided by average loss magnitude."""
    if not wins or not losses:
        return None
    avg_win = sum(wins) / len(wins)
    avg_loss = abs(sum(losses) / len(losses))
    if avg_loss <= 0:
        return None
    return round(avg_win / avg_loss, 4)


def payoff_implied_breakeven(payoff: float | None) -> float | None:
    """Return the win rate needed to break even for a payoff ratio."""
    if payoff is None or payoff <= 0:
        return None
    return round(1.0 / (1.0 + payoff), 4)


def win_rate_floor_from_payoff(payoff: float | None) -> dict[str, Any]:
    """Return the payoff-aware Wilson lower-bound target for promotion.

    The old fixed 0.42 floor remains as a conservative fallback when the desk
    cannot derive a payoff ratio. When payoff is known, the target becomes the
    strategy's own breakeven win rate plus the operator-approved margin.
    """
    breakeven = payoff_implied_breakeven(payoff)
    if breakeven is None:
        return {
            "winRateBreakeven": None,
            "winRateBreakevenMargin": WIN_RATE_BREAKEVEN_MARGIN,
            "winRateLowerBoundTarget": MIN_WIN_RATE_LOWER_BOUND,
            "winRateLowerBoundTargetSource": "fixed-fallback",
        }
    return {
        "winRateBreakeven": breakeven,
        "winRateBreakevenMargin": WIN_RATE_BREAKEVEN_MARGIN,
        "winRateLowerBoundTarget": round(min(0.999, breakeven + WIN_RATE_BREAKEVEN_MARGIN), 4),
        "winRateLowerBoundTargetSource": "payoff-implied-breakeven-plus-margin",
    }


def kelly_from_returns(win_rate: float | None, payoff: float | None) -> float | None:
    """Return a plain Kelly fraction from win rate and payoff ratio."""
    if win_rate is None or payoff is None or payoff <= 0:
        return None
    kelly = win_rate - ((1 - win_rate) / payoff)
    return round(max(0.0, kelly), 4)


def capped_risk_unit_cap(kelly: float | None, verdict_level: str) -> float:
    """Translate evidence into a max suggested risk-unit cap.

    We use one-quarter Kelly and hard caps because options-event strategies can
    gap violently. The cap is advisory for paper/broker-preview lanes only; live
    submit remains disabled elsewhere.
    """
    if verdict_level in {"insufficient-data", "evidence-building", "cooldown"}:
        return 0.0
    if verdict_level == "probation":
        return 0.25
    if kelly is None or kelly <= 0:
        return 0.25
    return round(min(MAX_RISK_UNIT_CAP, max(0.25, kelly * 0.25)), 4)


def false_positive_rate(tickets: list[dict[str, Any]]) -> float | None:
    """Return rejected/blocked share for a strategy's ticket funnel."""
    if not tickets:
        return None
    failed = sum(1 for ticket in tickets if ticket.get("status") in {"paper-blocked", "paper-rejected"})
    return round(failed / len(tickets), 4)


def closed_trade_records(tickets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract closed, scored paper-trade records with normalized risk metrics."""
    records: list[dict[str, Any]] = []
    for ticket in tickets:
        if outcome_status(ticket) != "closed":
            continue
        pnl = estimated_pnl(ticket)
        risk = max_loss(ticket)
        risk_return = return_on_risk(ticket)
        if pnl is None or risk_return is None:
            continue
        outcome = ticket.get("outcome") or {}
        records.append(
            {
                "ticketId": ticket.get("ticketId"),
                "ticker": ticket.get("ticker"),
                "strategy": strategy_key(ticket),
                "createdAt": ticket.get("createdAt"),
                "reviewedAt": outcome.get("reviewedAt"),
                "estimatedPnl": round(pnl, 2),
                "maxLoss": round(risk, 2),
                "returnOnRisk": round(risk_return, 6),
            }
        )
    return records


def verdict_for_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """Build a promotion verdict from conservative metric thresholds."""
    blockers: list[str] = []
    warnings: list[str] = []
    scored = int(metrics.get("scoredCount") or 0)
    expectancy_lower = metrics.get("expectancyPerRiskConfidence", {}).get("lower")
    win_lower = metrics.get("winRateLowerBound")
    win_target = metrics.get("winRateLowerBoundTarget")
    if win_target is None:
        win_target = win_rate_floor_from_payoff(metrics.get("payoffRatio")).get("winRateLowerBoundTarget")
    win_target = number(win_target, MIN_WIN_RATE_LOWER_BOUND)
    win_target_source = metrics.get("winRateLowerBoundTargetSource") or "fixed-fallback"
    pf = metrics.get("profitFactor")
    dd = metrics.get("maxDrawdownRiskUnits")
    fpr = metrics.get("falsePositiveRate")

    if scored <= 0:
        blockers.append("no closed scored paper trades yet")
    if scored < MIN_SCORED_TRADES_FOR_PROMOTION:
        blockers.append(
            f"need {MIN_SCORED_TRADES_FOR_PROMOTION - scored} more scored paper trades for promotion evidence"
        )
    if expectancy_lower is None or expectancy_lower <= MIN_EXPECTANCY_LOWER_BOUND:
        blockers.append("expectancy lower bound is not positive")
    if win_lower is None or win_lower < win_target:
        blockers.append(f"win-rate lower bound below {win_target} ({win_target_source})")
    if pf is None or pf < MIN_PROFIT_FACTOR:
        blockers.append(f"profit factor below {MIN_PROFIT_FACTOR}")
    if dd is not None and dd < MAX_DRAWDOWN_RISK_UNITS:
        blockers.append(f"drawdown worse than {MAX_DRAWDOWN_RISK_UNITS} risk units")
    if fpr is not None and fpr > MAX_FALSE_POSITIVE_RATE:
        warnings.append(f"ticket funnel false-positive rate above {MAX_FALSE_POSITIVE_RATE}")

    if scored == 0:
        level = "insufficient-data"
    elif dd is not None and dd < MAX_DRAWDOWN_RISK_UNITS:
        level = "cooldown"
    elif blockers:
        level = "evidence-building" if scored < MIN_SCORED_TRADES_FOR_PROMOTION else "probation"
    elif warnings:
        level = "probation"
    else:
        level = "promotable"

    message_by_level = {
        "insufficient-data": "No closed paper evidence yet.",
        "evidence-building": "Collect more closed paper outcomes before increasing authority.",
        "probation": "Positive signs exist, but one or more conservative gates still needs work.",
        "cooldown": "Drawdown gate failed; pause escalation and review the strategy.",
        "promotable": "Conservative evidence gates passed; eligible for next manual promotion review.",
    }
    return {
        "level": level,
        "promotable": level == "promotable",
        "message": message_by_level[level],
        "blockers": blockers,
        "warnings": warnings,
    }


def summarize_strategy(name: str, tickets: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize evidence for one strategy family."""
    records = closed_trade_records(tickets)
    returns = [record["returnOnRisk"] for record in records]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    win_rate = round(len(wins) / len(returns), 4) if returns else None
    payoff = payoff_ratio(wins, losses)
    kelly = kelly_from_returns(win_rate, payoff)
    confidence = confidence_interval(returns)
    win_floor = win_rate_floor_from_payoff(payoff)
    metrics = {
        "strategy": name,
        "ticketCount": len(tickets),
        "scoredCount": len(returns),
        "winCount": len(wins),
        "lossCount": len(losses),
        "openCount": sum(1 for ticket in tickets if outcome_status(ticket) == "open"),
        "statusCounts": dict(Counter(str(ticket.get("status") or "unknown") for ticket in tickets)),
        "winRate": win_rate,
        "winRateLowerBound": wilson_lower_bound(len(wins), len(returns)),
        "expectancyPerRiskConfidence": confidence,
        "profitFactor": profit_factor(returns),
        "payoffRatio": payoff,
        **win_floor,
        "kellyFraction": kelly,
        "maxDrawdownRiskUnits": max_drawdown(returns),
        "falsePositiveRate": false_positive_rate(tickets),
        "latestClosedTrades": records[-8:],
    }
    verdict = verdict_for_metrics(metrics)
    metrics["verdict"] = verdict
    metrics["riskUnitCap"] = capped_risk_unit_cap(kelly, verdict["level"])
    return metrics


def build_strategy_lab(ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the full strategy lab artifact from the paper ledger."""
    ledger = ledger or load_ledger()
    tickets = ledger.get("items", [])
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ticket in tickets:
        grouped[strategy_key(ticket)].append(ticket)

    strategies = [summarize_strategy(name, items) for name, items in sorted(grouped.items())]
    overall = summarize_strategy("ALL_STRATEGIES", tickets)
    promotion_candidates = [
        item for item in strategies if (item.get("verdict") or {}).get("promotable")
    ]
    cooldown_strategies = [
        item for item in strategies if (item.get("verdict") or {}).get("level") == "cooldown"
    ]
    desk_level = "review-for-promotion" if promotion_candidates else overall["verdict"]["level"]
    desk_message = (
        "Promotion candidates: " + ", ".join(item["strategy"] for item in promotion_candidates)
        if promotion_candidates
        else overall["verdict"]["message"]
    )
    return {
        "generatedAt": local_now().isoformat(),
        "sourceLedgerUpdatedAt": ledger.get("updatedAt"),
        "stage": "strategy-evidence-lab",
        "thresholds": {
            "minScoredTradesForPromotion": MIN_SCORED_TRADES_FOR_PROMOTION,
            "winRateFloorMode": "payoff-implied-breakeven-plus-margin",
            "winRateBreakevenMargin": WIN_RATE_BREAKEVEN_MARGIN,
            "legacyFixedMinWinRateLowerBound": MIN_WIN_RATE_LOWER_BOUND,
            "minExpectancyLowerBound": MIN_EXPECTANCY_LOWER_BOUND,
            "minProfitFactor": MIN_PROFIT_FACTOR,
            "maxFalsePositiveRate": MAX_FALSE_POSITIVE_RATE,
            "maxDrawdownRiskUnits": MAX_DRAWDOWN_RISK_UNITS,
            "maxRiskUnitCap": MAX_RISK_UNIT_CAP,
        },
        "overall": overall,
        "strategies": strategies,
        "promotionCandidates": [item["strategy"] for item in promotion_candidates],
        "cooldownStrategies": [item["strategy"] for item in cooldown_strategies],
        "deskVerdict": {
            "level": desk_level,
            "message": desk_message,
            "promotable": bool(promotion_candidates),
        },
    }


def strategy_lab_text(lab: dict[str, Any]) -> str:
    """Render the strategy lab as an operator-facing memo."""
    verdict = lab.get("deskVerdict") or {}
    overall = lab.get("overall") or {}
    overall_verdict = overall.get("verdict") or {}
    confidence = overall.get("expectancyPerRiskConfidence") or {}
    lines = [
        "Inferno Strategy Lab",
        "",
        f"Generated: {lab.get('generatedAt')}",
        f"Ledger updated: {lab.get('sourceLedgerUpdatedAt')}",
        f"Desk verdict: {verdict.get('level')} - {verdict.get('message')}",
        "",
        "Overall evidence:",
        f"- scored trades: {overall.get('scoredCount', 0)}",
        f"- win rate: {overall.get('winRate')} | Wilson lower: {overall.get('winRateLowerBound')} "
        f"| target: {overall.get('winRateLowerBoundTarget')} ({overall.get('winRateLowerBoundTargetSource')})",
        f"- expectancy/risk mean: {confidence.get('mean')} | lower: {confidence.get('lower')}",
        f"- profit factor: {overall.get('profitFactor')}",
        f"- payoff ratio: {overall.get('payoffRatio')} | breakeven: {overall.get('winRateBreakeven')} "
        f"| margin: {overall.get('winRateBreakevenMargin')}",
        f"- max drawdown risk units: {overall.get('maxDrawdownRiskUnits')}",
        f"- verdict: {overall_verdict.get('level')} | risk cap {overall.get('riskUnitCap')}",
        "",
        "Strategy gates:",
    ]
    if not lab.get("strategies"):
        lines.append("- no strategy tickets recorded yet")
    for item in lab.get("strategies", []):
        item_verdict = item.get("verdict") or {}
        item_confidence = item.get("expectancyPerRiskConfidence") or {}
        lines.append(
            f"- {item.get('strategy')}: {item.get('scoredCount')} scored | "
            f"win LB {item.get('winRateLowerBound')}/{item.get('winRateLowerBoundTarget')} | "
            f"exp LB {item_confidence.get('lower')} | "
            f"PF {item.get('profitFactor')} | "
            f"{item_verdict.get('level')} | cap {item.get('riskUnitCap')}"
        )
        for blocker in (item_verdict.get("blockers") or [])[:3]:
            lines.append(f"  blocker: {blocker}")
    return "\n".join(lines).rstrip() + "\n"


def save_strategy_lab(lab: dict[str, Any]) -> None:
    """Persist JSON and text strategy-lab artifacts."""
    ensure_dirs()
    atomic_write_json(STRATEGY_LAB_FILE, lab)
    atomic_write_text(STRATEGY_LAB_TEXT_FILE, strategy_lab_text(lab))


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for local/operator use."""
    parser = argparse.ArgumentParser(description="Build the Inferno strategy evidence lab.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    """CLI entry point for building or viewing the latest strategy lab."""
    args = parse_args()
    if args.command == "status" and STRATEGY_LAB_TEXT_FILE.exists():
        print(STRATEGY_LAB_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    lab = build_strategy_lab()
    save_strategy_lab(lab)
    print(strategy_lab_text(lab))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
