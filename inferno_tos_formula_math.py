from __future__ import annotations

"""Pure TOS-style formula mirrors for market context math.

thinkorswim custom columns are useful visually, but they are not a durable
automation source. This module makes the desk's current TOS-style ideas
explicit and testable:

- RVOL: latest volume divided by prior average volume
- trend: price/SMA20/SMA50 posture plus SMA20 slope
- support/resistance: recent low/high range
- momentum: ATR-normalized multi-horizon return stack
- strength: momentum + relative strength + trend + participation

The formulas are intentionally deterministic and side-effect free. They accept
already-loaded OHLCV history and never call broker, sheet, or network APIs.
"""

from typing import Any

import numpy as np
import pandas as pd


FORMULA_VERSION = "tos-formula-mirror-v1"


def clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    """Clamp a numeric value into a bounded range."""
    return min(upper, max(lower, value))


def number(value: Any, default: float | None = None) -> float | None:
    """Coerce loose values into floats."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("$", "").replace(",", "").replace("%", "").strip()
    if not cleaned or cleaned.upper() in {"N/A", "#N/A", "NAN", "NONE"}:
        return default
    try:
        return float(cleaned)
    except ValueError:
        return default


def numeric_series(history: pd.DataFrame, column: str) -> pd.Series:
    """Return a cleaned numeric series from a history frame."""
    if column not in history:
        return pd.Series(dtype="float64")
    return pd.to_numeric(history[column], errors="coerce").dropna()


def true_range(history: pd.DataFrame) -> pd.Series:
    """Return classic true range from High/Low/Close data."""
    high = pd.to_numeric(history["High"], errors="coerce")
    low = pd.to_numeric(history["Low"], errors="coerce")
    close = pd.to_numeric(history["Close"], errors="coerce")
    previous_close = close.shift()
    return pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1).dropna()


def compute_true_range(history: pd.DataFrame) -> pd.Series:
    """Compatibility alias for callers that use the formula name literally."""
    return true_range(history)


def atr_percent(history: pd.DataFrame, *, atr_window: int = 14) -> float | None:
    """Return latest ATR percent of close."""
    close = numeric_series(history, "Close")
    tr = true_range(history)
    if close.empty or tr.empty:
        return None
    atr = tr.rolling(window=atr_window).mean().dropna()
    if atr.empty or close.iloc[-1] <= 0:
        return None
    return round(float(atr.iloc[-1] / close.iloc[-1] * 100.0), 4)


def pct_return(close: pd.Series, lookback: int) -> float | None:
    """Return percent price change over a lookback in bars."""
    if lookback <= 0 or len(close) <= lookback:
        return None
    base = float(close.iloc[-lookback - 1])
    latest = float(close.iloc[-1])
    if base <= 0:
        return None
    return round((latest / base - 1.0) * 100.0, 4)


def weighted_return_pct(history: pd.DataFrame) -> float | None:
    """Return weighted 5/20/60-day return percent with missing windows ignored."""
    close = numeric_series(history, "Close")
    windows = ((5, 0.25), (20, 0.45), (60, 0.30))
    weighted_sum = 0.0
    weight_sum = 0.0
    for lookback, weight in windows:
        value = pct_return(close, lookback)
        if value is None:
            continue
        weighted_sum += value * weight
        weight_sum += weight
    if weight_sum <= 0:
        return None
    return round(weighted_sum / weight_sum, 4)


def relative_volume_from_series(volume: pd.Series, *, lookback: int = 20) -> float | None:
    """Return latest volume divided by prior average volume.

    The latest bar is excluded from the baseline so an in-progress or unusually
    large session does not raise its own denominator.
    """
    volume = pd.to_numeric(volume, errors="coerce").dropna()
    if len(volume) < 6:
        return None
    trailing = volume.tail(lookback + 1)
    baseline = trailing.iloc[:-1]
    average_volume = float(baseline.mean()) if not baseline.empty else 0.0
    if average_volume <= 0:
        return None
    return round(float(trailing.iloc[-1]) / average_volume, 4)


def relative_volume_from_history(history: pd.DataFrame, *, lookback: int = 20) -> float | None:
    """Return latest volume divided by prior average volume from OHLCV history."""
    return relative_volume_from_series(numeric_series(history, "Volume"), lookback=lookback)


def tos_rvol_from_history(history: pd.DataFrame) -> float | None:
    """Mirror TOS RVOL: volume / Average(volume, 30)."""
    volume = numeric_series(history, "Volume")
    if len(volume) < 30:
        return None
    average_volume = float(volume.rolling(window=30).mean().dropna().iloc[-1])
    if average_volume <= 0:
        return None
    return round(float(volume.iloc[-1]) / average_volume, 2)


def tos_pv52h_from_history(history: pd.DataFrame) -> float | None:
    """Mirror TOS Pv52H: close / Highest(high, 252) * 100."""
    close = numeric_series(history, "Close")
    high = numeric_series(history, "High")
    if close.empty or high.empty:
        return None
    high52 = float(high.tail(252).max())
    if high52 <= 0:
        return None
    return round(float(close.iloc[-1]) / high52 * 100.0, 1)


def tos_momentum_from_history(history: pd.DataFrame) -> float | None:
    """Mirror TOS MOM: close - Average(close, 10)."""
    close = numeric_series(history, "Close")
    if len(close) < 10:
        return None
    ma10 = float(close.rolling(window=10).mean().dropna().iloc[-1])
    return round(float(close.iloc[-1]) - ma10, 2)


def tos_atr_percent_from_history(history: pd.DataFrame) -> float | None:
    """Mirror TOS ATR%: Average(TrueRange(high, close, low), 14) / close * 100."""
    close = numeric_series(history, "Close")
    tr = true_range(history)
    if close.empty or len(tr) < 14 or close.iloc[-1] <= 0:
        return None
    atr = float(tr.rolling(window=14).mean().dropna().iloc[-1])
    return round(atr / float(close.iloc[-1]) * 100.0, 1)


def tos_strength_from_history(history: pd.DataFrame) -> float | None:
    """Mirror TOS Strength: (close - low) / (high - low) * 100 for the latest bar."""
    close = numeric_series(history, "Close")
    high = numeric_series(history, "High")
    low = numeric_series(history, "Low")
    if close.empty or high.empty or low.empty:
        return None
    range_width = float(high.iloc[-1]) - float(low.iloc[-1])
    strength = ((float(close.iloc[-1]) - float(low.iloc[-1])) / range_width) if range_width != 0 else 0.0
    return round(strength * 100.0, 1)


def tos_support_resistance_from_history(history: pd.DataFrame) -> dict[str, Any]:
    """Mirror TOS SUP/RES using 10-bar high/low proximity."""
    close = numeric_series(history, "Close")
    high = numeric_series(history, "High")
    low = numeric_series(history, "Low")
    if close.empty or high.empty or low.empty:
        return {
            "label": None,
            "nearHigh": None,
            "nearLow": None,
            "high10": None,
            "low10": None,
            "color": None,
        }
    high10 = float(high.tail(10).max())
    low10 = float(low.tail(10).min())
    latest_close = float(close.iloc[-1])
    near_high = (high10 - latest_close) / high10 < 0.02 if high10 != 0 else False
    near_low = (latest_close - low10) / low10 < 0.02 if low10 != 0 else False
    label = "\u2197 Near High" if near_high else "\u2198 Near Low" if near_low else "Neutral"
    color = "GREEN" if near_high else "RED" if near_low else "LIGHT_GRAY"
    return {
        "label": label,
        "nearHigh": near_high,
        "nearLow": near_low,
        "high10": round(high10, 4),
        "low10": round(low10, 4),
        "color": color,
    }


def tos_custom_quote_snapshot_from_history(history: pd.DataFrame) -> dict[str, Any]:
    """Return exact mirrors for the six visible TOS custom quote columns."""
    rvol = tos_rvol_from_history(history)
    pv52h = tos_pv52h_from_history(history)
    momentum = tos_momentum_from_history(history)
    atr_pct = tos_atr_percent_from_history(history)
    strength = tos_strength_from_history(history)
    support_resistance = tos_support_resistance_from_history(history)
    return {
        "source": "local-python-mirror-of-tos-thinkscript",
        "formulaStatus": "mirrored-from-user-screenshot-and-tos-cache",
        "tos_rvol": {
            "value": rvol,
            "color": "GREEN" if rvol is not None and rvol > 2 else "YELLOW" if rvol is not None and rvol > 1.5 else "LIGHT_GRAY",
            "thinkScript": "def avgVol = Average(volume, 30); def rvol = volume / avgVol;",
        },
        "tos_pv52h": {
            "value": pv52h,
            "color": "GREEN" if pv52h is not None and pv52h > 95 else "YELLOW" if pv52h is not None and pv52h > 85 else "RED",
            "thinkScript": "def high52 = Highest(high, 252); def pctToHigh = (close / high52) * 100;",
        },
        "tos_momentum": {
            "value": momentum,
            "color": "GREEN" if momentum is not None and momentum > 0 else "RED",
            "thinkScript": "def ma10 = Average(close, 10); def momentum = close - ma10;",
        },
        "tos_atr_percent": {
            "value": atr_pct,
            "color": "RED" if atr_pct is not None and atr_pct > 4 else "YELLOW" if atr_pct is not None and atr_pct > 2 else "GREEN",
            "thinkScript": "def atr = Average(TrueRange(high, close, low), 14); def atr_pct = (atr / close) * 100;",
        },
        "tos_strength": {
            "value": strength,
            "color": "GREEN" if strength is not None and strength > 70 else "YELLOW" if strength is not None and strength > 40 else "RED",
            "thinkScript": "def strength = if high - low != 0 then (close - low) / (high - low) else 0;",
        },
        "tos_support_resistance_state": {
            **support_resistance,
            "thinkScript": "def nearHigh = (Highest(high, 10) - close) / Highest(high, 10) < 0.02; def nearLow = (close - Lowest(low, 10)) / Lowest(low, 10) < 0.02;",
        },
    }


def rvol_bucket(value: float | None) -> str:
    """Classify relative volume into plain desk language."""
    if value is None:
        return "unknown"
    if value >= 2.0:
        return "surge"
    if value >= 1.4:
        return "active"
    if value >= 1.0:
        return "normal"
    if value >= 0.7:
        return "quiet"
    return "thin"


def trend_tone_from_label(label: Any) -> str:
    """Return the desk's hot/cold/wild tone for a trend label."""
    lowered = str(label or "").strip().lower()
    if lowered in {"bullish", "uptrend", "breakout"}:
        return "hot"
    if lowered in {"bearish", "downtrend", "breakdown"}:
        return "cold"
    return "wild"


def trend_score_from_label(label: Any) -> float:
    """Score trend posture on a 0-100 scale."""
    lowered = str(label or "").strip().lower()
    if lowered in {"bullish", "breakout"}:
        return 86.0
    if lowered == "uptrend":
        return 76.0
    if lowered in {"basing", "range"}:
        return 58.0
    if lowered == "neutral":
        return 50.0
    if lowered == "downtrend":
        return 28.0
    if lowered in {"bearish", "breakdown"}:
        return 18.0
    return 45.0


def trend_descriptor_from_history(history: pd.DataFrame, *, price: float | None = None) -> dict[str, Any]:
    """Return trend label/tone from price, SMA20, SMA50, and SMA20 slope."""
    close = numeric_series(history, "Close")
    if close.empty:
        return {"label": "Neutral", "tone": "wild", "sma20": None, "sma50": None, "sma20SlopePct": None}

    resolved_price = float(price) if price is not None and price > 0 else float(close.iloc[-1])
    sma20 = close.rolling(window=20).mean().dropna()
    sma50 = close.rolling(window=50).mean().dropna()
    latest_sma20 = float(sma20.iloc[-1]) if not sma20.empty else float(close.tail(20).mean())
    latest_sma50 = float(sma50.iloc[-1]) if not sma50.empty else latest_sma20
    prior_sma20 = float(sma20.iloc[-5]) if len(sma20) >= 5 else latest_sma20
    slope_pct = ((latest_sma20 / prior_sma20) - 1.0) * 100.0 if prior_sma20 > 0 else 0.0

    if resolved_price >= latest_sma20 >= latest_sma50 and latest_sma20 >= prior_sma20:
        label = "Bullish"
    elif resolved_price <= latest_sma20 <= latest_sma50 and latest_sma20 <= prior_sma20:
        label = "Bearish"
    elif resolved_price > latest_sma20:
        label = "Uptrend"
    elif resolved_price > 0 and abs(resolved_price - latest_sma20) / resolved_price <= 0.03:
        label = "Basing"
    else:
        label = "Neutral"

    return {
        "label": label,
        "tone": trend_tone_from_label(label),
        "sma20": round(latest_sma20, 4),
        "sma50": round(latest_sma50, 4),
        "sma20SlopePct": round(slope_pct, 4),
    }


def trend_descriptor_from_row(row: dict[str, Any]) -> dict[str, str]:
    """Return fallback trend from explicit tracker/TOS-like row fields."""
    explicit_label = str(row.get("trend") or "").strip()
    if explicit_label:
        return {"label": explicit_label, "tone": trend_tone_from_label(explicit_label)}

    setup_rec = str(row.get("setupRec") or "").lower()
    momentum_score = number(row.get("momentumScore"), 0.0) or 0.0
    value_score = number(row.get("valueScore"), 0.0) or 0.0
    if "avoid" in setup_rec:
        return {"label": "Bearish", "tone": "cold"}
    if momentum_score >= 1.1 and row.get("signalTrigger"):
        return {"label": "Bullish", "tone": "hot"}
    if value_score >= 1.0 and momentum_score <= 0.45:
        return {"label": "Basing", "tone": "wild"}
    if momentum_score >= 0.55:
        return {"label": "Uptrend", "tone": "hot"}
    return {"label": "Neutral", "tone": "wild"}


def support_resistance_from_history(history: pd.DataFrame, *, lookback: int = 20) -> dict[str, float]:
    """Return recent-range support/resistance from low/high history."""
    high = numeric_series(history, "High")
    low = numeric_series(history, "Low")
    if high.empty or low.empty:
        raise RuntimeError("insufficient high/low history for support/resistance")
    support = round(float(low.tail(lookback).min()), 2)
    resistance = round(float(high.tail(lookback).max()), 2)
    return {
        "support": support,
        "resistance": resistance,
        "rangeWidth": round(max(0.0, resistance - support), 2),
    }


def support_resistance_proxy_from_row(row: dict[str, Any]) -> dict[str, float]:
    """Return ATR-based fallback support/resistance from a tracker row."""
    price = number(row.get("price"), 0.0) or 0.0
    atr_from_percent = price * ((number(row.get("atrPercent"), 0.0) or 0.0) / 100.0)
    range_width = max(number(row.get("atr20Day"), 0.0) or 0.0, atr_from_percent, price * 0.02)
    return {
        "support": round(max(0.0, price - range_width), 2),
        "resistance": round(price + range_width, 2),
        "rangeWidth": round(range_width, 2),
    }


def relative_volume_proxy(row: dict[str, Any]) -> float:
    """Return a fallback RVOL proxy from tracker volatility/trigger fields."""
    proxy = (
        1.0
        + clamp(number(row.get("atrZScore"), 0.0) or 0.0, -2.0, 3.0) * 0.22
        + clamp(number(row.get("momentumScore"), 0.0) or 0.0, 0.0, 2.5) * 0.18
        + (0.22 if row.get("signalTrigger") else 0.0)
        + (0.12 if "urgent" in str(row.get("urgency") or "").lower() else 0.0)
    )
    return round(clamp(proxy, 0.55, 3.6), 2)


def tracker_score_snapshot_from_row(row: dict[str, Any]) -> dict[str, float]:
    """Mirror the current U:Y tracker score formulas from row values.

    Current sheet semantics:
    - Value Score rewards confidence, IV rank, and ATR expansion.
    - Momentum Score is positive IV-rank change, not price momentum.
    - Squeeze Score is positive compression from negative ATR z-score.
    - Ready Score copies Value Score only when the trigger is checked and the
      setup is not Avoid.
    - Priority is the sum of the four component scores.
    """
    confidence = number(row.get("confidence"), 0.0) or 0.0
    iv_rank = number(row.get("ivRank"), 0.0) or 0.0
    iv_rank_change = number(row.get("ivRankChange"), 0.0) or 0.0
    atr_z_score = number(row.get("atrZScore"), 0.0) or 0.0
    value_score = confidence * (iv_rank / 100.0) * (abs(atr_z_score) + 1.0)
    momentum_score = max(0.0, iv_rank_change)
    squeeze_score = max(0.0, -atr_z_score)
    setup_rec = str(row.get("setupRec") or "").strip().lower()
    ready_score = value_score if row.get("signalTrigger") and setup_rec != "avoid" else 0.0
    priority = value_score + momentum_score + squeeze_score + ready_score
    return {
        "valueScore": round(value_score, 4),
        "momentumScore": round(momentum_score, 4),
        "squeezeScore": round(squeeze_score, 4),
        "readyScore": round(ready_score, 4),
        "priority": round(priority, 4),
    }


def momentum_snapshot(history: pd.DataFrame, *, trend: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return ATR-normalized momentum components and tracker-scale score."""
    close = numeric_series(history, "Close")
    atr_pct = atr_percent(history)
    weighted = weighted_return_pct(history)
    roc5 = pct_return(close, 5)
    roc20 = pct_return(close, 20)
    roc60 = pct_return(close, 60)
    acceleration = None
    if roc5 is not None and roc20 is not None:
        acceleration = round(roc5 - (roc20 * 5.0 / 20.0), 4)

    atr_base = max(atr_pct or 0.0, 1.0)
    atr_multiple = None if weighted is None else round(weighted / atr_base, 4)
    trend_label = (trend or {}).get("label") or "Neutral"
    trend_tone = trend_tone_from_label(trend_label)
    trend_bonus = 0.25 if trend_tone == "hot" else -0.25 if trend_tone == "cold" else 0.05
    score = 1.25
    if atr_multiple is not None:
        score += atr_multiple * 0.18
    if acceleration is not None:
        score += acceleration * 0.035
    score += trend_bonus
    tracker_score = round(clamp(score, 0.0, 2.5), 4)
    return {
        "roc5Pct": roc5,
        "roc20Pct": roc20,
        "roc60Pct": roc60,
        "weightedReturnPct": weighted,
        "accelerationPct": acceleration,
        "atrPct": atr_pct,
        "atrMultiple": atr_multiple,
        "trackerScore": tracker_score,
        "score100": round((tracker_score / 2.5) * 100.0, 2),
    }


def strength_label(score: float | None) -> str:
    """Classify a strength score."""
    if score is None:
        return "unknown"
    if score >= 72:
        return "leader"
    if score >= 58:
        return "improving"
    if score >= 45:
        return "neutral"
    return "lagging"


def strength_snapshot(
    history: pd.DataFrame,
    *,
    benchmark_history: pd.DataFrame | None = None,
    trend: dict[str, Any] | None = None,
    rvol: float | None = None,
    momentum: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return absolute/relative strength components on a 0-100 scale."""
    trend = trend or trend_descriptor_from_history(history)
    momentum = momentum or momentum_snapshot(history, trend=trend)
    own_weighted = momentum.get("weightedReturnPct")
    benchmark_weighted = weighted_return_pct(benchmark_history) if benchmark_history is not None else None
    relative_strength = None
    if own_weighted is not None and benchmark_weighted is not None:
        relative_strength = round(float(own_weighted) - float(benchmark_weighted), 4)

    atr_multiple = number(momentum.get("atrMultiple"), 0.0) or 0.0
    absolute_score = clamp(50.0 + atr_multiple * 8.0 + (trend_score_from_label(trend.get("label")) - 50.0) * 0.25)
    relative_score = 50.0 if relative_strength is None else clamp(50.0 + relative_strength * 2.0)
    rvol_value = rvol if rvol is not None else relative_volume_from_history(history)
    if rvol_value is None:
        participation_score = 45.0
    elif rvol_value >= 1.5:
        participation_score = 86.0
    elif rvol_value >= 1.1:
        participation_score = 72.0
    elif rvol_value >= 0.8:
        participation_score = 54.0
    else:
        participation_score = 32.0
    score = round(
        clamp(
            momentum.get("score100", 50.0) * 0.35
            + relative_score * 0.25
            + trend_score_from_label(trend.get("label")) * 0.20
            + participation_score * 0.20
        ),
        2,
    )
    return {
        "score": score,
        "label": strength_label(score),
        "absoluteScore": round(absolute_score, 2),
        "relativeScore": round(relative_score, 2),
        "relativeStrengthPct": relative_strength,
        "benchmarkWeightedReturnPct": benchmark_weighted,
        "participationScore": round(participation_score, 2),
    }


def build_market_context_from_history(
    history: pd.DataFrame,
    *,
    price: float | None = None,
    atr_z_score: float | None = None,
    iv_rank_change: float | None = None,
    benchmark_history: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Return full market context from OHLCV history."""
    close = numeric_series(history, "Close")
    if close.empty:
        raise RuntimeError("insufficient price history for market context")
    resolved_price = float(price) if price is not None and price > 0 else float(close.iloc[-1])
    if resolved_price <= 0:
        resolved_price = float(close.iloc[-1])

    rvol = relative_volume_from_history(history)
    trend = trend_descriptor_from_history(history, price=resolved_price)
    levels = support_resistance_from_history(history)
    support = levels["support"]
    resistance = levels["resistance"]
    distance_to_support_pct = round(((resolved_price - support) / resolved_price) * 100.0, 2) if resolved_price > 0 else 0.0
    distance_to_resistance_pct = round(((resistance - resolved_price) / resolved_price) * 100.0, 2) if resolved_price > 0 else 0.0
    atr_expand = round(float(atr_z_score), 2) if atr_z_score is not None else 0.0
    iv_impulse = round(float(iv_rank_change), 3) if iv_rank_change is not None else 0.0
    momentum = momentum_snapshot(history, trend=trend)
    strength = strength_snapshot(
        history,
        benchmark_history=benchmark_history,
        trend=trend,
        rvol=rvol,
        momentum=momentum,
    )
    tos_custom_formula_mirror = tos_custom_quote_snapshot_from_history(history)
    alignment_score = clamp(
        ((rvol if rvol is not None else 1.0) - 1.0) * 18.0
        + max(atr_expand, 0.0) * 10.0
        + max(iv_impulse, 0.0) * 40.0
        + (14.0 if trend["tone"] == "hot" else 6.0 if trend["tone"] == "wild" else 0.0),
        0.0,
        100.0,
    )
    alignment_label = "Aligned" if alignment_score >= 72 else "Developing" if alignment_score >= 48 else "Fragile"
    return {
        "formulaVersion": FORMULA_VERSION,
        "rvol": "N/A" if rvol is None else round(float(rvol), 2),
        "rvolBucket": rvol_bucket(rvol),
        "trend": trend,
        "triggerBias": "Waiting",
        "atrExpansion": atr_expand,
        "ivImpulse": iv_impulse,
        "support": support,
        "resistance": resistance,
        "rangeWidth": levels["rangeWidth"],
        "distanceToSupportPct": distance_to_support_pct,
        "distanceToResistancePct": distance_to_resistance_pct,
        "momentum": momentum,
        "momentumScore": momentum.get("trackerScore"),
        "momentumSemantics": "price-atr-normalized",
        "priceMomentum": momentum,
        "priceMomentumScore": momentum.get("trackerScore"),
        "strength": strength,
        "strengthScore": strength.get("score"),
        "strengthLabel": strength.get("label"),
        "tosCustomFormulaMirror": tos_custom_formula_mirror,
        "alignmentScore": round(float(alignment_score), 1),
        "alignmentLabel": alignment_label,
        "sourceStatus": "history",
    }


def build_market_context_from_row(row: dict[str, Any], *, unknown_earnings_days: int = 999) -> dict[str, Any]:
    """Return market context from tracker row fields and TOS-like proxies."""
    existing_context = row.get("marketContext") if isinstance(row.get("marketContext"), dict) else {}
    price = number(row.get("price"), 0.0) or 0.0

    rvol_value = number(row.get("rvol"))
    if rvol_value is None:
        rvol_value = number(existing_context.get("rvol"))
    if rvol_value is None:
        rvol_value = relative_volume_proxy(row)

    trend_source = row.get("trend") or existing_context.get("trend")
    if isinstance(trend_source, dict):
        trend = {
            "label": str(trend_source.get("label") or "Neutral"),
            "tone": str(trend_source.get("tone") or trend_tone_from_label(trend_source.get("label"))),
        }
    else:
        trend = trend_descriptor_from_row({**row, "trend": trend_source})

    support = number(row.get("support"))
    resistance = number(row.get("resistance"))
    if support is None:
        support = number(existing_context.get("support"))
    if resistance is None:
        resistance = number(existing_context.get("resistance"))
    if support is None or resistance is None:
        proxy_levels = support_resistance_proxy_from_row(row)
        support = support if support is not None else proxy_levels["support"]
        resistance = resistance if resistance is not None else proxy_levels["resistance"]

    range_width = round(max(0.0, float(resistance) - float(support)), 2)
    distance_to_support_pct = number(row.get("distanceToSupportPct"))
    if distance_to_support_pct is None:
        distance_to_support_pct = number(existing_context.get("distanceToSupportPct"))
    if distance_to_support_pct is None:
        distance_to_support_pct = round(((price - float(support)) / price) * 100.0, 2) if price > 0 else 0.0

    distance_to_resistance_pct = number(row.get("distanceToResistancePct"))
    if distance_to_resistance_pct is None:
        distance_to_resistance_pct = number(existing_context.get("distanceToResistancePct"))
    if distance_to_resistance_pct is None:
        distance_to_resistance_pct = round(((float(resistance) - price) / price) * 100.0, 2) if price > 0 else 0.0

    atr_expand = number(row.get("atrZScore"))
    if atr_expand is None:
        atr_expand = number(existing_context.get("atrExpansion"), 0.0) or 0.0
    iv_impulse = number(row.get("ivRankChange"))
    if iv_impulse is None:
        iv_impulse = number(existing_context.get("ivImpulse"), 0.0) or 0.0

    momentum_score = number(row.get("momentumScore"), 0.0) or 0.0
    ready_score = number(row.get("readyScore"), 0.0) or 0.0
    tracker_scores = tracker_score_snapshot_from_row(row)
    alignment_score = clamp(
        (float(rvol_value) - 1.0) * 18.0
        + clamp(momentum_score, 0.0, 2.5) * 22.0
        + clamp(ready_score, 0.0, 2.5) * 14.0
        + (14.0 if row.get("signalTrigger") else 0.0),
        0.0,
        100.0,
    )
    alignment_label = "Aligned" if alignment_score >= 72 else "Developing" if alignment_score >= 48 else "Fragile"
    source_status = "fallback"
    if (
        price <= 0
        and float(support) <= 0
        and float(resistance) <= 0
        and str(trend.get("label") or "").strip() in {"", "N/A"}
        and not row.get("signalTrigger")
        and (number(row.get("daysUntilEarnings"), 0.0) or 0.0) >= unknown_earnings_days
    ):
        source_status = "unavailable"

    trend_score = trend_score_from_label(trend.get("label"))
    participation_score = 86.0 if rvol_value >= 1.5 else 72.0 if rvol_value >= 1.1 else 54.0 if rvol_value >= 0.8 else 32.0
    strength_score = round(
        clamp(
            (momentum_score / 2.5 * 100.0) * 0.38
            + (ready_score / 2.5 * 100.0) * 0.18
            + trend_score * 0.24
            + participation_score * 0.20
        ),
        2,
    )

    return {
        "formulaVersion": FORMULA_VERSION,
        "rvol": round(float(rvol_value), 2),
        "rvolBucket": rvol_bucket(float(rvol_value)),
        "trend": trend,
        "triggerBias": "Confirmed" if row.get("signalTrigger") else "Waiting",
        "atrExpansion": round(float(atr_expand), 2),
        "ivImpulse": round(float(iv_impulse), 3),
        "support": round(float(support), 2),
        "resistance": round(float(resistance), 2),
        "rangeWidth": range_width,
        "distanceToSupportPct": round(float(distance_to_support_pct), 2),
        "distanceToResistancePct": round(float(distance_to_resistance_pct), 2),
        "momentum": {
            "trackerScore": round(momentum_score, 4),
            "score100": round(momentum_score / 2.5 * 100.0, 2),
            "source": "tracker-row",
            "semantics": "positive-iv-rank-change",
        },
        "momentumScore": round(momentum_score, 4),
        "trackerScoreFormula": tracker_scores,
        "strength": {
            "score": strength_score,
            "label": strength_label(strength_score),
            "source": "tracker-row",
            "participationScore": round(participation_score, 2),
        },
        "strengthScore": strength_score,
        "strengthLabel": strength_label(strength_score),
        "tosCustomMetrics": row.get("tosCustomMetrics") or {},
        "tosCustomSignalSummary": row.get("tosCustomSignalSummary") or {},
        "tosCustomMetricSourceStatus": "captured" if row.get("tosCustomMetrics") else "missing",
        "alignmentScore": round(float(alignment_score), 1),
        "alignmentLabel": alignment_label,
        "sourceStatus": source_status,
    }
