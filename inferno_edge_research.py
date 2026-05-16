from __future__ import annotations

"""Online-world shovel edge research for the Inferno desk.

The earnings tracker is good at heat. This module asks a different question:
which companies are selling the tools, rails, chips, security, ads, and data
systems that modern online entertainment and internet life depend on? It then
separates trade candidates from long-term accumulation candidates so the desk
does not confuse a durable shovel thesis with a short-term catalyst.
"""

import argparse
import json
from datetime import timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from inferno_config import local_now
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
EDGE_RESEARCH_FILE = DATA_DIR / "inferno_edge_research.json"
EDGE_RESEARCH_TEXT_FILE = REPORTS_DIR / "edge_research_latest.txt"
EDGE_METADATA_CACHE_FILE = DATA_DIR / "inferno_edge_metadata_cache.json"
METADATA_CACHE_DAYS = 14

TECH_SHOVEL_CATEGORIES = {
    "AI/Compute Picks": {
        "tickers": {"NVDA", "AMD", "AVGO", "MRVL", "ARM", "SMCI", "DELL", "HPE"},
        "thesis": "compute engines, accelerators, networking silicon, and servers powering the online world",
        "baseScore": 96,
    },
    "Semiconductor Supply Chain": {
        "tickers": {"ASML", "TSM", "AMAT", "LRCX", "KLAC", "MU", "ON", "ADI", "NXPI", "TXN", "QCOM"},
        "thesis": "fabrication, memory, analog, and equipment rails required before software can exist",
        "baseScore": 92,
    },
    "Cloud/Data Rails": {
        "tickers": {"MSFT", "AMZN", "GOOGL", "GOOG", "ORCL", "SNOW", "MDB", "DDOG", "NET", "ESTC", "PLTR"},
        "thesis": "cloud, databases, observability, and data platforms that host the digital economy",
        "baseScore": 90,
    },
    "Cybersecurity Toll Booths": {
        "tickers": {"CHKP", "CRWD", "PANW", "RDWR", "ZS", "FTNT", "S", "OKTA", "CYBR", "TENB"},
        "thesis": "security gates every online business must keep paying for",
        "baseScore": 88,
    },
    "Attention/Ad Rails": {
        "tickers": {"META", "GOOGL", "GOOG", "TTD", "APP", "SNAP", "PINS", "ROKU"},
        "thesis": "auction, ad targeting, and attention monetization rails for online entertainment",
        "baseScore": 82,
    },
    "Creator/Game Platforms": {
        "tickers": {"RBLX", "U", "TTWO", "EA", "NTES", "SPOT", "NFLX", "DIS"},
        "thesis": "platforms and content systems where online entertainment demand shows up directly",
        "baseScore": 74,
    },
    "Commerce/Payment Rails": {
        "tickers": {"SHOP", "MELI", "PYPL", "SQ", "ADYEY", "V", "MA"},
        "thesis": "payments, storefronts, and transaction rails that monetize digital activity",
        "baseScore": 78,
    },
}

INDUSTRY_CATEGORY_KEYWORDS = [
    ("semiconductor", "Semiconductor Supply Chain"),
    ("software", "Cloud/Data Rails"),
    ("cloud", "Cloud/Data Rails"),
    ("data", "Cloud/Data Rails"),
    ("security", "Cybersecurity Toll Booths"),
    ("internet content", "Creator/Game Platforms"),
    ("entertainment", "Creator/Game Platforms"),
    ("advertising", "Attention/Ad Rails"),
    ("payment", "Commerce/Payment Rails"),
]


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    """Clamp a score into a predictable range."""
    return max(low, min(high, value))


def number(value: Any, default: float = 0.0) -> float:
    """Safely coerce spreadsheet/API values into floats."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_metadata_cache() -> dict[str, Any]:
    """Load cached fundamentals so the morning run is not needlessly chatty."""
    return load_json_file(EDGE_METADATA_CACHE_FILE) or {"tickers": {}}


def save_metadata_cache(cache: dict[str, Any]) -> None:
    """Persist yfinance metadata cache."""
    ensure_dirs()
    EDGE_METADATA_CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def cache_entry_fresh(entry: dict[str, Any]) -> bool:
    """Return whether a cached metadata record is still fresh."""
    fetched = pd.to_datetime(entry.get("fetchedAt"), errors="coerce")
    if pd.isna(fetched):
        return False
    return local_now() - fetched.to_pydatetime().astimezone() <= timedelta(days=METADATA_CACHE_DAYS)


def fetch_metadata(ticker: str, cache: dict[str, Any]) -> dict[str, Any]:
    """Fetch company metadata with cache fallback."""
    ticker = ticker.upper()
    entries = cache.setdefault("tickers", {})
    cached = entries.get(ticker)
    if isinstance(cached, dict) and cache_entry_fresh(cached):
        return cached

    metadata = {
        "ticker": ticker,
        "sector": "Unknown",
        "industry": "Unknown",
        "shortName": ticker,
        "grossMargins": None,
        "operatingMargins": None,
        "profitMargins": None,
        "revenueGrowth": None,
        "freeCashflow": None,
        "debtToEquity": None,
        "trailingPE": None,
        "forwardPE": None,
        "priceToSalesTrailing12Months": None,
        "beta": None,
        "fetchedAt": local_now().isoformat(),
        "source": "fallback",
    }
    try:
        info = yf.Ticker(ticker).get_info()
        for key in metadata:
            if key in {"ticker", "fetchedAt", "source"}:
                continue
            metadata[key] = info.get(key, metadata[key])
        metadata["source"] = "yfinance"
    except Exception as exc:  # noqa: BLE001
        metadata["error"] = f"{type(exc).__name__}: {exc}"
    entries[ticker] = metadata
    return metadata


def category_for_ticker(ticker: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """Classify a ticker into the online-world shovel taxonomy."""
    upper = ticker.upper()
    for category, config in TECH_SHOVEL_CATEGORIES.items():
        if upper in config["tickers"]:
            return {"category": category, **config}

    text = f"{metadata.get('sector', '')} {metadata.get('industry', '')}".lower()
    for keyword, category in INDUSTRY_CATEGORY_KEYWORDS:
        if keyword in text:
            config = TECH_SHOVEL_CATEGORIES[category]
            return {"category": category, **config}
    return {"category": "Unclassified", "thesis": "not clearly mapped to the online-world shovel thesis", "baseScore": 35}


def tracker_timing_score(row: dict[str, Any]) -> float:
    """Score short-term trade timing from existing tracker fields."""
    readiness = number(row.get("readiness"))
    priority = clamp(number(row.get("priority")) / 10 * 100)
    confidence = clamp(number(row.get("confidence")) / 3 * 100)
    trigger = 100.0 if row.get("signalTrigger") else 0.0
    days = number(row.get("daysUntilEarnings"), 999)
    timing_window = 100.0 if 0 <= days <= 21 else 55.0 if 22 <= days <= 45 else 25.0
    return round(
        readiness * 0.35
        + priority * 0.20
        + confidence * 0.15
        + trigger * 0.15
        + timing_window * 0.15,
        2,
    )


def market_context_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return the normalized confirmation block for a snapshot row."""
    context = row.get("marketContext")
    return context if isinstance(context, dict) else {}


def confirmation_score(row: dict[str, Any]) -> float:
    """Score whether the setup is actually being confirmed by market structure."""
    context = market_context_row(row)
    rvol = number(context.get("rvol"), 1.0)
    atr_expansion = number(context.get("atrExpansion"))
    distance_to_resistance = number(context.get("distanceToResistancePct"), 0.0)
    distance_to_support = number(context.get("distanceToSupportPct"), 0.0)
    trend = str((context.get("trend") or {}).get("label") or row.get("trend") or "Neutral")

    rvol_score = 100 if rvol >= 1.4 else 80 if rvol >= 1.1 else 55 if rvol >= 0.9 else 30
    trend_score = 100 if trend in {"Bullish", "Uptrend"} else 70 if trend == "Basing" else 50 if trend == "Neutral" else 20
    expansion_score = 100 if atr_expansion >= 1.0 else 75 if atr_expansion >= 0.3 else 45 if atr_expansion >= 0 else 25
    structure_score = 100 if distance_to_resistance >= 4 else 75 if distance_to_resistance >= 2 else 35
    accumulation_structure_score = 100 if distance_to_support <= 4 else 75 if distance_to_support <= 7 else 45

    if str(row.get("setupRec")) == "Vertical Call":
        return round(rvol_score * 0.25 + trend_score * 0.30 + expansion_score * 0.20 + structure_score * 0.25, 2)
    if str(row.get("setupRec")) == "Iron Condor":
        condor_heat = 100 if rvol <= 1.0 and atr_expansion <= 0.4 else 60 if rvol <= 1.2 else 25
        return round(condor_heat * 0.45 + accumulation_structure_score * 0.20 + trend_score * 0.15 + structure_score * 0.20, 2)
    return round(rvol_score * 0.30 + expansion_score * 0.25 + structure_score * 0.20 + accumulation_structure_score * 0.25, 2)


def quality_score(metadata: dict[str, Any]) -> float:
    """Score business quality from simple profitability and balance-sheet clues."""
    gross = clamp(number(metadata.get("grossMargins")) * 100, high=85) / 85 * 100
    operating = clamp(number(metadata.get("operatingMargins")) * 100, low=-20, high=45)
    operating = (operating + 20) / 65 * 100
    profit = clamp(number(metadata.get("profitMargins")) * 100, low=-20, high=35)
    profit = (profit + 20) / 55 * 100
    growth = clamp(number(metadata.get("revenueGrowth")) * 100, low=-20, high=50)
    growth = (growth + 20) / 70 * 100
    cash = 100.0 if number(metadata.get("freeCashflow")) > 0 else 35.0
    debt = number(metadata.get("debtToEquity"), 75)
    debt_score = clamp(100 - debt / 2, low=15, high=100)
    return round(gross * 0.22 + operating * 0.22 + profit * 0.18 + growth * 0.18 + cash * 0.12 + debt_score * 0.08, 2)


def valuation_risk_score(row: dict[str, Any], metadata: dict[str, Any]) -> float:
    """Score valuation risk with a bias against extreme multiple chasing."""
    pe = number(metadata.get("forwardPE") or metadata.get("trailingPE") or row.get("pe"), 999)
    ps = number(metadata.get("priceToSalesTrailing12Months"), 999)
    beta = number(metadata.get("beta"), 1.2)
    pe_score = 100 if pe <= 25 else 75 if pe <= 45 else 45 if pe <= 80 else 20
    ps_score = 100 if ps <= 6 else 75 if ps <= 12 else 45 if ps <= 20 else 20
    beta_score = 100 if beta <= 1.2 else 75 if beta <= 1.7 else 45 if beta <= 2.2 else 20
    value_stack = clamp(number(row.get("longTermScore")) / 10 * 100)
    return round(pe_score * 0.30 + ps_score * 0.25 + beta_score * 0.15 + value_stack * 0.30, 2)


def edge_score(row: dict[str, Any], metadata: dict[str, Any], category: dict[str, Any]) -> dict[str, Any]:
    """Calculate a combined edge score from thesis, timing, quality, and risk."""
    thesis = number(category.get("baseScore"))
    timing = tracker_timing_score(row)
    confirmation = confirmation_score(row)
    quality = quality_score(metadata)
    valuation = valuation_risk_score(row, metadata)
    score = round(thesis * 0.26 + timing * 0.24 + confirmation * 0.16 + quality * 0.20 + valuation * 0.14, 2)
    return {
        "edgeScore": score,
        "thesisScore": round(thesis, 2),
        "timingScore": timing,
        "confirmationScore": confirmation,
        "qualityScore": quality,
        "valuationRiskScore": valuation,
    }


def classify_lane(row: dict[str, Any], scores: dict[str, Any], category: dict[str, Any]) -> str:
    """Separate trade setups from long-term accumulation setups."""
    is_shovel = category.get("category") != "Unclassified"
    days = number(row.get("daysUntilEarnings"), 999)
    context = market_context_row(row)
    distance_to_support = number(context.get("distanceToSupportPct"), 999)
    if not is_shovel:
        return "Ignore For Theme"
    if (
        scores["edgeScore"] >= 72
        and scores["confirmationScore"] >= 60
        and row.get("signalTrigger")
        and number(row.get("readiness")) >= 85
        and days <= 21
    ):
        return "Catalyst Trade Candidate"
    if (
        scores["edgeScore"] >= 68
        and number(row.get("longTermScore")) >= 6.5
        and scores["qualityScore"] >= 50
        and distance_to_support <= 10
    ):
        return "Long-Term Shovel Accumulation"
    if scores["edgeScore"] >= 60:
        return "Research Watchlist"
    return "Theme Too Weak"


def thesis_line(row: dict[str, Any], metadata: dict[str, Any], category: dict[str, Any], lane: str) -> str:
    """Write a one-line thesis for the operator memo."""
    ticker = row.get("ticker")
    category_name = category.get("category")
    if lane == "Catalyst Trade Candidate":
        return f"{ticker} is a {category_name} name with live timing, but still needs strike/risk gates."
    if lane == "Long-Term Shovel Accumulation":
        return f"{ticker} maps to {category_name}; use weakness as inventory-building, not panic-chasing."
    if lane == "Research Watchlist":
        return f"{ticker} has a plausible {category_name} shovel thesis, but edge needs better timing or valuation."
    if category_name == "Unclassified":
        return f"{ticker} does not clearly fit the online-world shovel thesis."
    return f"{ticker} fits {category_name}, but current score is not strong enough."


def load_rows(rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Load snapshot rows unless rows were supplied directly by the morning pipeline."""
    if rows is not None:
        return rows
    snapshot = load_json_file(SNAPSHOT_FILE) or {}
    return snapshot.get("rows", [])


def build_edge_research(rows: list[dict[str, Any]] | None = None, limit: int = 40) -> dict[str, Any]:
    """Build the online-world shovel edge research package."""
    source_rows = load_rows(rows)
    cache = load_metadata_cache()
    candidates: list[dict[str, Any]] = []
    # Score the most relevant rows first so the report stays fast and focused.
    sorted_rows = sorted(
        source_rows,
        key=lambda item: (
            -number(item.get("readiness")),
            -number(item.get("longTermScore")),
            number(item.get("daysUntilEarnings"), 999),
        ),
    )[:limit]
    for row in sorted_rows:
        ticker = str(row.get("ticker", "")).upper()
        if not ticker:
            continue
        metadata = fetch_metadata(ticker, cache)
        category = category_for_ticker(ticker, metadata)
        scores = edge_score(row, metadata, category)
        lane = classify_lane(row, scores, category)
        candidates.append(
            {
                "ticker": ticker,
                "name": metadata.get("shortName") or ticker,
                "category": category.get("category"),
                "lane": lane,
                "edgeScore": scores["edgeScore"],
                "scores": scores,
                "readiness": row.get("readiness"),
                "longTermScore": row.get("longTermScore"),
                "daysUntilEarnings": row.get("daysUntilEarnings"),
                "setupRec": row.get("setupRec"),
                "signalTrigger": row.get("signalTrigger"),
                "marketContext": market_context_row(row),
                "sector": metadata.get("sector"),
                "industry": metadata.get("industry"),
                "thesis": thesis_line(row, metadata, category, lane),
            }
        )
    save_metadata_cache(cache)
    ranked = sorted(candidates, key=lambda item: item["edgeScore"], reverse=True)
    return {
        "generatedAt": local_now().isoformat(),
        "framework": "online-world-shovel-edge",
        "trackedRows": len(source_rows),
        "scoredRows": len(ranked),
        "topCatalystTrades": [item for item in ranked if item["lane"] == "Catalyst Trade Candidate"][:8],
        "topLongTermShovels": [item for item in ranked if item["lane"] == "Long-Term Shovel Accumulation"][:8],
        "researchWatchlist": [item for item in ranked if item["lane"] == "Research Watchlist"][:10],
        "ranked": ranked,
        "principles": [
            "prefer tool sellers over one-hit content demand",
            "separate catalyst trades from long-term accumulation",
            "do not escalate without paper evidence and authority manifest clearance",
            "punish crowded exposure even when individual tickers look strong",
        ],
    }


def edge_research_text(report: dict[str, Any]) -> str:
    """Render the edge report for the morning desk."""
    lines = [
        "Inferno Edge Research - Online-World Shovels",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Tracked rows: {report.get('trackedRows')} | scored: {report.get('scoredRows')}",
        "",
        "Principles:",
    ]
    for principle in report.get("principles", []):
        lines.append(f"- {principle}")

    def section(title: str, items: list[dict[str, Any]]) -> None:
        lines.extend(["", title + ":"])
        if not items:
            lines.append("- none")
            return
        for index, item in enumerate(items, start=1):
            lines.append(
                f"{index}. {item.get('ticker')} | {item.get('category')} | "
                f"{item.get('lane')} | edge {item.get('edgeScore')} | "
                f"timing {item.get('scores', {}).get('timingScore')} | "
                f"confirm {item.get('scores', {}).get('confirmationScore')} | "
                f"quality {item.get('scores', {}).get('qualityScore')}"
            )
            context = item.get("marketContext") or {}
            trend = (context.get("trend") or {}).get("label") or "Neutral"
            lines.append(
                f"   {item.get('thesis')} "
                f"(RVOL {context.get('rvol', 'N/A')}x | {trend} | "
                f"S {context.get('support', 'N/A')} / R {context.get('resistance', 'N/A')})"
            )

    section("Catalyst trade candidates", report.get("topCatalystTrades", []))
    section("Long-term shovel accumulation", report.get("topLongTermShovels", []))
    section("Research watchlist", report.get("researchWatchlist", []))
    return "\n".join(lines).rstrip() + "\n"


def save_edge_research(report: dict[str, Any]) -> None:
    """Persist JSON and text versions of the edge research report."""
    ensure_dirs()
    EDGE_RESEARCH_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    EDGE_RESEARCH_TEXT_FILE.write_text(edge_research_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build online-world shovel edge research.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    parser.add_argument("--limit", type=int, default=40, help="Maximum snapshot rows to score with metadata.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and EDGE_RESEARCH_TEXT_FILE.exists():
        print(EDGE_RESEARCH_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = build_edge_research(limit=args.limit)
    save_edge_research(report)
    print(edge_research_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
