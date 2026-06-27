from __future__ import annotations

"""Promotion gap analyzer for the Inferno strategy lab.

Reads the live strategy_lab.json artifact and reports the exact distance from
current desk state to each promotion-gate threshold. Where it can, it also
estimates how many additional scored paper tickets would close the gap if the
current hit rate holds — useful as a tactical "what's left to do" diagnostic
for the operator and the model.

This is research/diagnostic only:
- it does not modify any other artifact
- it cannot promote broker authority
- it cannot change any threshold
"""

import argparse
import json
from typing import Any

from inferno_config import local_now
from inferno_strategy_lab import (
    MAX_DRAWDOWN_RISK_UNITS,
    MAX_FALSE_POSITIVE_RATE,
    MIN_EXPECTANCY_LOWER_BOUND,
    MIN_PROFIT_FACTOR,
    MIN_SCORED_TRADES_FOR_PROMOTION,
    MIN_WIN_RATE_LOWER_BOUND,
    STRATEGY_LAB_FILE,
    WIN_RATE_BREAKEVEN_MARGIN,
    win_rate_floor_from_payoff,
    wilson_lower_bound,
)
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


PROMOTION_GAP_FILE = DATA_DIR / "inferno_promotion_gap.json"
PROMOTION_GAP_TEXT_FILE = REPORTS_DIR / "promotion_gap_latest.txt"
PROMOTION_GAP_STAGE = "promotion-gap-research-only"
# A safety ceiling on the trade projection loop so a hopeless hit rate cannot
# spin forever. If the answer is "more than 1000 trades," the operator should
# revisit the strategy, not wait for the analyzer.
MAX_PROJECTION_TRADES = 1000


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _gap(target: float | None, current: float | None) -> float | None:
    """Return the additive gap (target - current). Negative means cleared."""
    if target is None or current is None:
        return None
    return round(target - current, 6)


def trades_to_winrate_floor(
    wins: int, total: int, *, target: float = MIN_WIN_RATE_LOWER_BOUND,
    max_trades: int = MAX_PROJECTION_TRADES,
) -> int | None:
    """Project how many more trades clear the Wilson lower-bound floor.

    Holds the current hit rate constant. Returns ``None`` when the projection
    would exceed ``max_trades`` (i.e., the strategy is too far from the gate
    for a sample-size fix to plausibly close the gap).
    """
    if total <= 0:
        return None
    hit_rate = wins / total
    # Already cleared.
    current_lower = wilson_lower_bound(wins, total) or 0.0
    if current_lower >= target:
        return 0
    extra = 0
    extra_wins = 0.0
    while extra < max_trades:
        extra += 1
        extra_wins += hit_rate
        projected_wins = int(round(wins + extra_wins))
        projected_total = total + extra
        bound = wilson_lower_bound(projected_wins, projected_total) or 0.0
        if bound >= target:
            return extra
    return None


def analyze_strategy(strategy: dict[str, Any]) -> dict[str, Any]:
    """Compute the gap dictionary for one strategy summary."""
    win_count = int(strategy.get("winCount") or 0)
    loss_count = int(strategy.get("lossCount") or 0)
    scored_count = int(strategy.get("scoredCount") or 0)
    win_rate_lower = _safe_float(strategy.get("winRateLowerBound"))
    payoff_ratio = _safe_float(strategy.get("payoffRatio"))
    floor = win_rate_floor_from_payoff(payoff_ratio)
    win_rate_target = _safe_float(
        strategy.get("winRateLowerBoundTarget")
        if strategy.get("winRateLowerBoundTarget") is not None
        else floor.get("winRateLowerBoundTarget")
    )
    win_rate_target_source = (
        strategy.get("winRateLowerBoundTargetSource")
        or floor.get("winRateLowerBoundTargetSource")
    )
    win_rate_breakeven = _safe_float(
        strategy.get("winRateBreakeven")
        if strategy.get("winRateBreakeven") is not None
        else floor.get("winRateBreakeven")
    )
    expectancy = (strategy.get("expectancyPerRiskConfidence") or {}).get("lower")
    expectancy_lower = _safe_float(expectancy)
    profit_factor = _safe_float(strategy.get("profitFactor"))
    false_positive = _safe_float(strategy.get("falsePositiveRate"))
    drawdown = _safe_float(strategy.get("maxDrawdownRiskUnits"))

    cleared = {
        "scoredCount": scored_count >= MIN_SCORED_TRADES_FOR_PROMOTION,
        "winRateLowerBound": (win_rate_lower or 0.0) >= (win_rate_target or MIN_WIN_RATE_LOWER_BOUND),
        "expectancyLowerBound": (expectancy_lower if expectancy_lower is not None else -1.0)
        >= MIN_EXPECTANCY_LOWER_BOUND,
        "profitFactor": (profit_factor or 0.0) >= MIN_PROFIT_FACTOR,
        "falsePositiveRate": (false_positive if false_positive is not None else 1.0)
        <= MAX_FALSE_POSITIVE_RATE,
        "drawdown": (drawdown if drawdown is not None else MAX_DRAWDOWN_RISK_UNITS - 1)
        >= MAX_DRAWDOWN_RISK_UNITS,
    }
    gates_open = sum(1 for value in cleared.values() if value)
    gates_total = len(cleared)

    projected_extra_for_winrate = trades_to_winrate_floor(
        win_count,
        win_count + loss_count,
        target=win_rate_target or MIN_WIN_RATE_LOWER_BOUND,
    )

    return {
        "strategy": strategy.get("strategy"),
        "scoredCount": scored_count,
        "scoredCountTarget": MIN_SCORED_TRADES_FOR_PROMOTION,
        "scoredCountGap": max(0, MIN_SCORED_TRADES_FOR_PROMOTION - scored_count),
        "winRateLowerBound": win_rate_lower,
        "winRateLowerBoundTarget": win_rate_target,
        "winRateLowerBoundGap": _gap(win_rate_target, win_rate_lower),
        "winRateLowerBoundTargetSource": win_rate_target_source,
        "winRateBreakeven": win_rate_breakeven,
        "winRateBreakevenMargin": WIN_RATE_BREAKEVEN_MARGIN,
        "payoffRatio": payoff_ratio,
        "expectancyLowerBound": expectancy_lower,
        "expectancyLowerBoundTarget": MIN_EXPECTANCY_LOWER_BOUND,
        "expectancyLowerBoundGap": _gap(MIN_EXPECTANCY_LOWER_BOUND, expectancy_lower),
        "profitFactor": profit_factor,
        "profitFactorTarget": MIN_PROFIT_FACTOR,
        "profitFactorGap": _gap(MIN_PROFIT_FACTOR, profit_factor),
        "falsePositiveRate": false_positive,
        "falsePositiveRateCap": MAX_FALSE_POSITIVE_RATE,
        "drawdownRiskUnits": drawdown,
        "drawdownFloor": MAX_DRAWDOWN_RISK_UNITS,
        "tradesToWinRateFloor": projected_extra_for_winrate,
        "gatesOpen": gates_open,
        "gatesTotal": gates_total,
        "promotable": all(cleared.values()),
    }


def build_promotion_gap(lab: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the full promotion-gap analysis from a strategy_lab payload."""
    lab = lab if lab is not None else (load_json_file(STRATEGY_LAB_FILE) or {})
    strategies = lab.get("strategies") or []
    overall = lab.get("overall") or {}
    return {
        "generatedAt": local_now().isoformat(),
        "stage": PROMOTION_GAP_STAGE,
        "researchOnly": True,
        "promotable": False,
        "sourceLabGeneratedAt": lab.get("generatedAt"),
        "thresholds": {
            "scoredTradesForPromotion": MIN_SCORED_TRADES_FOR_PROMOTION,
            "winRateFloorMode": "payoff-implied-breakeven-plus-margin",
            "winRateBreakevenMargin": WIN_RATE_BREAKEVEN_MARGIN,
            "legacyFixedWinRateLowerBound": MIN_WIN_RATE_LOWER_BOUND,
            "expectancyLowerBound": MIN_EXPECTANCY_LOWER_BOUND,
            "profitFactor": MIN_PROFIT_FACTOR,
            "falsePositiveRateCap": MAX_FALSE_POSITIVE_RATE,
            "drawdownRiskUnitFloor": MAX_DRAWDOWN_RISK_UNITS,
        },
        "overall": analyze_strategy(overall) if overall else None,
        "strategies": [analyze_strategy(item) for item in strategies],
        "researchNotes": [
            "diagnostic-only; cannot change any lab threshold",
            "trades-to-floor projection assumes the current hit rate holds",
        ],
    }


def gap_text(gap: dict[str, Any]) -> str:
    """Render the gap analysis as a short operator memo."""
    overall = gap.get("overall") or {}
    lines = [
        "Inferno Promotion Gap (research-only)",
        "",
        f"Generated: {gap.get('generatedAt')}",
        f"Stage: {gap.get('stage')}",
        f"Source lab generated at: {gap.get('sourceLabGeneratedAt')}",
        "",
        f"Overall promotable: {overall.get('promotable')}",
        f"Overall gates open: {overall.get('gatesOpen')}/{overall.get('gatesTotal')}",
        "",
        "Overall gaps:",
        f"- scored trades:        {overall.get('scoredCount')}/{overall.get('scoredCountTarget')} "
        f"(gap {overall.get('scoredCountGap')})",
        f"- win-rate lower bound: {overall.get('winRateLowerBound')} vs {overall.get('winRateLowerBoundTarget')} "
        f"(gap {overall.get('winRateLowerBoundGap')}; {overall.get('winRateLowerBoundTargetSource')})",
        f"- payoff breakeven:     {overall.get('winRateBreakeven')} + margin "
        f"{overall.get('winRateBreakevenMargin')} | payoff ratio {overall.get('payoffRatio')}",
        f"- expectancy lower:     {overall.get('expectancyLowerBound')} vs {overall.get('expectancyLowerBoundTarget')} "
        f"(gap {overall.get('expectancyLowerBoundGap')})",
        f"- profit factor:        {overall.get('profitFactor')} vs {overall.get('profitFactorTarget')} "
        f"(gap {overall.get('profitFactorGap')})",
        f"- false-positive rate:  {overall.get('falsePositiveRate')} vs cap {overall.get('falsePositiveRateCap')}",
        f"- drawdown (R units):   {overall.get('drawdownRiskUnits')} vs floor {overall.get('drawdownFloor')}",
        f"- trades to clear win-rate floor at current hit rate: {overall.get('tradesToWinRateFloor')}",
        "",
        "Per-strategy gates open:",
    ]
    for strat in gap.get("strategies") or []:
        lines.append(
            f"- {strat.get('strategy')}: "
            f"{strat.get('gatesOpen')}/{strat.get('gatesTotal')} "
            f"| scored {strat.get('scoredCount')}/{strat.get('scoredCountTarget')} "
            f"| trades-to-WR-floor {strat.get('tradesToWinRateFloor')}"
        )
    lines.extend(
        [
            "",
            "Reminders:",
            "- diagnostic only; no thresholds were changed",
            "- cannot promote broker submission authority",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def save_promotion_gap(gap: dict[str, Any]) -> None:
    """Persist the gap JSON and text artifacts."""
    ensure_dirs()
    PROMOTION_GAP_FILE.write_text(json.dumps(gap, indent=2), encoding="utf-8")
    PROMOTION_GAP_TEXT_FILE.write_text(gap_text(gap), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnostic: report the gap between current strategy lab state and "
            "promotion-gate thresholds. Research only."
        )
    )
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and PROMOTION_GAP_TEXT_FILE.exists():
        print(PROMOTION_GAP_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    gap = build_promotion_gap()
    save_promotion_gap(gap)
    print(gap_text(gap))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
