from __future__ import annotations

"""Portfolio/context risk analytics for Inferno.

Single-ticket checks are necessary but not sufficient. This module asks the
portfolio-manager questions: are several trades the same factor bet, is one
sector dominating the queue, and is the market regime friendly or hostile?
"""

import argparse
import json
from collections import defaultdict
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

from inferno_config import local_now
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


EXECUTION_QUEUE_FILE = DATA_DIR / "inferno_execution_queue.json"
PAPER_EXECUTION_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
EXPOSURE_ANALYTICS_FILE = DATA_DIR / "inferno_exposure_analytics.json"
EXPOSURE_ANALYTICS_TEXT_FILE = REPORTS_DIR / "exposure_analytics_latest.txt"
TICKER_METADATA_CACHE_FILE = DATA_DIR / "inferno_ticker_metadata_cache.json"

CORRELATION_LOOKBACK = "3mo"
HIGH_CORRELATION_THRESHOLD = 0.70
MAX_SECTOR_SHARE = 0.60
MAX_SETUP_SHARE = 0.70
METADATA_CACHE_DAYS = 14


def number(value: Any, default: float = 0.0) -> float:
    """Safely coerce loose JSON values into floats."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_metadata_cache() -> dict[str, Any]:
    """Load ticker metadata cache."""
    return load_json_file(TICKER_METADATA_CACHE_FILE) or {"tickers": {}}


def save_metadata_cache(cache: dict[str, Any]) -> None:
    """Persist ticker metadata cache."""
    ensure_dirs()
    TICKER_METADATA_CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def cache_entry_fresh(entry: dict[str, Any]) -> bool:
    """Return whether cached metadata is still fresh enough for risk labels."""
    fetched = pd.to_datetime(entry.get("fetchedAt"), errors="coerce")
    if pd.isna(fetched):
        return False
    age = local_now() - fetched.to_pydatetime().astimezone()
    return age <= timedelta(days=METADATA_CACHE_DAYS)


def fetch_ticker_metadata(ticker: str, cache: dict[str, Any]) -> dict[str, Any]:
    """Fetch sector/industry metadata with cache fallback."""
    ticker = ticker.upper()
    entries = cache.setdefault("tickers", {})
    cached = entries.get(ticker)
    if isinstance(cached, dict) and cache_entry_fresh(cached):
        return cached

    metadata = {
        "ticker": ticker,
        "sector": "Unknown",
        "industry": "Unknown",
        "quoteType": "Unknown",
        "fetchedAt": local_now().isoformat(),
        "source": "fallback",
    }
    try:
        info = yf.Ticker(ticker).get_info()
        metadata.update(
            {
                "sector": info.get("sector") or "Unknown",
                "industry": info.get("industry") or "Unknown",
                "quoteType": info.get("quoteType") or "Unknown",
                "source": "yfinance",
            }
        )
    except Exception as exc:  # noqa: BLE001
        metadata["error"] = f"{type(exc).__name__}: {exc}"
    entries[ticker] = metadata
    return metadata


def load_execution_queue() -> dict[str, Any]:
    """Load current execution queue."""
    return load_json_file(EXECUTION_QUEUE_FILE) or {"items": []}


def load_paper_ledger() -> dict[str, Any]:
    """Load paper execution ledger."""
    return load_json_file(PAPER_EXECUTION_LEDGER_FILE) or {"items": []}


def active_paper_tickets(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Return currently open paper-staged tickets."""
    return [
        item for item in ledger.get("items", [])
        if item.get("status") == "paper-staged"
        and (item.get("outcome") or {}).get("status") == "open"
    ]


def candidate_rows(queue: dict[str, Any]) -> list[dict[str, Any]]:
    """Return execution queue rows as current risk candidates."""
    return [item for item in queue.get("items", []) if item.get("ticker")]


def ticker_universe(queue: dict[str, Any], ledger: dict[str, Any]) -> list[str]:
    """Collect tickers that matter to current risk view."""
    tickers = {str(item.get("ticker", "")).upper() for item in candidate_rows(queue)}
    tickers.update(str(item.get("ticker", "")).upper() for item in active_paper_tickets(ledger))
    return sorted(ticker for ticker in tickers if ticker)


def group_sum(items: list[dict[str, Any]], key: str, value: str) -> dict[str, float]:
    """Sum numeric values by a dictionary key."""
    grouped: dict[str, float] = defaultdict(float)
    for item in items:
        grouped[str(item.get(key) or "Unknown")] += number(item.get(value))
    return {name: round(amount, 4) for name, amount in sorted(grouped.items())}


def sector_exposure(rows: list[dict[str, Any]], cache: dict[str, Any]) -> dict[str, Any]:
    """Calculate candidate risk-unit exposure by sector."""
    enriched: list[dict[str, Any]] = []
    for row in rows:
        ticker = str(row.get("ticker", "")).upper()
        metadata = fetch_ticker_metadata(ticker, cache)
        enriched.append(
            {
                **row,
                "sector": metadata.get("sector", "Unknown"),
                "industry": metadata.get("industry", "Unknown"),
            }
        )
    by_sector = group_sum(enriched, "sector", "riskUnits")
    total = round(sum(by_sector.values()), 4)
    shares = {
        sector: round(amount / total, 4) if total else 0.0
        for sector, amount in by_sector.items()
    }
    largest = max(shares.items(), key=lambda item: item[1]) if shares else ("None", 0.0)
    return {
        "totalRiskUnits": total,
        "bySectorRiskUnits": by_sector,
        "sectorShares": shares,
        "largestSector": largest[0],
        "largestSectorShare": largest[1],
        "rows": [
            {
                "ticker": item.get("ticker"),
                "sector": item.get("sector"),
                "industry": item.get("industry"),
                "riskUnits": item.get("riskUnits"),
                "setupRec": item.get("setupRec"),
                "intentStatus": item.get("intentStatus"),
            }
            for item in enriched
        ],
    }


def setup_exposure(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate setup concentration from execution candidates."""
    by_setup = group_sum(rows, "setupRec", "riskUnits")
    total = round(sum(by_setup.values()), 4)
    shares = {
        setup: round(amount / total, 4) if total else 0.0
        for setup, amount in by_setup.items()
    }
    largest = max(shares.items(), key=lambda item: item[1]) if shares else ("None", 0.0)
    return {
        "bySetupRiskUnits": by_setup,
        "setupShares": shares,
        "largestSetup": largest[0],
        "largestSetupShare": largest[1],
    }


def price_history(ticker: str) -> pd.Series:
    """Fetch adjusted close history for correlation calculations."""
    try:
        history = yf.Ticker(ticker).history(period=CORRELATION_LOOKBACK, interval="1d", auto_adjust=True)
        if history.empty or "Close" not in history:
            return pd.Series(dtype=float, name=ticker)
        return pd.to_numeric(history["Close"], errors="coerce").dropna().rename(ticker)
    except Exception:  # noqa: BLE001
        return pd.Series(dtype=float, name=ticker)


def correlation_analysis(tickers: list[str]) -> dict[str, Any]:
    """Calculate simple return correlations and high-correlation pairs."""
    if len(tickers) < 2:
        return {"lookback": CORRELATION_LOOKBACK, "highCorrelationPairs": [], "clusters": []}
    series = [price_history(ticker) for ticker in tickers]
    frame = pd.concat([item for item in series if not item.empty], axis=1).dropna(how="all")
    returns = frame.pct_change().dropna(how="all")
    if returns.shape[1] < 2 or len(returns) < 10:
        return {"lookback": CORRELATION_LOOKBACK, "highCorrelationPairs": [], "clusters": [], "reason": "insufficient history"}
    corr = returns.corr()
    pairs: list[dict[str, Any]] = []
    for i, left in enumerate(corr.columns):
        for right in corr.columns[i + 1:]:
            value = corr.loc[left, right]
            if pd.notna(value) and abs(float(value)) >= HIGH_CORRELATION_THRESHOLD:
                pairs.append({"left": left, "right": right, "correlation": round(float(value), 4)})
    return {
        "lookback": CORRELATION_LOOKBACK,
        "highCorrelationThreshold": HIGH_CORRELATION_THRESHOLD,
        "highCorrelationPairs": sorted(pairs, key=lambda item: abs(item["correlation"]), reverse=True),
        "clusters": correlation_clusters(tickers, pairs),
    }


def correlation_clusters(tickers: list[str], pairs: list[dict[str, Any]]) -> list[list[str]]:
    """Build connected components from high-correlation pairs."""
    graph: dict[str, set[str]] = {ticker: set() for ticker in tickers}
    for pair in pairs:
        left = pair["left"]
        right = pair["right"]
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)

    seen: set[str] = set()
    clusters: list[list[str]] = []
    for ticker in graph:
        if ticker in seen:
            continue
        stack = [ticker]
        cluster: set[str] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            cluster.add(current)
            stack.extend(graph.get(current, set()) - seen)
        if len(cluster) > 1:
            clusters.append(sorted(cluster))
    return clusters


def index_series(symbol: str, period: str = "6mo") -> pd.Series:
    """Fetch index/ETF close history for market regime tagging."""
    try:
        history = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=True)
        if history.empty or "Close" not in history:
            return pd.Series(dtype=float, name=symbol)
        return pd.to_numeric(history["Close"], errors="coerce").dropna().rename(symbol)
    except Exception:  # noqa: BLE001
        return pd.Series(dtype=float, name=symbol)


def realized_vol(close: pd.Series, lookback: int = 20) -> float | None:
    """Annualized realized volatility from daily returns."""
    returns = close.pct_change().dropna().tail(lookback)
    if len(returns) < 5:
        return None
    return round(float(returns.std() * np.sqrt(252) * 100), 2)


def market_regime() -> dict[str, Any]:
    """Tag broad-market regime using SPY trend, realized vol, and VIX."""
    spy = index_series("SPY")
    qqq = index_series("QQQ")
    iwm = index_series("IWM")
    vix = index_series("^VIX", period="2mo")
    if spy.empty:
        return {"regime": "unknown", "riskLevel": "unknown", "reason": "SPY history unavailable"}

    close = float(spy.iloc[-1])
    sma20 = float(spy.tail(20).mean()) if len(spy) >= 20 else close
    sma50 = float(spy.tail(50).mean()) if len(spy) >= 50 else sma20
    vol20 = realized_vol(spy)
    vix_last = round(float(vix.iloc[-1]), 2) if not vix.empty else None
    qqq_return20 = round(float((qqq.iloc[-1] / qqq.iloc[-20] - 1) * 100), 2) if len(qqq) >= 20 else None
    iwm_return20 = round(float((iwm.iloc[-1] / iwm.iloc[-20] - 1) * 100), 2) if len(iwm) >= 20 else None

    if close > sma20 > sma50:
        trend = "bullish"
    elif close < sma20 < sma50:
        trend = "bearish"
    else:
        trend = "mixed"

    if (vix_last and vix_last >= 25) or (vol20 and vol20 >= 25):
        risk_level = "high"
    elif (vix_last and vix_last >= 18) or (vol20 and vol20 >= 18):
        risk_level = "elevated"
    else:
        risk_level = "normal"

    return {
        "regime": f"{trend}-{risk_level}",
        "trend": trend,
        "riskLevel": risk_level,
        "spyClose": round(close, 2),
        "spySma20": round(sma20, 2),
        "spySma50": round(sma50, 2),
        "spyRealizedVol20": vol20,
        "vix": vix_last,
        "qqqReturn20Pct": qqq_return20,
        "iwmReturn20Pct": iwm_return20,
    }


def exposure_verdict(
    sector: dict[str, Any],
    setup: dict[str, Any],
    correlation: dict[str, Any],
    regime: dict[str, Any],
) -> dict[str, Any]:
    """Produce a conservative exposure verdict."""
    warnings: list[str] = []
    if sector.get("largestSectorShare", 0) > MAX_SECTOR_SHARE:
        warnings.append(f"sector concentration high: {sector.get('largestSector')} at {sector.get('largestSectorShare'):.0%}")
    if setup.get("largestSetupShare", 0) > MAX_SETUP_SHARE:
        warnings.append(f"setup concentration high: {setup.get('largestSetup')} at {setup.get('largestSetupShare'):.0%}")
    if len(correlation.get("highCorrelationPairs", [])) >= 2:
        warnings.append(f"{len(correlation.get('highCorrelationPairs', []))} high-correlation pairs in candidate slate")
    if regime.get("riskLevel") == "high":
        warnings.append(f"market regime high risk: {regime.get('regime')}")

    return {
        "level": "review" if warnings else "clear",
        "warnings": warnings,
        "message": " ; ".join(warnings) if warnings else "No portfolio-level exposure warnings.",
    }


def build_exposure_analytics() -> dict[str, Any]:
    """Build full portfolio/context analytics package."""
    queue = load_execution_queue()
    ledger = load_paper_ledger()
    rows = candidate_rows(queue)
    cache = load_metadata_cache()
    tickers = ticker_universe(queue, ledger)
    sector = sector_exposure(rows, cache)
    save_metadata_cache(cache)
    setup = setup_exposure(rows)
    corr = correlation_analysis(tickers)
    regime = market_regime()
    verdict = exposure_verdict(sector, setup, corr, regime)
    return {
        "generatedAt": local_now().isoformat(),
        "sourceExecutionQueueUpdatedAt": queue.get("updatedAt"),
        "tickerCount": len(tickers),
        "tickers": tickers,
        "sectorExposure": sector,
        "setupExposure": setup,
        "correlation": corr,
        "marketRegime": regime,
        "verdict": verdict,
    }


def exposure_text(report: dict[str, Any]) -> str:
    """Render exposure analytics for operator review."""
    sector = report.get("sectorExposure") or {}
    setup = report.get("setupExposure") or {}
    corr = report.get("correlation") or {}
    regime = report.get("marketRegime") or {}
    verdict = report.get("verdict") or {}
    lines = [
        "Inferno Exposure Analytics",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Tickers: {', '.join(report.get('tickers', [])) or 'none'}",
        f"Verdict: {verdict.get('level')} - {verdict.get('message')}",
        "",
        "Market regime:",
        f"- regime: {regime.get('regime')}",
        f"- SPY: {regime.get('spyClose')} | SMA20 {regime.get('spySma20')} | SMA50 {regime.get('spySma50')}",
        f"- realized vol 20d: {regime.get('spyRealizedVol20')} | VIX {regime.get('vix')}",
        f"- QQQ 20d: {regime.get('qqqReturn20Pct')}% | IWM 20d: {regime.get('iwmReturn20Pct')}%",
        "",
        "Sector exposure:",
    ]
    for sector_name, amount in (sector.get("bySectorRiskUnits") or {}).items():
        share = (sector.get("sectorShares") or {}).get(sector_name, 0)
        lines.append(f"- {sector_name}: {amount} risk units ({share:.0%})")

    lines.append("")
    lines.append("Setup exposure:")
    for setup_name, amount in (setup.get("bySetupRiskUnits") or {}).items():
        share = (setup.get("setupShares") or {}).get(setup_name, 0)
        lines.append(f"- {setup_name}: {amount} risk units ({share:.0%})")

    lines.append("")
    lines.append("High-correlation pairs:")
    pairs = corr.get("highCorrelationPairs") or []
    if not pairs:
        lines.append("- none")
    for pair in pairs[:10]:
        lines.append(f"- {pair.get('left')} / {pair.get('right')}: {pair.get('correlation')}")

    lines.append("")
    lines.append("Clusters:")
    clusters = corr.get("clusters") or []
    if not clusters:
        lines.append("- none")
    for cluster in clusters:
        lines.append(f"- {', '.join(cluster)}")
    return "\n".join(lines).rstrip() + "\n"


def save_exposure_analytics(report: dict[str, Any]) -> None:
    """Persist JSON and text exposure reports."""
    ensure_dirs()
    EXPOSURE_ANALYTICS_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    EXPOSURE_ANALYTICS_TEXT_FILE.write_text(exposure_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build portfolio exposure and market-regime analytics.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and EXPOSURE_ANALYTICS_TEXT_FILE.exists():
        print(EXPOSURE_ANALYTICS_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = build_exposure_analytics()
    save_exposure_analytics(report)
    print(exposure_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
