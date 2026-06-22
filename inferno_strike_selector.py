from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

from inferno_config import EXECUTION_QUEUE_LIMIT, MAX_SINGLE_TICKET_DOLLARS, ROOT, local_now
from inferno_doctor import in_current_service_cycle
from inferno_options_math import (
    approximate_call_delta,
    approximate_gamma,
    approximate_put_delta,
    approximate_theta,
    approximate_vega,
)
from inferno_schwab_options import SCHWAB_OPTIONS_FILE
from inferno_risk_policy import evaluate_strike_item
from server import (
    APPROVAL_QUEUE_FILE,
    DATA_DIR,
    REPORTS_DIR,
    SNAPSHOT_FILE,
    ensure_dirs,
    load_json_file,
    send_email,
    smtp_configured,
)


EXECUTION_QUEUE_FILE = DATA_DIR / "inferno_execution_queue.json"
STRIKE_PLAN_FILE = DATA_DIR / "inferno_strike_plan.json"
STRIKE_PLAN_TEXT_FILE = REPORTS_DIR / "strike_plan_latest.txt"

AUTOMATION_STAGE = "paper-strike-selection-only"
MAX_DEFAULT_INTENTS = 5
MAX_ACCEPTABLE_SPREAD_PCT = 0.35
# Cap any single setup from dominating the strike slate. When a setup exceeds
# this share of OK plans, the lowest-priority excess plans are flagged for
# shadow-only follow-up via ``concentrationDemoted``. This governor never
# promotes anything; it only demotes, so it cannot bypass authority gates.
SETUP_CONCENTRATION_LIMIT = 0.60
SETUP_CONCENTRATION_DEMOTION_REASON = "setup-concentration-cap"
PAPER_REHEARSAL_VARIANT_FAMILY = "cap-aware-long-strangle"


@dataclass(frozen=True)
class OptionLeg:
    instruction: str
    put_call: str
    symbol: str
    expiration: str
    strike: float
    bid: float
    ask: float
    mid: float
    volume: int
    open_interest: int
    implied_volatility: float
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "instruction": self.instruction,
            "putCall": self.put_call,
            "symbol": self.symbol,
            "expiration": self.expiration,
            "strike": self.strike,
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid,
            "volume": self.volume,
            "openInterest": self.open_interest,
            "impliedVolatility": self.implied_volatility,
            "delta": self.delta,
            "gamma": self.gamma,
            "theta": self.theta,
            "vega": self.vega,
        }


def number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if pd.notna(parsed) else default


def integer(value: Any, default: int = 0) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return default
    return parsed


def load_schwab_options_index() -> dict[str, dict[str, Any]]:
    """Load the latest read-only Schwab option summary keyed by ticker.

    The strike selector must remain useful before OAuth is configured, so this
    helper treats missing/disabled Schwab artifacts as an empty enrichment layer
    instead of an error. When present, the risk policy can use it to block ugly
    chains or warn on fragile ones.
    """
    if not SCHWAB_OPTIONS_FILE.exists():
        return {}
    try:
        report = json.loads(SCHWAB_OPTIONS_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    rows = report.get("rows") if isinstance(report, dict) else []
    if not isinstance(rows, list):
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        indexed[symbol] = {
            **row,
            "sourceGeneratedAt": report.get("generatedAt"),
            "sourceStatus": report.get("status"),
            "researchOnly": report.get("researchOnly", True),
        }
    return indexed


def schwab_options_for_intent(intent: dict[str, Any], index: dict[str, dict[str, Any]] | None) -> dict[str, Any] | None:
    """Return Schwab option-chain enrichment for one execution intent."""
    if not index:
        return None
    ticker = str(intent.get("ticker") or "").upper().strip()
    return index.get(ticker)


def effective_intent_for_pricing(intent: dict[str, Any], schwab_options: dict[str, Any] | None) -> dict[str, Any]:
    """Prefer Schwab chain underlyings for strike math while preserving source price."""
    source_price = number(intent.get("price"))
    schwab_price = number((schwab_options or {}).get("underlyingPrice"))
    effective_price = schwab_price if schwab_price > 0 else source_price
    adjusted = {
        **intent,
        "sourcePrice": source_price,
        "price": effective_price,
        "underlyingPriceSource": "schwab-options-underlying" if schwab_price > 0 else "execution-intent",
    }
    market_context = dict(intent.get("marketContext") or {})
    if effective_price > 0:
        support = number(market_context.get("support"))
        resistance = number(market_context.get("resistance"))
        if support > 0:
            market_context["distanceToSupportPct"] = round((effective_price - support) / effective_price * 100.0, 4)
        if resistance > 0:
            market_context["distanceToResistancePct"] = round((resistance - effective_price) / effective_price * 100.0, 4)
    adjusted["marketContext"] = market_context
    return adjusted


def load_execution_queue() -> dict[str, Any]:
    """Load the execution queue, rebuilding it when the saved desk drifted stale.

    The strike selector is only useful when it prices the same names the
    execution desk is currently staging. If the cached queue is empty or from an
    older service cycle while the snapshot still has a review queue, we rebuild
    the queue first instead of silently pricing nothing.
    """
    queue = load_json_file(EXECUTION_QUEUE_FILE) or {}
    snapshot = load_json_file(SNAPSHOT_FILE) or {}
    desired = [
        str(ticker).upper()
        for ticker in (snapshot.get("reviewQueueTickers") or [])[:EXECUTION_QUEUE_LIMIT]
        if str(ticker).strip()
    ]
    actual = [
        str(item.get("ticker", "")).upper()
        for item in (queue.get("items") or [])
        if str(item.get("ticker", "")).strip()
    ]
    updated_at = str(queue.get("updatedAt") or queue.get("generatedAt") or "")
    queue_current = bool(updated_at) and in_current_service_cycle(updated_at, now=local_now())
    if queue_current and ((not desired and not actual) or actual == desired):
        return queue

    from inferno_execution_clerk import build_execution_queue, save_execution_queue

    approval_queue = load_json_file(APPROVAL_QUEUE_FILE) or {"items": []}
    refreshed = build_execution_queue(snapshot, approval_queue)
    save_execution_queue(refreshed)
    return refreshed


def option_mid(row: pd.Series) -> float:
    bid = number(row.get("bid"))
    ask = number(row.get("ask"))
    last = number(row.get("lastPrice"))
    if bid > 0 and ask > 0:
        return round((bid + ask) / 2, 4)
    return round(last, 4)


def option_spread_pct(row: pd.Series) -> float:
    bid = number(row.get("bid"))
    ask = number(row.get("ask"))
    mid = option_mid(row)
    if mid <= 0 or ask <= 0:
        return 1.0
    return round(max(0.0, (ask - bid) / mid), 4)


def days_to_expiration(expiration: str) -> int:
    """Return calendar days from the local service date to expiration."""
    parsed = parse_date(expiration)
    if not parsed:
        return 1
    return max(1, (parsed.date() - local_now().date()).days)


def normalized_iv_for_math(value: Any) -> float | None:
    """Normalize vendor IV values into annualized decimal form for Greeks."""
    sigma = number(value)
    if sigma <= 0:
        return None
    return round(sigma / 100.0, 6) if sigma > 3 else round(sigma, 6)


def approximate_leg_greeks(row: pd.Series, put_call: str, expiration: str, spot: float) -> dict[str, float | None]:
    """Approximate Greeks for a candidate leg from vendor IV.

    yfinance chains do not carry Greeks. This keeps strategy selection honest by
    using the same audited Black-Scholes primitives as the rest of the desk.
    """
    sigma = normalized_iv_for_math(row.get("impliedVolatility"))
    strike = number(row.get("strike"))
    if not sigma or spot <= 0 or strike <= 0:
        return {"delta": None, "gamma": None, "theta": None, "vega": None}
    dte = days_to_expiration(expiration)
    side = str(put_call).upper()
    delta = approximate_call_delta(spot, strike, sigma, dte) if side == "CALL" else approximate_put_delta(spot, strike, sigma, dte)
    return {
        "delta": round(delta, 4),
        "gamma": round(approximate_gamma(spot, strike, sigma, dte), 6),
        "theta": round(approximate_theta(spot, strike, sigma, dte, put_call=side), 6),
        "vega": round(approximate_vega(spot, strike, sigma, dte), 6),
    }


def to_leg(row: pd.Series, instruction: str, put_call: str, expiration: str, spot: float | None = None) -> OptionLeg:
    greeks = approximate_leg_greeks(row, put_call, expiration, number(spot)) if spot else {}
    return OptionLeg(
        instruction=instruction,
        put_call=put_call,
        symbol=str(row.get("contractSymbol", "")),
        expiration=expiration,
        strike=round(number(row.get("strike")), 4),
        bid=round(number(row.get("bid")), 4),
        ask=round(number(row.get("ask")), 4),
        mid=option_mid(row),
        volume=integer(row.get("volume")),
        open_interest=integer(row.get("openInterest")),
        implied_volatility=round(number(row.get("impliedVolatility")), 6),
        delta=greeks.get("delta"),
        gamma=greeks.get("gamma"),
        theta=greeks.get("theta"),
        vega=greeks.get("vega"),
    )


def parse_date(value: Any) -> datetime | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def choose_expiration(expirations: tuple[str, ...], days_until_earnings: int) -> str | None:
    if not expirations:
        return None

    today = local_now().date()
    target_date = today + pd.Timedelta(days=max(0, days_until_earnings)).to_pytimedelta()
    parsed_expirations: list[tuple[str, datetime]] = []
    for expiration in expirations:
        parsed = parse_date(expiration)
        if parsed:
            parsed_expirations.append((expiration, parsed))

    if not parsed_expirations:
        return expirations[0]

    future = [(raw, parsed) for raw, parsed in parsed_expirations if parsed.date() >= target_date]
    if future:
        return min(future, key=lambda item: item[1])[0]
    return max(parsed_expirations, key=lambda item: item[1])[0]


def ranked_expiration_candidates(expirations: tuple[str, ...], days_until_earnings: int, limit: int = 4) -> list[str]:
    """Return a short ranked list of expirations to try for strike construction.

    Some chains come back sparse or malformed for one date even when nearby
    expirations are usable. We try the target date first, then the closest
    alternates, instead of throwing the whole setup away immediately.
    """
    primary = choose_expiration(expirations, days_until_earnings)
    if not primary:
        return []
    today = local_now().date()
    target_date = today + pd.Timedelta(days=max(0, days_until_earnings)).to_pytimedelta()
    ranked: list[tuple[str, int]] = []
    for expiration in expirations:
        parsed = parse_date(expiration)
        if not parsed:
            continue
        distance = abs((parsed.date() - target_date).days)
        if expiration == primary:
            distance = -1
        ranked.append((expiration, distance))
    ordered: list[str] = []
    for expiration, _ in sorted(ranked, key=lambda item: item[1]):
        if expiration not in ordered:
            ordered.append(expiration)
    return ordered[:limit]


def clean_chain(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()

    cleaned = frame.copy()
    zeros = pd.Series(0, index=cleaned.index, dtype=float)
    cleaned["strike"] = pd.to_numeric(cleaned["strike"], errors="coerce")
    cleaned["bid"] = pd.to_numeric(cleaned.get("bid", zeros), errors="coerce").fillna(0)
    cleaned["ask"] = pd.to_numeric(cleaned.get("ask", zeros), errors="coerce").fillna(0)
    cleaned["lastPrice"] = pd.to_numeric(cleaned.get("lastPrice", zeros), errors="coerce").fillna(0)
    cleaned["volume"] = pd.to_numeric(cleaned.get("volume", zeros), errors="coerce").fillna(0)
    cleaned["openInterest"] = pd.to_numeric(cleaned.get("openInterest", zeros), errors="coerce").fillna(0)
    cleaned = cleaned.dropna(subset=["strike"])
    # Avoid contracts with no visible price. Those are ghosts, not tickets.
    return cleaned[(cleaned["ask"] > 0) | (cleaned["bid"] > 0) | (cleaned["lastPrice"] > 0)]


def nearest_row(frame: pd.DataFrame, target: float) -> pd.Series | None:
    if frame.empty:
        return None
    ranked = frame.assign(_distance=(frame["strike"] - target).abs()).sort_values(
        by=["_distance", "openInterest", "volume"],
        ascending=[True, False, False],
    )
    return ranked.iloc[0]


def next_higher_row(frame: pd.DataFrame, strike: float) -> pd.Series | None:
    candidates = frame[frame["strike"] > strike].sort_values("strike")
    return candidates.iloc[0] if not candidates.empty else None


def next_lower_row(frame: pd.DataFrame, strike: float) -> pd.Series | None:
    candidates = frame[frame["strike"] < strike].sort_values("strike", ascending=False)
    return candidates.iloc[0] if not candidates.empty else None


def buyable(frame: pd.DataFrame) -> pd.DataFrame:
    """Contracts we can realistically buy require a visible ask."""
    if frame.empty or "ask" not in frame.columns:
        return pd.DataFrame(columns=frame.columns)
    return frame[frame["ask"] > 0]


def sellable(frame: pd.DataFrame) -> pd.DataFrame:
    """Contracts we can realistically sell require a visible bid."""
    if frame.empty or "bid" not in frame.columns:
        return pd.DataFrame(columns=frame.columns)
    return frame[frame["bid"] > 0]


def build_liquidity_notes(legs: list[OptionLeg]) -> list[str]:
    notes: list[str] = []
    for leg in legs:
        spread_pct = ((leg.ask - leg.bid) / leg.mid) if leg.mid > 0 else 1.0
        if spread_pct > MAX_ACCEPTABLE_SPREAD_PCT:
            notes.append(f"{leg.symbol} spread is wide at {spread_pct:.0%}")
        if leg.open_interest <= 0 and leg.volume <= 0:
            notes.append(f"{leg.symbol} has no visible volume/open interest")
    return notes


def net_greek_summary(legs: list[OptionLeg]) -> dict[str, Any]:
    """Aggregate signed Greeks for a multi-leg plan."""
    totals = {"netDelta": 0.0, "netGamma": 0.0, "netTheta": 0.0, "netVega": 0.0}
    completeness = {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}
    for leg in legs:
        sign = -1.0 if leg.instruction.upper().startswith("SELL") else 1.0
        for key, attr in (
            ("netDelta", "delta"),
            ("netGamma", "gamma"),
            ("netTheta", "theta"),
            ("netVega", "vega"),
        ):
            value = getattr(leg, attr)
            if value is None:
                continue
            totals[key] += sign * float(value)
            completeness[attr] += 1
    complete_count = min(completeness.values()) if completeness else 0
    leg_count = len(legs) or 1
    summary = {key: round(value, 6) for key, value in totals.items()}
    summary["greeksComplete"] = complete_count == len(legs)
    summary["greeksCompletenessPct"] = round(complete_count / leg_count, 4)
    if summary["netTheta"] > 0 and summary["netVega"] < 0:
        summary["volPosture"] = "short-vol-theta-positive"
    elif summary["netTheta"] < 0 and summary["netVega"] > 0:
        summary["volPosture"] = "long-vol-theta-negative"
    else:
        summary["volPosture"] = "mixed"
    return summary


VERTICAL_DEBIT_MAX_WIDTH_RATIO = 0.95  # debit > 0.95 × width = guaranteed loss on fill


def vertical_call_plan(intent: dict[str, Any], expiration: str, calls: pd.DataFrame) -> dict[str, Any] | None:
    price = number(intent.get("price"))
    long_call_row = nearest_row(buyable(calls), price)
    if long_call_row is None:
        return None
    short_call_row = next_higher_row(sellable(calls), number(long_call_row.get("strike")))
    if short_call_row is None:
        return None

    long_leg = to_leg(long_call_row, "BUY_TO_OPEN", "CALL", expiration, price)
    short_leg = to_leg(short_call_row, "SELL_TO_OPEN", "CALL", expiration, price)
    debit = max(0.0, long_leg.ask - short_leg.bid)
    width = max(0.0, short_leg.strike - long_leg.strike)
    # Refuse plans where the worst-case fill (ask of long − bid of short)
    # exceeds 95% of the strike width. At debit > width the spread guarantees
    # a loss even on a perfect win; at debit > 0.95×width R:R is < 0.05 and
    # the trade is dominated by slippage. This catches the FTNT/ACMR-style
    # case where illiquid leg spreads stack into a guaranteed-loss plan.
    if width > 0 and debit > width * VERTICAL_DEBIT_MAX_WIDTH_RATIO:
        return None
    max_profit = max(0.0, width - debit)
    legs = [long_leg, short_leg]

    return {
        "strategy": "CALL_DEBIT_SPREAD",
        "direction": "bullish-defined-risk",
        "expiration": expiration,
        "legs": [leg.as_dict() for leg in legs],
        "estimatedDebit": round(debit, 4),
        "estimatedMaxLoss": round(debit * 100, 2),
        "estimatedMaxProfit": round(max_profit * 100, 2),
        "breakEven": round(long_leg.strike + debit, 4),
        "width": round(width, 4),
        "greekSummary": net_greek_summary(legs),
        "liquidityNotes": build_liquidity_notes(legs),
    }


def straddle_plan(intent: dict[str, Any], expiration: str, calls: pd.DataFrame, puts: pd.DataFrame) -> dict[str, Any] | None:
    price = number(intent.get("price"))
    call_row = nearest_row(buyable(calls), price)
    put_row = nearest_row(buyable(puts), price)
    if call_row is None or put_row is None:
        return None

    call_leg = to_leg(call_row, "BUY_TO_OPEN", "CALL", expiration, price)
    put_leg = to_leg(put_row, "BUY_TO_OPEN", "PUT", expiration, price)
    debit = call_leg.ask + put_leg.ask
    center = round((call_leg.strike + put_leg.strike) / 2, 4)
    legs = [call_leg, put_leg]

    return {
        "strategy": "LONG_STRADDLE",
        "direction": "long-volatility",
        "expiration": expiration,
        "legs": [leg.as_dict() for leg in legs],
        "estimatedDebit": round(debit, 4),
        "estimatedMaxLoss": round(debit * 100, 2),
        "estimatedMaxProfit": "uncapped",
        "lowerBreakEven": round(center - debit, 4),
        "upperBreakEven": round(center + debit, 4),
        "greekSummary": net_greek_summary(legs),
        "liquidityNotes": build_liquidity_notes(legs),
    }


def cap_aware_long_strangle_plan(
    intent: dict[str, Any],
    expiration: str,
    calls: pd.DataFrame,
    puts: pd.DataFrame,
) -> dict[str, Any] | None:
    """Build a paper-only capped rehearsal variant for oversized straddles.

    The live thesis stays the same: long volatility around the event. The only
    thing we change is the practice weapon. When the at-the-money straddle is
    too expensive for the paper cap, we look for the closest out-of-the-money
    call/put pair that still expresses expansion and fits the rehearsal budget.
    """
    price = number(intent.get("price"))
    cap_debit = round(MAX_SINGLE_TICKET_DOLLARS / 100.0, 4)
    call_subset = buyable(calls[calls["strike"] >= price]).copy()
    put_subset = buyable(puts[puts["strike"] <= price]).copy()
    if call_subset.empty or put_subset.empty:
        return None
    call_candidates = call_subset.assign(
        _distance=(call_subset["strike"] - price).abs()
    ).sort_values(by=["_distance", "openInterest", "volume"], ascending=[True, False, False]).head(12)
    put_candidates = put_subset.assign(
        _distance=(price - put_subset["strike"]).abs()
    ).sort_values(by=["_distance", "openInterest", "volume"], ascending=[True, False, False]).head(12)

    best_pair: tuple[pd.Series, pd.Series, float, float] | None = None
    for _, call_row in call_candidates.iterrows():
        for _, put_row in put_candidates.iterrows():
            debit = round(number(call_row.get("ask")) + number(put_row.get("ask")), 4)
            if debit <= 0 or debit > cap_debit:
                continue
            distance = round(
                abs(number(call_row.get("strike")) - price) + abs(price - number(put_row.get("strike"))),
                4,
            )
            if best_pair is None or (distance, -debit) < (best_pair[3], -best_pair[2]):
                best_pair = (call_row, put_row, debit, distance)

    if best_pair is None:
        return None

    call_row, put_row, debit, _ = best_pair
    call_leg = to_leg(call_row, "BUY_TO_OPEN", "CALL", expiration, price)
    put_leg = to_leg(put_row, "BUY_TO_OPEN", "PUT", expiration, price)
    legs = [call_leg, put_leg]
    return {
        "strategy": "LONG_STRANGLE",
        "direction": "paper-long-volatility-rehearsal",
        "expiration": expiration,
        "legs": [leg.as_dict() for leg in legs],
        "estimatedDebit": round(debit, 4),
        "estimatedMaxLoss": round(debit * 100, 2),
        "estimatedMaxProfit": "uncapped",
        "lowerBreakEven": round(put_leg.strike - debit, 4),
        "upperBreakEven": round(call_leg.strike + debit, 4),
        "greekSummary": net_greek_summary(legs),
        "liquidityNotes": build_liquidity_notes(legs),
        "paperVariantOnly": True,
        "variantFamily": PAPER_REHEARSAL_VARIANT_FAMILY,
        "variantForStrategy": "LONG_STRADDLE",
        "variantReason": (
            f"ATM straddle exceeds the ${MAX_SINGLE_TICKET_DOLLARS:.0f} paper cap; "
            "use a capped long-strangle for rehearsal only."
        ),
    }


def is_size_cap_block(reason: Any) -> bool:
    """Return whether a block reason is purely about paper sizing limits."""
    text = str(reason or "").lower()
    return "exceeds single-ticket cap" in text or "projected daily max loss" in text


def effective_paper_rehearsal_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Return a paper-only synthetic item when a capped rehearsal variant is clean.

    We only swap to the variant when the primary structure is blocked *solely*
    because it is too expensive for the paper desk. Structural issues like wide
    spreads or bad reward/risk still fail closed.
    """
    variant = item.get("paperRehearsalVariant") or {}
    primary_blocks = list(((item.get("riskVerdict") or {}).get("blocks") or []))
    if not variant or not primary_blocks or not all(is_size_cap_block(reason) for reason in primary_blocks):
        return None
    variant_verdict = variant.get("riskVerdict") or {}
    if not variant_verdict.get("passed"):
        return None
    return {
        **item,
        "paperVariantOnly": True,
        "paperVariantFamily": variant.get("variantFamily"),
        "paperVariantOfStrategy": variant.get("variantForStrategy") or (item.get("strikePlan") or {}).get("strategy"),
        "strikePlan": variant,
        "riskVerdict": variant_verdict,
    }


def effective_strategy_alternative_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Return the best clean Greek-supported strategy alternative, if any."""
    alternatives = []
    for alternative in item.get("strategyAlternatives") or []:
        verdict = alternative.get("riskVerdict") or {}
        if verdict.get("passed"):
            alternatives.append(alternative)
    if not alternatives:
        return None
    alternatives.sort(
        key=lambda alt: (
            number(alt.get("estimatedMaxLoss"), 99999.0),
            -abs(number((alt.get("greekSummary") or {}).get("netTheta"))),
        )
    )
    alternative = alternatives[0]
    return {
        **item,
        "paperVariantOnly": True,
        "paperVariantFamily": alternative.get("variantFamily"),
        "paperVariantOfStrategy": alternative.get("variantForStrategy") or (item.get("strikePlan") or {}).get("strategy"),
        "strikePlan": alternative,
        "riskVerdict": alternative.get("riskVerdict") or {},
    }


def put_credit_spread_plan(intent: dict[str, Any], expiration: str, puts: pd.DataFrame) -> dict[str, Any] | None:
    """Build a bullish/neutral defined-risk put credit spread.

    This is the first non-call, non-straddle alternative the desk may consider:
    positive theta, negative vega, bounded max loss, and a short strike below
    the current price/support area. It remains paper-only until evidence earns
    more authority.
    """
    price = number(intent.get("price"))
    market_context = intent.get("marketContext") or {}
    support = number(market_context.get("support"))
    atr = max(number(intent.get("atr20Day")), price * max(number(intent.get("atrPercent")) / 100.0, 0.04))
    target = min(price - atr, support * 0.99 if support > 0 else price - atr)
    short_put_row = nearest_row(sellable(puts[puts["strike"] < price]), target)
    if short_put_row is None:
        return None
    long_put_row = next_lower_row(buyable(puts), number(short_put_row.get("strike")))
    if long_put_row is None:
        return None

    short_put = to_leg(short_put_row, "SELL_TO_OPEN", "PUT", expiration, price)
    long_put = to_leg(long_put_row, "BUY_TO_OPEN", "PUT", expiration, price)
    credit = round(short_put.bid - long_put.ask, 4)
    width = max(0.0, short_put.strike - long_put.strike)
    if credit <= 0 or width <= 0 or credit >= width:
        return None
    max_loss = max(0.0, width - credit)
    legs = [short_put, long_put]
    support_cushion = None
    if support > 0 and short_put.strike > 0:
        support_cushion = round((support - short_put.strike) / short_put.strike * 100.0, 4)

    return {
        "strategy": "PUT_CREDIT_SPREAD",
        "direction": "bullish-defined-risk-premium",
        "expiration": expiration,
        "legs": [leg.as_dict() for leg in legs],
        "estimatedCredit": round(credit, 4),
        "estimatedMaxLoss": round(max_loss * 100, 2),
        "estimatedMaxProfit": round(credit * 100, 2),
        "breakEven": round(short_put.strike - credit, 4),
        "width": round(width, 4),
        "shortPutStrike": short_put.strike,
        "longPutStrike": long_put.strike,
        "supportCushionToShortPct": support_cushion,
        "greekSummary": net_greek_summary(legs),
        "liquidityNotes": build_liquidity_notes(legs),
    }


def put_debit_spread_plan(intent: dict[str, Any], expiration: str, puts: pd.DataFrame) -> dict[str, Any] | None:
    """Build a bearish defined-risk put debit spread."""
    price = number(intent.get("price"))
    long_put_row = nearest_row(buyable(puts), price)
    if long_put_row is None:
        return None
    short_put_row = next_lower_row(sellable(puts), number(long_put_row.get("strike")))
    if short_put_row is None:
        return None

    long_put = to_leg(long_put_row, "BUY_TO_OPEN", "PUT", expiration, price)
    short_put = to_leg(short_put_row, "SELL_TO_OPEN", "PUT", expiration, price)
    debit = round(long_put.ask - short_put.bid, 4)
    width = max(0.0, long_put.strike - short_put.strike)
    if debit <= 0 or width <= 0 or debit > width * VERTICAL_DEBIT_MAX_WIDTH_RATIO:
        return None
    max_profit = max(0.0, width - debit)
    legs = [long_put, short_put]

    return {
        "strategy": "PUT_DEBIT_SPREAD",
        "direction": "bearish-defined-risk",
        "expiration": expiration,
        "legs": [leg.as_dict() for leg in legs],
        "estimatedDebit": round(debit, 4),
        "estimatedMaxLoss": round(debit * 100, 2),
        "estimatedMaxProfit": round(max_profit * 100, 2),
        "breakEven": round(long_put.strike - debit, 4),
        "width": round(width, 4),
        "greekSummary": net_greek_summary(legs),
        "liquidityNotes": build_liquidity_notes(legs),
    }


def iron_condor_plan(intent: dict[str, Any], expiration: str, calls: pd.DataFrame, puts: pd.DataFrame) -> dict[str, Any] | None:
    price = number(intent.get("price"))
    atr = max(number(intent.get("atr20Day")), price * 0.05)
    short_call_row = nearest_row(sellable(calls[calls["strike"] > price]), price + atr)
    short_put_row = nearest_row(sellable(puts[puts["strike"] < price]), price - atr)
    if short_call_row is None or short_put_row is None:
        return None

    long_call_row = next_higher_row(buyable(calls), number(short_call_row.get("strike")))
    long_put_row = next_lower_row(buyable(puts), number(short_put_row.get("strike")))
    if long_call_row is None or long_put_row is None:
        return None

    short_call = to_leg(short_call_row, "SELL_TO_OPEN", "CALL", expiration, price)
    long_call = to_leg(long_call_row, "BUY_TO_OPEN", "CALL", expiration, price)
    short_put = to_leg(short_put_row, "SELL_TO_OPEN", "PUT", expiration, price)
    long_put = to_leg(long_put_row, "BUY_TO_OPEN", "PUT", expiration, price)
    credit = (short_call.bid + short_put.bid) - (long_call.ask + long_put.ask)
    call_width = max(0.0, long_call.strike - short_call.strike)
    put_width = max(0.0, short_put.strike - long_put.strike)
    max_width = max(call_width, put_width)
    legs = [short_call, long_call, short_put, long_put]

    return {
        "strategy": "IRON_CONDOR",
        "direction": "defined-risk-premium",
        "expiration": expiration,
        "legs": [leg.as_dict() for leg in legs],
        "estimatedCredit": round(credit, 4),
        "estimatedMaxLoss": round(max(0.0, max_width - credit) * 100, 2),
        "estimatedMaxProfit": round(max(0.0, credit) * 100, 2),
        "shortCallStrike": short_call.strike,
        "shortPutStrike": short_put.strike,
        "greekSummary": net_greek_summary(legs),
        "liquidityNotes": build_liquidity_notes(legs),
    }


def greek_supports_short_premium(plan: dict[str, Any]) -> bool:
    """Return True when net Greeks match a short-premium thesis."""
    greeks = plan.get("greekSummary") or {}
    return bool(
        greeks.get("greeksComplete")
        and number(greeks.get("netTheta")) > 0
        and number(greeks.get("netVega")) < 0
    )


def greek_supports_directional_debit(plan: dict[str, Any], *, expected_delta_sign: int) -> bool:
    """Return True when net Greeks match a directional debit thesis."""
    greeks = plan.get("greekSummary") or {}
    delta = number(greeks.get("netDelta"))
    vega = number(greeks.get("netVega"))
    if not greeks.get("greeksComplete"):
        return False
    if expected_delta_sign > 0 and delta <= 0:
        return False
    if expected_delta_sign < 0 and delta >= 0:
        return False
    return vega >= 0


def strategy_alternative_gate(intent: dict[str, Any], strategy: str, plan: dict[str, Any]) -> tuple[bool, str]:
    """Decide whether an alternative deserves risk-policy evaluation."""
    context = intent.get("marketContext") or {}
    trend = str((context.get("trend") or {}).get("label") or "Neutral")
    rvol = number(context.get("rvol"), 1.0)
    atr_expansion = number(context.get("atrExpansion") or intent.get("atrZScore"), 0.0)
    distance_to_support = number(context.get("distanceToSupportPct"), 999.0)
    distance_to_resistance = number(context.get("distanceToResistancePct"), 999.0)
    iv_rank = number(intent.get("ivRank"), 50.0)

    if strategy == "PUT_CREDIT_SPREAD":
        if trend not in {"Bullish", "Uptrend", "Base"}:
            return False, f"trend {trend} does not support bullish put-credit alternative"
        if iv_rank < 45.0:
            return False, f"IV rank {iv_rank:.1f} is not rich enough to sell put-credit premium"
        if distance_to_support < 6.0:
            return False, "support cushion is too thin for a put-credit alternative"
        if rvol > 2.25 or atr_expansion > 2.0:
            return False, "movement risk is too hot for short put premium"
        if not greek_supports_short_premium(plan) or number((plan.get("greekSummary") or {}).get("netDelta")) <= 0:
            return False, "Greeks do not support bullish short-premium posture"
        return True, "bullish support cushion plus positive-theta/negative-vega put credit alternative"

    if strategy == "PUT_DEBIT_SPREAD":
        if trend not in {"Bearish", "Downtrend"}:
            return False, f"trend {trend} does not support bearish put-debit alternative"
        if distance_to_support < 3.0:
            return False, "support is too close for a bearish put-debit alternative"
        if not greek_supports_directional_debit(plan, expected_delta_sign=-1):
            return False, "Greeks do not support bearish debit posture"
        return True, "bearish trend plus negative-delta defined-risk put debit alternative"

    if strategy == "IRON_CONDOR":
        if trend not in {"Neutral", "Base"}:
            return False, f"trend {trend} is not calm enough for an iron-condor alternative"
        if iv_rank < 50.0:
            return False, f"IV rank {iv_rank:.1f} is not rich enough for condor premium"
        if rvol > 1.15 or atr_expansion > 0.6:
            return False, "expansion risk is too high for an iron-condor alternative"
        if min(distance_to_support, distance_to_resistance) < 4.0:
            return False, "range edge is too close for an iron-condor alternative"
        if not greek_supports_short_premium(plan):
            return False, "Greeks do not support short-premium condor posture"
        return True, "calm range plus positive-theta/negative-vega condor alternative"

    return False, "unsupported alternative"


def mark_strategy_alternative(plan: dict[str, Any], *, variant_for: str, reason: str) -> dict[str, Any]:
    """Annotate an alternative plan as paper-only and auditable."""
    return {
        **plan,
        "paperVariantOnly": True,
        "variantFamily": f"greek-supported-{str(plan.get('strategy') or '').lower().replace('_', '-')}",
        "variantForStrategy": variant_for,
        "variantReason": reason,
    }


def build_strategy_alternatives(
    intent: dict[str, Any],
    expiration: str,
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    *,
    primary_strategy: str | None,
) -> list[dict[str, Any]]:
    """Build Greek-gated alternatives to the tracker's first-choice setup."""
    alternatives: list[dict[str, Any]] = []
    variant_for = primary_strategy or str(intent.get("setupRec") or "UNKNOWN")
    candidates = [
        put_credit_spread_plan(intent, expiration, puts),
        put_debit_spread_plan(intent, expiration, puts),
        iron_condor_plan(intent, expiration, calls, puts),
    ]
    for plan in candidates:
        if not plan:
            continue
        ok, reason = strategy_alternative_gate(intent, str(plan.get("strategy") or ""), plan)
        if not ok:
            continue
        alternatives.append(mark_strategy_alternative(plan, variant_for=variant_for, reason=reason))
    return alternatives


def build_strike_plan_for_intent(
    intent: dict[str, Any],
    schwab_options_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ticker = str(intent.get("ticker", "")).upper()
    setup = str(intent.get("setupRec", ""))
    schwab_options = schwab_options_for_intent(intent, schwab_options_index)
    pricing_intent = effective_intent_for_pricing(intent, schwab_options)
    market_context = pricing_intent.get("marketContext") or {}
    trend = (market_context.get("trend") or {}).get("label") or "Neutral"
    base = {
        "ticker": ticker,
        "generatedAt": local_now().isoformat(),
        "automationStage": AUTOMATION_STAGE,
        "intentStatus": intent.get("intentStatus"),
        "intentBlocks": intent.get("intentBlocks") or [],
        "approvalStatus": intent.get("approvalStatus"),
        "setupRec": setup,
        "price": pricing_intent.get("price"),
        "sourcePrice": pricing_intent.get("sourcePrice"),
        "underlyingPriceSource": pricing_intent.get("underlyingPriceSource"),
        "daysUntilEarnings": intent.get("daysUntilEarnings"),
        "riskUnits": intent.get("riskUnits"),
        "ivRank": intent.get("ivRank"),
        "ivRankChange": intent.get("ivRankChange"),
        "atrPercent": intent.get("atrPercent"),
        "paperOnly": True,
        "liveTradingAllowed": False,
        "marketContext": market_context,
        "marketContextSummary": {
            "rvol": market_context.get("rvol"),
            "trend": trend,
            "support": market_context.get("support"),
            "resistance": market_context.get("resistance"),
            "distanceToSupportPct": market_context.get("distanceToSupportPct"),
            "distanceToResistancePct": market_context.get("distanceToResistancePct"),
            "atrPercent": intent.get("atrPercent") or market_context.get("atrPercent"),
            "ivRank": intent.get("ivRank") or market_context.get("ivRank"),
        },
        "schwabOptions": schwab_options,
    }

    try:
        if number(pricing_intent.get("price")) <= 0:
            return {**base, "ok": False, "reason": "missing usable underlying price"}
        stock = yf.Ticker(ticker)
        expirations = ranked_expiration_candidates(stock.options, integer(pricing_intent.get("daysUntilEarnings")))
        if not expirations:
            return {**base, "ok": False, "reason": "no option expirations found"}
        attempts: list[str] = []
        for expiration in expirations:
            chain = stock.option_chain(expiration)
            calls = clean_chain(chain.calls)
            puts = clean_chain(chain.puts)

            rehearsal_variant = None
            strategy_alternatives: list[dict[str, Any]] = []
            if setup == "Vertical Call":
                strategy = vertical_call_plan(pricing_intent, expiration, calls)
            elif setup == "Straddle":
                strategy = straddle_plan(pricing_intent, expiration, calls, puts)
                if strategy and number(strategy.get("estimatedMaxLoss")) > MAX_SINGLE_TICKET_DOLLARS:
                    rehearsal_variant = cap_aware_long_strangle_plan(pricing_intent, expiration, calls, puts)
            elif setup == "Iron Condor":
                strategy = iron_condor_plan(pricing_intent, expiration, calls, puts)
            else:
                strategy = None

            if strategy is None:
                attempts.append(expiration)
                continue
            strategy_alternatives = build_strategy_alternatives(
                pricing_intent,
                expiration,
                calls,
                puts,
                primary_strategy=strategy.get("strategy"),
            )

            return {
                **base,
                "ok": True,
                "expiration": expiration,
                "strikePlan": strategy,
                "paperRehearsalVariant": rehearsal_variant,
                "strategyAlternatives": strategy_alternatives,
                "orderPolicy": {
                    "entryOrderType": "LIMIT",
                    "timeInForce": "DAY",
                    "requiresHumanApproval": True,
                    "requiresBrokerPreview": True,
                    "killSwitches": [
                        "stale snapshot",
                        "daily risk budget exceeded",
                        "missing approval",
                        "wide spread",
                        "no quote",
                    ],
                },
            }

        tried = ", ".join(attempts) or "none"
        return {
            **base,
            "ok": False,
            "expirationCandidates": expirations,
            "reason": f"no supported strike plan for {setup} across expirations: {tried}",
        }
    except Exception as exc:  # noqa: BLE001
        return {**base, "ok": False, "reason": f"{type(exc).__name__}: {exc}"}


def annotate_strike_plans(plans: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    """Apply risk review and concentration control to raw strike-plan items."""
    annotated_plans: list[dict[str, Any]] = []
    for plan in plans:
        annotated = {
            **plan,
            "riskVerdict": evaluate_strike_item(plan, strike_plan_generated_at=generated_at).as_dict(),
        }
        variant = annotated.get("paperRehearsalVariant") or {}
        if variant:
            variant_item = {
                **annotated,
                "strikePlan": variant,
            }
            annotated["paperRehearsalVariant"] = {
                **variant,
                "riskVerdict": evaluate_strike_item(
                    variant_item,
                    strike_plan_generated_at=generated_at,
                ).as_dict(),
            }
        alternatives = []
        for alternative in annotated.get("strategyAlternatives") or []:
            alternative_item = {
                **annotated,
                "strikePlan": alternative,
            }
            alternatives.append(
                {
                    **alternative,
                    "riskVerdict": evaluate_strike_item(
                        alternative_item,
                        strike_plan_generated_at=generated_at,
                    ).as_dict(),
                }
            )
        if alternatives:
            annotated["strategyAlternatives"] = alternatives
        annotated_plans.append(annotated)
    annotated_plans, governor = apply_setup_concentration_governor(annotated_plans)
    return annotated_plans, governor


def setup_share_counts(plans: list[dict[str, Any]]) -> dict[str, float]:
    """Return setup-level share of OK plans for the concentration governor."""
    ok_plans = [plan for plan in plans if plan.get("ok") and not plan.get("concentrationDemoted")]
    total = len(ok_plans)
    if not total:
        return {}
    counts: dict[str, int] = {}
    for plan in ok_plans:
        setup = str(plan.get("setupRec") or "Unknown")
        counts[setup] = counts.get(setup, 0) + 1
    return {setup: round(count / total, 4) for setup, count in counts.items()}


def apply_setup_concentration_governor(
    plans: list[dict[str, Any]],
    *,
    limit: float = SETUP_CONCENTRATION_LIMIT,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Demote excess same-setup plans to shadow-only when concentration > limit.

    The governor only annotates: it sets ``concentrationDemoted=True`` and an
    accompanying reason on the lowest-priority excess plans. ``ok`` and other
    risk-gate fields are untouched, so this cannot promote anything past an
    authority check. The first plans in the input order keep primary status,
    and excess plans drop in stable reverse order from each over-limit setup.
    """
    if not plans or limit <= 0 or limit >= 1:
        return plans, {
            "limit": limit,
            "demoted": [],
            "preDemotionShares": setup_share_counts(plans),
            "postDemotionShares": setup_share_counts(plans),
        }

    pre_shares = setup_share_counts(plans)
    annotated = [dict(plan) for plan in plans]
    # Use the full ok-pool (including any already-demoted items) as the cap
    # denominator so the rule is stable across repeated invocations. Without
    # this, demoting once shrinks the pool and would re-trigger demotion on a
    # second pass — breaking idempotency.
    total_ok_full = sum(1 for plan in annotated if plan.get("ok"))
    ok_indexes_by_setup: dict[str, list[int]] = {}
    for index, plan in enumerate(annotated):
        if not plan.get("ok") or plan.get("concentrationDemoted"):
            continue
        setup = str(plan.get("setupRec") or "Unknown")
        ok_indexes_by_setup.setdefault(setup, []).append(index)

    demoted: list[dict[str, Any]] = []
    if total_ok_full == 0:
        return annotated, {
            "limit": limit,
            "demoted": demoted,
            "preDemotionShares": pre_shares,
            "postDemotionShares": pre_shares,
        }

    import math

    max_allowed_per_setup = max(1, math.floor(limit * total_ok_full))
    for setup, indexes in ok_indexes_by_setup.items():
        if len(indexes) <= max_allowed_per_setup:
            continue
        excess = len(indexes) - max_allowed_per_setup
        # Demote in stable reverse order so earlier-queued tickets keep primary.
        for index in indexes[-excess:]:
            plan = annotated[index]
            plan["concentrationDemoted"] = True
            plan["concentrationDemotionReason"] = SETUP_CONCENTRATION_DEMOTION_REASON
            demoted.append(
                {
                    "ticker": plan.get("ticker"),
                    "setupRec": setup,
                    "reason": SETUP_CONCENTRATION_DEMOTION_REASON,
                }
            )

    post_shares = setup_share_counts(annotated)
    return annotated, {
        "limit": limit,
        "demoted": demoted,
        "preDemotionShares": pre_shares,
        "postDemotionShares": post_shares,
    }


def build_strike_plan_from_queue(
    queue: dict[str, Any],
    limit: int | None = None,
    schwab_options_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a strike plan for an explicit queue without touching disk state."""
    items = queue.get("items", [])[: limit or MAX_DEFAULT_INTENTS]
    schwab_index = load_schwab_options_index() if schwab_options_index is None else schwab_options_index
    plans = [build_strike_plan_for_intent(item, schwab_index) for item in items]
    generated_at = local_now().isoformat()
    plans, governor = annotate_strike_plans(plans, generated_at)
    schwab_enriched_count = sum(1 for plan in plans if plan.get("schwabOptions"))
    return {
        "generatedAt": generated_at,
        "automationStage": AUTOMATION_STAGE,
        "brokerReady": False,
        "liveTradingAllowed": False,
        "schwabOptionsEnrichedCount": schwab_enriched_count,
        "schwabOptionsQualityLabels": {
            plan.get("ticker"): (plan.get("schwabOptions") or {}).get("quoteQualityLabel")
            for plan in plans
            if plan.get("schwabOptions")
        },
        "sourceExecutionQueueUpdatedAt": queue.get("updatedAt"),
        "count": len(plans),
        "okCount": sum(1 for plan in plans if plan.get("ok")),
        "failedCount": sum(1 for plan in plans if not plan.get("ok")),
        "primaryCount": sum(
            1 for plan in plans if plan.get("ok") and not plan.get("concentrationDemoted")
        ),
        "concentrationDemotedCount": sum(
            1 for plan in plans if plan.get("concentrationDemoted")
        ),
        "concentrationGovernor": governor,
        "items": plans,
    }


def build_strike_plan(limit: int = MAX_DEFAULT_INTENTS) -> dict[str, Any]:
    queue = load_execution_queue()
    return build_strike_plan_from_queue(queue, limit=limit)


def format_money(value: Any) -> str:
    if isinstance(value, str):
        return value
    return f"${number(value):.2f}"


def build_text_report(plan: dict[str, Any]) -> str:
    lines = [
        "Inferno Strike Plan",
        "",
        f"Generated: {plan.get('generatedAt')}",
        f"Stage: {plan.get('automationStage')}",
        f"Live trading allowed: {plan.get('liveTradingAllowed')}",
        f"Plans: {plan.get('okCount')} ok / {plan.get('failedCount')} failed",
        f"Schwab option chains attached: {plan.get('schwabOptionsEnrichedCount', 0)}",
        "",
    ]

    for item in plan.get("items", []):
        if not item.get("ok"):
            lines.extend(
                [
                    f"{item.get('ticker')} | {item.get('setupRec')} | FAILED",
                    f"  Reason: {item.get('reason')}",
                    "",
                ]
            )
            continue

        strike_plan = item.get("strikePlan", {})
        legs = strike_plan.get("legs", [])
        price_text = format_money(item.get("price"))
        source_price = number(item.get("sourcePrice"))
        source_detail = ""
        if source_price > 0 and abs(source_price - number(item.get("price"))) > 0.01:
            source_detail = f" ({item.get('underlyingPriceSource')}; source {format_money(source_price)})"
        cost = strike_plan.get("estimatedDebit", strike_plan.get("estimatedCredit", 0))
        cost_label = "Debit" if "estimatedDebit" in strike_plan else "Credit"
        lines.extend(
            [
                f"{item.get('ticker')} | {strike_plan.get('strategy')} | {item.get('intentStatus')} | {item.get('approvalStatus')}",
                f"  Underlying: {price_text}{source_detail} | Expiration: {strike_plan.get('expiration')} | {cost_label}: {format_money(cost)}",
                f"  Risk: {format_money(strike_plan.get('estimatedMaxLoss'))} max loss | Profit: {format_money(strike_plan.get('estimatedMaxProfit'))}",
            ]
        )
        context = item.get("marketContext") or {}
        trend = (context.get("trend") or {}).get("label") or item.get("marketContextSummary", {}).get("trend") or "Neutral"
        lines.append(
            f"  Confirmation: RVOL {context.get('rvol', 'N/A')}x | {trend} | "
            f"S {context.get('support', 'N/A')} / R {context.get('resistance', 'N/A')}"
        )
        schwab_options = item.get("schwabOptions") or {}
        if schwab_options:
            move = schwab_options.get("atmImpliedMovePct")
            move_text = f"{move * 100:.1f}%" if isinstance(move, (int, float)) else "N/A"
            lines.append(
                f"  Schwab chain: {schwab_options.get('quoteQualityScore')}/"
                f"{schwab_options.get('quoteQualityLabel')} | "
                f"move {move_text} ({schwab_options.get('atmExpectedMoveBucket')}) | "
                f"spread {schwab_options.get('atmSpreadQuality')} | "
                f"liq {schwab_options.get('atmLiquidityScore')}"
            )
        greeks = strike_plan.get("greekSummary") or {}
        if greeks:
            lines.append(
                f"  Greeks: delta {greeks.get('netDelta')} | gamma {greeks.get('netGamma')} | "
                f"theta {greeks.get('netTheta')} | vega {greeks.get('netVega')} | {greeks.get('volPosture')}"
            )
        for leg in legs:
            lines.append(
                f"  {leg.get('instruction')} {leg.get('putCall')} {leg.get('strike')} "
                f"{leg.get('symbol')} bid/ask {leg.get('bid')}/{leg.get('ask')}"
            )
        notes = strike_plan.get("liquidityNotes") or []
        if notes:
            lines.append(f"  Liquidity notes: {'; '.join(notes)}")
        risk_blocks = (item.get("riskVerdict") or {}).get("blocks") or []
        if risk_blocks:
            lines.append(f"  Risk blocks: {'; '.join(risk_blocks)}")
        variant = item.get("paperRehearsalVariant") or {}
        variant_verdict = variant.get("riskVerdict") or {}
        if variant and variant_verdict.get("passed"):
            lines.append(
                f"  Paper rehearsal: {variant.get('strategy')} | debit {format_money(variant.get('estimatedDebit'))} | "
                f"max loss {format_money(variant.get('estimatedMaxLoss'))}"
            )
            lines.append(f"  Rehearsal note: {variant.get('variantReason')}")
        alternatives = item.get("strategyAlternatives") or []
        for alternative in alternatives[:3]:
            alt_verdict = alternative.get("riskVerdict") or {}
            cost = alternative.get("estimatedDebit", alternative.get("estimatedCredit", 0))
            cost_label = "debit" if "estimatedDebit" in alternative else "credit"
            alt_greeks = alternative.get("greekSummary") or {}
            lines.append(
                f"  Alternative: {alternative.get('strategy')} | {cost_label} {format_money(cost)} | "
                f"max loss {format_money(alternative.get('estimatedMaxLoss'))} | "
                f"risk {'pass' if alt_verdict.get('passed') else 'block'}"
            )
            if alt_greeks:
                lines.append(
                    f"    Greeks: delta {alt_greeks.get('netDelta')} | theta {alt_greeks.get('netTheta')} | "
                    f"vega {alt_greeks.get('netVega')} | {alt_greeks.get('volPosture')}"
                )
            lines.append(f"    note: {alternative.get('variantReason')}")
            blocks = alt_verdict.get("blocks") or []
            if blocks:
                lines.append(f"    blocks: {'; '.join(blocks[:3])}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def save_strike_plan(plan: dict[str, Any]) -> dict[str, str]:
    ensure_dirs()
    STRIKE_PLAN_FILE.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    STRIKE_PLAN_TEXT_FILE.write_text(build_text_report(plan), encoding="utf-8")
    return {
        "json": str(STRIKE_PLAN_FILE),
        "text": str(STRIKE_PLAN_TEXT_FILE),
    }


def send_strike_plan_email(plan: dict[str, Any], ledger_text: str | None = None) -> bool:
    if not smtp_configured():
        return False
    brief = build_text_report(plan)
    if ledger_text:
        brief = f"{brief}\n\n{ledger_text}".rstrip() + "\n"
    payload = {
        "brief": brief,
        "sourceLabel": "Inferno Strike Plan",
        "rows": [],
        "longTermRows": [],
        "executionQueue": {},
    }
    subject = f"[DIABLO TRADING] Strike Plan - {local_now().strftime('%Y-%m-%d')}"
    return send_email(payload, subject=subject)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build paper-only option strike plans from the Inferno execution queue.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    parser.add_argument("--limit", type=int, default=MAX_DEFAULT_INTENTS, help="Maximum execution intents to price.")
    parser.add_argument("--email", action="store_true", help="Email the strike plan after building it.")
    parser.add_argument(
        "--record-ledger",
        action="store_true",
        help="Record generated tickets in the paper execution ledger before exiting.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and STRIKE_PLAN_TEXT_FILE.exists():
        print(STRIKE_PLAN_TEXT_FILE.read_text(encoding="utf-8"))
        return 0

    plan = build_strike_plan(limit=args.limit)
    save_strike_plan(plan)
    ledger_text = None
    if args.record_ledger:
        from inferno_paper_execution import ledger_summary, record_from_strike_plan

        ledger_result = record_from_strike_plan(plan)
        ledger_text = ledger_summary(ledger_result["ledger"])
    print(build_text_report(plan))
    if ledger_text:
        print(ledger_text)
    if args.email:
        sent = send_strike_plan_email(plan, ledger_text=ledger_text)
        print(f"Strike email sent: {'yes' if sent else 'no'}")
    return 0 if plan.get("okCount", 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
