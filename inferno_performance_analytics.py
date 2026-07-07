from __future__ import annotations

"""Performance analytics for the Inferno paper ledger.

This is the beginning of the desk's evidence engine. It summarizes paper tickets,
closed outcomes, block reasons, and strategy-level expectancy so future
automation decisions can be promoted by data instead of confidence theater.
"""

import argparse
import json
from collections import Counter, defaultdict
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_paper_execution import load_ledger
from inferno_trade_evidence import normalized_outcome, strategy_family
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


PERFORMANCE_ANALYTICS_FILE = DATA_DIR / "inferno_performance_analytics.json"
PERFORMANCE_ANALYTICS_TEXT_FILE = REPORTS_DIR / "performance_analytics_latest.txt"
MIN_SAMPLE_FOR_PROMOTION = 30
MIN_EXPECTANCY_FOR_PROMOTION = 1.0
MAX_FALSE_POSITIVE_RATE = 0.45
MIN_PROFIT_FACTOR_FOR_PROMOTION = 1.25


def number(value: Any, default: float = 0.0) -> float:
    """Safely coerce loose ledger values into floats."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def outcome_status(ticket: dict[str, Any]) -> str:
    """Return normalized outcome status for one paper ticket."""
    outcome = ticket.get("outcome") or {}
    return str(outcome.get("status") or "unknown")


def estimated_pnl(ticket: dict[str, Any]) -> float | None:
    """Return estimated P/L when an outcome has been closed."""
    outcome = ticket.get("outcome") or {}
    if outcome.get("estimatedPnl") is None:
        return None
    return number(outcome.get("estimatedPnl"))


def max_loss(ticket: dict[str, Any]) -> float:
    """Return ticket max loss dollars for return-on-risk calculations."""
    metrics = ((ticket.get("riskVerdict") or {}).get("metrics") or {})
    if metrics.get("maxLossDollars") is not None:
        return max(0.0, number(metrics.get("maxLossDollars")))
    return max(0.0, number(ticket.get("estimatedMaxLoss")))


def return_on_risk(ticket: dict[str, Any]) -> float | None:
    """Return P/L divided by max loss for one closed paper ticket."""
    pnl = estimated_pnl(ticket)
    risk = max_loss(ticket)
    if pnl is None or risk <= 0:
        return None
    return round(pnl / risk, 6)


def strategy_key(ticket: dict[str, Any]) -> str:
    """Group tickets by strategy, preserving unknowns for audit visibility."""
    return str(ticket.get("strategy") or ticket.get("setupRec") or "UNKNOWN")


def arm_key(ticket: dict[str, Any]) -> str:
    """Return a pre-registered campaign arm label when one is present."""
    arm = str(ticket.get("arm") or ticket.get("campaignArm") or "").upper().strip()
    return arm if arm in {"A", "B", "C", "D"} else ""


def summarize_closed_tickets(tickets: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate P/L metrics for closed paper tickets."""
    closed = [ticket for ticket in tickets if outcome_status(ticket) == "closed"]
    pnls = [estimated_pnl(ticket) for ticket in closed if estimated_pnl(ticket) is not None]
    returns = [value for value in (return_on_risk(ticket) for ticket in closed) if value is not None]
    normalized = [normalized_outcome(ticket) for ticket in closed]
    gross_r = [row["grossR"] for row in normalized if row.get("grossR") is not None]
    net_r = [row["netREstimate"] for row in normalized if row.get("netREstimate") is not None]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    total_loss_abs = abs(sum(losses))
    win_rate = round(len(wins) / len(pnls), 4) if pnls else None
    avg_win = round(sum(wins) / len(wins), 2) if wins else None
    avg_loss = round(sum(losses) / len(losses), 2) if losses else None
    return {
        "closedCount": len(closed),
        "scoredCount": len(pnls),
        "winCount": len(wins),
        "lossCount": len(losses),
        "winRate": win_rate,
        "totalPnl": round(sum(pnls), 2),
        "averagePnl": round(sum(pnls) / len(pnls), 2) if pnls else None,
        "averageWin": avg_win,
        "averageLoss": avg_loss,
        "payoffRatio": round(abs(avg_win / avg_loss), 4) if avg_win is not None and avg_loss else None,
        "profitFactor": round(sum(wins) / total_loss_abs, 4) if total_loss_abs else None,
        "expectancy": round(sum(pnls) / len(pnls), 2) if pnls else None,
        "expectancyPerDollarRisk": round(sum(returns) / len(returns), 6) if returns else None,
        "averageGrossR": round(sum(gross_r) / len(gross_r), 6) if gross_r else None,
        "averageNetREstimate": round(sum(net_r) / len(net_r), 6) if net_r else None,
        "estimatedFrictionDollars": round(
            sum(row.get("estimatedFrictionDollars") or 0.0 for row in normalized),
            2,
        ),
        "netRDataQuality": "modeled-friction-not-realized",
        "tradeSharpe": sharpe_ratio(returns),
        "tradeSortino": sortino_ratio(returns),
        "maxDrawdownDollars": max_drawdown(pnls),
        "historicalVar95": historical_var(pnls, confidence=0.95),
        "historicalCvar95": historical_cvar(pnls, confidence=0.95),
        "kellyFraction": kelly_fraction(win_rate, avg_win, avg_loss),
    }


def mean(values: list[float]) -> float | None:
    """Mean helper that returns None for empty samples."""
    return sum(values) / len(values) if values else None


def sample_std(values: list[float]) -> float | None:
    """Sample standard deviation for small trade-return samples."""
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    variance = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
    return variance ** 0.5


def downside_std(values: list[float], target: float = 0.0) -> float | None:
    """Downside deviation below target return."""
    downside = [min(0.0, value - target) for value in values]
    if len(downside) < 2:
        return None
    variance = sum(value ** 2 for value in downside) / (len(downside) - 1)
    return variance ** 0.5


def sharpe_ratio(returns: list[float]) -> float | None:
    """Trade-level Sharpe-like ratio using return-on-risk samples."""
    avg = mean(returns)
    std = sample_std(returns)
    if avg is None or not std:
        return None
    return round(avg / std, 4)


def sortino_ratio(returns: list[float]) -> float | None:
    """Trade-level Sortino-like ratio using downside return-on-risk samples."""
    avg = mean(returns)
    downside = downside_std(returns)
    if avg is None or not downside:
        return None
    return round(avg / downside, 4)


def max_drawdown(pnls: list[float]) -> float | None:
    """Calculate peak-to-trough drawdown on cumulative paper P/L."""
    if not pnls:
        return None
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return round(worst, 2)


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile helper."""
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * pct))))
    return ordered[index]


def historical_var(pnls: list[float], confidence: float = 0.95) -> float | None:
    """Historical left-tail VaR on paper P/L samples."""
    value = percentile(pnls, 1 - confidence)
    return round(value, 2) if value is not None else None


def historical_cvar(pnls: list[float], confidence: float = 0.95) -> float | None:
    """Historical expected shortfall / CVaR on the left tail."""
    threshold = historical_var(pnls, confidence)
    if threshold is None:
        return None
    tail = [pnl for pnl in pnls if pnl <= threshold]
    return round(sum(tail) / len(tail), 2) if tail else None


def kelly_fraction(win_rate: float | None, average_win: float | None, average_loss: float | None) -> float | None:
    """Approximate Kelly fraction from win rate and payoff ratio.

    This is informational only. The execution policy does not size trades from
    Kelly because event options can gap violently and samples will be tiny early.
    """
    if win_rate is None or average_win is None or not average_loss:
        return None
    payoff = abs(average_win / average_loss)
    if payoff <= 0:
        return None
    kelly = win_rate - ((1 - win_rate) / payoff)
    return round(max(0.0, kelly), 4)


def block_reason_counts(tickets: list[dict[str, Any]]) -> dict[str, int]:
    """Count every block reason across rejected and blocked tickets."""
    counter: Counter[str] = Counter()
    for ticket in tickets:
        for reason in ticket.get("blockReasons") or []:
            counter[str(reason)] += 1
    return dict(counter.most_common())


# Coarse-grained categorizer for the verbose block-reason strings. Each entry
# pairs a human-readable bucket label with substrings to match (case-insensitive).
# Order matters: the first matching bucket wins, so put the most specific
# categories first. Tickets without any blockReasons drop into "other".
BLOCK_REASON_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("approval-missing", ("human approval missing", "execution intent is not approval-ready")),
    ("size-cap-violation", ("exceeds single-ticket cap", "exceeds cap")),
    ("wide-spread", ("spread is wide", "spread too wide")),
    ("reward-risk-floor", ("reward/risk", "below debit-spread floor")),
    ("missing-quote", ("no quote", "no bid", "no ask", "missing quote")),
    ("strike-plan-error", ("no supported strike plan", "no option expirations")),
    ("setup-concentration-cap", ("setup-concentration-cap", "concentration cap")),
    ("exception", ("error:", "keyerror", "valueerror", "exception")),
)


def categorize_block_reason(reason: str) -> str:
    """Map a verbose block-reason string to a coarse, actionable bucket."""
    text = (reason or "").lower()
    for label, needles in BLOCK_REASON_CATEGORIES:
        for needle in needles:
            if needle in text:
                return label
    return "other"


def block_reason_categories(tickets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Group block reasons into coarse buckets with counts and example strings.

    The verbose ``topBlockReasons`` is great for forensic detail but unwieldy at
    a glance. This view collapses 40+ unique strings into a handful of buckets
    so the desk can see the dominant funnel killer instantly. Each bucket keeps
    up to three example strings for context.
    """
    bucket_counts: Counter[str] = Counter()
    bucket_examples: dict[str, list[str]] = {}
    for ticket in tickets:
        for reason in ticket.get("blockReasons") or []:
            label = categorize_block_reason(str(reason))
            bucket_counts[label] += 1
            examples = bucket_examples.setdefault(label, [])
            if len(examples) < 3 and reason not in examples:
                examples.append(str(reason))
    return {
        label: {"count": count, "examples": bucket_examples.get(label, [])}
        for label, count in bucket_counts.most_common()
    }


def risk_summary(tickets: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize risk exposure metrics from the latest verdicts."""
    max_losses: list[float] = []
    reward_risk_values: list[float] = []
    for ticket in tickets:
        metrics = ((ticket.get("riskVerdict") or {}).get("metrics") or {})
        if metrics.get("maxLossDollars") is not None:
            max_losses.append(number(metrics.get("maxLossDollars")))
        if metrics.get("debitSpreadRewardRisk") is not None:
            reward_risk_values.append(number(metrics.get("debitSpreadRewardRisk")))
    return {
        "averageMaxLoss": round(sum(max_losses) / len(max_losses), 2) if max_losses else None,
        "largestMaxLoss": round(max(max_losses), 2) if max_losses else None,
        "averageRewardRisk": round(sum(reward_risk_values) / len(reward_risk_values), 4) if reward_risk_values else None,
        "bestRewardRisk": round(max(reward_risk_values), 4) if reward_risk_values else None,
        "worstRewardRisk": round(min(reward_risk_values), 4) if reward_risk_values else None,
    }


def leg_spread_pct(leg: dict[str, Any]) -> float | None:
    """Calculate bid/ask spread percentage from a leg's midpoint."""
    bid = number(leg.get("bid"))
    ask = number(leg.get("ask"))
    mid = number(leg.get("mid"))
    if mid <= 0:
        mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0
    if mid <= 0 or ask <= 0:
        return None
    return round(max(0.0, (ask - bid) / mid), 6)


def liquidity_summary(tickets: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize option quote quality across all ledger legs."""
    spreads: list[float] = []
    zero_volume_legs = 0
    zero_open_interest_legs = 0
    total_legs = 0
    for ticket in tickets:
        for leg in ticket.get("legs", []):
            total_legs += 1
            spread = leg_spread_pct(leg)
            if spread is not None:
                spreads.append(spread)
            if number(leg.get("volume")) <= 0:
                zero_volume_legs += 1
            if number(leg.get("openInterest")) <= 0:
                zero_open_interest_legs += 1
    return {
        "totalLegs": total_legs,
        "averageSpreadPct": round(sum(spreads) / len(spreads), 6) if spreads else None,
        "widestSpreadPct": round(max(spreads), 6) if spreads else None,
        "zeroVolumeLegs": zero_volume_legs,
        "zeroOpenInterestLegs": zero_open_interest_legs,
    }


def strategy_summary(tickets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate tickets and outcomes by strategy."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ticket in tickets:
        grouped[strategy_key(ticket)].append(ticket)

    summaries: list[dict[str, Any]] = []
    for strategy, items in sorted(grouped.items()):
        closed_metrics = summarize_closed_tickets(items)
        blocked_count = sum(1 for item in items if item.get("status") == "paper-blocked")
        rejected_count = sum(1 for item in items if item.get("status") == "paper-rejected")
        staged_count = sum(1 for item in items if item.get("status") == "paper-staged")
        false_positive_rate = round((blocked_count + rejected_count) / len(items), 4) if items else None
        eligible_for_promotion = (
            closed_metrics["scoredCount"] >= MIN_SAMPLE_FOR_PROMOTION
            and (closed_metrics["expectancy"] or 0) >= MIN_EXPECTANCY_FOR_PROMOTION
            and (closed_metrics["profitFactor"] or 0) >= MIN_PROFIT_FACTOR_FOR_PROMOTION
            and (false_positive_rate or 1) <= MAX_FALSE_POSITIVE_RATE
        )
        summaries.append(
            {
                "strategy": strategy,
                "count": len(items),
                "paperStaged": staged_count,
                "blocked": blocked_count,
                "rejected": rejected_count,
                "falsePositiveRate": false_positive_rate,
                "closed": closed_metrics,
                "eligibleForPromotion": eligible_for_promotion,
                "promotionReason": (
                    "eligible for next review gate"
                    if eligible_for_promotion
                    else f"needs {MIN_SAMPLE_FOR_PROMOTION} scored tickets and positive expectancy"
                ),
            }
        )
    return summaries


def family_summary(tickets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate the same closed metrics by comparable strategy family."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ticket in tickets:
        grouped[strategy_family(ticket)].append(ticket)
    return [
        {"family": family, **summarize_closed_tickets(items)}
        for family, items in sorted(grouped.items())
    ]


def arm_summary(tickets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate paper outcomes by pre-registered campaign arm."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ticket in tickets:
        arm = arm_key(ticket)
        if arm:
            grouped[arm].append(ticket)
    return [
        {
            "arm": arm,
            "count": len(items),
            "exitRule": next((item.get("exitRule") or item.get("campaignExitRule") for item in items if item.get("exitRule") or item.get("campaignExitRule")), None),
            **summarize_closed_tickets(items),
        }
        for arm, items in sorted(grouped.items())
    ]


def build_performance_analytics(ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the current analytics package from the paper ledger."""
    ledger = ledger or load_ledger()
    tickets = ledger.get("items", [])
    statuses = Counter(str(ticket.get("status") or "unknown") for ticket in tickets)
    outcomes = Counter(outcome_status(ticket) for ticket in tickets)
    closed = summarize_closed_tickets(tickets)
    blocks = block_reason_counts(tickets)
    block_categories = block_reason_categories(tickets)
    strategies = strategy_summary(tickets)
    families = family_summary(tickets)
    arms = arm_summary(tickets)
    analytics = {
        "generatedAt": local_now().isoformat(),
        "sourceLedgerUpdatedAt": ledger.get("updatedAt"),
        "count": len(tickets),
        "statusCounts": dict(statuses),
        "outcomeCounts": dict(outcomes),
        "closedMetrics": closed,
        "riskSummary": risk_summary(tickets),
        "liquiditySummary": liquidity_summary(tickets),
        "topBlockReasons": blocks,
        "blockReasonCategories": block_categories,
        "strategies": strategies,
        "families": families,
        "armSummary": arms,
        "deskVerdict": desk_verdict(closed, strategies, blocks),
    }
    return analytics


def desk_verdict(closed: dict[str, Any], strategies: list[dict[str, Any]], blocks: dict[str, int]) -> dict[str, Any]:
    """Produce a conservative desk-level automation verdict."""
    promoted = [item["strategy"] for item in strategies if item.get("eligibleForPromotion")]
    if promoted:
        return {
            "level": "review-for-more-authority",
            "message": f"Strategies ready for next review gate: {', '.join(promoted)}",
        }
    if closed.get("scoredCount", 0) < MIN_SAMPLE_FOR_PROMOTION:
        return {
            "level": "evidence-building",
            "message": f"Need at least {MIN_SAMPLE_FOR_PROMOTION} scored paper tickets before promotion review.",
        }
    if blocks:
        top_reason = next(iter(blocks))
        return {
            "level": "tighten-filters",
            "message": f"Most common block: {top_reason}",
        }
    return {
        "level": "hold",
        "message": "No promotion signal yet.",
    }


def analytics_text(analytics: dict[str, Any]) -> str:
    """Render analytics as a concise operator report."""
    closed = analytics.get("closedMetrics") or {}
    risk = analytics.get("riskSummary") or {}
    liquidity = analytics.get("liquiditySummary") or {}
    verdict = analytics.get("deskVerdict") or {}
    lines = [
        "Inferno Performance Analytics",
        "",
        f"Generated: {analytics.get('generatedAt')}",
        f"Ledger updated: {analytics.get('sourceLedgerUpdatedAt')}",
        f"Tickets: {analytics.get('count', 0)}",
        f"Desk verdict: {verdict.get('level')} - {verdict.get('message')}",
        "",
        "Status counts:",
    ]
    for status, count in sorted((analytics.get("statusCounts") or {}).items()):
        lines.append(f"- {status}: {count}")

    lines.extend(
        [
            "",
            "Closed-ticket metrics:",
            f"- scored: {closed.get('scoredCount', 0)}",
            f"- win rate: {closed.get('winRate')}",
            f"- expectancy: {closed.get('expectancy')}",
            f"- average gross R: {closed.get('averageGrossR')}",
            f"- average net R estimate: {closed.get('averageNetREstimate')}",
            f"- modeled friction: {closed.get('estimatedFrictionDollars')}",
            f"- total P/L: {closed.get('totalPnl')}",
            "",
            "Risk profile:",
            f"- average max loss: {risk.get('averageMaxLoss')}",
            f"- largest max loss: {risk.get('largestMaxLoss')}",
            f"- average reward/risk: {risk.get('averageRewardRisk')}",
            "",
            "Liquidity profile:",
            f"- total option legs: {liquidity.get('totalLegs')}",
            f"- average spread pct: {liquidity.get('averageSpreadPct')}",
            f"- widest spread pct: {liquidity.get('widestSpreadPct')}",
            f"- zero volume legs: {liquidity.get('zeroVolumeLegs')}",
            f"- zero open-interest legs: {liquidity.get('zeroOpenInterestLegs')}",
            "",
            "Top block reasons:",
        ]
    )
    block_reasons = analytics.get("topBlockReasons") or {}
    if block_reasons:
        for reason, count in list(block_reasons.items())[:8]:
            lines.append(f"- {count}x {reason}")
    else:
        lines.append("- none")

    lines.extend(["", "Block reason categories:"])
    block_categories = analytics.get("blockReasonCategories") or {}
    if block_categories:
        for label, payload in list(block_categories.items())[:8]:
            example = (payload.get("examples") or ["-"])[0]
            lines.append(f"- {payload.get('count', 0)}x {label} (e.g. {example})")
    else:
        lines.append("- none")

    lines.extend(["", "Strategy table:"])
    for item in analytics.get("strategies", []):
        closed_metrics = item.get("closed") or {}
        lines.append(
            f"- {item.get('strategy')}: {item.get('count')} tickets | "
            f"staged {item.get('paperStaged')} | blocked {item.get('blocked')} | "
            f"closed {closed_metrics.get('scoredCount')} | expectancy {closed_metrics.get('expectancy')} | "
            f"promotion {item.get('eligibleForPromotion')}"
        )
    lines.extend(["", "Campaign arm table:"])
    arms = analytics.get("armSummary") or []
    if arms:
        for item in arms:
            lines.append(
                f"- {item.get('arm')}: n={item.get('count')} | exit={item.get('exitRule')} | "
                f"closed={item.get('scoredCount')} | grossR={item.get('averageGrossR')} | "
                f"netR={item.get('averageNetREstimate')} | friction=${item.get('estimatedFrictionDollars')}"
            )
    else:
        lines.append("- none")
    lines.extend(["", "Strategy-family net-R table:"])
    for item in analytics.get("families") or []:
        lines.append(
            f"- {item.get('family')}: n={item.get('scoredCount')} | "
            f"grossR={item.get('averageGrossR')} | netR={item.get('averageNetREstimate')} | "
            f"friction=${item.get('estimatedFrictionDollars')}"
        )
    return "\n".join(lines).rstrip() + "\n"


def save_performance_analytics(analytics: dict[str, Any]) -> None:
    """Persist JSON and text analytics artifacts."""
    ensure_dirs()
    atomic_write_json(PERFORMANCE_ANALYTICS_FILE, analytics)
    atomic_write_text(PERFORMANCE_ANALYTICS_TEXT_FILE, analytics_text(analytics))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build performance analytics from the Inferno paper ledger.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and PERFORMANCE_ANALYTICS_TEXT_FILE.exists():
        print(PERFORMANCE_ANALYTICS_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    analytics = build_performance_analytics()
    save_performance_analytics(analytics)
    print(analytics_text(analytics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
