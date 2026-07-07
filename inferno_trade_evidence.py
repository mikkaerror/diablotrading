from __future__ import annotations

"""Shared research primitives for decision cards and normalized outcomes.

This module contains no file writes and no authority logic. It gives the paper,
shadow, analytics, and behavior layers one vocabulary for strategy families,
volatility context, friction estimates, decision-card completeness, and R-unit
outcomes.
"""

from datetime import date, datetime
from typing import Any


CONTRACT_MULTIPLIER = 100.0
LONG_VOL_STRATEGIES = {"LONG_STRADDLE", "LONG_STRANGLE"}
LONG_VOL_MAX_IMPLIED_MOVE_PCT = 20.0
LONG_VOL_MAX_ATM_SPREAD_PCT = 30.0
LONG_VOL_MAX_NLV_PCT = 25.0
LONG_VOL_EVENT_WINDOW_DAYS = 7
LONG_VOL_EVENT_IMPLIED_MOVE_MIN_PCT = 10.0
LONG_VOL_EVENT_IMPLIED_MOVE_MAX_PCT = 20.0


def text(value: Any) -> str:
    return str(value or "").strip()


def number(value: Any, default: float | None = None) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    raw = text(value).replace("$", "").replace(",", "").replace("%", "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def parse_date(value: Any) -> date | None:
    raw = text(value)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def strategy_name(item: dict[str, Any]) -> str:
    return text(
        item.get("strategy")
        or (item.get("strikePlan") or {}).get("strategy")
        or item.get("setupRec")
    ).upper()


def strategy_family(item: dict[str, Any]) -> str:
    raw = strategy_name(item).replace("_", " ")
    if "STRADDLE" in raw:
        return "Long Straddle"
    if "STRANGLE" in raw:
        return "Long Strangle"
    if "IRON CONDOR" in raw:
        return "Iron Condor"
    if "CREDIT" in raw:
        return "Credit Spread"
    if "DEBIT" in raw or "VERTICAL" in raw:
        return "Vertical Debit"
    if "COVERED CALL" in raw:
        return "Covered Call"
    if "CASH SECURED PUT" in raw:
        return "Cash-Secured Put"
    return raw.title() or "Unknown"


def is_long_vol(item: dict[str, Any]) -> bool:
    raw = strategy_name(item).replace("_", " ")
    return "STRADDLE" in raw or "STRANGLE" in raw


def normalized_percent(value: Any) -> float | None:
    """Normalize decimal fractions and already-percent values to percentage points."""
    parsed = number(value)
    if parsed is None:
        return None
    return round(parsed * 100.0 if abs(parsed) <= 1.0 else parsed, 4)


def _first_number(*values: Any) -> float | None:
    for value in values:
        parsed = number(value)
        if parsed is not None:
            return parsed
    return None


def max_loss_dollars(item: dict[str, Any]) -> float:
    metrics = ((item.get("riskVerdict") or {}).get("metrics") or {})
    plan = item.get("strikePlan") or {}
    value = _first_number(
        metrics.get("maxLossDollars"),
        item.get("estimatedMaxLoss"),
        plan.get("estimatedMaxLoss"),
        item.get("maxLossDollars"),
    )
    return max(0.0, value or 0.0)


def gross_pnl_dollars(item: dict[str, Any]) -> float | None:
    outcome = item.get("outcome") or {}
    return _first_number(
        outcome.get("estimatedPnl"),
        outcome.get("realizedPnl"),
        item.get("realizedPnl"),
        item.get("pnl"),
        item.get("outcomePnl"),
    )


def _leg_direction(leg: dict[str, Any]) -> int | None:
    instruction = text(leg.get("instruction")).upper()
    if instruction.startswith("BUY"):
        return 1
    if instruction.startswith("SELL"):
        return -1
    return None


def entry_mid_value(item: dict[str, Any]) -> float | None:
    legs = item.get("legs") or (item.get("strikePlan") or {}).get("legs") or []
    if not legs:
        return None
    net = 0.0
    for leg in legs:
        direction = _leg_direction(leg)
        mid = number(leg.get("mid"))
        if mid is None:
            bid = number(leg.get("bid"))
            ask = number(leg.get("ask"))
            if bid is not None and ask is not None:
                mid = (bid + ask) / 2.0
        if direction is None or mid is None:
            return None
        net += direction * mid
    return round(net, 6)


def estimated_friction(item: dict[str, Any]) -> dict[str, Any]:
    """Estimate round-trip friction without pretending it is realized slippage."""
    explicit = _first_number(
        (item.get("outcome") or {}).get("feesAndSlippage"),
        (item.get("outcome") or {}).get("estimatedFrictionDollars"),
    )
    if explicit is not None:
        return {
            "dollars": round(max(0.0, explicit), 4),
            "source": "outcome-explicit",
            "realized": False,
        }

    campaign_friction = _first_number(item.get("estimatedTotalSpreadFrictionDollars"))
    if campaign_friction is not None:
        return {
            "dollars": round(max(0.0, campaign_friction), 4),
            "source": "full-atm-spread-per-crossing",
            "realized": False,
        }

    outcome_notes = text((item.get("outcome") or {}).get("notes")).lower()
    if "expiration intrinsic" in outcome_notes or "expired" in outcome_notes:
        return {
            "dollars": 0.0,
            "source": "expiration-outcome-entry-limit-already-in-pnl",
            "realized": False,
        }

    entry_limit = _first_number(item.get("entryLimit"), (item.get("strikePlan") or {}).get("estimatedDebit"))
    spread_pct = _first_number(
        item.get("paperFillFrictionPct"),
        item.get("atmSpreadPctAtEntry"),
        (item.get("schwabOptions") or {}).get("paperFillFrictionPct"),
        (item.get("schwabOptions") or {}).get("atmWindowMedianSpreadPct"),
        (item.get("schwabOptions") or {}).get("atmSpreadPct"),
    )
    if spread_pct is not None and spread_pct > 1:
        spread_pct /= 100.0
    crossings = int(_first_number(item.get("paperFrictionCrossings")) or 0)
    if entry_limit is not None and spread_pct is not None and spread_pct > 0 and crossings > 0:
        return {
            "dollars": round(entry_limit * spread_pct * CONTRACT_MULTIPLIER * crossings, 4),
            "source": "full-atm-spread-per-crossing",
            "realized": False,
        }

    mid = entry_mid_value(item)
    if entry_limit is None or mid is None:
        return {"dollars": 0.0, "source": "unavailable", "realized": False}

    # Estimated P/L is already measured from entryLimit, so the entry cushion
    # is already embedded. Use one matching exit-side cushion only.
    one_way = abs(entry_limit - mid) * CONTRACT_MULTIPLIER
    return {
        "dollars": round(one_way, 4),
        "source": "modeled-exit-cushion-from-entry-quote",
        "realized": False,
    }


def normalized_outcome(item: dict[str, Any]) -> dict[str, Any]:
    gross = gross_pnl_dollars(item)
    risk = max_loss_dollars(item)
    friction = estimated_friction(item)
    net = gross - friction["dollars"] if gross is not None else None
    return {
        "grossPnlDollars": round(gross, 4) if gross is not None else None,
        "maxLossDollars": round(risk, 4),
        "grossR": round(gross / risk, 6) if gross is not None and risk > 0 else None,
        "estimatedFrictionDollars": friction["dollars"],
        "frictionSource": friction["source"],
        "frictionRealized": friction["realized"],
        "netPnlEstimateDollars": round(net, 4) if net is not None else None,
        "netREstimate": round(net / risk, 6) if net is not None and risk > 0 else None,
    }


def net_greeks(item: dict[str, Any]) -> dict[str, Any]:
    plan = item.get("strikePlan") or {}
    summary = plan.get("greekSummary") or item.get("greekSummary") or {}
    if summary:
        return {
            "netDelta": number(summary.get("netDelta")),
            "netGamma": number(summary.get("netGamma")),
            "netTheta": number(summary.get("netTheta")),
            "netVega": number(summary.get("netVega")),
            "greeksComplete": bool(summary.get("greeksComplete")),
            "volPosture": summary.get("volPosture"),
            "source": "strike-plan-net-greeks",
        }
    schwab = item.get("schwabOptions") or {}
    values = {
        "netDelta": number(schwab.get("atmNetDelta")),
        "netGamma": number(schwab.get("atmNetGamma")),
        "netTheta": number(schwab.get("atmNetTheta")),
        "netVega": number(schwab.get("atmNetVega")),
    }
    complete = all(value is not None for value in values.values())
    return {**values, "greeksComplete": complete, "volPosture": None, "source": "schwab-atm-proxy"}


def volatility_context(item: dict[str, Any]) -> dict[str, Any]:
    market = item.get("marketContext") or {}
    summary = item.get("marketContextSummary") or {}
    schwab = item.get("schwabOptions") or {}
    iv_rank = _first_number(item.get("ivRank"), market.get("ivRank"), summary.get("ivRank"))
    atr_pct = _first_number(item.get("atrPercent"), market.get("atrPercent"), summary.get("atrPercent"))
    return {
        "ivRank": round(iv_rank, 4) if iv_rank is not None else None,
        "ivRankChange": _first_number(item.get("ivRankChange"), market.get("ivRankChange")),
        "atmImpliedVolatilityPct": normalized_percent(schwab.get("atmImpliedVolatility")),
        "atmImpliedMovePct": normalized_percent(schwab.get("atmImpliedMovePct")),
        "atmSpreadPct": normalized_percent(schwab.get("atmSpreadPct")),
        "atrPercent": round(atr_pct, 4) if atr_pct is not None else None,
        "termStructure": item.get("volatilityTermStructure"),
        "quoteQualityScore": number(schwab.get("quoteQualityScore")),
        "quoteQualityLabel": schwab.get("quoteQualityLabel"),
        "atmSpreadQuality": schwab.get("atmSpreadQuality"),
        "atmLiquidityScore": number(schwab.get("atmLiquidityScore")),
        "sourceStatus": "partial" if iv_rank is not None or schwab else "missing",
        "interpretation": "context-only; no single IV threshold selects the strategy",
    }


def _profit_and_time_plan(strategy: str) -> dict[str, Any]:
    normalized = strategy.replace("_", " ")
    if "STRADDLE" in normalized or "STRANGLE" in normalized:
        return {
            "profitPlan": ["review at +0.5R", "review at +1.0R", "retain runner only by rule"],
            "maximumLossPlan": "close at the precommitted loss threshold; never add",
            "timePlan": "review at 21 DTE; hard close under the existing T-2 rule; pre-event exit unless explicitly tested",
        }
    if "CREDIT" in strategy or strategy == "IRON_CONDOR":
        return {
            "profitPlan": ["test 50% of max profit against matched alternatives"],
            "maximumLossPlan": "close at the precommitted credit-loss threshold; never widen risk",
            "timePlan": "review at 21 DTE and again in the final week; do not treat 21 DTE as a universal close",
        }
    return {
        "profitPlan": ["test +50% and +80% of max profit cohorts"],
        "maximumLossPlan": "close at the precommitted debit-loss threshold; never add",
        "timePlan": "review at 21 DTE; hard close under the existing T-2 rule",
    }


def _machine_thesis(item: dict[str, Any]) -> str:
    strategy = strategy_name(item)
    market = item.get("marketContext") or {}
    summary = item.get("marketContextSummary") or {}
    trend = text((market.get("trend") or {}).get("label") or summary.get("trend") or "unknown")
    return (
        f"Research comparison for {text(item.get('ticker')).upper()} using {strategy or 'UNKNOWN'}; "
        f"the measurable thesis is {trend.lower()} direction/volatility behavior after premium and friction."
    )


def _disconfirming_evidence(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for source in (
        item.get("intentBlocks") or [],
        (item.get("riskVerdict") or {}).get("blocks") or [],
        (item.get("riskVerdict") or {}).get("warnings") or [],
        (item.get("strikePlan") or {}).get("liquidityNotes") or [],
        (item.get("schwabOptions") or {}).get("qualityFlags") or [],
    ):
        for value in source:
            cleaned = text(value)
            if cleaned and cleaned not in values:
                values.append(cleaned)
    return values


def long_vol_hurdle(item: dict[str, Any]) -> dict[str, Any]:
    if not is_long_vol(item):
        return {"status": "not-applicable", "paperComparisonAllowed": True}

    context = volatility_context(item)
    baseline = _first_number(item.get("price"), item.get("underlyingPrice"))
    plan = item.get("strikePlan") or {}
    implied = context.get("atmImpliedMovePct")
    if implied is None and baseline and baseline > 0:
        lower = number(plan.get("lowerBreakEven") or item.get("lowerBreakEven"))
        upper = number(plan.get("upperBreakEven") or item.get("upperBreakEven"))
        moves = []
        if lower is not None and lower < baseline:
            moves.append((baseline - lower) / baseline * 100.0)
        if upper is not None and upper > baseline:
            moves.append((upper - baseline) / baseline * 100.0)
        implied = min(moves) if moves else None

    summary = item.get("marketContextSummary") or {}
    forecast = _first_number(
        item.get("forecastRealizedMovePct"),
        summary.get("forecastRealizedMovePct"),
        (item.get("decisionInputs") or {}).get("forecastRealizedMovePct"),
    )
    friction = estimated_friction(item)
    friction_pct = (
        friction["dollars"] / (baseline * CONTRACT_MULTIPLIER) * 100.0
        if baseline and baseline > 0
        else None
    )
    required = implied + (friction_pct or 0.0) if implied is not None else None
    edge = forecast - required if forecast is not None and required is not None else None
    spread_pct = context.get("atmSpreadPct")
    days_to_earnings = _first_number(
        item.get("daysUntilEarnings"),
        item.get("daysToEarnings"),
        summary.get("daysUntilEarnings"),
        summary.get("daysToEarnings"),
    )
    event_move_in_range = (
        implied is not None
        and LONG_VOL_EVENT_IMPLIED_MOVE_MIN_PCT <= implied <= LONG_VOL_EVENT_IMPLIED_MOVE_MAX_PCT
    )
    evidence_guards: list[str] = []
    if implied is not None and implied > LONG_VOL_MAX_IMPLIED_MOVE_PCT:
        evidence_guards.append("implied-move-above-20pct")
    if spread_pct is not None and spread_pct > LONG_VOL_MAX_ATM_SPREAD_PCT:
        evidence_guards.append("atm-spread-above-30pct")
    if (
        days_to_earnings is not None
        and 0 <= days_to_earnings <= LONG_VOL_EVENT_WINDOW_DAYS
        and not event_move_in_range
    ):
        evidence_guards.append("event-window-outside-10-to-20pct-implied-move")

    if implied is None:
        status = "shadow-only-unpriced"
    elif "atm-spread-above-30pct" in evidence_guards:
        status = "shadow-only-wide-spread"
    elif "implied-move-above-20pct" in evidence_guards:
        status = "shadow-only-high-implied-move"
    elif "event-window-outside-10-to-20pct-implied-move" in evidence_guards:
        status = "shadow-only-event-premium-mismatch"
    elif forecast is None:
        status = "shadow-only-missing-forecast"
    elif edge is None or edge <= 0:
        status = "shadow-only-negative-hurdle"
    elif context.get("atmSpreadQuality") == "untradeable":
        status = "shadow-only-untradeable-spread"
    else:
        status = "eligible-for-paper-comparison"
    return {
        "status": status,
        "paperComparisonAllowed": status == "eligible-for-paper-comparison",
        "impliedMovePct": round(implied, 4) if implied is not None else None,
        "forecastRealizedMovePct": round(forecast, 4) if forecast is not None else None,
        "estimatedAdditionalFrictionPctUnderlying": (
            round(friction_pct, 4) if friction_pct is not None else None
        ),
        "requiredMovePct": round(required, 4) if required is not None else None,
        "forecastEdgePct": round(edge, 4) if edge is not None else None,
        "atmSpreadPct": spread_pct,
        "daysUntilEarnings": (
            round(days_to_earnings, 2) if days_to_earnings is not None else None
        ),
        "deskEvidenceGuards": evidence_guards,
        "deskEvidencePolicy": {
            "maxImpliedMovePct": LONG_VOL_MAX_IMPLIED_MOVE_PCT,
            "maxAtmSpreadPct": LONG_VOL_MAX_ATM_SPREAD_PCT,
            "eventWindowDays": LONG_VOL_EVENT_WINDOW_DAYS,
            "eventImpliedMoveRangePct": [
                LONG_VOL_EVENT_IMPLIED_MOVE_MIN_PCT,
                LONG_VOL_EVENT_IMPLIED_MOVE_MAX_PCT,
            ],
            "basis": "desk shadow-ledger concentration, recency, and implied-move cohorts",
            "promotionEligible": False,
        },
        "reason": (
            "Long vol must forecast movement above the implied move and modeled friction; "
            "desk-specific premium, spread, and event guards remain shadow-only until "
            "fresh risk-passed evidence overturns them."
        ),
    }


def decision_card(item: dict[str, Any], *, account_nlv: float | None = None) -> dict[str, Any]:
    strategy = strategy_name(item)
    risk = max_loss_dollars(item)
    greeks = net_greeks(item)
    volatility = volatility_context(item)
    hurdle = long_vol_hurdle(item)
    plan = _profit_and_time_plan(strategy)
    disconfirming = _disconfirming_evidence(item)
    missing: list[str] = []
    if not strategy:
        missing.append("strategy")
    if risk <= 0:
        missing.append("maximum-loss")
    if not greeks.get("greeksComplete"):
        missing.append("net-greeks")
    if volatility.get("sourceStatus") == "missing":
        missing.append("volatility-context")
    if is_long_vol(item) and not hurdle.get("paperComparisonAllowed"):
        missing.append("long-vol-premium-hurdle")
    max_loss_pct = (
        round(risk / account_nlv * 100.0, 4)
        if account_nlv and account_nlv > 0
        else None
    )
    if (
        is_long_vol(item)
        and max_loss_pct is not None
        and max_loss_pct > LONG_VOL_MAX_NLV_PCT
    ):
        missing.append("long-vol-size-above-25pct-nlv")
    return {
        "version": 1,
        "machineThesis": _machine_thesis(item),
        "operatorThesis": text((item.get("decisionInputs") or {}).get("operatorThesis")) or None,
        "edgeSource": (
            "realized-move-or-iv-expansion"
            if is_long_vol(item)
            else "defined-risk-direction-or-carry"
        ),
        "disconfirmingEvidence": disconfirming or ["no explicit contradiction captured"],
        "maximumLossDollars": round(risk, 2),
        "maximumLossPctOfNlv": max_loss_pct,
        "longVolMaxLossPctOfNlvPolicy": LONG_VOL_MAX_NLV_PCT if is_long_vol(item) else None,
        **plan,
        "netGreeks": greeks,
        "liquidity": {
            "notes": list((item.get("strikePlan") or {}).get("liquidityNotes") or []),
            "quoteQualityLabel": volatility.get("quoteQualityLabel"),
            "atmSpreadQuality": volatility.get("atmSpreadQuality"),
        },
        "volatilityContext": volatility,
        "longVolHurdle": hurdle,
        "noTradeReason": (
            None
            if not missing
            else "Decision card incomplete or the premium hurdle failed: " + ", ".join(missing)
        ),
        "complete": not missing,
        "missingFields": missing,
        "paperComparisonAllowed": not missing,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
    }


def entry_dte(item: dict[str, Any]) -> int | None:
    opened = parse_date(item.get("tradeDate") or item.get("createdAt"))
    expiration = parse_date(item.get("expiration"))
    if opened is None or expiration is None:
        return None
    return (expiration - opened).days


def exit_dte(item: dict[str, Any]) -> int | None:
    outcome = item.get("outcome") or {}
    reviewed = parse_date(outcome.get("reviewedAt"))
    expiration = parse_date(item.get("expiration"))
    if reviewed is None or expiration is None:
        return None
    return (expiration - reviewed).days


def holding_days(item: dict[str, Any]) -> int | None:
    opened = parse_date(item.get("tradeDate") or item.get("createdAt"))
    reviewed = parse_date((item.get("outcome") or {}).get("reviewedAt"))
    if opened is None or reviewed is None:
        return None
    return max(0, (reviewed - opened).days)


def dte_bucket(value: int | None) -> str:
    if value is None:
        return "unknown"
    if value <= 6:
        return "0-6"
    if value <= 14:
        return "7-14"
    if value <= 21:
        return "15-21"
    if value <= 35:
        return "22-35"
    if value <= 50:
        return "36-50"
    return "51+"
