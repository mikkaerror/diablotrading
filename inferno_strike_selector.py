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


def to_leg(row: pd.Series, instruction: str, put_call: str, expiration: str) -> OptionLeg:
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


def vertical_call_plan(intent: dict[str, Any], expiration: str, calls: pd.DataFrame) -> dict[str, Any] | None:
    price = number(intent.get("price"))
    long_call_row = nearest_row(buyable(calls), price)
    if long_call_row is None:
        return None
    short_call_row = next_higher_row(sellable(calls), number(long_call_row.get("strike")))
    if short_call_row is None:
        return None

    long_leg = to_leg(long_call_row, "BUY_TO_OPEN", "CALL", expiration)
    short_leg = to_leg(short_call_row, "SELL_TO_OPEN", "CALL", expiration)
    debit = max(0.0, long_leg.ask - short_leg.bid)
    width = max(0.0, short_leg.strike - long_leg.strike)
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
        "liquidityNotes": build_liquidity_notes(legs),
    }


def straddle_plan(intent: dict[str, Any], expiration: str, calls: pd.DataFrame, puts: pd.DataFrame) -> dict[str, Any] | None:
    price = number(intent.get("price"))
    call_row = nearest_row(buyable(calls), price)
    put_row = nearest_row(buyable(puts), price)
    if call_row is None or put_row is None:
        return None

    call_leg = to_leg(call_row, "BUY_TO_OPEN", "CALL", expiration)
    put_leg = to_leg(put_row, "BUY_TO_OPEN", "PUT", expiration)
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
    call_leg = to_leg(call_row, "BUY_TO_OPEN", "CALL", expiration)
    put_leg = to_leg(put_row, "BUY_TO_OPEN", "PUT", expiration)
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

    short_call = to_leg(short_call_row, "SELL_TO_OPEN", "CALL", expiration)
    long_call = to_leg(long_call_row, "BUY_TO_OPEN", "CALL", expiration)
    short_put = to_leg(short_put_row, "SELL_TO_OPEN", "PUT", expiration)
    long_put = to_leg(long_put_row, "BUY_TO_OPEN", "PUT", expiration)
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
        "liquidityNotes": build_liquidity_notes(legs),
    }


def build_strike_plan_for_intent(intent: dict[str, Any]) -> dict[str, Any]:
    ticker = str(intent.get("ticker", "")).upper()
    setup = str(intent.get("setupRec", ""))
    market_context = intent.get("marketContext") or {}
    trend = (market_context.get("trend") or {}).get("label") or "Neutral"
    base = {
        "ticker": ticker,
        "generatedAt": local_now().isoformat(),
        "automationStage": AUTOMATION_STAGE,
        "intentStatus": intent.get("intentStatus"),
        "approvalStatus": intent.get("approvalStatus"),
        "setupRec": setup,
        "price": intent.get("price"),
        "daysUntilEarnings": intent.get("daysUntilEarnings"),
        "riskUnits": intent.get("riskUnits"),
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
        },
    }

    try:
        stock = yf.Ticker(ticker)
        expirations = ranked_expiration_candidates(stock.options, integer(intent.get("daysUntilEarnings")))
        if not expirations:
            return {**base, "ok": False, "reason": "no option expirations found"}
        attempts: list[str] = []
        for expiration in expirations:
            chain = stock.option_chain(expiration)
            calls = clean_chain(chain.calls)
            puts = clean_chain(chain.puts)

            rehearsal_variant = None
            if setup == "Vertical Call":
                strategy = vertical_call_plan(intent, expiration, calls)
            elif setup == "Straddle":
                strategy = straddle_plan(intent, expiration, calls, puts)
                if strategy and number(strategy.get("estimatedMaxLoss")) > MAX_SINGLE_TICKET_DOLLARS:
                    rehearsal_variant = cap_aware_long_strangle_plan(intent, expiration, calls, puts)
            elif setup == "Iron Condor":
                strategy = iron_condor_plan(intent, expiration, calls, puts)
            else:
                strategy = None

            if strategy is None:
                attempts.append(expiration)
                continue

            return {
                **base,
                "ok": True,
                "expiration": expiration,
                "strikePlan": strategy,
                "paperRehearsalVariant": rehearsal_variant,
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


def build_strike_plan_from_queue(queue: dict[str, Any], limit: int | None = None) -> dict[str, Any]:
    """Build a strike plan for an explicit queue without touching disk state."""
    items = queue.get("items", [])[: limit or MAX_DEFAULT_INTENTS]
    plans = [build_strike_plan_for_intent(item) for item in items]
    generated_at = local_now().isoformat()
    plans, governor = annotate_strike_plans(plans, generated_at)
    return {
        "generatedAt": generated_at,
        "automationStage": AUTOMATION_STAGE,
        "brokerReady": False,
        "liveTradingAllowed": False,
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
        cost = strike_plan.get("estimatedDebit", strike_plan.get("estimatedCredit", 0))
        cost_label = "Debit" if "estimatedDebit" in strike_plan else "Credit"
        lines.extend(
            [
                f"{item.get('ticker')} | {strike_plan.get('strategy')} | {item.get('intentStatus')} | {item.get('approvalStatus')}",
                f"  Underlying: {price_text} | Expiration: {strike_plan.get('expiration')} | {cost_label}: {format_money(cost)}",
                f"  Risk: {format_money(strike_plan.get('estimatedMaxLoss'))} max loss | Profit: {format_money(strike_plan.get('estimatedMaxProfit'))}",
            ]
        )
        context = item.get("marketContext") or {}
        trend = (context.get("trend") or {}).get("label") or item.get("marketContextSummary", {}).get("trend") or "Neutral"
        lines.append(
            f"  Confirmation: RVOL {context.get('rvol', 'N/A')}x | {trend} | "
            f"S {context.get('support', 'N/A')} / R {context.get('resistance', 'N/A')}"
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
