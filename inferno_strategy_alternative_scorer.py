from __future__ import annotations

"""Research-only defined-risk alternative scorer.

The expected-move ledger now tells the desk when long-vol premium is demanding
too much movement. This module takes the next step: for hard/extreme long-vol
candidates, compare non-call defined-risk structures that could express the
same thesis with better theta/vega posture.

Strict contract:
- diagnostic-only and research-only
- no broker calls, approvals, order creation, or authority promotion
- unpriced alternatives are capped; they are ideas to price, not tickets
"""

import argparse
import json
from typing import Any

from inferno_config import MAX_SINGLE_TICKET_DOLLARS, local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


STRATEGY_ALTERNATIVE_SCORER_FILE = DATA_DIR / "inferno_strategy_alternative_scorer.json"
STRATEGY_ALTERNATIVE_SCORER_TEXT_FILE = REPORTS_DIR / "strategy_alternative_scorer_latest.txt"
STRATEGY_ALTERNATIVE_SCORER_STAGE = "strategy-alternative-scorer-research-only"

EXPECTED_MOVE_LEDGER_FILE = DATA_DIR / "inferno_expected_move_ledger.json"
PAPER_BOTTLENECK_REDUCER_FILE = DATA_DIR / "inferno_paper_bottleneck_reducer.json"
STRIKE_PLAN_FILE = DATA_DIR / "inferno_strike_plan.json"

PRIMARY_HURDLES = {"hard", "extreme"}
WATCH_HURDLES = {"stretch"}
SUPPORTED_ALTERNATIVES = ("PUT_CREDIT_SPREAD", "IRON_CONDOR", "PUT_DEBIT_SPREAD", "STAND_ASIDE")


def text(value: Any) -> str:
    """Normalize loose artifact values to stripped text."""
    return str(value or "").strip()


def norm(value: Any) -> str:
    """Normalize symbols/labels for matching."""
    return text(value).upper()


def number(value: Any, default: float | None = None) -> float | None:
    """Coerce artifact values into floats without trusting display formatting."""
    if isinstance(value, (int, float)):
        return float(value)
    raw = text(value).replace("$", "").replace(",", "").replace("%", "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def clamp_score(value: float) -> float:
    """Keep diagnostic scores in a stable 0-100 range."""
    return round(max(0.0, min(100.0, value)), 4)


def lookup_by_ticker(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return the first row for each ticker."""
    lookup: dict[str, dict[str, Any]] = {}
    for item in items:
        ticker = norm(item.get("ticker"))
        if ticker and ticker not in lookup:
            lookup[ticker] = item
    return lookup


def strike_plan_lookup(strike_plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index strike-plan rows by ticker."""
    return lookup_by_ticker([item for item in strike_plan.get("items") or [] if isinstance(item, dict)])


def reducer_lookup(reducer: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index reducer scenarios by ticker."""
    return lookup_by_ticker([item for item in reducer.get("scenarioSlate") or [] if isinstance(item, dict)])


def metric_context(strike_item: dict[str, Any] | None) -> dict[str, Any]:
    """Extract quote-quality and drift metrics from a strike-plan item."""
    if not strike_item:
        return {
            "chainPriced": False,
            "quoteQualityLabel": "missing",
            "qualityFlags": ["missing-strike-plan"],
            "atmSpreadPct": None,
            "underlyingSourceDriftPct": None,
        }
    metrics = (strike_item.get("riskVerdict") or {}).get("metrics") or {}
    schwab = metrics.get("schwabOptions") or {}
    return {
        "chainPriced": True,
        "quoteQualityLabel": text(schwab.get("quoteQualityLabel") or "unknown"),
        "qualityFlags": list(schwab.get("qualityFlags") or []),
        "atmSpreadPct": number(schwab.get("atmSpreadPct")),
        "atmLiquidityScore": number(schwab.get("atmLiquidityScore")),
        "underlyingSourceDriftPct": number(metrics.get("underlyingSourceDriftPct")),
    }


def chain_penalty(quality: dict[str, Any]) -> tuple[float, list[str]]:
    """Return a confidence penalty from chain/quote quality."""
    penalty = 0.0
    warnings: list[str] = []
    if not quality.get("chainPriced"):
        penalty += 8.0
        warnings.append("no priced strike-plan row yet; cap confidence and run strike cycle before staging")
    label = text(quality.get("quoteQualityLabel")).lower()
    if label == "poor":
        penalty += 8.0
        warnings.append("poor option-chain quote quality")
    elif label == "fragile":
        penalty += 4.0
        warnings.append("fragile option-chain quote quality")
    flags = {text(flag).lower() for flag in quality.get("qualityFlags") or []}
    if "no-liquid-contracts" in flags:
        penalty += 18.0
        warnings.append("no-liquid-contracts flag blocks confidence")
    if "thin-atm-liquidity" in flags:
        penalty += 6.0
        warnings.append("thin ATM liquidity")
    spread = number(quality.get("atmSpreadPct"))
    if spread is not None and spread > 0.20:
        penalty += 6.0
        warnings.append("wide ATM spread")
    drift = abs(number(quality.get("underlyingSourceDriftPct"), 0.0) or 0.0)
    if drift > 5.0:
        penalty += 8.0
        warnings.append(f"underlying source drift {drift:.2f}% exceeds 5%")
    return penalty, warnings


def merged_context(
    candidate: dict[str, Any],
    reducer_item: dict[str, Any] | None,
    strike_item: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge expected-move, reducer, and strike-plan context for one ticker."""
    reducer_item = reducer_item or {}
    market = dict(reducer_item.get("marketContextSummary") or {})
    market.update({k: v for k, v in (candidate.get("marketContextSummary") or {}).items() if v is not None})
    quality = metric_context(strike_item)
    penalty, warnings = chain_penalty(quality)
    return {
        "ticker": norm(candidate.get("ticker")),
        "hurdle": text(candidate.get("premiumHurdleLabel")),
        "hurdleAtrMultiple": number(candidate.get("requiredMoveAtrMultiple")),
        "longVolPressureScore": number(candidate.get("rankPressureScore"), number(candidate.get("scenarioScore"), 0.0)) or 0.0,
        "scenarioScore": number(candidate.get("scenarioScore"), 0.0) or 0.0,
        "readiness": number(candidate.get("readiness"), 0.0) or 0.0,
        "requiredMovePct": number(candidate.get("impliedMovePct")),
        "atrPercent": number(candidate.get("atrPercent") or market.get("atrPercent")),
        "trend": text(market.get("trend")),
        "rvol": number(market.get("rvol")),
        "ivRank": number(market.get("ivRank")),
        "distanceToSupportPct": number(market.get("distanceToSupportPct")),
        "distanceToResistancePct": number(market.get("distanceToResistancePct")),
        "daysUntilEarnings": number(reducer_item.get("daysUntilEarnings")),
        "estimatedMaxLoss": number(candidate.get("estimatedMaxLoss") or reducer_item.get("estimatedMaxLoss")),
        "paperAutoSelected": bool(candidate.get("paperAutoSelected")),
        "chainQuality": quality,
        "chainPenalty": penalty,
        "chainWarnings": warnings,
    }


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    """Return numerator/denominator when both are usable."""
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def bullish_trend(trend: str) -> bool:
    """Return True when trend text supports bullish structures."""
    raw = trend.lower()
    return "bull" in raw or "uptrend" in raw or raw == "up"


def bearish_trend(trend: str) -> bool:
    """Return True when trend text supports bearish structures."""
    raw = trend.lower()
    return "bear" in raw or "downtrend" in raw or raw == "down"


def calm_trend(trend: str) -> bool:
    """Return True for neutral/range labels."""
    raw = trend.lower()
    return any(token in raw for token in ("neutral", "range", "sideways", "flat", "calm"))


def score_with_quality(raw_score: float, context: dict[str, Any]) -> tuple[float, list[str]]:
    """Apply chain-quality penalty and cap unpriced alternatives."""
    score = raw_score - (number(context.get("chainPenalty"), 0.0) or 0.0)
    notes = list(context.get("chainWarnings") or [])
    if not (context.get("chainQuality") or {}).get("chainPriced"):
        score = min(score, 72.0)
        notes.append("unpriced alternative score capped at 72")
    return clamp_score(score), notes


def put_credit_spread_score(context: dict[str, Any]) -> dict[str, Any]:
    """Score bullish defined-risk short-premium via put credit spread."""
    raw = 45.0
    reasons: list[str] = []
    warnings: list[str] = []
    if bullish_trend(context["trend"]):
        raw += 16.0
        reasons.append("bullish/uptrend context supports positive-delta put credit posture")
    elif calm_trend(context["trend"]):
        raw += 4.0
        reasons.append("neutral context is acceptable for conservative short-premium")
    else:
        raw -= 16.0
        warnings.append(f"trend {context['trend'] or 'unknown'} does not support bullish put credit")

    support_atr = ratio(context.get("distanceToSupportPct"), context.get("atrPercent"))
    if support_atr is None:
        warnings.append("missing support/ATR cushion")
    elif support_atr >= 2.5:
        raw += 14.0
        reasons.append(f"support cushion is {support_atr:.2f} ATR")
    elif support_atr >= 1.5:
        raw += 8.0
        reasons.append(f"support cushion is usable at {support_atr:.2f} ATR")
    elif support_atr >= 1.0:
        raw += 3.0
        warnings.append(f"support cushion is thin at {support_atr:.2f} ATR")
    else:
        raw -= 18.0
        warnings.append(f"support cushion is too thin at {support_atr:.2f} ATR")

    iv_rank = context.get("ivRank")
    if iv_rank is not None and iv_rank >= 30:
        raw += 8.0
        reasons.append(f"IV rank {iv_rank:.1f} supports short premium")
    elif iv_rank is not None and iv_rank >= 20:
        raw += 4.0
        reasons.append(f"IV rank {iv_rank:.1f} is adequate for defined-risk credit")
    else:
        raw -= 4.0
        warnings.append("IV rank is low or missing for short-premium collection")

    if context.get("hurdle") == "extreme":
        raw += 12.0
        reasons.append("extreme long-vol hurdle favors short-premium alternatives")
    elif context.get("hurdle") == "hard":
        raw += 8.0
        reasons.append("hard long-vol hurdle favors defined-risk premium")
    elif context.get("hurdle") == "stretch":
        raw += 3.0
        reasons.append("stretch long-vol hurdle gives mild support to short premium")

    rvol = context.get("rvol")
    if rvol is not None and rvol > 2.0:
        raw -= 8.0
        warnings.append(f"rvol {rvol:.2f} is elevated for short premium")
    elif rvol is not None and rvol > 1.5:
        raw -= 4.0
        warnings.append(f"rvol {rvol:.2f} needs smaller sizing")

    score, quality_notes = score_with_quality(raw, context)
    warnings.extend(quality_notes)
    return {
        "strategy": "PUT_CREDIT_SPREAD",
        "score": score,
        "rawScore": clamp_score(raw),
        "scoreEdgeVsLongVol": round(score - context["longVolPressureScore"], 4),
        "expectedGreekPosture": {
            "delta": "mild-positive",
            "theta": "positive",
            "vega": "negative",
            "maxLoss": "defined",
        },
        "mathInputs": {
            "supportAtrMultiple": support_atr,
            "ivRank": context.get("ivRank"),
            "rvol": context.get("rvol"),
        },
        "reasons": reasons,
        "warnings": warnings,
    }


def iron_condor_score(context: dict[str, Any]) -> dict[str, Any]:
    """Score neutral defined-risk short-premium via iron condor."""
    raw = 40.0
    reasons: list[str] = []
    warnings: list[str] = []
    support_atr = ratio(context.get("distanceToSupportPct"), context.get("atrPercent"))
    resistance_atr = ratio(context.get("distanceToResistancePct"), context.get("atrPercent"))
    range_atr = min(value for value in (support_atr, resistance_atr) if value is not None) if support_atr is not None and resistance_atr is not None else None
    if range_atr is None:
        warnings.append("missing two-sided range/ATR cushion")
    elif range_atr >= 2.0:
        raw += 14.0
        reasons.append(f"two-sided range cushion is {range_atr:.2f} ATR")
    elif range_atr >= 1.25:
        raw += 6.0
        reasons.append(f"two-sided range cushion is marginal at {range_atr:.2f} ATR")
    else:
        raw -= 18.0
        warnings.append(f"two-sided range cushion is too tight at {range_atr:.2f} ATR")

    if calm_trend(context["trend"]):
        raw += 10.0
        reasons.append("calm/range trend supports neutral premium")
    elif bullish_trend(context["trend"]) or bearish_trend(context["trend"]):
        raw -= 6.0
        warnings.append(f"directional trend {context['trend'] or 'unknown'} weakens condor fit")

    rvol = context.get("rvol")
    if rvol is not None and rvol <= 1.0:
        raw += 8.0
        reasons.append(f"rvol {rvol:.2f} is calm enough for range premium")
    elif rvol is not None and rvol <= 1.25:
        raw += 4.0
        reasons.append(f"rvol {rvol:.2f} is acceptable")
    elif rvol is not None and rvol > 1.5:
        raw -= 8.0
        warnings.append(f"rvol {rvol:.2f} is too active for condor comfort")

    iv_rank = context.get("ivRank")
    if iv_rank is not None and iv_rank >= 25:
        raw += 6.0
        reasons.append(f"IV rank {iv_rank:.1f} helps short-vol premium")

    if context.get("hurdle") in {"hard", "extreme"}:
        raw += 8.0
        reasons.append("expensive long-vol hurdle supports short-vol comparison")

    dte = context.get("daysUntilEarnings")
    if dte is not None and dte <= 7:
        raw -= 6.0
        warnings.append(f"{dte:.0f} days to earnings leaves event-gap risk")

    score, quality_notes = score_with_quality(raw, context)
    warnings.extend(quality_notes)
    return {
        "strategy": "IRON_CONDOR",
        "score": score,
        "rawScore": clamp_score(raw),
        "scoreEdgeVsLongVol": round(score - context["longVolPressureScore"], 4),
        "expectedGreekPosture": {
            "delta": "near-neutral",
            "theta": "positive",
            "vega": "negative",
            "maxLoss": "defined",
        },
        "mathInputs": {
            "supportAtrMultiple": support_atr,
            "resistanceAtrMultiple": resistance_atr,
            "rangeAtrMultiple": range_atr,
            "rvol": context.get("rvol"),
        },
        "reasons": reasons,
        "warnings": warnings,
    }


def put_debit_spread_score(context: dict[str, Any]) -> dict[str, Any]:
    """Score bearish defined-risk debit via put debit spread."""
    raw = 35.0
    reasons: list[str] = []
    warnings: list[str] = []
    if bearish_trend(context["trend"]):
        raw += 18.0
        reasons.append("bearish trend supports negative-delta debit")
    elif bullish_trend(context["trend"]):
        raw -= 10.0
        warnings.append(f"bullish trend {context['trend']} fights bearish put debit")
    elif calm_trend(context["trend"]):
        raw += 2.0
        reasons.append("neutral trend allows a small bearish hedge only")

    resistance_atr = ratio(context.get("distanceToResistancePct"), context.get("atrPercent"))
    if resistance_atr is None:
        warnings.append("missing resistance/ATR context")
    elif resistance_atr <= 0.5:
        raw += 14.0
        reasons.append(f"resistance is very close at {resistance_atr:.2f} ATR")
    elif resistance_atr <= 1.0:
        raw += 8.0
        reasons.append(f"resistance is close at {resistance_atr:.2f} ATR")
    elif resistance_atr <= 1.5:
        raw += 4.0
        reasons.append(f"resistance is within {resistance_atr:.2f} ATR")
    else:
        raw -= 6.0
        warnings.append(f"resistance is not close enough at {resistance_atr:.2f} ATR")

    rvol = context.get("rvol")
    if rvol is not None and rvol > 1.5:
        raw += 4.0
        reasons.append(f"rvol {rvol:.2f} supports directional movement")

    iv_rank = context.get("ivRank")
    if iv_rank is not None and iv_rank < 25:
        raw += 4.0
        reasons.append(f"IV rank {iv_rank:.1f} keeps debit less punished")
    elif iv_rank is not None and iv_rank > 50:
        raw -= 4.0
        warnings.append(f"IV rank {iv_rank:.1f} makes debit structures expensive")

    if context.get("hurdle") in {"hard", "extreme"}:
        raw += 4.0
        reasons.append("defined-risk debit beats uncapped long-vol premium exposure")

    score, quality_notes = score_with_quality(raw, context)
    warnings.extend(quality_notes)
    return {
        "strategy": "PUT_DEBIT_SPREAD",
        "score": score,
        "rawScore": clamp_score(raw),
        "scoreEdgeVsLongVol": round(score - context["longVolPressureScore"], 4),
        "expectedGreekPosture": {
            "delta": "negative",
            "theta": "limited-negative",
            "vega": "limited-positive",
            "maxLoss": "defined",
        },
        "mathInputs": {
            "resistanceAtrMultiple": resistance_atr,
            "ivRank": context.get("ivRank"),
            "rvol": context.get("rvol"),
        },
        "reasons": reasons,
        "warnings": warnings,
    }


def stand_aside_score(context: dict[str, Any]) -> dict[str, Any]:
    """Score no-new-structure as a valid risk decision."""
    raw = 42.0
    reasons = ["standing aside is a valid defined-risk decision when premium and chain quality disagree"]
    warnings: list[str] = []
    if context.get("hurdle") == "extreme":
        raw += 20.0
        reasons.append("extreme long-vol hurdle")
    elif context.get("hurdle") == "hard":
        raw += 12.0
        reasons.append("hard long-vol hurdle")
    if context.get("chainPenalty", 0) >= 20:
        raw += 12.0
        reasons.append("option-chain quality penalty is severe")
    elif context.get("chainPenalty", 0) >= 10:
        raw += 6.0
        reasons.append("option-chain quality penalty is meaningful")
    estimated_loss = context.get("estimatedMaxLoss")
    if estimated_loss is not None and estimated_loss > MAX_SINGLE_TICKET_DOLLARS:
        raw += 6.0
        reasons.append(f"original long-vol max loss exceeds ${MAX_SINGLE_TICKET_DOLLARS:.0f} cap")
    return {
        "strategy": "STAND_ASIDE",
        "score": clamp_score(raw),
        "rawScore": clamp_score(raw),
        "scoreEdgeVsLongVol": round(clamp_score(raw) - context["longVolPressureScore"], 4),
        "expectedGreekPosture": {
            "delta": "none",
            "theta": "none",
            "vega": "none",
            "maxLoss": "zero new risk",
        },
        "mathInputs": {
            "chainPenalty": context.get("chainPenalty"),
            "estimatedMaxLoss": estimated_loss,
        },
        "reasons": reasons,
        "warnings": warnings,
    }


def score_alternatives(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Score the supported non-call alternatives for one candidate."""
    alternatives = [
        put_credit_spread_score(context),
        iron_condor_score(context),
        put_debit_spread_score(context),
        stand_aside_score(context),
    ]
    return sorted(
        alternatives,
        key=lambda item: (
            -number(item.get("score"), 0.0),
            item.get("strategy") == "STAND_ASIDE",
            text(item.get("strategy")),
        ),
    )


def recommendation_for(alternatives: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    """Choose the top diagnostic recommendation and verdict."""
    tradable_alts = [item for item in alternatives if item.get("strategy") != "STAND_ASIDE"]
    best_alt = tradable_alts[0] if tradable_alts else None
    stand_aside = next((item for item in alternatives if item.get("strategy") == "STAND_ASIDE"), None)
    if not best_alt:
        return {"strategy": "STAND_ASIDE", "verdict": "stand-aside", "reason": "no supported alternative"}
    edge = number(best_alt.get("scoreEdgeVsLongVol"), 0.0) or 0.0
    score = number(best_alt.get("score"), 0.0) or 0.0
    stand_score = number((stand_aside or {}).get("score"), 0.0) or 0.0
    if stand_score > score + 5.0:
        return {
            "strategy": "STAND_ASIDE",
            "verdict": "stand-aside",
            "reason": "chain/risk penalties beat the available alternatives",
        }
    if score >= 70 and edge >= 5.0:
        return {
            "strategy": best_alt["strategy"],
            "verdict": "prefer-alternative-research",
            "reason": "alternative score clears long-vol pressure by at least 5 points",
        }
    if score >= 55:
        return {
            "strategy": best_alt["strategy"],
            "verdict": "compare-in-paper",
            "reason": "alternative is plausible but needs priced-chain confirmation",
        }
    return {
        "strategy": "STAND_ASIDE",
        "verdict": "insufficient-alternative-edge",
        "reason": "no non-call alternative clears the research threshold",
    }


def candidate_scorecard(
    candidate: dict[str, Any],
    *,
    reducer_item: dict[str, Any] | None = None,
    strike_item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one ticker-level alternative scorecard."""
    context = merged_context(candidate, reducer_item, strike_item)
    alternatives = score_alternatives(context)
    recommendation = recommendation_for(alternatives, context)
    return {
        "ticker": context["ticker"],
        "hurdle": context["hurdle"],
        "hurdleAtrMultiple": context.get("hurdleAtrMultiple"),
        "scenarioScore": context.get("scenarioScore"),
        "longVolPressureScore": context.get("longVolPressureScore"),
        "requiredMovePct": context.get("requiredMovePct"),
        "atrPercent": context.get("atrPercent"),
        "trend": context.get("trend"),
        "chainQuality": context.get("chainQuality"),
        "chainPenalty": context.get("chainPenalty"),
        "recommendation": recommendation,
        "alternatives": alternatives,
        "authority": {
            "brokerSubmitAllowed": False,
            "liveTradingAllowed": False,
            "promotable": False,
        },
    }


def build_strategy_alternative_scorer(
    *,
    expected_move: dict[str, Any] | None = None,
    reducer: dict[str, Any] | None = None,
    strike_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the research-only defined-risk alternative scorer."""
    ensure_dirs()
    expected_move = expected_move if expected_move is not None else (load_json_file(EXPECTED_MOVE_LEDGER_FILE) or {})
    reducer = reducer if reducer is not None else (load_json_file(PAPER_BOTTLENECK_REDUCER_FILE) or {})
    strike_plan = strike_plan if strike_plan is not None else (load_json_file(STRIKE_PLAN_FILE) or {})
    reducer_by_ticker = reducer_lookup(reducer)
    strike_by_ticker = strike_plan_lookup(strike_plan)
    pressure_candidates = [
        item
        for item in expected_move.get("currentCandidates") or expected_move.get("currentPressureCandidates") or []
        if text(item.get("premiumHurdleLabel")) in PRIMARY_HURDLES | WATCH_HURDLES
    ]
    scorecards = [
        candidate_scorecard(
            item,
            reducer_item=reducer_by_ticker.get(norm(item.get("ticker"))),
            strike_item=strike_by_ticker.get(norm(item.get("ticker"))),
        )
        for item in pressure_candidates
    ]
    primary = [item for item in scorecards if item.get("hurdle") in PRIMARY_HURDLES]
    verdict_counts: dict[str, int] = {}
    recommendation_counts: dict[str, int] = {}
    for item in scorecards:
        verdict = text((item.get("recommendation") or {}).get("verdict")) or "unknown"
        strategy = text((item.get("recommendation") or {}).get("strategy")) or "unknown"
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
        recommendation_counts[strategy] = recommendation_counts.get(strategy, 0) + 1
    overall_verdict = "no-pressure-candidates"
    if primary:
        if verdict_counts.get("prefer-alternative-research"):
            overall_verdict = "alternatives-preferred"
        elif verdict_counts.get("compare-in-paper"):
            overall_verdict = "alternatives-watch"
        else:
            overall_verdict = "stand-aside-biased"
    return {
        "generatedAt": local_now().isoformat(),
        "stage": STRATEGY_ALTERNATIVE_SCORER_STAGE,
        "verdict": overall_verdict,
        "researchOnly": True,
        "diagnosticOnly": True,
        "promotable": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "counts": {
            "pressureCandidates": len(scorecards),
            "primaryHardExtreme": len(primary),
            "watchStretch": sum(1 for item in scorecards if item.get("hurdle") in WATCH_HURDLES),
            "verdicts": verdict_counts,
            "recommendations": recommendation_counts,
        },
        "scorecards": sorted(
            scorecards,
            key=lambda item: (
                -number((item.get("alternatives") or [{}])[0].get("score"), 0.0),
                text(item.get("ticker")),
            ),
        ),
        "rules": [
            "Only non-call defined-risk alternatives are scored in this pass.",
            "Scores are diagnostic rankings; unpriced alternatives must be priced by strike cycle before staging.",
            "No strategy here can relax paper/live gates or broker-submit authority.",
        ],
    }


def fmt(value: Any) -> str:
    """Render optional numeric values compactly."""
    parsed = number(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:.4g}"


def strategy_alternative_scorer_text(payload: dict[str, Any]) -> str:
    """Render a concise alternative-scorer memo."""
    counts = payload.get("counts") or {}
    lines = [
        "Inferno Strategy Alternative Scorer",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Verdict: {payload.get('verdict')}",
        "Authority: research-only; promotable=False; liveTradingAllowed=False",
        "",
        "Counts:",
        f"- pressure candidates: {counts.get('pressureCandidates', 0)}",
        f"- hard/extreme candidates: {counts.get('primaryHardExtreme', 0)}",
        f"- stretch watch candidates: {counts.get('watchStretch', 0)}",
        f"- verdicts: {json.dumps(counts.get('verdicts') or {})}",
        f"- recommendations: {json.dumps(counts.get('recommendations') or {})}",
        "",
        "Ticker scorecards:",
    ]
    if not payload.get("scorecards"):
        lines.append("- none")
    for item in payload.get("scorecards") or []:
        rec = item.get("recommendation") or {}
        alternatives = item.get("alternatives") or []
        rec_alt = next(
            (alt for alt in alternatives if alt.get("strategy") == rec.get("strategy")),
            next(iter(alternatives), {}),
        )
        best_overall = next(iter(alternatives), {})
        lines.append(
            f"- {item.get('ticker')} | hurdle={item.get('hurdle')} "
            f"ATRx={fmt(item.get('hurdleAtrMultiple'))} | "
            f"long-vol pressure score={fmt(item.get('longVolPressureScore'))} | "
            f"recommend={rec.get('strategy')} ({rec.get('verdict')})"
        )
        lines.append(
            f"  recommended score: {rec_alt.get('strategy')} {fmt(rec_alt.get('score'))} | "
            f"edge vs long vol {fmt(rec_alt.get('scoreEdgeVsLongVol'))} | "
            f"chain penalty {fmt(item.get('chainPenalty'))}"
        )
        if best_overall.get("strategy") != rec_alt.get("strategy"):
            lines.append(
                f"  competing risk decision: {best_overall.get('strategy')} "
                f"{fmt(best_overall.get('score'))}"
            )
        posture = rec_alt.get("expectedGreekPosture") or {}
        lines.append(
            f"  greeks: delta={posture.get('delta')} | theta={posture.get('theta')} | "
            f"vega={posture.get('vega')} | maxLoss={posture.get('maxLoss')}"
        )
        reasons = rec_alt.get("reasons") or []
        warnings = rec_alt.get("warnings") or []
        if reasons:
            lines.append(f"  why: {'; '.join(str(reason) for reason in reasons[:3])}")
        if warnings:
            lines.append(f"  watch: {'; '.join(str(warning) for warning in warnings[:3])}")
    lines.extend(["", "Rules:"])
    for rule in payload.get("rules") or []:
        lines.append(f"- {rule}")
    return "\n".join(lines).rstrip() + "\n"


def save_strategy_alternative_scorer(payload: dict[str, Any]) -> None:
    """Persist strategy alternative scorer artifacts."""
    ensure_dirs()
    atomic_write_json(STRATEGY_ALTERNATIVE_SCORER_FILE, payload)
    atomic_write_text(STRATEGY_ALTERNATIVE_SCORER_TEXT_FILE, strategy_alternative_scorer_text(payload))


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Score non-call defined-risk alternatives for pressured long-vol candidates.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    """Run the strategy alternative scorer CLI."""
    args = parse_args()
    if args.command == "status" and STRATEGY_ALTERNATIVE_SCORER_TEXT_FILE.exists():
        print(STRATEGY_ALTERNATIVE_SCORER_TEXT_FILE.read_text(encoding="utf-8"))
        latest = json.loads(STRATEGY_ALTERNATIVE_SCORER_FILE.read_text(encoding="utf-8")) if STRATEGY_ALTERNATIVE_SCORER_FILE.exists() else {}
        return 0 if latest.get("promotable") is False else 1
    payload = build_strategy_alternative_scorer()
    save_strategy_alternative_scorer(payload)
    print(strategy_alternative_scorer_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
