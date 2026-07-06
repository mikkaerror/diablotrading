from __future__ import annotations

"""Research-only pricing pass for defined-risk strategy alternatives.

The alternative scorer says which defined-risk structures deserve comparison.
This module asks the stricter question: can the strike selector build a priced
variant from the option chain, and what does the paper risk policy say?

Strict contract:
- research-only and diagnostic-only
- never mutates the execution queue, approval queue, paper ledger, or main
  strike plan
- no broker order creation, no live authority, no paper auto-stage
"""

import argparse
import json
from typing import Any, Callable

import pandas as pd
import yfinance as yf

from inferno_config import (
    MAX_SINGLE_TICKET_DOLLARS,
    MIN_CREDIT_SPREAD_CREDIT_RISK,
    local_now,
)
from inferno_io import atomic_write_json, atomic_write_text
from inferno_risk_policy import evaluate_strike_item
from inferno_strike_selector import (
    AUTOMATION_STAGE,
    build_liquidity_notes,
    buyable,
    clean_chain,
    effective_intent_for_pricing,
    iron_condor_plan,
    load_schwab_options_index,
    net_greek_summary,
    put_credit_spread_plan,
    put_debit_spread_plan,
    ranked_expiration_candidates,
    sellable,
    schwab_options_for_intent,
    to_leg,
    vertical_call_plan,
)
from inferno_ticket_cap_policy import current_ticket_cap_policy
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


STRATEGY_ALTERNATIVE_PRICING_FILE = DATA_DIR / "inferno_strategy_alternative_pricing.json"
STRATEGY_ALTERNATIVE_PRICING_TEXT_FILE = REPORTS_DIR / "strategy_alternative_pricing_latest.txt"
STRATEGY_ALTERNATIVE_PRICING_STAGE = "strategy-alternative-pricing-research-only"

STRATEGY_ALTERNATIVE_SCORER_FILE = DATA_DIR / "inferno_strategy_alternative_scorer.json"
PAPER_BOTTLENECK_REDUCER_FILE = DATA_DIR / "inferno_paper_bottleneck_reducer.json"
PAPER_VARIANT_SCANNER_FILE = DATA_DIR / "inferno_paper_variant_scanner.json"

DEFAULT_LIMIT = 6
DEFAULT_VARIANTS_PER_TICKER = 3
PUT_CREDIT_LADDER_SHORT_LIMIT = 18
PUT_CREDIT_LADDER_LONG_LIMIT = 8
PUT_CREDIT_LADDER_REPORT_LIMIT = 12
PUT_CREDIT_SUPPORT_SAFE_REPORT_LIMIT = 5
IRON_CONDOR_SHORT_LIMIT = 8
IRON_CONDOR_WING_LIMIT = 3
IRON_CONDOR_LADDER_REPORT_LIMIT = 12
IRON_CONDOR_RANGE_SAFE_REPORT_LIMIT = 5
PRICEABLE_RECOMMENDATIONS = {"CALL_DEBIT_SPREAD", "PUT_CREDIT_SPREAD", "IRON_CONDOR", "PUT_DEBIT_SPREAD"}
FALLBACK_RECOMMENDATION_VERDICT = "fallback-price-check"
VERDICT_PRIORITY = {
    "prefer-alternative-research": 0,
    "compare-in-paper": 1,
    FALLBACK_RECOMMENDATION_VERDICT: 2,
    "stand-aside": 2,
    "insufficient-alternative-edge": 3,
}


def text(value: Any) -> str:
    """Normalize values into stripped display text."""
    return str(value or "").strip()


def norm(value: Any) -> str:
    """Normalize ticker/strategy labels."""
    return text(value).upper()


def number(value: Any, default: float | None = None) -> float | None:
    """Coerce artifact numbers without trusting display formatting."""
    if isinstance(value, (int, float)):
        return float(value)
    raw = text(value).replace("$", "").replace(",", "").replace("%", "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def ticket_cap_policy() -> dict[str, Any]:
    """Return the current ticket-cap policy with a safe config fallback."""
    try:
        return current_ticket_cap_policy() or {}
    except Exception:
        return {
            "effectiveBand": {
                "hardCapDollars": float(MAX_SINGLE_TICKET_DOLLARS),
                "minTargetDollars": 0.0,
                "targetTicketDollars": float(MAX_SINGLE_TICKET_DOLLARS),
                "sourceRiskCapSource": "ticket-policy-unavailable",
            }
        }


def effective_ticket_cap_dollars() -> float:
    """Return the research construction hard cap for priced variants."""
    policy = ticket_cap_policy()
    construction = (policy.get("constructionBand") or {}).get("hardCapDollars")
    effective = construction if construction is not None else (policy.get("effectiveBand") or {}).get("hardCapDollars")
    parsed = number(effective, float(MAX_SINGLE_TICKET_DOLLARS)) or float(MAX_SINGLE_TICKET_DOLLARS)
    return float(parsed)


def target_ticket_floor_dollars() -> float:
    """Return the research construction target lower band for warnings only."""
    policy = ticket_cap_policy()
    construction = (policy.get("constructionBand") or {}).get("minTargetDollars")
    floor = construction if construction is not None else (policy.get("effectiveBand") or {}).get("minTargetDollars")
    parsed = number(floor, 0.0) or 0.0
    return float(parsed)


def lookup_by_ticker(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index rows by ticker."""
    lookup: dict[str, dict[str, Any]] = {}
    for item in items:
        ticker = norm(item.get("ticker"))
        if ticker and ticker not in lookup:
            lookup[ticker] = item
    return lookup


def reducer_lookup(reducer: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index reducer scenarios by ticker."""
    return lookup_by_ticker([item for item in reducer.get("scenarioSlate") or [] if isinstance(item, dict)])


def scorecard_priority(item: dict[str, Any]) -> tuple[Any, ...]:
    """Return ticker-level priority for strategy pricing."""
    recommendation = item.get("recommendation") or {}
    return (
        VERDICT_PRIORITY.get(text(recommendation.get("verdict")), 9),
        -abs(number(item.get("longVolPressureScore"), 0.0) or 0.0),
        norm(item.get("ticker")),
    )


def alternative_reason(alt: dict[str, Any], recommendation: dict[str, Any]) -> str:
    """Summarize why a specific strategy variant is being priced."""
    reasons = [text(reason) for reason in alt.get("reasons") or [] if text(reason)]
    if reasons:
        return "; ".join(reasons[:2])
    return text(recommendation.get("reason"))


def priceable_strategy_rows(item: dict[str, Any], *, variants_per_ticker: int = 1) -> list[dict[str, Any]]:
    """Expand one scorer row into ranked priceable strategy variants."""
    recommendation = item.get("recommendation") or {}
    recommended_strategy = norm(recommendation.get("strategy"))
    alternatives = [
        alt
        for alt in item.get("alternatives") or []
        if isinstance(alt, dict) and norm(alt.get("strategy")) in PRICEABLE_RECOMMENDATIONS
    ]
    if not alternatives and recommended_strategy in PRICEABLE_RECOMMENDATIONS:
        alternatives = [{"strategy": recommended_strategy}]

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for alt in alternatives:
        strategy = norm(alt.get("strategy"))
        if strategy in seen or strategy not in PRICEABLE_RECOMMENDATIONS:
            continue
        seen.add(strategy)
        rank = len(rows) + 1
        if rank > max(1, variants_per_ticker):
            break
        is_primary = strategy == recommended_strategy
        row = {
            **item,
            "recommendedStrategy": strategy,
            "sourceRecommendedStrategy": recommended_strategy,
            "recommendationVerdict": text(recommendation.get("verdict")) if is_primary else FALLBACK_RECOMMENDATION_VERDICT,
            "recommendationReason": text(recommendation.get("reason")) if is_primary else alternative_reason(alt, recommendation),
            "candidateStrategyRank": rank,
            "fallbackVariant": not is_primary,
            "sourceAlternative": alt,
            "sourceAlternativeScore": number(alt.get("score")),
            "sourceAlternativeRawScore": number(alt.get("rawScore")),
            "sourceAlternativeEdgeVsLongVol": number(alt.get("scoreEdgeVsLongVol")),
            "sourceAlternativeWarnings": alt.get("warnings") or [],
        }
        rows.append(row)
    return rows


def scanner_candidate_rows(paper_variant_scanner: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return scanner candidates normalized to the scorer candidate shape."""
    if not paper_variant_scanner:
        return []
    rows = [
        item
        for item in paper_variant_scanner.get("pricingCandidates") or []
        if isinstance(item, dict) and norm(item.get("recommendedStrategy")) in PRICEABLE_RECOMMENDATIONS
    ]
    rows.sort(
        key=lambda item: (
            -(number(item.get("sourceAlternativeScore"), 0.0) or 0.0),
            norm(item.get("ticker")),
        )
    )
    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(rows, start=1):
        normalized.append(
            {
                **item,
                "recommendedStrategy": norm(item.get("recommendedStrategy")),
                "sourceRecommendedStrategy": text(item.get("sourceRecommendedStrategy")) or "PAPER_VARIANT_SCANNER",
                "recommendationVerdict": text(item.get("recommendationVerdict")) or "paper-variant-research",
                "recommendationReason": text(item.get("recommendationReason")) or "paper variant scanner candidate",
                "candidateStrategyRank": int(number(item.get("candidateStrategyRank"), idx) or idx),
                "fallbackVariant": bool(item.get("fallbackVariant", False)),
                "sourceAlternativeWarnings": item.get("sourceAlternativeWarnings") or [],
                "paperVariantOnly": True,
            }
        )
    return normalized


def source_candidates(
    scorer: dict[str, Any],
    *,
    limit: int = DEFAULT_LIMIT,
    variants_per_ticker: int = 1,
    paper_variant_scanner: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return prioritized defined-risk strategy variants for pricing."""
    rows = [item for item in scorer.get("scorecards") or [] if isinstance(item, dict)]
    priceable_scorecards = [
        item
        for item in rows
        if priceable_strategy_rows(item, variants_per_ticker=1)
    ]
    priceable_scorecards.sort(key=scorecard_priority)
    candidates: list[dict[str, Any]] = []
    selected_tickers: set[str] = set()
    selected_keys: set[tuple[str, str]] = set()
    for item in priceable_scorecards[: max(0, limit)]:
        ticker = norm(item.get("ticker"))
        rows_for_ticker = priceable_strategy_rows(item, variants_per_ticker=variants_per_ticker)
        if rows_for_ticker and ticker:
            selected_tickers.add(ticker)
        for row in rows_for_ticker:
            key = (norm(row.get("ticker")), norm(row.get("recommendedStrategy")))
            if key[0] and key[1] and key not in selected_keys:
                selected_keys.add(key)
                candidates.append(row)
    remaining_ticker_slots = max(0, limit - len(selected_tickers))
    if remaining_ticker_slots <= 0:
        return candidates

    added_scanner_tickers: set[str] = set()
    for row in scanner_candidate_rows(paper_variant_scanner):
        ticker = norm(row.get("ticker"))
        strategy = norm(row.get("recommendedStrategy"))
        key = (ticker, strategy)
        if not ticker or not strategy or key in selected_keys or ticker in selected_tickers:
            continue
        if len(added_scanner_tickers) >= remaining_ticker_slots:
            break
        selected_keys.add(key)
        added_scanner_tickers.add(ticker)
        candidates.append(row)
    return candidates


def trend_label(value: Any) -> str:
    """Normalize trend text for strike selector market context."""
    if isinstance(value, dict):
        return text(value.get("label") or value.get("tone")) or "Neutral"
    raw = text(value)
    return raw or "Neutral"


def intent_from_candidate(candidate: dict[str, Any], reducer_item: dict[str, Any] | None) -> dict[str, Any]:
    """Build an in-memory strike-selector intent from scorer/reducer context."""
    reducer_item = reducer_item or {}
    reducer_market = dict(reducer_item.get("marketContextSummary") or {})
    candidate_market = dict(candidate.get("marketContextSummary") or {})
    trend = trend_label(reducer_market.get("trend") or candidate_market.get("trend") or candidate.get("trend"))
    price = number(reducer_item.get("price") or reducer_item.get("baselineUnderlyingPrice"))
    if price is None:
        price = number(candidate.get("price") or candidate.get("baselineUnderlyingPrice"))
    atr_percent = number(
        reducer_market.get("atrPercent")
        or candidate_market.get("atrPercent")
        or candidate.get("atrPercent")
    )
    days_until_earnings = reducer_item.get("daysUntilEarnings")
    if days_until_earnings is None:
        days_until_earnings = candidate.get("daysUntilEarnings")
    return {
        "ticker": norm(candidate.get("ticker")),
        "setupRec": "Alternative Research",
        "intentStatus": "strategy-alternative-research",
        "intentBlocks": [],
        "approvalStatus": "research-only",
        "price": price,
        "daysUntilEarnings": days_until_earnings,
        "riskUnits": 0,
        "ivRank": number(reducer_market.get("ivRank") or candidate_market.get("ivRank") or candidate.get("ivRank")),
        "atrPercent": atr_percent,
        "atr20Day": (price * atr_percent / 100.0) if price and atr_percent else None,
        "marketContext": {
            "trend": {"label": trend},
            "rvol": reducer_market.get("rvol") or candidate_market.get("rvol") or candidate.get("rvol"),
            "support": reducer_market.get("support") or candidate_market.get("support") or candidate.get("support"),
            "resistance": reducer_market.get("resistance") or candidate_market.get("resistance") or candidate.get("resistance"),
            "distanceToSupportPct": (
                reducer_market.get("distanceToSupportPct")
                or candidate_market.get("distanceToSupportPct")
                or candidate.get("distanceToSupportPct")
            ),
            "distanceToResistancePct": (
                reducer_market.get("distanceToResistancePct")
                or candidate_market.get("distanceToResistancePct")
                or candidate.get("distanceToResistancePct")
            ),
            "atrExpansion": reducer_market.get("atrExpansion") or reducer_market.get("atrZScore"),
        },
    }


def plan_for_strategy(
    strategy: str,
    pricing_intent: dict[str, Any],
    expiration: str,
    calls,
    puts,
) -> dict[str, Any] | None:
    """Build the requested strategy from cleaned option chains."""
    if strategy == "CALL_DEBIT_SPREAD":
        return vertical_call_plan(pricing_intent, expiration, calls)
    if strategy == "PUT_CREDIT_SPREAD":
        return put_credit_spread_plan(pricing_intent, expiration, puts)
    if strategy == "PUT_DEBIT_SPREAD":
        return put_debit_spread_plan(pricing_intent, expiration, puts)
    if strategy == "IRON_CONDOR":
        return iron_condor_plan(pricing_intent, expiration, calls, puts)
    return None


def leg_spread_pct(leg: Any) -> float:
    """Return one leg's bid/ask spread as a fraction of mid."""
    if number(getattr(leg, "mid", None), 0.0) <= 0:
        return 1.0
    return round(max(0.0, (number(getattr(leg, "ask", 0.0), 0.0) - number(getattr(leg, "bid", 0.0), 0.0)) / number(getattr(leg, "mid", 0.0), 1.0)), 4)


def put_credit_optimizer_notes(plan: dict[str, Any], pricing_intent: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return optimizer-level blocks/warnings for one put-credit spread."""
    blocks: list[str] = []
    warnings: list[str] = []
    credit_risk = number(plan.get("creditRisk"))
    support_cushion = number(plan.get("supportCushionToShortPct"))
    max_loss = number(plan.get("estimatedMaxLoss"), 0.0) or 0.0
    ticket_cap = effective_ticket_cap_dollars()
    greeks = plan.get("greekSummary") or {}
    support = number((pricing_intent.get("marketContext") or {}).get("support"))
    short_strike = number(plan.get("shortPutStrike"))

    if credit_risk is None or credit_risk < MIN_CREDIT_SPREAD_CREDIT_RISK:
        blocks.append(
            f"credit/risk {credit_risk or 0.0:.2f} is below optimizer floor {MIN_CREDIT_SPREAD_CREDIT_RISK:.2f}"
        )
    if max_loss > ticket_cap:
        blocks.append(f"max loss ${max_loss:.2f} exceeds single-ticket cap ${ticket_cap:.2f}")
    if support and short_strike and short_strike >= support:
        blocks.append(f"short put {short_strike:.2f} is at/above support {support:.2f}")
    elif support_cushion is not None and support_cushion < 0.5:
        warnings.append(f"support cushion to short put is thin at {support_cushion:.2f}%")
    if not greeks.get("greeksComplete"):
        warnings.append("Greek estimate is incomplete")
    if number(greeks.get("netTheta"), 0.0) <= 0 or number(greeks.get("netVega"), 0.0) >= 0:
        blocks.append("Greeks do not show positive-theta/negative-vega short-premium posture")
    return blocks, warnings


def strategy_optimizer_notes(plan: dict[str, Any], pricing_intent: dict[str, Any] | None = None) -> tuple[list[str], list[str]]:
    """Return generic optimizer-level notes for non-ladder strategy variants."""
    blocks: list[str] = []
    warnings: list[str] = []
    strategy = norm(plan.get("strategy"))
    max_loss = number(plan.get("estimatedMaxLoss"), 0.0) or 0.0
    max_profit = number(plan.get("estimatedMaxProfit"), 0.0) or 0.0
    ticket_cap = effective_ticket_cap_dollars()
    target_floor = target_ticket_floor_dollars()
    greeks = plan.get("greekSummary") or {}
    context = (pricing_intent or {}).get("marketContext") or {}

    if max_loss > ticket_cap:
        blocks.append(f"max loss ${max_loss:.2f} exceeds single-ticket cap ${ticket_cap:.2f}")
    elif target_floor and max_loss < target_floor:
        warnings.append(f"max loss ${max_loss:.2f} is below target ticket band floor ${target_floor:.2f}")
    if not greeks.get("greeksComplete"):
        warnings.append("Greek estimate is incomplete")

    if strategy == "CALL_DEBIT_SPREAD":
        debit = number(plan.get("estimatedDebit"), 0.0) or 0.0
        break_even = number(plan.get("breakEven"))
        resistance = number(context.get("resistance"))
        if debit <= 0:
            blocks.append(f"call debit spread debit {debit:.2f} is not positive")
        if max_profit <= 0:
            blocks.append("call debit spread has no positive max-profit estimate")
        if number(greeks.get("netDelta"), 0.0) <= 0:
            blocks.append("call debit spread does not carry positive delta")
        if resistance and break_even and break_even >= resistance:
            warnings.append(f"call debit breakeven {break_even:.2f} is at/above resistance {resistance:.2f}")
    elif strategy == "IRON_CONDOR":
        credit = number(plan.get("estimatedCredit"), 0.0) or 0.0
        credit_risk = round((credit * 100.0) / max_loss, 4) if credit > 0 and max_loss > 0 else 0.0
        plan["creditRisk"] = credit_risk
        if credit <= 0:
            blocks.append(f"iron condor credit {credit:.2f} is not positive")
        if credit_risk < MIN_CREDIT_SPREAD_CREDIT_RISK:
            blocks.append(
                f"credit/risk {credit_risk:.2f} is below optimizer floor {MIN_CREDIT_SPREAD_CREDIT_RISK:.2f}"
            )
        if number(greeks.get("netTheta"), 0.0) <= 0 or number(greeks.get("netVega"), 0.0) >= 0:
            blocks.append("Greeks do not show positive-theta/negative-vega short-premium posture")
        support = number(context.get("support"))
        resistance = number(context.get("resistance"))
        short_put = number(plan.get("shortPutStrike"))
        short_call = number(plan.get("shortCallStrike"))
        if support and short_put and short_put >= support:
            blocks.append(f"short put {short_put:.2f} is at/above support {support:.2f}")
        if resistance and short_call and short_call <= resistance:
            blocks.append(f"short call {short_call:.2f} is at/below resistance {resistance:.2f}")
    elif strategy == "PUT_DEBIT_SPREAD":
        debit = number(plan.get("estimatedDebit"), 0.0) or 0.0
        if debit <= 0:
            blocks.append(f"put debit spread debit {debit:.2f} is not positive")
        if max_profit <= 0:
            blocks.append("put debit spread has no positive max-profit estimate")

    return blocks, warnings


def put_credit_ladder_score(plan: dict[str, Any]) -> float:
    """Rank put-credit candidates by credit/risk, cushion, liquidity, and size."""
    credit_risk = number(plan.get("creditRisk"), 0.0) or 0.0
    support_cushion = max(0.0, number(plan.get("supportCushionToShortPct"), 0.0) or 0.0)
    max_spread_pct = number(plan.get("maxLegSpreadPct"), 1.0) or 1.0
    ticket_cap = effective_ticket_cap_dollars()
    max_loss = number(plan.get("estimatedMaxLoss"), ticket_cap) or ticket_cap
    greeks = plan.get("greekSummary") or {}
    theta = max(0.0, number(greeks.get("netTheta"), 0.0) or 0.0)
    vega_bonus = 4.0 if number(greeks.get("netVega"), 0.0) < 0 else -6.0
    size_penalty = max(0.0, (max_loss - ticket_cap) / 25.0)
    score = (
        credit_risk * 120.0
        + min(support_cushion, 8.0) * 2.0
        + min(theta * 100.0, 8.0)
        + vega_bonus
        - max_spread_pct * 35.0
        - size_penalty
    )
    return round(score, 4)


def iron_condor_ladder_score(plan: dict[str, Any]) -> float:
    """Rank condors by credit/risk, range cushion, liquidity, and Greeks."""
    credit_risk = number(plan.get("creditRisk"), 0.0) or 0.0
    range_cushion = max(0.0, min(
        number(plan.get("supportCushionToShortPutPct"), 0.0) or 0.0,
        number(plan.get("resistanceCushionToShortCallPct"), 0.0) or 0.0,
    ))
    max_spread_pct = number(plan.get("maxLegSpreadPct"), 1.0) or 1.0
    ticket_cap = effective_ticket_cap_dollars()
    max_loss = number(plan.get("estimatedMaxLoss"), ticket_cap) or ticket_cap
    width_skew = number(plan.get("wingWidthSkewPct"), 0.0) or 0.0
    greeks = plan.get("greekSummary") or {}
    theta = max(0.0, number(greeks.get("netTheta"), 0.0) or 0.0)
    delta_penalty = abs(number(greeks.get("netDelta"), 0.0) or 0.0) * 40.0
    vega_bonus = 4.0 if number(greeks.get("netVega"), 0.0) < 0 else -6.0
    size_penalty = max(0.0, (max_loss - ticket_cap) / 25.0)
    score = (
        credit_risk * 125.0
        + min(range_cushion, 8.0) * 2.5
        + min(theta * 100.0, 10.0)
        + vega_bonus
        - max_spread_pct * 35.0
        - width_skew * 12.0
        - delta_penalty
        - size_penalty
    )
    return round(score, 4)


def put_credit_plan_from_pair(
    pricing_intent: dict[str, Any],
    expiration: str,
    short_put_row,
    long_put_row,
) -> dict[str, Any] | None:
    """Build one put-credit spread from explicit short/long rows."""
    price = number(pricing_intent.get("price"), 0.0) or 0.0
    short_put = to_leg(short_put_row, "SELL_TO_OPEN", "PUT", expiration, price)
    long_put = to_leg(long_put_row, "BUY_TO_OPEN", "PUT", expiration, price)
    credit = round(short_put.bid - long_put.ask, 4)
    width = round(max(0.0, short_put.strike - long_put.strike), 4)
    if width <= 0 or credit <= 0 or credit >= width:
        return None
    max_loss = round((width - credit) * 100.0, 2)
    credit_risk = round(credit / (width - credit), 4) if width > credit else None
    support = number((pricing_intent.get("marketContext") or {}).get("support"))
    support_cushion = None
    if support and short_put.strike > 0:
        support_cushion = round((support - short_put.strike) / short_put.strike * 100.0, 4)
    legs = [short_put, long_put]
    spreads = [leg_spread_pct(leg) for leg in legs]
    plan = {
        "strategy": "PUT_CREDIT_SPREAD",
        "direction": "bullish-defined-risk-premium",
        "expiration": expiration,
        "legs": [leg.as_dict() for leg in legs],
        "estimatedCredit": credit,
        "estimatedMaxLoss": max_loss,
        "estimatedMaxProfit": round(credit * 100.0, 2),
        "breakEven": round(short_put.strike - credit, 4),
        "width": width,
        "creditRisk": credit_risk,
        "shortPutStrike": short_put.strike,
        "longPutStrike": long_put.strike,
        "supportReference": support,
        "shortPutBelowSupport": bool(support and short_put.strike < support),
        "supportCushionToShortPct": support_cushion,
        "maxLegSpreadPct": round(max(spreads), 4),
        "avgLegSpreadPct": round(sum(spreads) / len(spreads), 4),
        "greekSummary": net_greek_summary(legs),
        "liquidityNotes": build_liquidity_notes(legs),
    }
    optimizer_blocks, optimizer_warnings = put_credit_optimizer_notes(plan, pricing_intent)
    plan["optimizerBlocks"] = optimizer_blocks
    plan["optimizerWarnings"] = optimizer_warnings
    plan["optimizerPassed"] = not optimizer_blocks
    plan["optimizerScore"] = put_credit_ladder_score(plan)
    return plan


def iron_condor_plan_from_rows(
    pricing_intent: dict[str, Any],
    expiration: str,
    short_call_row,
    long_call_row,
    short_put_row,
    long_put_row,
) -> dict[str, Any] | None:
    """Build one iron condor from explicit short and long wing rows."""
    price = number(pricing_intent.get("price"), 0.0) or 0.0
    short_call = to_leg(short_call_row, "SELL_TO_OPEN", "CALL", expiration, price)
    long_call = to_leg(long_call_row, "BUY_TO_OPEN", "CALL", expiration, price)
    short_put = to_leg(short_put_row, "SELL_TO_OPEN", "PUT", expiration, price)
    long_put = to_leg(long_put_row, "BUY_TO_OPEN", "PUT", expiration, price)
    call_width = round(max(0.0, long_call.strike - short_call.strike), 4)
    put_width = round(max(0.0, short_put.strike - long_put.strike), 4)
    max_width = round(max(call_width, put_width), 4)
    credit = round(short_call.bid + short_put.bid - long_call.ask - long_put.ask, 4)
    if call_width <= 0 or put_width <= 0 or max_width <= 0 or credit <= 0 or credit >= max_width:
        return None

    max_loss = round((max_width - credit) * 100.0, 2)
    credit_risk = round((credit * 100.0) / max_loss, 4) if max_loss > 0 else None
    context = pricing_intent.get("marketContext") or {}
    support = number(context.get("support"))
    resistance = number(context.get("resistance"))
    support_cushion = None
    resistance_cushion = None
    if support and short_put.strike > 0:
        support_cushion = round((support - short_put.strike) / short_put.strike * 100.0, 4)
    if resistance and short_call.strike > 0:
        resistance_cushion = round((short_call.strike - resistance) / short_call.strike * 100.0, 4)

    legs = [short_call, long_call, short_put, long_put]
    spreads = [leg_spread_pct(leg) for leg in legs]
    width_skew = round(abs(call_width - put_width) / max_width, 4) if max_width > 0 else None
    plan = {
        "strategy": "IRON_CONDOR",
        "direction": "defined-risk-premium",
        "expiration": expiration,
        "legs": [leg.as_dict() for leg in legs],
        "estimatedCredit": credit,
        "estimatedMaxLoss": max_loss,
        "estimatedMaxProfit": round(credit * 100.0, 2),
        "breakEvenLower": round(short_put.strike - credit, 4),
        "breakEvenUpper": round(short_call.strike + credit, 4),
        "creditRisk": credit_risk,
        "shortCallStrike": short_call.strike,
        "longCallStrike": long_call.strike,
        "shortPutStrike": short_put.strike,
        "longPutStrike": long_put.strike,
        "callWidth": call_width,
        "putWidth": put_width,
        "maxWingWidth": max_width,
        "wingWidthSkewPct": width_skew,
        "supportReference": support,
        "resistanceReference": resistance,
        "shortPutBelowSupport": bool(support and short_put.strike < support),
        "shortCallAboveResistance": bool(resistance and short_call.strike > resistance),
        "rangeSafe": bool((not support or short_put.strike < support) and (not resistance or short_call.strike > resistance)),
        "supportCushionToShortPutPct": support_cushion,
        "resistanceCushionToShortCallPct": resistance_cushion,
        "maxLegSpreadPct": round(max(spreads), 4),
        "avgLegSpreadPct": round(sum(spreads) / len(spreads), 4),
        "greekSummary": net_greek_summary(legs),
        "liquidityNotes": build_liquidity_notes(legs),
    }
    optimizer_blocks, optimizer_warnings = strategy_optimizer_notes(plan, pricing_intent)
    plan["optimizerBlocks"] = optimizer_blocks
    plan["optimizerWarnings"] = optimizer_warnings
    plan["optimizerPassed"] = not optimizer_blocks
    plan["optimizerScore"] = iron_condor_ladder_score(plan)
    return plan


def sorted_put_credit_ladder_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort ladder rows by pass status, score, and credit/risk."""
    return sorted(
        rows,
        key=lambda row: (
            not bool(row.get("combinedPassed")),
            not bool(row.get("paperRiskPassed")),
            not bool(row.get("optimizerPassed")),
            -(number(row.get("optimizerScore"), 0.0) or 0.0),
            -(number(row.get("creditRisk"), 0.0) or 0.0),
            number(row.get("estimatedMaxLoss"), 99999.0) or 99999.0,
        ),
    )


def sorted_condor_ladder_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort condor ladder rows by pass status, score, and balanced risk."""
    return sorted(
        rows,
        key=lambda row: (
            not bool(row.get("combinedPassed")),
            not bool(row.get("paperRiskPassed")),
            not bool(row.get("optimizerPassed")),
            not bool(row.get("rangeSafe")),
            -(number(row.get("optimizerScore"), 0.0) or 0.0),
            -(number(row.get("creditRisk"), 0.0) or 0.0),
            number(row.get("estimatedMaxLoss"), 99999.0) or 99999.0,
        ),
    )


def compact_ladder_row(plan: dict[str, Any], risk_verdict: dict[str, Any]) -> dict[str, Any]:
    """Return a ladder row with compact report fields and private plan handles."""
    paper_risk_passed = bool(risk_verdict.get("passed"))
    optimizer_passed = bool(plan.get("optimizerPassed"))
    return {
        "_strikePlan": plan,
        "_riskVerdict": risk_verdict,
        "expiration": plan.get("expiration"),
        "strategy": plan.get("strategy"),
        "shortPutStrike": plan.get("shortPutStrike"),
        "longPutStrike": plan.get("longPutStrike"),
        "shortCallStrike": plan.get("shortCallStrike"),
        "longCallStrike": plan.get("longCallStrike"),
        "supportReference": plan.get("supportReference"),
        "resistanceReference": plan.get("resistanceReference"),
        "shortPutBelowSupport": plan.get("shortPutBelowSupport"),
        "shortCallAboveResistance": plan.get("shortCallAboveResistance"),
        "rangeSafe": plan.get("rangeSafe"),
        "width": plan.get("width"),
        "callWidth": plan.get("callWidth"),
        "putWidth": plan.get("putWidth"),
        "maxWingWidth": plan.get("maxWingWidth"),
        "estimatedCredit": plan.get("estimatedCredit"),
        "estimatedMaxLoss": plan.get("estimatedMaxLoss"),
        "estimatedMaxProfit": plan.get("estimatedMaxProfit"),
        "creditRisk": plan.get("creditRisk"),
        "supportCushionToShortPct": plan.get("supportCushionToShortPct"),
        "supportCushionToShortPutPct": plan.get("supportCushionToShortPutPct"),
        "resistanceCushionToShortCallPct": plan.get("resistanceCushionToShortCallPct"),
        "maxLegSpreadPct": plan.get("maxLegSpreadPct"),
        "optimizerScore": plan.get("optimizerScore"),
        "optimizerPassed": optimizer_passed,
        "paperRiskPassed": paper_risk_passed,
        "combinedPassed": optimizer_passed and paper_risk_passed,
        "optimizerBlocks": plan.get("optimizerBlocks") or [],
        "riskBlocks": risk_verdict.get("blocks") or [],
        "warnings": (plan.get("optimizerWarnings") or []) + (risk_verdict.get("warnings") or []),
    }


def public_ladder_row(row: dict[str, Any]) -> dict[str, Any]:
    """Strip internal plan handles before persisting/reporting a ladder row."""
    return {key: value for key, value in row.items() if not key.startswith("_")}


def support_aware_short_put_rows(puts, pricing_intent: dict[str, Any]):
    """Sample near-price and support-safe short puts for ladder construction."""
    price = number(pricing_intent.get("price"), 0.0) or 0.0
    if puts.empty or price <= 0:
        return pd.DataFrame(columns=puts.columns)
    tradable = sellable(puts[puts["strike"] < price])
    if tradable.empty:
        return tradable
    near_price = tradable.sort_values("strike", ascending=False).head(PUT_CREDIT_LADDER_SHORT_LIMIT)
    support = number((pricing_intent.get("marketContext") or {}).get("support"))
    if not support:
        return near_price
    support_safe = tradable[tradable["strike"] < support].sort_values("strike", ascending=False).head(
        PUT_CREDIT_LADDER_SHORT_LIMIT
    )
    if support_safe.empty:
        return near_price
    return (
        pd.concat([near_price, support_safe])
        .drop_duplicates(subset=["contractSymbol", "strike"], keep="first")
        .sort_values("strike", ascending=False)
    )


def condor_short_call_rows(calls, pricing_intent: dict[str, Any]):
    """Sample near-price and resistance-safe short calls for condor ladders."""
    price = number(pricing_intent.get("price"), 0.0) or 0.0
    if calls.empty or price <= 0:
        return pd.DataFrame(columns=calls.columns)
    tradable = sellable(calls[calls["strike"] > price])
    if tradable.empty:
        return tradable
    near_price = tradable.sort_values("strike", ascending=True).head(IRON_CONDOR_SHORT_LIMIT)
    resistance = number((pricing_intent.get("marketContext") or {}).get("resistance"))
    if not resistance:
        return near_price
    resistance_safe = tradable[tradable["strike"] > resistance].sort_values("strike", ascending=True).head(
        IRON_CONDOR_SHORT_LIMIT
    )
    if resistance_safe.empty:
        return near_price
    return (
        pd.concat([near_price, resistance_safe])
        .drop_duplicates(subset=["contractSymbol", "strike"], keep="first")
        .sort_values("strike", ascending=True)
    )


def condor_short_put_rows(puts, pricing_intent: dict[str, Any]):
    """Sample near-price and support-safe short puts for condor ladders."""
    return support_aware_short_put_rows(puts, pricing_intent)


def build_put_credit_ladder(
    pricing_intent: dict[str, Any],
    expiration: str,
    puts,
    *,
    base_item: dict[str, Any],
    generated_at: str,
) -> list[dict[str, Any]]:
    """Enumerate and evaluate multiple put-credit strike pairs."""
    short_rows = support_aware_short_put_rows(puts, pricing_intent)
    if short_rows.empty:
        return []
    ladder: list[dict[str, Any]] = []
    for _, short_row in short_rows.iterrows():
        short_strike = number(short_row.get("strike"))
        long_rows = buyable(puts[puts["strike"] < short_strike]).sort_values("strike", ascending=False).head(PUT_CREDIT_LADDER_LONG_LIMIT)
        for _, long_row in long_rows.iterrows():
            plan = put_credit_plan_from_pair(pricing_intent, expiration, short_row, long_row)
            if not plan:
                continue
            item = {
                **base_item,
                "ok": True,
                "expiration": expiration,
                "strikePlan": plan,
            }
            risk = evaluate_strike_item(item, strike_plan_generated_at=generated_at, mode="paper").as_dict()
            ladder.append(compact_ladder_row(plan, risk))
    return sorted_put_credit_ladder_rows(ladder)


def build_iron_condor_ladder(
    pricing_intent: dict[str, Any],
    expiration: str,
    calls,
    puts,
    *,
    base_item: dict[str, Any],
    generated_at: str,
) -> list[dict[str, Any]]:
    """Enumerate and evaluate multiple iron-condor strike/wing combinations."""
    short_call_rows = condor_short_call_rows(calls, pricing_intent)
    short_put_rows = condor_short_put_rows(puts, pricing_intent)
    if short_call_rows.empty or short_put_rows.empty:
        return []
    ladder: list[dict[str, Any]] = []
    buyable_calls = buyable(calls)
    buyable_puts = buyable(puts)
    for _, short_call_row in short_call_rows.iterrows():
        short_call_strike = number(short_call_row.get("strike"))
        long_call_rows = buyable_calls[buyable_calls["strike"] > short_call_strike].sort_values("strike").head(
            IRON_CONDOR_WING_LIMIT
        )
        if long_call_rows.empty:
            continue
        for _, short_put_row in short_put_rows.iterrows():
            short_put_strike = number(short_put_row.get("strike"))
            long_put_rows = buyable_puts[buyable_puts["strike"] < short_put_strike].sort_values(
                "strike", ascending=False
            ).head(IRON_CONDOR_WING_LIMIT)
            if long_put_rows.empty:
                continue
            for _, long_call_row in long_call_rows.iterrows():
                for _, long_put_row in long_put_rows.iterrows():
                    plan = iron_condor_plan_from_rows(
                        pricing_intent,
                        expiration,
                        short_call_row,
                        long_call_row,
                        short_put_row,
                        long_put_row,
                    )
                    if not plan:
                        continue
                    item = {
                        **base_item,
                        "ok": True,
                        "expiration": expiration,
                        "strikePlan": plan,
                    }
                    risk = evaluate_strike_item(item, strike_plan_generated_at=generated_at, mode="paper").as_dict()
                    ladder.append(compact_ladder_row(plan, risk))
    return sorted_condor_ladder_rows(ladder)


def annotate_variant(plan: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Mark a priced variant as research-only and connect it to the scorer."""
    return {
        **plan,
        "paperVariantOnly": True,
        "researchOnly": True,
        "diagnosticOnly": True,
        "variantFamily": f"priced-{text(plan.get('strategy')).lower().replace('_', '-')}",
        "variantForStrategy": candidate.get("sourceFamily") or "pressured-long-vol",
        "sourcePaperVariant": bool(candidate.get("paperVariantOnly")),
        "variantReason": candidate.get("recommendationReason"),
        "sourceRecommendationVerdict": candidate.get("recommendationVerdict"),
        "sourceRecommendedStrategy": candidate.get("sourceRecommendedStrategy"),
        "sourceAlternativeScore": candidate.get("sourceAlternativeScore"),
        "sourceAlternativeEdgeVsLongVol": candidate.get("sourceAlternativeEdgeVsLongVol"),
        "candidateStrategyRank": candidate.get("candidateStrategyRank"),
        "fallbackVariant": bool(candidate.get("fallbackVariant")),
    }


def build_priced_item(
    *,
    candidate: dict[str, Any],
    reducer_item: dict[str, Any] | None,
    schwab_options_index: dict[str, dict[str, Any]],
    generated_at: str,
    ticker_factory: Callable[[str], Any] = yf.Ticker,
) -> dict[str, Any]:
    """Price one recommended alternative without mutating operational artifacts."""
    strategy = norm(candidate.get("recommendedStrategy"))
    intent = intent_from_candidate(candidate, reducer_item)
    schwab_options = schwab_options_for_intent(intent, schwab_options_index)
    pricing_intent = effective_intent_for_pricing(intent, schwab_options)
    base = {
        "ticker": intent.get("ticker"),
        "generatedAt": generated_at,
        "stage": STRATEGY_ALTERNATIVE_PRICING_STAGE,
        "automationStage": AUTOMATION_STAGE,
        "recommendedStrategy": strategy,
        "sourceRecommendedStrategy": candidate.get("sourceRecommendedStrategy"),
        "candidateStrategyRank": candidate.get("candidateStrategyRank"),
        "fallbackVariant": bool(candidate.get("fallbackVariant")),
        "sourceAlternativeScore": candidate.get("sourceAlternativeScore"),
        "sourceAlternativeRawScore": candidate.get("sourceAlternativeRawScore"),
        "sourceAlternativeEdgeVsLongVol": candidate.get("sourceAlternativeEdgeVsLongVol"),
        "sourceAlternativeWarnings": candidate.get("sourceAlternativeWarnings") or [],
        "recommendationVerdict": candidate.get("recommendationVerdict"),
        "longVolHurdle": candidate.get("hurdle"),
        "longVolAtrMultiple": candidate.get("hurdleAtrMultiple"),
        "longVolPressureScore": candidate.get("longVolPressureScore"),
        "intent": intent,
        "price": pricing_intent.get("price"),
        "sourcePrice": pricing_intent.get("sourcePrice"),
        "underlyingPriceSource": pricing_intent.get("underlyingPriceSource"),
        "daysUntilEarnings": intent.get("daysUntilEarnings"),
        "paperVariantOnly": bool(candidate.get("paperVariantOnly")),
        "paperVariantFamily": candidate.get("sourceFamily"),
        "paperOnly": True,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "marketContext": pricing_intent.get("marketContext") or {},
        "marketContextSummary": {
            "trend": trend_label((pricing_intent.get("marketContext") or {}).get("trend", {}).get("label")),
            "rvol": (pricing_intent.get("marketContext") or {}).get("rvol"),
            "support": (pricing_intent.get("marketContext") or {}).get("support"),
            "resistance": (pricing_intent.get("marketContext") or {}).get("resistance"),
            "distanceToSupportPct": (pricing_intent.get("marketContext") or {}).get("distanceToSupportPct"),
            "distanceToResistancePct": (pricing_intent.get("marketContext") or {}).get("distanceToResistancePct"),
        },
        "schwabOptions": schwab_options,
        "researchOnly": True,
        "diagnosticOnly": True,
        "promotable": False,
    }
    if number(pricing_intent.get("price"), 0.0) <= 0:
        return {**base, "ok": False, "status": "failed", "reason": "missing usable underlying price"}
    try:
        stock = ticker_factory(str(intent.get("ticker")))
        expirations = ranked_expiration_candidates(stock.options, int(number(intent.get("daysUntilEarnings"), 0) or 0))
        attempts: list[str] = []
        put_credit_ladder: list[dict[str, Any]] = []
        iron_condor_ladder: list[dict[str, Any]] = []
        for expiration in expirations:
            chain = stock.option_chain(expiration)
            calls = clean_chain(chain.calls)
            puts = clean_chain(chain.puts)
            if strategy == "PUT_CREDIT_SPREAD":
                expiration_ladder = build_put_credit_ladder(
                    pricing_intent,
                    expiration,
                    puts,
                    base_item={**base, "expiration": expiration},
                    generated_at=generated_at,
                )
                if not expiration_ladder:
                    attempts.append(expiration)
                    continue
                put_credit_ladder.extend(expiration_ladder)
                continue
            if strategy == "IRON_CONDOR":
                expiration_ladder = build_iron_condor_ladder(
                    pricing_intent,
                    expiration,
                    calls,
                    puts,
                    base_item={**base, "expiration": expiration},
                    generated_at=generated_at,
                )
                if not expiration_ladder:
                    attempts.append(expiration)
                    continue
                iron_condor_ladder.extend(expiration_ladder)
                continue
            plan = plan_for_strategy(strategy, pricing_intent, expiration, calls, puts)
            if not plan:
                attempts.append(expiration)
                continue
            optimizer_blocks, optimizer_warnings = strategy_optimizer_notes(plan, pricing_intent)
            plan["optimizerBlocks"] = optimizer_blocks
            plan["optimizerWarnings"] = optimizer_warnings
            plan["optimizerPassed"] = not optimizer_blocks
            variant = annotate_variant(plan, candidate)
            item = {
                **base,
                "ok": True,
                "status": "priced",
                "expiration": expiration,
                "strikePlan": variant,
            }
            risk_verdict = evaluate_strike_item(item, strike_plan_generated_at=generated_at, mode="paper").as_dict()
            item["riskVerdict"] = risk_verdict
            item["optimizerPassed"] = not optimizer_blocks
            item["paperRiskPassed"] = bool(risk_verdict.get("passed"))
            item["combinedPassed"] = bool(risk_verdict.get("passed")) and not optimizer_blocks
            return item
        if strategy == "PUT_CREDIT_SPREAD" and put_credit_ladder:
            ladder = sorted_put_credit_ladder_rows(put_credit_ladder)
            support_safe_ladder = [row for row in ladder if row.get("shortPutBelowSupport")]
            best = ladder[0]
            best_plan = dict(best.get("_strikePlan") or {})
            best_risk = dict(best.get("_riskVerdict") or {})
            variant = annotate_variant(best_plan, candidate)
            return {
                **base,
                "ok": True,
                "status": "priced",
                "expiration": variant.get("expiration"),
                "expirationCandidates": expirations,
                "strikePlan": variant,
                "riskVerdict": best_risk,
                "optimizerPassed": bool(best.get("optimizerPassed")),
                "paperRiskPassed": bool(best.get("paperRiskPassed")),
                "combinedPassed": bool(best.get("combinedPassed")),
                "putCreditLadderRows": len(ladder),
                "putCreditSupportSafeRows": len(support_safe_ladder),
                "putCreditLadder": [
                    public_ladder_row(row)
                    for row in ladder[:PUT_CREDIT_LADDER_REPORT_LIMIT]
                ],
                "putCreditSupportSafeLadder": [
                    public_ladder_row(row)
                    for row in support_safe_ladder[:PUT_CREDIT_SUPPORT_SAFE_REPORT_LIMIT]
                ],
            }
        if strategy == "IRON_CONDOR" and iron_condor_ladder:
            ladder = sorted_condor_ladder_rows(iron_condor_ladder)
            range_safe_ladder = [row for row in ladder if row.get("rangeSafe")]
            best = ladder[0]
            best_plan = dict(best.get("_strikePlan") or {})
            best_risk = dict(best.get("_riskVerdict") or {})
            variant = annotate_variant(best_plan, candidate)
            return {
                **base,
                "ok": True,
                "status": "priced",
                "expiration": variant.get("expiration"),
                "expirationCandidates": expirations,
                "strikePlan": variant,
                "riskVerdict": best_risk,
                "optimizerPassed": bool(best.get("optimizerPassed")),
                "paperRiskPassed": bool(best.get("paperRiskPassed")),
                "combinedPassed": bool(best.get("combinedPassed")),
                "ironCondorLadderRows": len(ladder),
                "ironCondorRangeSafeRows": len(range_safe_ladder),
                "ironCondorLadder": [
                    public_ladder_row(row)
                    for row in ladder[:IRON_CONDOR_LADDER_REPORT_LIMIT]
                ],
                "ironCondorRangeSafeLadder": [
                    public_ladder_row(row)
                    for row in range_safe_ladder[:IRON_CONDOR_RANGE_SAFE_REPORT_LIMIT]
                ],
            }
        return {
            **base,
            "ok": False,
            "status": "no-plan",
            "expirationCandidates": expirations,
            "reason": f"no {strategy} plan across expirations: {', '.join(attempts) or 'none'}",
        }
    except Exception as exc:  # noqa: BLE001
        return {**base, "ok": False, "status": "failed", "reason": f"{type(exc).__name__}: {exc}"}


def priced_item_passed(item: dict[str, Any]) -> bool:
    """Return the combined pass flag for a priced research variant."""
    if item.get("status") != "priced":
        return False
    if "combinedPassed" in item:
        return bool(item.get("combinedPassed"))
    return bool((item.get("riskVerdict") or {}).get("passed"))


def build_strategy_alternative_pricing(
    *,
    scorer: dict[str, Any] | None = None,
    reducer: dict[str, Any] | None = None,
    paper_variant_scanner: dict[str, Any] | None = None,
    limit: int = DEFAULT_LIMIT,
    variants_per_ticker: int = DEFAULT_VARIANTS_PER_TICKER,
    ticker_factory: Callable[[str], Any] = yf.Ticker,
    schwab_options_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the research-only alternative pricing artifact."""
    ensure_dirs()
    should_load_scanner = scorer is None and paper_variant_scanner is None
    scorer = scorer if scorer is not None else (load_json_file(STRATEGY_ALTERNATIVE_SCORER_FILE) or {})
    reducer = reducer if reducer is not None else (load_json_file(PAPER_BOTTLENECK_REDUCER_FILE) or {})
    if should_load_scanner:
        paper_variant_scanner = load_json_file(PAPER_VARIANT_SCANNER_FILE) or {}
    reducer_by_ticker = reducer_lookup(reducer)
    candidates = source_candidates(
        scorer,
        limit=limit,
        variants_per_ticker=variants_per_ticker,
        paper_variant_scanner=paper_variant_scanner,
    )
    schwab_index = load_schwab_options_index() if schwab_options_index is None else schwab_options_index
    generated_at = local_now().isoformat()
    cap_policy = ticket_cap_policy()
    items = [
        build_priced_item(
            candidate=candidate,
            reducer_item=reducer_by_ticker.get(norm(candidate.get("ticker"))),
            schwab_options_index=schwab_index,
            generated_at=generated_at,
            ticker_factory=ticker_factory,
        )
        for candidate in candidates
    ]
    priced = [item for item in items if item.get("status") == "priced"]
    risk_pass = [item for item in priced if priced_item_passed(item)]
    verdict = "no-priceable-candidates"
    if items:
        if risk_pass:
            verdict = "priced-risk-pass"
        elif priced:
            verdict = "priced-risk-blocked"
        else:
            verdict = "pricing-failed"
    return {
        "generatedAt": generated_at,
        "stage": STRATEGY_ALTERNATIVE_PRICING_STAGE,
        "verdict": verdict,
        "researchOnly": True,
        "diagnosticOnly": True,
        "promotable": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "ticketCapPolicy": {
            "verdict": cap_policy.get("verdict"),
            "requestedBand": cap_policy.get("requestedBand") or {},
            "constructionBand": cap_policy.get("constructionBand") or {},
            "effectiveBand": cap_policy.get("effectiveBand") or {},
            "callOptionsPosture": cap_policy.get("callOptionsPosture") or {},
        },
        "counts": {
            "requested": len(candidates),
            "tickerGroups": len({norm(item.get("ticker")) for item in candidates if norm(item.get("ticker"))}),
            "variantsPerTicker": variants_per_ticker,
            "fallbackVariants": sum(1 for item in candidates if item.get("fallbackVariant")),
            "scannerCandidates": sum(1 for item in candidates if item.get("paperVariantOnly")),
            "requestedByStrategy": {
                strategy: sum(1 for item in candidates if item.get("recommendedStrategy") == strategy)
                for strategy in sorted({text(item.get("recommendedStrategy")) for item in candidates if text(item.get("recommendedStrategy"))})
            },
            "priced": len(priced),
            "failed": sum(1 for item in items if item.get("status") == "failed"),
            "noPlan": sum(1 for item in items if item.get("status") == "no-plan"),
            "riskPassed": len(risk_pass),
            "riskBlocked": sum(
                1
                for item in priced
                if not priced_item_passed(item)
            ),
            "optimizerPassed": sum(1 for item in priced if item.get("optimizerPassed")),
            "optimizerBlocked": sum(1 for item in priced if item.get("optimizerPassed") is False),
            "ladderRows": sum(len(item.get("putCreditLadder") or []) for item in priced),
            "supportSafeLadderRows": sum(int(item.get("putCreditSupportSafeRows") or 0) for item in priced),
            "ironCondorLadderRows": sum(len(item.get("ironCondorLadder") or []) for item in priced),
            "ironCondorRangeSafeRows": sum(int(item.get("ironCondorRangeSafeRows") or 0) for item in priced),
        },
        "items": items,
        "rules": [
            "This pass prices alternatives only; it does not write the main strike plan.",
            "Combined pass means optimizer and paper-risk quality only, not live authority.",
            "Broker submit remains false and every priced variant requires explicit human review.",
            "The ticket-cap policy sets a target band; only the hard cap is a blocking optimizer limit.",
        ],
    }


def fmt_money(value: Any) -> str:
    """Render optional money values."""
    parsed = number(value)
    if parsed is None:
        return "n/a"
    return f"${parsed:.2f}"


def fmt(value: Any) -> str:
    """Render optional numeric values."""
    parsed = number(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:.4g}"


def plan_price_summary(plan: dict[str, Any]) -> str:
    """Render strategy cost/credit consistently."""
    if "estimatedCredit" in plan:
        return f"credit {fmt_money(plan.get('estimatedCredit'))}"
    if "estimatedDebit" in plan:
        return f"debit {fmt_money(plan.get('estimatedDebit'))}"
    return "cost n/a"


def plan_strike_summary(plan: dict[str, Any]) -> str:
    """Render strategy-specific strike details."""
    strategy = norm(plan.get("strategy"))
    if strategy == "CALL_DEBIT_SPREAD":
        return f"breakeven {fmt(plan.get('breakEven'))} | width {fmt(plan.get('width'))}"
    if strategy == "PUT_CREDIT_SPREAD":
        return (
            f"short put {plan.get('shortPutStrike')} / long put {plan.get('longPutStrike')} | "
            f"breakeven {fmt(plan.get('breakEven'))} | support cushion {fmt(plan.get('supportCushionToShortPct'))}%"
        )
    if strategy == "PUT_DEBIT_SPREAD":
        return f"breakeven {fmt(plan.get('breakEven'))} | width {fmt(plan.get('width'))}"
    if strategy == "IRON_CONDOR":
        return (
            f"call wing {plan.get('shortCallStrike')}/{plan.get('longCallStrike')} | "
            f"put wing {plan.get('shortPutStrike')}/{plan.get('longPutStrike')} | "
            f"max profit {fmt_money(plan.get('estimatedMaxProfit'))}"
        )
    return f"breakeven {fmt(plan.get('breakEven'))}"


def strategy_alternative_pricing_text(payload: dict[str, Any]) -> str:
    """Render the alternative pricing memo."""
    counts = payload.get("counts") or {}
    cap_policy = payload.get("ticketCapPolicy") or {}
    construction_band = cap_policy.get("constructionBand") or {}
    effective_band = cap_policy.get("effectiveBand") or {}
    posture = cap_policy.get("callOptionsPosture") or {}
    lines = [
        "Inferno Strategy Alternative Pricing",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Verdict: {payload.get('verdict')}",
        "Authority: research-only; promotable=False; liveTradingAllowed=False",
        "",
        "Counts:",
        f"- requested: {counts.get('requested', 0)}",
        f"- ticker groups: {counts.get('tickerGroups', 0)}",
        f"- variants per ticker: {counts.get('variantsPerTicker', 0)}",
        f"- fallback variants: {counts.get('fallbackVariants', 0)}",
        f"- scanner candidates: {counts.get('scannerCandidates', 0)}",
        f"- requested by strategy: {json.dumps(counts.get('requestedByStrategy') or {})}",
        f"- priced: {counts.get('priced', 0)}",
        f"- combined passed: {counts.get('riskPassed', 0)}",
        f"- combined blocked: {counts.get('riskBlocked', 0)}",
        f"- optimizer passed/blocked: {counts.get('optimizerPassed', 0)} / {counts.get('optimizerBlocked', 0)}",
        f"- put-credit ladder rows retained: {counts.get('ladderRows', 0)}",
        f"- support-safe ladder rows found: {counts.get('supportSafeLadderRows', 0)}",
        f"- iron-condor ladder rows retained: {counts.get('ironCondorLadderRows', 0)}",
        f"- range-safe condor rows found: {counts.get('ironCondorRangeSafeRows', 0)}",
        f"- failed/no-plan: {counts.get('failed', 0)} / {counts.get('noPlan', 0)}",
        (
            f"- research construction cap: {fmt_money(construction_band.get('hardCapDollars'))} | "
            f"target floor {fmt_money(construction_band.get('minTargetDollars'))} | "
            f"simulated paper budget {fmt_money(effective_band.get('hardCapDollars'))} | "
            f"new entries allowed {effective_band.get('newEntriesAllowed')} | "
            f"call posture {posture.get('mode') or 'n/a'}"
        ),
        "",
        "Priced alternatives:",
    ]
    if not payload.get("items"):
        lines.append("- none")
    for item in payload.get("items") or []:
        if item.get("status") != "priced":
            lines.append(
                f"- {item.get('ticker')} | {item.get('recommendedStrategy')} | "
                f"{item.get('status')} | {item.get('reason')}"
            )
            continue
        plan = item.get("strikePlan") or {}
        risk = item.get("riskVerdict") or {}
        greeks = plan.get("greekSummary") or {}
        optimizer_passed = bool(item.get("optimizerPassed", True))
        paper_risk_passed = bool(item.get("paperRiskPassed", risk.get("passed")))
        combined_passed = bool(item.get("combinedPassed", paper_risk_passed and optimizer_passed))
        lines.append(
            f"- {item.get('ticker')} | {plan.get('strategy')} | expiration {item.get('expiration')} | "
            f"{plan_price_summary(plan)} | max loss {fmt_money(plan.get('estimatedMaxLoss'))} | "
            f"combined {'pass' if combined_passed else 'block'}"
        )
        lines.append(
            f"  source: rank {item.get('candidateStrategyRank') or 'n/a'} | "
            f"{'fallback' if item.get('fallbackVariant') else 'primary'} | "
            f"score {fmt(item.get('sourceAlternativeScore'))} | edge {fmt(item.get('sourceAlternativeEdgeVsLongVol'))}"
        )
        lines.append(
            f"  gates: optimizer {'pass' if optimizer_passed else 'block'} | "
            f"paper risk {'pass' if paper_risk_passed else 'block'}"
        )
        lines.append(f"  strikes: {plan_strike_summary(plan)}")
        lines.append(
            f"  greeks: delta {greeks.get('netDelta')} | theta {greeks.get('netTheta')} | "
            f"vega {greeks.get('netVega')} | {greeks.get('volPosture')}"
        )
        blocks = risk.get("blocks") or []
        optimizer_blocks = plan.get("optimizerBlocks") or []
        warnings = risk.get("warnings") or []
        optimizer_warnings = plan.get("optimizerWarnings") or []
        if optimizer_blocks:
            lines.append(f"  optimizer blocks: {'; '.join(str(block) for block in optimizer_blocks[:4])}")
        if blocks:
            lines.append(f"  blocks: {'; '.join(str(block) for block in blocks[:4])}")
        if optimizer_warnings:
            lines.append(f"  optimizer warnings: {'; '.join(str(warning) for warning in optimizer_warnings[:4])}")
        if warnings:
            lines.append(f"  warnings: {'; '.join(str(warning) for warning in warnings[:4])}")
        ladder = item.get("putCreditLadder") or []
        if ladder:
            lines.append("  best ladder candidates:")
            for row in ladder[:5]:
                row_blocks = (row.get("optimizerBlocks") or []) + (row.get("riskBlocks") or [])
                row_combined = bool(row.get("combinedPassed"))
                lines.append(
                    f"    {row.get('expiration')} {row.get('shortPutStrike')}/{row.get('longPutStrike')} | "
                    f"credit {fmt_money(row.get('estimatedCredit'))} | max loss {fmt_money(row.get('estimatedMaxLoss'))} | "
                    f"credit/risk {fmt(row.get('creditRisk'))} | support cushion {fmt(row.get('supportCushionToShortPct'))}% | "
                    f"support-safe {'yes' if row.get('shortPutBelowSupport') else 'no'} | "
                    f"combined {'pass' if row_combined else 'block'}"
                )
                if row_blocks:
                    lines.append(f"      blocks: {'; '.join(str(block) for block in row_blocks[:3])}")
        support_safe_ladder = item.get("putCreditSupportSafeLadder") or []
        if support_safe_ladder:
            lines.append("  support-safe candidates:")
            for row in support_safe_ladder[:3]:
                row_blocks = (row.get("optimizerBlocks") or []) + (row.get("riskBlocks") or [])
                lines.append(
                    f"    {row.get('expiration')} {row.get('shortPutStrike')}/{row.get('longPutStrike')} | "
                    f"credit {fmt_money(row.get('estimatedCredit'))} | max loss {fmt_money(row.get('estimatedMaxLoss'))} | "
                    f"credit/risk {fmt(row.get('creditRisk'))} | combined {'pass' if row.get('combinedPassed') else 'block'}"
                )
                if row_blocks:
                    lines.append(f"      blocks: {'; '.join(str(block) for block in row_blocks[:3])}")
        condor_ladder = item.get("ironCondorLadder") or []
        if condor_ladder:
            lines.append("  best condor ladder candidates:")
            for row in condor_ladder[:5]:
                row_blocks = (row.get("optimizerBlocks") or []) + (row.get("riskBlocks") or [])
                lines.append(
                    f"    {row.get('expiration')} calls {row.get('shortCallStrike')}/{row.get('longCallStrike')} "
                    f"puts {row.get('shortPutStrike')}/{row.get('longPutStrike')} | "
                    f"credit {fmt_money(row.get('estimatedCredit'))} | max loss {fmt_money(row.get('estimatedMaxLoss'))} | "
                    f"credit/risk {fmt(row.get('creditRisk'))} | range-safe {'yes' if row.get('rangeSafe') else 'no'} | "
                    f"combined {'pass' if row.get('combinedPassed') else 'block'}"
                )
                if row_blocks:
                    lines.append(f"      blocks: {'; '.join(str(block) for block in row_blocks[:3])}")
        range_safe_ladder = item.get("ironCondorRangeSafeLadder") or []
        if range_safe_ladder:
            lines.append("  range-safe condor candidates:")
            for row in range_safe_ladder[:3]:
                row_blocks = (row.get("optimizerBlocks") or []) + (row.get("riskBlocks") or [])
                lines.append(
                    f"    {row.get('expiration')} calls {row.get('shortCallStrike')}/{row.get('longCallStrike')} "
                    f"puts {row.get('shortPutStrike')}/{row.get('longPutStrike')} | "
                    f"credit {fmt_money(row.get('estimatedCredit'))} | max loss {fmt_money(row.get('estimatedMaxLoss'))} | "
                    f"credit/risk {fmt(row.get('creditRisk'))} | combined {'pass' if row.get('combinedPassed') else 'block'}"
                )
                if row_blocks:
                    lines.append(f"      blocks: {'; '.join(str(block) for block in row_blocks[:3])}")
    lines.extend(["", "Rules:"])
    for rule in payload.get("rules") or []:
        lines.append(f"- {rule}")
    return "\n".join(lines).rstrip() + "\n"


def save_strategy_alternative_pricing(payload: dict[str, Any]) -> None:
    """Persist strategy alternative pricing artifacts."""
    ensure_dirs()
    atomic_write_json(STRATEGY_ALTERNATIVE_PRICING_FILE, payload)
    atomic_write_text(STRATEGY_ALTERNATIVE_PRICING_TEXT_FILE, strategy_alternative_pricing_text(payload))


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Price research-only defined-risk alternatives.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Maximum ticker groups to price.")
    parser.add_argument(
        "--variants-per-ticker",
        type=int,
        default=DEFAULT_VARIANTS_PER_TICKER,
        help="Ranked defined-risk strategy variants to price per ticker group.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the alternative pricing CLI."""
    args = parse_args()
    if args.command == "status" and STRATEGY_ALTERNATIVE_PRICING_TEXT_FILE.exists():
        print(STRATEGY_ALTERNATIVE_PRICING_TEXT_FILE.read_text(encoding="utf-8"))
        latest = json.loads(STRATEGY_ALTERNATIVE_PRICING_FILE.read_text(encoding="utf-8")) if STRATEGY_ALTERNATIVE_PRICING_FILE.exists() else {}
        return 0 if latest.get("promotable") is False else 1
    payload = build_strategy_alternative_pricing(limit=args.limit, variants_per_ticker=args.variants_per_ticker)
    save_strategy_alternative_pricing(payload)
    print(strategy_alternative_pricing_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
