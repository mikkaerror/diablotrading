from __future__ import annotations

"""Refresh the fixed AI-infrastructure research basket from Schwab candles.

This lane reads market data only.  It derives trend and trailing-return inputs
for the already-declared basket universe, and publishes them only when every
symbol has enough daily history.  A partial fetch is recorded but cannot shrink
the expected universe or replace the last complete signal set.
"""

import argparse
from pathlib import Path
from typing import Any

from inferno_ai_basket_momentum import build as build_momentum
from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_schwab_price_history import (
    build_report as build_price_history_report,
    refresh_access_token_if_possible,
)
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


STAGE = "ai-basket-refresh-research-only"
OUTPUT_FILE = DATA_DIR / "inferno_ai_basket_refresh.json"
REPORT_FILE = REPORTS_DIR / "ai_basket_refresh_latest.txt"
UNIVERSE_FILE = DATA_DIR.parent / "research" / "ai_basket_universe.json"
SNAPSHOT_FILE = DATA_DIR / "ai_basket_snapshot.json"
MOMENTUM_FILE = DATA_DIR / "ai_basket_momentum.json"
MIN_CANDLES = 200
RETURN_SESSIONS = {"1M": 21, "3M": 63, "6M": 126}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def basket_records(payload: Any) -> list[dict[str, Any]]:
    """Return basket records from the legacy list or provenance wrapper."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        return [row for row in payload.get("records") or [] if isinstance(row, dict)]
    return []


def declared_universe(payload: Any) -> list[str]:
    """Preserve the source-declared universe without adding new membership."""
    explicit = payload.get("expectedUniverse") if isinstance(payload, dict) else None
    raw = explicit if isinstance(explicit, list) and explicit else [row.get("symbol") for row in basket_records(payload)]
    out: list[str] = []
    seen: set[str] = set()
    for value in raw:
        symbol = _text(value).upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
    return out


def _history_values(row: dict[str, Any]) -> tuple[list[float], list[float], list[float]]:
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    for candle in row.get("candles") or []:
        close = _number(candle.get("close")) if isinstance(candle, dict) else None
        high = _number(candle.get("high")) if isinstance(candle, dict) else None
        low = _number(candle.get("low")) if isinstance(candle, dict) else None
        if close is None or high is None or low is None:
            continue
        closes.append(close)
        highs.append(high)
        lows.append(low)
    return closes, highs, lows


def _trailing_return(closes: list[float], sessions: int) -> float | None:
    if len(closes) <= sessions or closes[-sessions - 1] <= 0:
        return None
    return round((closes[-1] / closes[-sessions - 1] - 1.0) * 100.0, 4)


def derive_inputs(
    price_history: dict[str, Any],
    basket: Any,
    *,
    generated_at: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Derive complete snapshot and momentum inputs from normalized candles."""
    universe = declared_universe(basket)
    categories = {
        _text(row.get("symbol")).upper(): _text(row.get("cat"))
        for row in basket_records(basket)
        if _text(row.get("symbol"))
    }
    history = {
        _text(row.get("symbol")).upper(): row
        for row in price_history.get("rows") or []
        if isinstance(row, dict) and _text(row.get("symbol"))
    }
    snapshot_rows: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    blocked: dict[str, list[str]] = {}
    for symbol in universe:
        row = history.get(symbol)
        reasons: list[str] = []
        if row is None:
            reasons.append("missing-price-history")
            closes: list[float] = []
            highs: list[float] = []
            lows: list[float] = []
        else:
            closes, highs, lows = _history_values(row)
            if len(closes) < MIN_CANDLES:
                reasons.append(f"fewer-than-{MIN_CANDLES}-candles")
        returns = {label: _trailing_return(closes, sessions) for label, sessions in RETURN_SESSIONS.items()}
        if any(value is None for value in returns.values()):
            reasons.append("trailing-return-history-incomplete")
        if reasons:
            blocked[symbol] = sorted(set(reasons))
            continue
        snapshot_rows.append(
            {
                "symbol": symbol,
                "cat": categories.get(symbol, ""),
                "price": round(closes[-1], 4),
                "priceAvg50": round(sum(closes[-50:]) / 50.0, 4),
                "priceAvg200": round(sum(closes[-200:]) / 200.0, 4),
                "yearHigh": round(max(highs[-252:]), 4),
                "yearLow": round(min(lows[-252:]), 4),
            }
        )
        changes.append({"symbol": symbol, **returns})

    snapshot_complete = bool(universe) and len(snapshot_rows) == len(universe) and not blocked
    snapshot = {
        "generatedAt": generated_at,
        "stage": STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "source": {
            "provider": "schwab-price-history",
            "generatedAt": price_history.get("generatedAt"),
            "status": price_history.get("status"),
            "endpoint": price_history.get("endpoint"),
        },
        "expectedUniverse": universe,
        "records": snapshot_rows,
    }
    momentum = build_momentum(changes, expected_universe=universe)
    momentum.update(
        {
            "generatedAt": generated_at,
            "promotable": False,
            "authorityChanged": False,
            "brokerSubmitAllowed": False,
            "liveTradingAllowed": False,
            "expectedUniverse": universe,
            "source": {
                "provider": "schwab-price-history",
                "generatedAt": price_history.get("generatedAt"),
                "returnSessions": RETURN_SESSIONS,
            },
        }
    )
    complete = snapshot_complete and bool(momentum.get("signalsTrusted"))
    assessment = {
        "complete": complete,
        "momentumTrusted": bool(momentum.get("signalsTrusted")),
        "expectedCount": len(universe),
        "publishedCount": len(snapshot_rows),
        "missingCount": len(blocked),
        "blockedSymbols": blocked,
    }
    return snapshot, momentum, assessment


def build_refresh(
    basket: Any,
    *,
    price_history: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Fetch or consume read-only candles and construct refresh artifacts."""
    universe = declared_universe(basket)
    history = price_history if price_history is not None else build_price_history_report(universe, symbol_limit=len(universe))
    generated_at = generated_at or local_now().isoformat()
    snapshot, momentum, assessment = derive_inputs(history, basket, generated_at=generated_at)
    payload = {
        "generatedAt": generated_at,
        "stage": STAGE,
        "verdict": "complete" if assessment["complete"] else "fail-closed",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "published": bool(assessment["complete"]),
        "source": {
            "provider": "schwab-price-history",
            "generatedAt": history.get("generatedAt"),
            "status": history.get("status"),
            "configured": history.get("configured"),
            "errors": history.get("errors") or [],
        },
        "counts": assessment,
        "rules": [
            "Use only the previously declared basket universe.",
            f"Require at least {MIN_CANDLES} normalized daily candles for every symbol.",
            "Publish snapshot and momentum together only after complete coverage.",
            "A partial refresh cannot replace the last complete signal set or change authority.",
        ],
    }
    return payload, snapshot, momentum


def render(payload: dict[str, Any]) -> str:
    counts = payload.get("counts") or {}
    lines = [
        "Inferno AI Basket Market-Data Refresh",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')} | published={payload.get('published')}",
        "Authority: research-only; broker submit OFF; live trading OFF",
        f"Source: {payload.get('source', {}).get('provider')} | {payload.get('source', {}).get('status')}",
        f"Coverage: {counts.get('publishedCount', 0)}/{counts.get('expectedCount', 0)} | blocked {counts.get('missingCount', 0)}",
    ]
    for symbol, reasons in (counts.get("blockedSymbols") or {}).items():
        lines.append(f"- {symbol}: {', '.join(reasons)}")
    lines += ["", "Publication contract:"] + [f"- {rule}" for rule in payload.get("rules") or []]
    return "\n".join(lines).rstrip() + "\n"


def save(payload: dict[str, Any], snapshot: dict[str, Any], momentum: dict[str, Any]) -> None:
    """Persist the run and atomically publish signals only on full coverage."""
    ensure_dirs()
    atomic_write_json(OUTPUT_FILE, payload)
    atomic_write_text(REPORT_FILE, render(payload))
    if payload.get("published"):
        atomic_write_json(SNAPSHOT_FILE, snapshot)
        atomic_write_json(MOMENTUM_FILE, momentum)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("run", "status"), default="run")
    parser.add_argument("--skip-refresh", action="store_true", help="Skip OAuth token refresh before the read-only market-data pull")
    args = parser.parse_args()
    if args.command == "status":
        print(REPORT_FILE.read_text(encoding="utf-8") if REPORT_FILE.exists() else "No AI-basket refresh report yet.")
        return 0
    basket = load_json_file(UNIVERSE_FILE) if UNIVERSE_FILE.exists() else []
    refresh_status = None if args.skip_refresh else refresh_access_token_if_possible()
    payload, snapshot, momentum = build_refresh(basket)
    if refresh_status is not None:
        payload["source"]["tokenRefresh"] = refresh_status
    save(payload, snapshot, momentum)
    print(render(payload), end="")
    return 0 if payload.get("published") else 1


if __name__ == "__main__":
    raise SystemExit(main())
