from __future__ import annotations

"""Build a research-only sizing, positioning, and timing plan.

The capital allocator divides available cash into sleeves. This companion view
starts from total NLV and subtracts current holdings before suggesting that any
cash is deployable. It also reconciles tracker candidate prices with Schwab
daily closes and makes the evidence/timing constraints explicit.

It never changes authority, stages an order, or submits to a broker.
"""

import argparse
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


SIZING_POSITIONING_TIMING_FILE = DATA_DIR / "inferno_sizing_positioning_timing.json"
SIZING_POSITIONING_TIMING_TEXT_FILE = REPORTS_DIR / "sizing_positioning_timing_latest.txt"
SCHWAB_ACCOUNT_FILE = DATA_DIR / "inferno_schwab_account_sync.json"
STRATEGY_LAB_FILE = DATA_DIR / "inferno_strategy_lab.json"
CAPITAL_SCALING_FILE = DATA_DIR / "inferno_capital_scaling.json"
EDGE_RESEARCH_FILE = DATA_DIR / "inferno_edge_research.json"
SCHWAB_PRICE_HISTORY_FILE = DATA_DIR / "inferno_schwab_price_history.json"
FAST_PAPER_FILE = DATA_DIR / "inferno_fast_paper_cohort.json"
EXPECTED_MOVE_FILE = DATA_DIR / "inferno_expected_move_ledger.json"
LATEST_SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"

STAGE = "sizing-positioning-timing-research-only"
NEW_NAME_STARTER_LOW_PCT = 0.05
NEW_NAME_STARTER_HIGH_PCT = 0.075
NEW_NAME_REVIEW_CAP_PCT = 0.10
AGGRESSIVE_EQUITY_CEILING_PCT = 0.65
MATERIAL_PRICE_DRIFT_PCT = 0.02


def number(value: Any, default: float = 0.0) -> float:
    """Coerce loose numeric values into floats."""
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value or "").replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return default


def standard_policy_sleeves(nlv: float) -> dict[str, float]:
    """Mirror the operator-selected Standard NLV bands."""
    if nlv < 5_000:
        return {"options": 0.25, "longTerm": 0.50, "cash": 0.25}
    if nlv < 25_000:
        return {"options": 0.20, "longTerm": 0.60, "cash": 0.20}
    if nlv < 100_000:
        return {"options": 0.15, "longTerm": 0.70, "cash": 0.15}
    return {"options": 0.10, "longTerm": 0.80, "cash": 0.10}


def current_sleeves(account: dict[str, Any], nlv: float) -> dict[str, Any]:
    """Classify broker positions into equity, option, and cash sleeves."""
    equity = 0.0
    options = 0.0
    by_symbol: list[dict[str, Any]] = []
    for position in account.get("positions") or []:
        market_value = number(position.get("markValue"))
        asset_type = str(position.get("assetType") or "EQUITY").upper()
        if asset_type == "OPTION":
            options += market_value
        else:
            equity += market_value
        by_symbol.append(
            {
                "symbol": str(position.get("symbol") or "").upper(),
                "assetType": asset_type,
                "marketValue": round(market_value, 2),
                "weightPct": round(market_value / nlv * 100.0, 2) if nlv > 0 else 0.0,
            }
        )
    cash = number(account.get("totalCash"))
    return {
        "equityDollars": round(equity, 2),
        "optionDollars": round(options, 2),
        "cashDollars": round(cash, 2),
        "equityPct": round(equity / nlv, 4) if nlv > 0 else 0.0,
        "optionsPct": round(options / nlv, 4) if nlv > 0 else 0.0,
        "cashPct": round(cash / nlv, 4) if nlv > 0 else 0.0,
        "positions": sorted(by_symbol, key=lambda item: item["weightPct"], reverse=True),
    }


def evidence_adjusted_sleeves(
    policy: dict[str, float],
    strategy_promotable: bool,
) -> dict[str, float]:
    """Keep unearned options capital in cash until evidence promotes."""
    if strategy_promotable:
        return dict(policy)
    return {
        "options": 0.0,
        "longTerm": policy["longTerm"],
        "cash": policy["cash"] + policy["options"],
    }


def sleeve_gaps(
    current: dict[str, Any],
    target: dict[str, float],
    nlv: float,
) -> dict[str, Any]:
    """Return target-minus-current sleeve dollars and percentages."""
    rows: dict[str, Any] = {}
    mapping = {
        "options": ("optionDollars", "optionsPct"),
        "longTerm": ("equityDollars", "equityPct"),
        "cash": ("cashDollars", "cashPct"),
    }
    for sleeve, (dollar_key, pct_key) in mapping.items():
        target_dollars = nlv * target[sleeve]
        actual_dollars = number(current.get(dollar_key))
        rows[sleeve] = {
            "targetPct": round(target[sleeve], 4),
            "actualPct": round(number(current.get(pct_key)), 4),
            "targetDollars": round(target_dollars, 2),
            "actualDollars": round(actual_dollars, 2),
            "gapDollars": round(target_dollars - actual_dollars, 2),
            "overweightDollars": round(max(0.0, actual_dollars - target_dollars), 2),
            "underweightDollars": round(max(0.0, target_dollars - actual_dollars), 2),
        }
    return rows


def price_history_by_symbol(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index Schwab price-history rows by ticker."""
    return {
        str(row.get("symbol") or "").upper(): row
        for row in payload.get("rows") or []
        if row.get("symbol")
    }


def candidate_reconciliation(
    edge_research: dict[str, Any],
    price_history: dict[str, Any],
    snapshot: dict[str, Any],
    nlv: float,
) -> list[dict[str, Any]]:
    """Compare tracker candidate geometry with broker-derived daily closes."""
    history = price_history_by_symbol(price_history)
    snapshot_rows = {
        str(row.get("ticker") or "").upper(): row
        for row in snapshot.get("rows") or []
        if row.get("ticker")
    }
    rows: list[dict[str, Any]] = []
    for candidate in edge_research.get("topLongTermShovels") or []:
        ticker = str(candidate.get("ticker") or "").upper()
        market = candidate.get("marketContext") or {}
        tracker_row = snapshot_rows.get(ticker) or {}
        tracker_price = number(candidate.get("price"), number(tracker_row.get("price")))
        broker_row = history.get(ticker) or {}
        broker_close = number(broker_row.get("latestClose"))
        support = number(market.get("support"))
        drift = (
            (broker_close - tracker_price) / tracker_price
            if tracker_price > 0 and broker_close > 0
            else None
        )
        support_distance = (
            (broker_close - support) / support
            if support > 0 and broker_close > 0
            else None
        )
        one_share_pct = broker_close / nlv if nlv > 0 else None
        material_drift = drift is None or abs(drift) > MATERIAL_PRICE_DRIFT_PCT
        rows.append(
            {
                "ticker": ticker,
                "edgeScore": number(candidate.get("edgeScore")),
                "longTermScore": number(candidate.get("longTermScore")),
                "qualityScore": number((candidate.get("scores") or {}).get("qualityScore")),
                "trackerPrice": round(tracker_price, 2) if tracker_price > 0 else None,
                "schwabLastClose": round(broker_close, 2) if broker_close > 0 else None,
                "priceDriftPct": round(drift * 100.0, 2) if drift is not None else None,
                "materialPriceDrift": material_drift,
                "support": round(support, 2) if support > 0 else None,
                "schwabDistanceToSupportPct": (
                    round(support_distance * 100.0, 2)
                    if support_distance is not None
                    else None
                ),
                "oneSharePctOfNlv": (
                    round(one_share_pct * 100.0, 2)
                    if one_share_pct is not None
                    else None
                ),
                "priceHistoryLatestDate": broker_row.get("latestDate"),
                "decision": (
                    "reconcile-live-quote-before-sizing"
                    if material_drift
                    else "watch-for-broker-confirmed-support"
                ),
            }
        )
    return rows


def build_sizing_positioning_timing(
    artifacts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the total-account positioning and timing overlay."""
    source = artifacts or {
        "account": load_json_file(SCHWAB_ACCOUNT_FILE) or {},
        "strategyLab": load_json_file(STRATEGY_LAB_FILE) or {},
        "capitalScaling": load_json_file(CAPITAL_SCALING_FILE) or {},
        "edgeResearch": load_json_file(EDGE_RESEARCH_FILE) or {},
        "priceHistory": load_json_file(SCHWAB_PRICE_HISTORY_FILE) or {},
        "fastPaper": load_json_file(FAST_PAPER_FILE) or {},
        "expectedMove": load_json_file(EXPECTED_MOVE_FILE) or {},
        "snapshot": load_json_file(LATEST_SNAPSHOT_FILE) or {},
    }
    account = source.get("account") or {}
    strategy_lab = source.get("strategyLab") or {}
    scaling = source.get("capitalScaling") or {}
    edge = source.get("edgeResearch") or {}
    price_history = source.get("priceHistory") or {}
    fast_paper = source.get("fastPaper") or {}
    expected_move = source.get("expectedMove") or {}
    snapshot = source.get("snapshot") or {}

    nlv = number(account.get("netLiquidatingValue"))
    current = current_sleeves(account, nlv)
    policy = standard_policy_sleeves(nlv)
    strategy_promotable = bool(
        ((strategy_lab.get("deskVerdict") or {}).get("promotable"))
        or (((strategy_lab.get("overall") or {}).get("verdict") or {}).get("promotable"))
    )
    adjusted = evidence_adjusted_sleeves(policy, strategy_promotable)
    gaps = sleeve_gaps(current, adjusted, nlv)
    equity = current["equityDollars"]
    cash = current["cashDollars"]
    equity_target = adjusted["longTerm"]
    deposit_to_dilute = (
        max(0.0, equity / equity_target - nlv)
        if equity_target > 0 and nlv > 0
        else 0.0
    )
    aggressive_capacity = max(0.0, nlv * AGGRESSIVE_EQUITY_CEILING_PCT - equity)
    recommendation = scaling.get("recommendation") or {}
    overall_evidence = strategy_lab.get("overall") or {}
    fast_counts = fast_paper.get("counts") or {}
    expected_overall = expected_move.get("overall") or {}

    if gaps["longTerm"]["overweightDollars"] > 0 and not strategy_promotable:
        verdict = "rebuild-cash-and-prove-edge"
    elif gaps["longTerm"]["underweightDollars"] > 0:
        verdict = "conditional-equity-accumulation"
    else:
        verdict = "balanced-hold"

    candidates = candidate_reconciliation(edge, price_history, snapshot, nlv)
    return {
        "generatedAt": local_now().isoformat(),
        "stage": STAGE,
        "verdict": verdict,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "account": {
            "netLiquidatingValue": round(nlv, 2),
            "cash": round(cash, 2),
            "accountSuffix": account.get("matchedSuffix"),
        },
        "policySleeves": policy,
        "evidenceAdjustedSleeves": adjusted,
        "currentSleeves": current,
        "sleeveGaps": gaps,
        "positioningMath": {
            "equityTrimToAdjustedTargetDollars": gaps["longTerm"]["overweightDollars"],
            "cashDepositToDiluteEquityToAdjustedTargetDollars": round(deposit_to_dilute, 2),
            "newEquityCapacityAtStandardTargetDollars": gaps["longTerm"]["underweightDollars"],
            "newEquityCapacityAtAggressive65PctCeilingDollars": round(aggressive_capacity, 2),
            "newNameStarterLowDollars": round(nlv * NEW_NAME_STARTER_LOW_PCT, 2),
            "newNameStarterHighDollars": round(nlv * NEW_NAME_STARTER_HIGH_PCT, 2),
            "newNameReviewCapDollars": round(nlv * NEW_NAME_REVIEW_CAP_PCT, 2),
            "freezeAddsToExistingTheme": gaps["longTerm"]["overweightDollars"] > 0,
        },
        "optionsSizing": {
            "strategyPromotable": strategy_promotable,
            "liveMaxLossDollars": 0.0 if not strategy_promotable else number(
                recommendation.get("recommendedCap")
            ),
            "researchReferenceTicketDollars": number(recommendation.get("recommendedCap")),
            "researchReferenceDailyCapDollars": number(
                recommendation.get("recommendedDailyCap")
            ),
            "scoredPromotionTrades": int(number(overall_evidence.get("scoredCount"))),
            "remainingPromotionTrades": max(
                0, 30 - int(number(overall_evidence.get("scoredCount")))
            ),
        },
        "paperPositioning": {
            "fastPaperOpen": int(number(fast_counts.get("open"))),
            "fastPaperExitEligibleDate": min(
                [
                    str(row.get("exitEligibleDate"))
                    for row in fast_paper.get("openSlate") or []
                    if row.get("exitEligibleDate")
                ],
                default=None,
            ),
            "longVolExpectedMoveBeatRate": expected_overall.get("beatRate"),
            "longVolMeanMoveEdgePct": expected_overall.get("meanMoveEdgePct"),
            "nextCohortFamilyRule": (
                "At most 2 of 5 long-vol slots; reserve at least 2 slots for "
                "defined-risk directional structures and 1 for a neutral/credit comparison."
            ),
        },
        "candidateReconciliation": candidates,
        "timingPlan": [
            {
                "date": "2026-06-22",
                "phase": "reconcile",
                "action": (
                    "Refresh Schwab quotes after the open; do not trade the opening print. "
                    "Close due fast-paper simulations only on later-session bid/ask quotes."
                ),
            },
            {
                "date": "2026-06-23",
                "phase": "conditional-review",
                "action": (
                    "Review one starter share tranche only if the total-account sleeve gap "
                    "allows it and the broker price confirms support without a chase gap."
                ),
            },
            {
                "date": "2026-06-24",
                "phase": "pre-macro-hold",
                "action": (
                    "Avoid adding correlated high-beta exposure immediately ahead of the "
                    "June 25 GDP, PCE, and durable-goods release cluster."
                ),
            },
            {
                "date": "2026-06-25",
                "phase": "post-data-reprice",
                "action": (
                    "Wait at least 60 minutes after the 8:30 ET releases, then rerun price, "
                    "support, and spread checks before considering any tranche."
                ),
            },
            {
                "date": "2026-06-26",
                "phase": "confirm-or-preserve",
                "action": (
                    "Add only if post-event support holds and the position still fits the "
                    "portfolio target; otherwise preserve cash into the next week."
                ),
            },
        ],
        "nextActions": [
            "Treat total NLV, not available cash alone, as the sleeve-allocation denominator.",
            "Do not add to TE, IREN, HIVE, or CLSK while the equity/theme sleeve is above its evidence-adjusted target.",
            "Reconcile CHKP and DBX against Monday broker quotes before sizing; tracker prices are not authoritative.",
            "Keep live options max loss at $0 and use $25/$75 only as research ticket/daily reference caps.",
            "Diversify the next five-slot paper cohort away from the current long-vol concentration.",
        ],
        "operatorRule": (
            "Research overlay only. Any live position change requires a fresh broker quote, "
            "normal desk gates, and explicit operator confirmation."
        ),
    }


def money(value: Any) -> str:
    """Render dollars."""
    return f"${number(value):,.2f}"


def pct(value: Any) -> str:
    """Render a fraction as a percentage."""
    return f"{number(value) * 100.0:.1f}%"


def render_sizing_positioning_timing(payload: dict[str, Any]) -> str:
    """Render the positioning plan."""
    current = payload.get("currentSleeves") or {}
    policy = payload.get("policySleeves") or {}
    adjusted = payload.get("evidenceAdjustedSleeves") or {}
    gaps = payload.get("sleeveGaps") or {}
    math = payload.get("positioningMath") or {}
    options = payload.get("optionsSizing") or {}
    paper = payload.get("paperPositioning") or {}
    lines = [
        "Inferno Sizing, Positioning, and Timing",
        "=" * 39,
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Operator rule: {payload.get('operatorRule')}",
        "",
        "Total-account sleeve view",
        f"- Current: shares {pct(current.get('equityPct'))} | options {pct(current.get('optionsPct'))} | cash {pct(current.get('cashPct'))}",
        f"- Standard policy: shares {pct(policy.get('longTerm'))} | options {pct(policy.get('options'))} | cash {pct(policy.get('cash'))}",
        f"- Evidence-adjusted: shares {pct(adjusted.get('longTerm'))} | options {pct(adjusted.get('options'))} | cash {pct(adjusted.get('cash'))}",
        f"- Share overweight: {money((gaps.get('longTerm') or {}).get('overweightDollars'))}",
        f"- Cash shortfall to adjusted target: {money((gaps.get('cash') or {}).get('underweightDollars'))}",
        "",
        "Positioning math",
        f"- Trim needed to reach adjusted target now: {money(math.get('equityTrimToAdjustedTargetDollars'))}",
        f"- Cash deposit needed to dilute shares to target without trimming: {money(math.get('cashDepositToDiluteEquityToAdjustedTargetDollars'))}",
        f"- New share capacity at Standard target: {money(math.get('newEquityCapacityAtStandardTargetDollars'))}",
        f"- New share capacity at aggressive 65% ceiling: {money(math.get('newEquityCapacityAtAggressive65PctCeilingDollars'))}",
        f"- New-name starter band: {money(math.get('newNameStarterLowDollars'))} to {money(math.get('newNameStarterHighDollars'))}",
        f"- New-name review cap: {money(math.get('newNameReviewCapDollars'))}",
        "",
        "Options",
        f"- Live max loss now: {money(options.get('liveMaxLossDollars'))}",
        f"- Research ticket / daily reference: {money(options.get('researchReferenceTicketDollars'))} / {money(options.get('researchReferenceDailyCapDollars'))}",
        f"- Promotion evidence: {options.get('scoredPromotionTrades', 0)} scored | {options.get('remainingPromotionTrades', 0)} remaining",
        "",
        "Paper positioning",
        f"- Fast-paper open: {paper.get('fastPaperOpen', 0)} | exit eligible {paper.get('fastPaperExitEligibleDate')}",
        f"- Long-vol expected-move beat rate: {number(paper.get('longVolExpectedMoveBeatRate')) * 100.0:.1f}%",
        f"- Long-vol mean move edge: {number(paper.get('longVolMeanMoveEdgePct')):.2f}%",
        f"- Next cohort: {paper.get('nextCohortFamilyRule')}",
        "",
        "Candidate price reconciliation",
    ]
    for row in payload.get("candidateReconciliation") or []:
        lines.append(
            f"- {row.get('ticker')}: tracker {money(row.get('trackerPrice'))} | "
            f"Schwab close {money(row.get('schwabLastClose'))} | "
            f"drift {number(row.get('priceDriftPct')):.2f}% | "
            f"support distance {number(row.get('schwabDistanceToSupportPct')):.2f}% | "
            f"{row.get('decision')}"
        )
    lines.extend(["", "Next-week timing"])
    for row in payload.get("timingPlan") or []:
        lines.append(f"- {row.get('date')} | {row.get('phase')}: {row.get('action')}")
    lines.extend(["", "Next actions"])
    lines.extend(
        f"{index}. {action}"
        for index, action in enumerate(payload.get("nextActions") or [], 1)
    )
    return "\n".join(lines).rstrip() + "\n"


def save_sizing_positioning_timing(payload: dict[str, Any]) -> None:
    """Persist JSON and text artifacts."""
    ensure_dirs()
    atomic_write_json(SIZING_POSITIONING_TIMING_FILE, payload)
    atomic_write_text(
        SIZING_POSITIONING_TIMING_TEXT_FILE,
        render_sizing_positioning_timing(payload),
    )


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Build the research-only sizing, positioning, and timing plan."
    )
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    if args.command == "status" and SIZING_POSITIONING_TIMING_TEXT_FILE.exists():
        print(SIZING_POSITIONING_TIMING_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_sizing_positioning_timing()
    save_sizing_positioning_timing(payload)
    print(render_sizing_positioning_timing(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
