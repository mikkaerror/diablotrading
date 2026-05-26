from __future__ import annotations

"""Anti-confirmation audit for TOS custom metric theory.

The exact TOS mirrors are useful, but they should not become "green means buy"
features. This module consumes Schwab daily candles, recomputes improved
companions for each visible metric, and writes a thesis-support report that
explicitly separates:

- what supports the bullish/long-vol thesis
- what contradicts it
- what is merely context
- which formulas are noisy, redundant, or scale-unsafe

Safety contract:
- reads local Schwab price-history and custom-metric artifacts
- no TOS UI, account/order endpoints, Sheet writes, queue mutation, or staging
"""

import argparse
import json
from itertools import combinations
from pathlib import Path
from typing import Any

import pandas as pd

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_schwab_price_history import SCHWAB_PRICE_HISTORY_FILE
from inferno_tos_formula_math import (
    tos_custom_quote_snapshot_from_history,
    true_range,
)
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


TOS_METRIC_THEORY_AUDIT_FILE = DATA_DIR / "inferno_tos_metric_theory_audit.json"
TOS_METRIC_THEORY_AUDIT_TEXT_FILE = REPORTS_DIR / "tos_metric_theory_audit_latest.txt"
TOS_METRIC_THEORY_AUDIT_STAGE = "tos-metric-theory-audit"

VISIBLE_KEYS = (
    "tos_rvol",
    "tos_pv52h",
    "tos_momentum",
    "tos_atr_percent",
    "tos_strength",
    "tos_support_resistance_state",
)

FORMULA_THEORY = {
    "tos_rvol": {
        "formula": "volume / Average(volume, 30)",
        "theoryVerdict": "keep-with-cleaner-companion",
        "decisionRole": "participation / attention",
        "caveat": "TOS Average includes the current bar, so spikes dampen their own denominator. Intraday daily candles also undercount volume until the session is complete.",
        "preferredCompanion": "rvolPrior30 and 63-day volume percentile",
    },
    "tos_pv52h": {
        "formula": "close / Highest(high, 252) * 100",
        "theoryVerdict": "keep-as-context",
        "decisionRole": "breakout proximity or extension risk",
        "caveat": "Near a 52-week high is not automatically bullish; it can also mean stretched entry risk when ATR% is high or momentum is fading.",
        "preferredCompanion": "drawdownFrom52HighPct with momentumAtrMultiple",
    },
    "tos_momentum": {
        "formula": "close - Average(close, 10)",
        "theoryVerdict": "revise-before-ranking",
        "decisionRole": "short-term directional impulse",
        "caveat": "Raw dollar momentum is not scale-safe across tickers. A $5 move means different things for PL and ASML.",
        "preferredCompanion": "momentumPct and momentumAtrMultiple",
    },
    "tos_atr_percent": {
        "formula": "Average(TrueRange(high, close, low), 14) / close * 100",
        "theoryVerdict": "keep-for-risk-not-direction",
        "decisionRole": "range risk, sizing, premium hurdle, slippage caution",
        "caveat": "High ATR% is not bullish or bearish by itself; it raises the movement and execution-friction bar.",
        "preferredCompanion": "required move versus ATR and option premium",
    },
    "tos_strength": {
        "formula": "(close - low) / (high - low) * 100",
        "theoryVerdict": "downgrade-single-bar-signal",
        "decisionRole": "latest close-location pressure",
        "caveat": "A single day's close location is noisy. It should be checked against a 5-day close-location average.",
        "preferredCompanion": "closeLocation5d",
    },
    "tos_support_resistance_state": {
        "formula": "10-day high/low proximity within 2%",
        "theoryVerdict": "keep-tactical-only",
        "decisionRole": "near-term level context",
        "caveat": "A 10-day level is tactical, not a full thesis. It needs 20/60-day context and option expected move before it gates trades.",
        "preferredCompanion": "20-day and 60-day range distances",
    },
}


def text(value: Any) -> str:
    """Normalize display text."""
    return str(value or "").strip()


def number(value: Any, default: float | None = None) -> float | None:
    """Coerce loose numeric values."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = text(value).replace(",", "").replace("$", "").replace("%", "")
    if not cleaned or cleaned.upper() in {"N/A", "NAN", "NONE", "--"}:
        return default
    try:
        return float(cleaned)
    except ValueError:
        return default


def rounded(value: Any, digits: int = 4) -> float | None:
    """Round an optional number."""
    parsed = number(value)
    if parsed is None:
        return None
    return round(parsed, digits)


def normalize_symbol(value: Any) -> str:
    """Normalize ticker symbols."""
    return text(value).upper().lstrip("$")


def history_from_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert serialized Schwab candle records into an OHLCV frame."""
    rows: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        rows.append(
            {
                "Datetime": pd.to_datetime(record.get("datetime"), utc=True, errors="coerce"),
                "Open": number(record.get("open")),
                "High": number(record.get("high")),
                "Low": number(record.get("low")),
                "Close": number(record.get("close")),
                "Volume": number(record.get("volume")),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["Datetime", "Open", "High", "Low", "Close", "Volume"])
    return frame.sort_values("Datetime").dropna(subset=["Open", "High", "Low", "Close"]).reset_index(drop=True)


def latest_value(mirror: dict[str, Any], key: str, field: str = "value") -> Any:
    """Read one field from a TOS mirror cell."""
    cell = mirror.get(key) if isinstance(mirror, dict) else None
    return cell.get(field) if isinstance(cell, dict) else None


def percentile_rank(latest: float, baseline: pd.Series) -> float | None:
    """Return latest value's percentile rank against a baseline series."""
    clean = pd.to_numeric(baseline, errors="coerce").dropna()
    if clean.empty:
        return None
    return round(float((clean <= latest).mean() * 100.0), 2)


def close_location_series(history: pd.DataFrame) -> pd.Series:
    """Return close location inside each candle's high-low range."""
    high = pd.to_numeric(history["High"], errors="coerce")
    low = pd.to_numeric(history["Low"], errors="coerce")
    close = pd.to_numeric(history["Close"], errors="coerce")
    width = high - low
    return ((close - low) / width.where(width != 0, 1.0) * 100.0).dropna()


def rvol_prior_average(history: pd.DataFrame, *, lookback: int = 30) -> float | None:
    """Return volume RVOL using the prior bars only as denominator."""
    volume = pd.to_numeric(history["Volume"], errors="coerce").dropna()
    if len(volume) <= lookback:
        return None
    baseline = volume.iloc[-lookback - 1 : -1]
    average = float(baseline.mean()) if not baseline.empty else 0.0
    if average <= 0:
        return None
    return round(float(volume.iloc[-1]) / average, 2)


def atr_value(history: pd.DataFrame, *, lookback: int = 14) -> float | None:
    """Return latest simple ATR."""
    tr = true_range(history)
    if len(tr) < lookback:
        return None
    return round(float(tr.rolling(window=lookback).mean().dropna().iloc[-1]), 4)


def range_distance(close: float, high_value: float, low_value: float) -> dict[str, float | None]:
    """Return close distance from high/low range boundaries."""
    if close <= 0 or high_value <= 0 or low_value <= 0:
        return {"distanceToHighPct": None, "distanceToLowPct": None}
    return {
        "distanceToHighPct": round((high_value - close) / close * 100.0, 2),
        "distanceToLowPct": round((close - low_value) / close * 100.0, 2),
    }


def companion_metrics(history: pd.DataFrame, mirror: dict[str, Any]) -> dict[str, Any]:
    """Return normalized companion features for the exact TOS mirrors."""
    close = pd.to_numeric(history["Close"], errors="coerce").dropna()
    high = pd.to_numeric(history["High"], errors="coerce").dropna()
    low = pd.to_numeric(history["Low"], errors="coerce").dropna()
    volume = pd.to_numeric(history["Volume"], errors="coerce").dropna()
    if close.empty or high.empty or low.empty:
        return {}

    latest_close = float(close.iloc[-1])
    sma10 = float(close.rolling(window=10).mean().dropna().iloc[-1]) if len(close) >= 10 else None
    atr14 = atr_value(history)
    raw_momentum = number(latest_value(mirror, "tos_momentum"))
    momentum_pct = round((latest_close / sma10 - 1.0) * 100.0, 2) if sma10 and sma10 > 0 else None
    momentum_atr = round((latest_close - sma10) / atr14, 2) if sma10 and atr14 and atr14 > 0 else None
    close_location = close_location_series(history)
    high20 = float(high.tail(20).max())
    low20 = float(low.tail(20).min())
    high60 = float(high.tail(60).max())
    low60 = float(low.tail(60).min())
    latest_volume = float(volume.iloc[-1]) if not volume.empty else None
    prior_volume_baseline = volume.iloc[-64:-1] if len(volume) >= 2 else pd.Series(dtype="float64")

    pv52h = number(latest_value(mirror, "tos_pv52h"))
    return {
        "latestClose": round(latest_close, 4),
        "latestVolume": int(latest_volume or 0),
        "rvolTos": number(latest_value(mirror, "tos_rvol")),
        "rvolPrior30": rvol_prior_average(history),
        "volumePercentile63": percentile_rank(float(latest_volume), prior_volume_baseline) if latest_volume is not None else None,
        "pv52h": pv52h,
        "drawdownFrom52HighPct": round(100.0 - pv52h, 2) if pv52h is not None else None,
        "momentumRaw": raw_momentum,
        "momentumPct": momentum_pct,
        "momentumAtrMultiple": momentum_atr,
        "atrPercent": number(latest_value(mirror, "tos_atr_percent")),
        "atr14": atr14,
        "strengthLatest": number(latest_value(mirror, "tos_strength")),
        "closeLocation5d": round(float(close_location.tail(5).mean()), 2) if len(close_location) >= 5 else None,
        "closeLocation10d": round(float(close_location.tail(10).mean()), 2) if len(close_location) >= 10 else None,
        "supportResistanceState": latest_value(mirror, "tos_support_resistance_state", "label"),
        "range20": {"high": round(high20, 4), "low": round(low20, 4), **range_distance(latest_close, high20, low20)},
        "range60": {"high": round(high60, 4), "low": round(low60, 4), **range_distance(latest_close, high60, low60)},
    }


def add_rule(target: list[dict[str, Any]], *, metric: str, message: str, value: Any = None) -> None:
    """Append one evidence rule."""
    target.append({"metric": metric, "value": value, "message": message})


def thesis_evidence(features: dict[str, Any]) -> dict[str, Any]:
    """Classify support and challenge evidence for a ticker thesis."""
    supports: list[dict[str, Any]] = []
    challenges: list[dict[str, Any]] = []
    context: list[dict[str, Any]] = []
    caveats: list[str] = []

    rvol = number(features.get("rvolPrior30"))
    rvol_tos = number(features.get("rvolTos"))
    pv52h = number(features.get("pv52h"))
    momentum_atr = number(features.get("momentumAtrMultiple"))
    momentum_pct = number(features.get("momentumPct"))
    atr_pct = number(features.get("atrPercent"))
    strength = number(features.get("strengthLatest"))
    close_location_5d = number(features.get("closeLocation5d"))
    supres = text(features.get("supportResistanceState"))

    if rvol is not None:
        if rvol >= 1.5:
            add_rule(supports, metric="rvolPrior30", value=rvol, message="participation is above the prior 30-day baseline")
        elif rvol < 0.75:
            add_rule(challenges, metric="rvolPrior30", value=rvol, message="participation is quiet versus the prior 30-day baseline")
        else:
            add_rule(context, metric="rvolPrior30", value=rvol, message="participation is ordinary")
    if rvol is not None and rvol_tos is not None and abs(rvol - rvol_tos) >= 0.2:
        caveats.append("TOS RVOL and prior-30 RVOL diverge because the TOS denominator includes the current bar.")

    if pv52h is not None:
        if pv52h >= 95:
            add_rule(supports, metric="pv52h", value=pv52h, message="price is close to its 52-week high")
            if atr_pct is not None and atr_pct >= 4:
                add_rule(challenges, metric="pv52h+atrPercent", value=atr_pct, message="near-high plus high ATR can be extension risk, not just breakout quality")
        elif pv52h < 80:
            add_rule(challenges, metric="pv52h", value=pv52h, message="price is meaningfully below the 52-week high")
        else:
            add_rule(context, metric="pv52h", value=pv52h, message="price is in the upper-middle part of its annual range")

    if momentum_atr is not None:
        if momentum_atr >= 0.5 and (momentum_pct or 0) > 0:
            add_rule(supports, metric="momentumAtrMultiple", value=momentum_atr, message="10-day momentum is positive after normalizing by ATR")
        elif momentum_atr <= -0.5:
            add_rule(challenges, metric="momentumAtrMultiple", value=momentum_atr, message="10-day momentum is negative after normalizing by ATR")
        else:
            add_rule(context, metric="momentumAtrMultiple", value=momentum_atr, message="10-day momentum is not decisive")
    caveats.append("Raw MOM is dollar-denominated and should not rank tickers without percent or ATR normalization.")

    if atr_pct is not None:
        if atr_pct >= 4:
            add_rule(challenges, metric="atrPercent", value=atr_pct, message="realized range is hot; sizing, slippage, and premium hurdle need extra proof")
        elif atr_pct <= 2:
            add_rule(supports, metric="atrPercent", value=atr_pct, message="realized range is controlled enough for cleaner sizing")
        else:
            add_rule(context, metric="atrPercent", value=atr_pct, message="realized range is moderate")

    if close_location_5d is not None:
        if close_location_5d >= 65:
            add_rule(supports, metric="closeLocation5d", value=close_location_5d, message="buyers have held closes in the upper part of the range recently")
        elif close_location_5d <= 35:
            add_rule(challenges, metric="closeLocation5d", value=close_location_5d, message="recent closes are weak inside daily ranges")
        else:
            add_rule(context, metric="closeLocation5d", value=close_location_5d, message="recent close location is neutral")
    if strength is not None and close_location_5d is not None and abs(strength - close_location_5d) >= 30:
        caveats.append("Latest Strength is far from the 5-day close-location average, so the single-bar signal may be noisy.")

    if "Near High" in supres:
        add_rule(supports, metric="supportResistanceState", value=supres, message="price is near the 10-day high")
    elif "Near Low" in supres:
        add_rule(challenges, metric="supportResistanceState", value=supres, message="price is near the 10-day low")
    elif supres:
        add_rule(context, metric="supportResistanceState", value=supres, message="price is not pressing a 10-day boundary")

    if rvol is not None and rvol >= 1.5 and momentum_atr is not None and momentum_atr < 0:
        add_rule(challenges, metric="rvol+momentum", value={"rvolPrior30": rvol, "momentumAtrMultiple": momentum_atr}, message="high participation with negative momentum can be distribution, not confirmation")

    support_count = len(supports)
    challenge_count = len(challenges)
    if support_count >= 3 and challenge_count <= 1:
        posture = "supports-thesis"
    elif challenge_count > support_count:
        posture = "challenges-thesis"
    elif support_count and challenge_count:
        posture = "mixed-thesis"
    else:
        posture = "inconclusive"

    return {
        "posture": posture,
        "supportCount": support_count,
        "challengeCount": challenge_count,
        "contextCount": len(context),
        "supports": supports,
        "challenges": challenges,
        "context": context,
        "antiYesManCaveats": list(dict.fromkeys(caveats)),
    }


def data_quality(symbol: str, row: dict[str, Any], history: pd.DataFrame, mirror: dict[str, Any]) -> dict[str, Any]:
    """Return data-quality warnings for one ticker."""
    issues: list[str] = []
    candle_count = len(history)
    if candle_count < 252:
        issues.append("less-than-252-candles-pv52h-is-window-limited")
    if candle_count < 31:
        issues.append("less-than-31-candles-clean-rvol-unavailable")
    missing_formula_values = []
    for key in VISIBLE_KEYS:
        cell = mirror.get(key) if isinstance(mirror, dict) else None
        if not isinstance(cell, dict):
            missing_formula_values.append(key)
        elif key == "tos_support_resistance_state" and not cell.get("label"):
            missing_formula_values.append(key)
        elif key != "tos_support_resistance_state" and cell.get("value") is None:
            missing_formula_values.append(key)
    latest = row.get("latestDate")
    return {
        "symbol": symbol,
        "candleCount": candle_count,
        "latestDate": latest,
        "formulaReady": not missing_formula_values,
        "missingFormulaValues": missing_formula_values,
        "issues": issues,
    }


def audit_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Audit one Schwab price-history row."""
    symbol = normalize_symbol(row.get("symbol"))
    history = history_from_records(row.get("candles") or [])
    if not symbol or history.empty:
        return None
    mirror = row.get("tosCustomFormulaMirror")
    if not isinstance(mirror, dict) or not mirror:
        mirror = tos_custom_quote_snapshot_from_history(history)
    features = companion_metrics(history, mirror)
    evidence = thesis_evidence(features)
    quality = data_quality(symbol, row, history, mirror)
    return {
        "symbol": symbol,
        "posture": evidence["posture"],
        "dataQuality": quality,
        "exactTosMirror": {key: mirror.get(key) for key in VISIBLE_KEYS if isinstance(mirror.get(key), dict)},
        "companionFeatures": features,
        "evidence": evidence,
    }


def redundancy_scan(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Find highly correlated features across the current universe."""
    data: list[dict[str, Any]] = []
    for row in rows:
        features = row.get("companionFeatures") or {}
        data.append(
            {
                "rvolTos": features.get("rvolTos"),
                "rvolPrior30": features.get("rvolPrior30"),
                "pv52h": features.get("pv52h"),
                "momentumPct": features.get("momentumPct"),
                "momentumAtrMultiple": features.get("momentumAtrMultiple"),
                "atrPercent": features.get("atrPercent"),
                "strengthLatest": features.get("strengthLatest"),
                "closeLocation5d": features.get("closeLocation5d"),
            }
        )
    frame = pd.DataFrame(data).apply(pd.to_numeric, errors="coerce").dropna(axis=1, how="all")
    if len(frame) < 5 or len(frame.columns) < 2:
        return {"sampleSize": len(frame), "highCorrelationPairs": [], "note": "need at least five rows for a useful redundancy scan"}
    corr = frame.corr(method="spearman", min_periods=5)
    pairs: list[dict[str, Any]] = []
    for left, right in combinations(corr.columns, 2):
        value = corr.loc[left, right]
        if pd.isna(value):
            continue
        if abs(float(value)) >= 0.75:
            pairs.append({"left": left, "right": right, "spearman": round(float(value), 4)})
    return {
        "sampleSize": len(frame),
        "highCorrelationPairs": sorted(pairs, key=lambda item: -abs(item["spearman"])),
        "note": "high correlations mean those features should not be double-counted as independent evidence",
    }


def selected_rows(price_history_report: dict[str, Any], *, symbols: set[str] | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    """Filter price-history rows for an audit run."""
    rows: list[dict[str, Any]] = []
    for row in price_history_report.get("rows") or []:
        if not isinstance(row, dict):
            continue
        symbol = normalize_symbol(row.get("symbol"))
        if symbols and symbol not in symbols:
            continue
        rows.append(row)
        if limit is not None and len(rows) >= limit:
            break
    return rows


def build_theory_audit(
    price_history_report: dict[str, Any],
    *,
    symbols: set[str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Build an anti-confirmation audit over Schwab-derived TOS metrics."""
    source_rows = selected_rows(price_history_report, symbols=symbols, limit=limit)
    rows = [audited for row in source_rows if (audited := audit_row(row)) is not None]
    posture_counts: dict[str, int] = {}
    issue_counts: dict[str, int] = {}
    for row in rows:
        posture = row.get("posture") or "unknown"
        posture_counts[posture] = posture_counts.get(posture, 0) + 1
        for issue in ((row.get("dataQuality") or {}).get("issues") or []):
            issue_counts[issue] = issue_counts.get(issue, 0) + 1

    if not source_rows:
        verdict = "insufficient-price-history"
    elif not rows:
        verdict = "insufficient-candles"
    elif any(item.get("theoryVerdict", "").startswith("revise") for item in FORMULA_THEORY.values()):
        verdict = "formula-policy-needs-review"
    else:
        verdict = "formula-theory-ready"

    return {
        "generatedAt": local_now().isoformat(),
        "stage": TOS_METRIC_THEORY_AUDIT_STAGE,
        "authority": {
            "readOnly": True,
            "touchesTos": False,
            "touchesBrokerAccountOrOrders": False,
            "touchesSheets": False,
            "stagesTrades": False,
        },
        "source": {
            "provider": "schwab-price-history",
            "artifact": str(SCHWAB_PRICE_HISTORY_FILE),
            "status": price_history_report.get("status"),
            "generatedAt": price_history_report.get("generatedAt"),
        },
        "verdict": verdict,
        "formulaTheory": FORMULA_THEORY,
        "selectedRows": len(source_rows),
        "checked": len(rows),
        "postureCounts": dict(sorted(posture_counts.items())),
        "dataQualityIssueCounts": dict(sorted(issue_counts.items())),
        "redundancy": redundancy_scan(rows),
        "rows": rows,
        "nextActions": theory_next_actions(rows),
    }


def theory_next_actions(rows: list[dict[str, Any]]) -> list[str]:
    """Return concrete follow-up actions from the audit."""
    actions = [
        "Use Schwab price-history sync as the default source for the six OHLCV-derived metrics.",
        "Treat raw MOM as display only; rank with momentumPct or momentumAtrMultiple.",
        "Treat ATR% as a risk/sizing feature, not a bullish/bearish signal.",
        "Do not double-count highly correlated companion features as independent thesis evidence.",
        "Calibrate any formula weight against closed paper/shadow outcomes before it can affect live gates.",
    ]
    if any((row.get("dataQuality") or {}).get("issues") for row in rows):
        actions.append("Backfill or request more candles before trusting 52-week and RVOL comparisons on short histories.")
    if any(row.get("posture") == "challenges-thesis" for row in rows):
        actions.append("Review challenge-heavy tickers manually before they influence strategy selection.")
    return actions


def format_rule(rule: dict[str, Any]) -> str:
    """Render one evidence rule."""
    value = rule.get("value")
    suffix = f" ({value})" if value is not None and value != "" else ""
    return f"{rule.get('metric')}{suffix}: {rule.get('message')}"


def theory_audit_text(payload: dict[str, Any]) -> str:
    """Render an operator memo for the formula theory audit."""
    lines = [
        "Inferno TOS Metric Theory Audit",
        "=" * 32,
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Verdict: {payload.get('verdict')}",
        f"Source: {(payload.get('source') or {}).get('provider')} | status={(payload.get('source') or {}).get('status')}",
        f"Checked: {payload.get('checked')} of {payload.get('selectedRows')} selected rows",
        "",
        "Formula policy",
    ]
    for key, item in (payload.get("formulaTheory") or {}).items():
        lines.append(f"- {key}: {item.get('theoryVerdict')} | {item.get('decisionRole')}")
        lines.append(f"  caveat: {item.get('caveat')}")
        lines.append(f"  preferred: {item.get('preferredCompanion')}")

    redundancy = payload.get("redundancy") or {}
    lines.extend(["", "Redundancy scan"])
    pairs = redundancy.get("highCorrelationPairs") or []
    if pairs:
        for pair in pairs[:8]:
            lines.append(f"- {pair.get('left')} vs {pair.get('right')}: spearman {pair.get('spearman')}")
    else:
        lines.append(f"- {redundancy.get('note')}")

    rows = payload.get("rows") or []
    lines.extend(["", "Ticker thesis checks"])
    for row in rows[:12]:
        features = row.get("companionFeatures") or {}
        evidence = row.get("evidence") or {}
        lines.append(
            f"- {row.get('symbol')}: {row.get('posture')} | "
            f"rvol={features.get('rvolPrior30')} pv52h={features.get('pv52h')} "
            f"momATR={features.get('momentumAtrMultiple')} atr%={features.get('atrPercent')} "
            f"loc5d={features.get('closeLocation5d')}"
        )
        supports = evidence.get("supports") or []
        challenges = evidence.get("challenges") or []
        if supports:
            lines.append(f"  supports: {format_rule(supports[0])}")
        if challenges:
            lines.append(f"  challenges: {format_rule(challenges[0])}")
        caveats = evidence.get("antiYesManCaveats") or []
        if caveats:
            lines.append(f"  caveat: {caveats[0]}")
    if not rows:
        lines.append("- No rows checked.")

    lines.extend(["", "Next actions"])
    lines.extend(f"- {action}" for action in payload.get("nextActions") or [])
    return "\n".join(lines).rstrip() + "\n"


def save_theory_audit(payload: dict[str, Any]) -> None:
    """Persist theory audit artifacts."""
    ensure_dirs()
    atomic_write_json(TOS_METRIC_THEORY_AUDIT_FILE, payload)
    atomic_write_text(TOS_METRIC_THEORY_AUDIT_TEXT_FILE, theory_audit_text(payload))


def parse_symbols(raw: list[str]) -> set[str] | None:
    """Parse optional symbol filters."""
    symbols = {normalize_symbol(item) for item in raw if normalize_symbol(item)}
    return symbols or None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Audit whether TOS custom metrics are thesis-useful or misleading.")
    parser.add_argument("symbols", nargs="*", help="Optional symbols to audit")
    parser.add_argument("--price-history-json", default=str(SCHWAB_PRICE_HISTORY_FILE), help="Schwab price-history artifact path")
    parser.add_argument("--limit", type=int, help="Optional row limit")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    args = parser.parse_args(argv)

    source = load_json_file(Path(args.price_history_json)) or {}
    payload = build_theory_audit(source, symbols=parse_symbols(args.symbols), limit=args.limit)
    save_theory_audit(payload)
    print(json.dumps(payload, indent=2) if args.json else theory_audit_text(payload), end="")
    return 0 if payload.get("checked", 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
