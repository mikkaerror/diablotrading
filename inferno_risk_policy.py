from __future__ import annotations

"""Central risk policy for the Inferno execution stack.

The dashboard can be loud and theatrical. This module is intentionally not. It
is the portfolio manager standing behind the demon throne with a clipboard,
blocking tickets that exceed size, freshness, duplicate, or reward/risk gates.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from inferno_config import (
    MAX_DAILY_TICKET_DOLLARS,
    MAX_OPEN_PAPER_TICKETS,
    MAX_SINGLE_TICKET_DOLLARS,
    MAX_STRIKE_PLAN_AGE_MINUTES,
    MAX_UNDERLYING_SOURCE_DIVERGENCE_PCT,
    MIN_CREDIT_SPREAD_CREDIT_RISK,
    MIN_DEBIT_SPREAD_REWARD_RISK,
    local_now,
)

SCHWAB_OPTIONS_MAX_AGE_HOURS = 36.0


def current_single_ticket_cap() -> dict[str, Any]:
    """Resolve the effective per-ticket cap for the current cycle.

    Consults ``inferno_capital_scaling.current_recommended_cap()`` lazily so
    risk policy stays importable even if the scaling module is missing or
    broken. Always returns a safe ``float`` for ``effectiveCap``: the config
    constant is the floor-of-truth fallback.

    Return shape::

        {
          "effectiveCap":          float,  # always present
          "source":                str,    # "ack" | "config-default" | "scaling-unavailable"
          "recommendedCap":        float | None,
          "ackedCap":              float | None,
          "verdict":               str | None,
          "shouldUseRecommendation": bool,
        }
    """
    try:
        from inferno_capital_scaling import current_recommended_cap  # lazy
        info = current_recommended_cap() or {}
    except Exception:
        return {
            "effectiveCap": float(MAX_SINGLE_TICKET_DOLLARS),
            "source": "scaling-unavailable",
            "recommendedCap": None,
            "ackedCap": None,
            "verdict": None,
            "shouldUseRecommendation": False,
        }
    effective = info.get("effectiveCap")
    if effective is None or not isinstance(effective, (int, float)):
        effective = float(MAX_SINGLE_TICKET_DOLLARS)
    return {
        "effectiveCap": float(effective),
        "source": "ack" if info.get("shouldUseRecommendation") else "config-default",
        "recommendedCap": info.get("recommendedCap"),
        "ackedCap": info.get("ackedCap"),
        "verdict": info.get("verdict"),
        "shouldUseRecommendation": bool(info.get("shouldUseRecommendation")),
    }


@dataclass(frozen=True)
class RiskVerdict:
    """Structured risk verdict consumed by strike and paper-execution flows."""

    passed: bool
    blocks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe copy for audit artifacts."""
        return {
            "passed": self.passed,
            "blocks": self.blocks,
            "warnings": self.warnings,
            "metrics": self.metrics,
        }


def number(value: Any, default: float = 0.0) -> float:
    """Safely coerce loose spreadsheet/API values into floats."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed


def parse_timestamp(value: Any) -> datetime | None:
    """Parse ISO timestamps while tolerating missing or malformed data."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def strategy_plan(item: dict[str, Any]) -> dict[str, Any]:
    """Return the nested strike-plan object for a strike item."""
    plan = item.get("strikePlan")
    return plan if isinstance(plan, dict) else {}


def max_loss_dollars(item: dict[str, Any]) -> float:
    """Estimate max ticket loss in dollars.

    The strike selector already writes `estimatedMaxLoss` in contract dollars.
    If a strategy ever omits that field, debit paid is the fallback because debit
    strategies can normally lose the premium.
    """
    plan = strategy_plan(item)
    explicit_loss = number(plan.get("estimatedMaxLoss"), default=-1)
    if explicit_loss >= 0:
        return explicit_loss
    debit = number(plan.get("estimatedDebit"), default=0)
    return round(debit * 100, 2)


def max_profit_dollars(item: dict[str, Any]) -> float | None:
    """Return numeric max profit when known; `None` means uncapped/unknown."""
    raw = strategy_plan(item).get("estimatedMaxProfit")
    if isinstance(raw, str):
        return None
    return number(raw, default=0)


def open_paper_items(ledger_items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Find currently open simulated tickets in the paper ledger."""
    items = ledger_items or []
    return [
        item for item in items
        if item.get("status") == "paper-staged"
        and (item.get("outcome") or {}).get("status") == "open"
    ]


def same_ticker_open(ticker: str, ledger_items: list[dict[str, Any]] | None) -> bool:
    """Prevent repeated exposure to the same ticker before the first ticket resolves."""
    ticker = ticker.upper()
    return any(str(item.get("ticker", "")).upper() == ticker for item in open_paper_items(ledger_items))


def projected_daily_loss(item: dict[str, Any], ledger_items: list[dict[str, Any]] | None) -> float:
    """Calculate today's simulated max-loss exposure after adding `item`."""
    today = local_now().date().isoformat()
    current = sum(
        number(item.get("estimatedMaxLoss"))
        for item in open_paper_items(ledger_items)
        if item.get("tradeDate") == today
    )
    return round(current + max_loss_dollars(item), 2)


def strike_plan_age_minutes(generated_at: str | None) -> float | None:
    """Return age in minutes for stale-data gating."""
    parsed = parse_timestamp(generated_at)
    if not parsed:
        return None
    age_seconds = (local_now() - parsed).total_seconds()
    return round(max(0.0, age_seconds / 60), 2)


def debit_spread_reward_risk(item: dict[str, Any]) -> float | None:
    """Compute reward/risk for debit spreads when both sides are bounded."""
    plan = strategy_plan(item)
    if "estimatedDebit" not in plan:
        return None
    loss = max_loss_dollars(item)
    profit = max_profit_dollars(item)
    if profit is None or loss <= 0:
        return None
    return round(profit / loss, 4)


def credit_spread_credit_risk(item: dict[str, Any]) -> float | None:
    """Compute credit/risk for defined-risk credit spreads."""
    plan = strategy_plan(item)
    if "estimatedCredit" not in plan:
        return None
    credit = number(plan.get("estimatedCredit"), default=0) * 100
    loss = max_loss_dollars(item)
    if credit <= 0 or loss <= 0:
        return 0.0
    return round(credit / loss, 4)


def underlying_source_drift(item: dict[str, Any]) -> dict[str, Any]:
    """Compare the intent price with Schwab's current chain underlying."""
    source_price = number(item.get("sourcePrice"), number(item.get("price")))
    effective_price = number(item.get("price"))
    schwab_options = item.get("schwabOptions") if isinstance(item.get("schwabOptions"), dict) else {}
    schwab_underlying = number(schwab_options.get("underlyingPrice")) if schwab_options else 0.0
    drift_pct = None
    if source_price > 0 and schwab_underlying > 0:
        drift_pct = round((schwab_underlying - source_price) / source_price * 100.0, 4)
    return {
        "sourcePrice": source_price or None,
        "effectivePrice": effective_price or None,
        "schwabUnderlyingPrice": schwab_underlying or None,
        "underlyingSourceDriftPct": drift_pct,
        "maxUnderlyingSourceDivergencePct": MAX_UNDERLYING_SOURCE_DIVERGENCE_PCT,
    }


VISIBLE_QUOTE_MIN_PRICE = 0.10  # bids/asks below this are not real markets


def visible_quote_blocks(item: dict[str, Any]) -> list[str]:
    """Require executable-looking quotes on every option leg.

    Buy legs need an ask ≥ $0.10. Sell legs need a bid ≥ $0.10. The dollar
    floor catches cases where the option market has effectively walked away
    (e.g., bid of $0.05 on an illiquid OTM strike) — those quotes look
    "visible" but are not real markets. The Phase A slippage investigation
    surfaced THR-style cases where bid=$0.05 was feeding through to wildly
    conservative debit estimates via the worst-case ask-minus-bid formula.
    """
    blocks: list[str] = []
    for leg in strategy_plan(item).get("legs", []):
        instruction = str(leg.get("instruction", "")).upper()
        symbol = leg.get("symbol") or "UNKNOWN"
        ask = number(leg.get("ask"))
        bid = number(leg.get("bid"))
        if instruction.startswith("BUY") and ask < VISIBLE_QUOTE_MIN_PRICE:
            blocks.append(
                f"{symbol} buy leg ask {ask:.2f} below visible-market floor "
                f"${VISIBLE_QUOTE_MIN_PRICE:.2f}"
            )
        if instruction.startswith("SELL") and bid < VISIBLE_QUOTE_MIN_PRICE:
            blocks.append(
                f"{symbol} sell leg bid {bid:.2f} below visible-market floor "
                f"${VISIBLE_QUOTE_MIN_PRICE:.2f}"
            )
    return blocks


def market_context_guards(item: dict[str, Any]) -> tuple[list[str], list[str], dict[str, Any]]:
    """Apply setup-aware blocks and warnings from confirmation metrics."""
    plan = strategy_plan(item)
    context = item.get("marketContext") or {}
    strategy = str(plan.get("strategy") or "")
    trend = str((context.get("trend") or {}).get("label") or item.get("marketContextSummary", {}).get("trend") or "Neutral")
    rvol = number(context.get("rvol"), 1.0)
    atr_expansion = number(context.get("atrExpansion"), 0.0)
    distance_to_resistance = number(context.get("distanceToResistancePct"), 999.0)
    distance_to_support = number(context.get("distanceToSupportPct"), 999.0)

    blocks: list[str] = []
    warnings: list[str] = []

    if strategy == "CALL_DEBIT_SPREAD":
        if trend in {"Bearish", "Downtrend"}:
            blocks.append("bullish call spread conflicts with bearish trend")
        if distance_to_resistance <= 1.5:
            blocks.append("bullish call spread is too close to resistance")
        elif distance_to_resistance <= 3.0:
            warnings.append("bullish call spread has limited room before resistance")
        if rvol < 0.9:
            warnings.append("bullish call spread lacks strong RVOL confirmation")
    elif strategy == "PUT_DEBIT_SPREAD":
        if trend in {"Bullish", "Uptrend"}:
            blocks.append("bearish put spread conflicts with bullish trend")
        if distance_to_support <= 1.5:
            blocks.append("bearish put spread is too close to support")
        elif distance_to_support <= 3.0:
            warnings.append("bearish put spread has limited room before support")
        if rvol < 0.9:
            warnings.append("bearish put spread lacks strong RVOL confirmation")
    elif strategy == "PUT_CREDIT_SPREAD":
        if trend in {"Bearish", "Downtrend"}:
            blocks.append("bullish put credit spread conflicts with bearish trend")
        if distance_to_support <= 3.0:
            blocks.append("put credit spread is too close to support")
        elif distance_to_support <= 6.0:
            warnings.append("put credit spread has modest support cushion")
        if rvol >= 2.25 or atr_expansion >= 2.0:
            blocks.append("put credit spread is fighting extreme expansion risk")
        elif rvol >= 1.5 or atr_expansion >= 1.2:
            warnings.append("put credit spread is selling premium into elevated movement risk")
    elif strategy == "IRON_CONDOR":
        if rvol >= 1.35 or atr_expansion >= 1.0:
            blocks.append("iron condor is fighting expansion and elevated RVOL")
        elif rvol >= 1.15 or atr_expansion >= 0.6:
            warnings.append("iron condor is warming up; premium capture may be less forgiving")
        if min(distance_to_support, distance_to_resistance) <= 2.0:
            warnings.append("iron condor sits close to one edge of the structure range")
    elif strategy in {"LONG_STRADDLE", "LONG_STRANGLE"}:
        if rvol < 0.85 and atr_expansion <= 0:
            warnings.append("long-volatility structure lacks strong expansion confirmation")
        if trend in {"Bearish", "Downtrend"} and distance_to_support <= 1.5:
            warnings.append("long-volatility structure is leaning into support; breakout proof matters")

    return blocks, warnings, {
        "trend": trend,
        "rvol": rvol,
        "atrExpansion": atr_expansion,
        "distanceToSupportPct": distance_to_support,
        "distanceToResistancePct": distance_to_resistance,
    }


def schwab_option_quality_guards(item: dict[str, Any]) -> tuple[list[str], list[str], dict[str, Any]]:
    """Apply read-only Schwab option-chain quality gates when available.

    Missing Schwab data is not a blocker because OAuth may not be configured yet.
    Attached Schwab data, however, is treated as higher-confidence quote
    evidence than generic vendor chains, so ugly quote-quality flags can block a
    paper ticket before it pollutes the evidence loop.
    """
    schwab_options = item.get("schwabOptions")
    if not isinstance(schwab_options, dict) or not schwab_options:
        return [], [], {"attached": False}

    score = number(schwab_options.get("quoteQualityScore"), 0)
    label = str(schwab_options.get("quoteQualityLabel") or "unknown")
    flags = [str(flag) for flag in (schwab_options.get("qualityFlags") or [])]
    atm_spread_quality = str(schwab_options.get("atmSpreadQuality") or "unknown")
    atm_bucket = str(schwab_options.get("atmExpectedMoveBucket") or "unknown")
    atm_liquidity = number(schwab_options.get("atmLiquidityScore"), 0)
    spread_pct = number(schwab_options.get("atmSpreadPct"), 0)
    source_status = str(schwab_options.get("sourceStatus") or "").strip().lower()
    source_generated_at = schwab_options.get("sourceGeneratedAt")
    source_age_minutes = (
        strike_plan_age_minutes(str(source_generated_at))
        if source_generated_at
        else None
    )
    source_age_hours = (
        round(source_age_minutes / 60.0, 2)
        if source_age_minutes is not None
        else None
    )

    blocks: list[str] = []
    warnings: list[str] = []

    if source_status and source_status not in {"ok", "fixture"}:
        blocks.append(f"Schwab option source status is {source_status}")
    if source_age_hours is None:
        warnings.append("Schwab option source timestamp is missing")
    elif source_age_hours > SCHWAB_OPTIONS_MAX_AGE_HOURS:
        blocks.append(f"Schwab option chain is stale at {source_age_hours:.1f} hours")

    hard_flags = {
        "empty-chain",
        "missing-underlying-price",
        "missing-atm-pair",
        "no-liquid-contracts",
        "wide-atm-spread",
    }
    for flag in flags:
        if flag in hard_flags:
            blocks.append(f"Schwab option chain quality block: {flag}")
        elif flag == "incomplete-greeks":
            warnings.append("Schwab option chain has incomplete Greeks")
        else:
            warnings.append(f"Schwab option chain warning: {flag}")

    if score and score < 50:
        blocks.append(f"Schwab quote quality {score:.0f}/{label} is below paper threshold")
    elif 50 <= score < 70:
        warnings.append(f"Schwab quote quality is fragile at {score:.0f}/{label}")
    if atm_spread_quality in {"wide", "untradeable"}:
        blocks.append(f"Schwab ATM spread is {atm_spread_quality}")
    if atm_liquidity and atm_liquidity < 50:
        blocks.append(f"Schwab ATM liquidity score {atm_liquidity:.0f} is too thin")
    elif 50 <= atm_liquidity < 70:
        warnings.append(f"Schwab ATM liquidity score {atm_liquidity:.0f} needs manual review")
    if atm_bucket == "inferno":
        warnings.append("Schwab ATM implied move is inferno-hot; size and exit discipline matter")

    return blocks, warnings, {
        "attached": True,
        "sourceGeneratedAt": source_generated_at,
        "sourceStatus": schwab_options.get("sourceStatus"),
        "sourceAgeHours": source_age_hours,
        "maxSourceAgeHours": SCHWAB_OPTIONS_MAX_AGE_HOURS,
        "quoteQualityScore": score,
        "quoteQualityLabel": label,
        "qualityFlags": flags,
        "atmSpreadPct": spread_pct,
        "atmSpreadQuality": atm_spread_quality,
        "atmLiquidityScore": atm_liquidity,
        "atmExpectedMoveBucket": atm_bucket,
        "atmImpliedMovePct": schwab_options.get("atmImpliedMovePct"),
    }


def evaluate_strike_item(
    item: dict[str, Any],
    *,
    strike_plan_generated_at: str | None = None,
    ledger_items: list[dict[str, Any]] | None = None,
) -> RiskVerdict:
    """Evaluate whether a strike ticket can be paper-staged.

    This is not a live-trading green light. A passing verdict means the ticket is
    clean enough to enter the paper evidence machine.
    """
    blocks: list[str] = []
    warnings: list[str] = []
    ticker = str(item.get("ticker", "")).upper()
    loss = max_loss_dollars(item)
    projected_loss = projected_daily_loss(item, ledger_items)
    age = strike_plan_age_minutes(strike_plan_generated_at)
    rr = debit_spread_reward_risk(item)
    credit_rr = credit_spread_credit_risk(item)
    underlying_drift = underlying_source_drift(item)
    open_items = open_paper_items(ledger_items)
    plan = strategy_plan(item)
    context_blocks, context_warnings, context_metrics = market_context_guards(item)
    schwab_blocks, schwab_warnings, schwab_metrics = schwab_option_quality_guards(item)

    if not item.get("ok"):
        blocks.append(str(item.get("reason") or "strike plan failed"))
    if age is None:
        warnings.append("strike plan timestamp is missing")
    elif age > MAX_STRIKE_PLAN_AGE_MINUTES:
        blocks.append(f"strike plan is stale at {age:.0f} minutes old")
    if same_ticker_open(ticker, ledger_items):
        blocks.append(f"{ticker} already has an open paper ticket")
    if len(open_items) >= MAX_OPEN_PAPER_TICKETS:
        blocks.append(f"open paper ticket cap reached ({MAX_OPEN_PAPER_TICKETS})")
    cap_info = current_single_ticket_cap()
    effective_cap = cap_info["effectiveCap"]
    if loss > effective_cap:
        cap_source = cap_info.get("source") or "config-default"
        blocks.append(
            f"max loss ${loss:.2f} exceeds single-ticket cap ${effective_cap:.2f} ({cap_source})"
        )
    if projected_loss > MAX_DAILY_TICKET_DOLLARS:
        blocks.append(f"projected daily max loss ${projected_loss:.2f} exceeds cap ${MAX_DAILY_TICKET_DOLLARS:.2f}")
    if rr is not None and rr < MIN_DEBIT_SPREAD_REWARD_RISK:
        blocks.append(f"reward/risk {rr:.2f} is below debit-spread floor {MIN_DEBIT_SPREAD_REWARD_RISK:.2f}")
    if credit_rr is not None and credit_rr < MIN_CREDIT_SPREAD_CREDIT_RISK:
        blocks.append(
            f"credit/risk {credit_rr:.2f} is below credit-spread floor {MIN_CREDIT_SPREAD_CREDIT_RISK:.2f}"
        )
    drift_pct = underlying_drift.get("underlyingSourceDriftPct")
    if drift_pct is not None and abs(drift_pct) > MAX_UNDERLYING_SOURCE_DIVERGENCE_PCT:
        blocks.append(
            f"source price ${underlying_drift.get('sourcePrice'):.2f} diverges from Schwab underlying "
            f"${underlying_drift.get('schwabUnderlyingPrice'):.2f} by {abs(drift_pct):.2f}%; "
            "refresh tracker/execution queue before staging"
        )
    elif drift_pct is not None and abs(drift_pct) > 2.0:
        warnings.append(
            f"source price differs from Schwab underlying by {abs(drift_pct):.2f}%; "
            "prefer refreshed tracker context before sizing"
        )
    blocks.extend(visible_quote_blocks(item))
    blocks.extend(plan.get("liquidityNotes") or [])
    blocks.extend(schwab_blocks)

    if item.get("liveTradingAllowed"):
        blocks.append("unexpected liveTradingAllowed flag detected")
    if not plan.get("legs") and item.get("ok"):
        blocks.append("strike plan has no option legs")

    blocks.extend(context_blocks)
    warnings.extend(context_warnings)
    warnings.extend(schwab_warnings)

    metrics = {
        "ticker": ticker,
        "maxLossDollars": loss,
        "maxSingleTicketDollars": MAX_SINGLE_TICKET_DOLLARS,
        "effectiveSingleTicketCap": effective_cap,
        "effectiveSingleTicketCapSource": cap_info.get("source"),
        "scalingRecommendation": cap_info.get("recommendedCap"),
        "scalingVerdict": cap_info.get("verdict"),
        "projectedDailyLossDollars": projected_loss,
        "maxDailyTicketDollars": MAX_DAILY_TICKET_DOLLARS,
        "openPaperTickets": len(open_items),
        "maxOpenPaperTickets": MAX_OPEN_PAPER_TICKETS,
        "strikePlanAgeMinutes": age,
        "maxStrikePlanAgeMinutes": MAX_STRIKE_PLAN_AGE_MINUTES,
        "debitSpreadRewardRisk": rr,
        "minDebitSpreadRewardRisk": MIN_DEBIT_SPREAD_REWARD_RISK,
        "creditSpreadCreditRisk": credit_rr,
        "minCreditSpreadCreditRisk": MIN_CREDIT_SPREAD_CREDIT_RISK,
        **underlying_drift,
        "marketContext": context_metrics,
        "schwabOptions": schwab_metrics,
    }
    return RiskVerdict(passed=not blocks, blocks=blocks, warnings=warnings, metrics=metrics)
