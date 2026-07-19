#!/usr/bin/env python3
"""AI / data-center basket vs its sector benchmark (SMH) — research-only.

Answers weekly: which held names are actually BEATING the semiconductor ETF, and
is the basket as a whole earning its single-name concentration versus just owning
SMH? (See docs/BASKET_VS_SMH_2026-07-13.md for the finding this automates.)

Relative strength vs the benchmark = blend of (% above 200-day) and (distance from
52-week high), each name minus the benchmark's. Positive = stronger trend / closer
to high than the sector. Trend-strength proxy, not literal trailing return.

Input: a batch-quote JSON list that INCLUDES the benchmark ticker (default SMH).
The weekly task already fetches the basket; just add SMH to its symbol list.

Boundary: research-only, decision-support. Ranks names vs a benchmark; places no
trades. Not financial advice.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from inferno_ai_basket_config import BASKET as CATS
from inferno_ai_basket_config import (
    SYMBOLS, data_contract_trusted, factor_bucket, load_data_contract, normalize_symbol,
)
from inferno_io import atomic_write_json, atomic_write_text

ROOT = Path(__file__).resolve().parent
OUT_JSON = ROOT / "data" / "ai_basket_vs_benchmark.json"
OUT_TXT = ROOT / "reports" / "ai_basket_vs_benchmark_latest.txt"

def _metrics(q: dict) -> Optional[tuple[float, float]]:
    p, a200, hi = q.get("price"), q.get("priceAvg200"), q.get("yearHigh")
    if None in (p, a200, hi) or not a200 or not hi:
        return None
    return (p / a200 - 1) * 100, (p / hi - 1) * 100  # %above200, offHigh


def _expected_symbols(expected_universe: list[str] | None = None) -> list[str]:
    return list(dict.fromkeys(
        normalize_symbol(symbol)
        for symbol in (expected_universe if expected_universe is not None else SYMBOLS)
        if normalize_symbol(symbol)
    ))


def build(
    quotes: list[dict], benchmark: str = "SMH", *, expected_universe: list[str] | None = None,
    data_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    expected = _expected_symbols(expected_universe)
    benchmark = normalize_symbol(benchmark)
    expected_set = set(expected)
    allowed = expected_set | {benchmark}
    by: dict[str, dict] = {}
    input_symbols: list[str] = []
    for quote in quotes:
        if not isinstance(quote, dict):
            continue
        symbol = normalize_symbol(quote.get("symbol"))
        if symbol:
            input_symbols.append(symbol)
        if symbol not in allowed or symbol in by:
            continue
        by[symbol] = {**quote, "symbol": symbol}
    duplicate_symbols = sorted(
        symbol for symbol in set(input_symbols)
        if symbol in allowed and input_symbols.count(symbol) > 1
    )
    missing_symbols = sorted(
        symbol for symbol in expected_set
        if _metrics(by.get(symbol) or {}) is None
    )
    extras = sorted(set(input_symbols) - allowed)
    contract = load_data_contract() if data_contract is None else data_contract
    contract_trusted = data_contract_trusted(contract)
    bq = by.get(benchmark)
    bm = _metrics(bq) if bq else None
    common = {
        "stage": "ai-basket-vs-benchmark-research-only",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(),
        "benchmark": benchmark,
        "expectedUniverse": expected,
        "expectedCount": len(expected),
        "coverageCount": len(expected) - len(missing_symbols),
        "missingSymbols": missing_symbols,
        "extraSymbolsIgnored": extras,
        "duplicateSymbols": duplicate_symbols,
        "dataContractTrusted": contract_trusted,
        "dataContractVerdict": contract.get("verdict") if isinstance(contract, dict) else None,
    }
    if bm is None:
        return {
            **common, "verdict": "fail-closed", "signalsTrusted": False,
            "error": f"benchmark {benchmark} missing/incomplete in quotes", "ranking": [],
        }
    if not expected or missing_symbols or duplicate_symbols or not contract_trusted:
        return {
            **common, "verdict": "fail-closed", "signalsTrusted": False,
            "error": "declared basket inputs incomplete or duplicated", "ranking": [],
        }
    b200, boff = bm
    rows = []
    for sym, q in by.items():
        if sym == benchmark:
            continue
        mm = _metrics(q)
        if mm is None:
            continue
        v200, off = mm
        rel = (v200 - b200) * 0.5 + (off - boff) * 0.5
        rows.append({"symbol": sym, "cat": CATS.get(sym, ""),
                     "aboveB200": round(v200, 1), "offHigh": round(off, 1),
                     "relStrength": round(rel, 1), "beatsSector": rel > 0})
    rows.sort(key=lambda d: -d["relStrength"])
    n = len(rows)
    beats = sum(1 for r in rows if r["beatsSector"])
    avg200 = st.mean([r["aboveB200"] for r in rows]) if rows else 0.0
    avgoff = st.mean([r["offHigh"] for r in rows]) if rows else 0.0

    # per-category rollup (strength by pocket of the theme)
    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        by_cat.setdefault(r["cat"] or "—", []).append(r)
    cat_rows = []
    for cat, items in by_cat.items():
        k = len(items)
        cat_rows.append({
            "category": cat,
            "count": k,
            "pctOfBasket": round(100 * k / n) if n else 0,
            "avgAbove200": round(st.mean([i["aboveB200"] for i in items]), 1),
            "namesInUptrend": sum(1 for i in items if i["aboveB200"] > 0),
            "avgRelStrength": round(st.mean([i["relStrength"] for i in items]), 1),
        })
    cat_rows.sort(key=lambda d: -d["avgRelStrength"])

    # coarse factor-bucket concentration (single-factor risk read)
    buckets: dict[str, int] = {}
    for r in rows:
        buckets[factor_bucket(r["cat"])] = buckets.get(factor_bucket(r["cat"]), 0) + 1
    concentration = {b: {"count": c, "pct": round(100 * c / n) if n else 0}
                     for b, c in buckets.items()}

    return {
        **common,
        "verdict": "trusted",
        "signalsTrusted": True,
        "benchmarkAbove200": round(b200, 1),
        "benchmarkOffHigh": round(boff, 1),
        "count": n,
        "namesBeatingSector": beats,
        "basketAvgAbove200": round(avg200, 1),
        "basketAvgOffHigh": round(avgoff, 1),
        "basketBeatsBenchmark": (avg200 > b200 and avgoff > boff),
        "leaders": [r["symbol"] for r in rows if r["beatsSector"]][:8],
        "laggards": [r["symbol"] for r in rows if not r["beatsSector"]][-8:],
        "byCategory": cat_rows,
        "concentration": concentration,
        "ranking": rows,
    }


def text(p: dict[str, Any]) -> str:
    if p.get("error"):
        return f"basket-vs-benchmark: {p['error']}"
    L = [f"AI / data-center basket vs {p['benchmark']} (sector benchmark) — research-only",
         f"Generated: {p['generatedAt']}",
         f"{p['benchmark']}: +{p['benchmarkAbove200']:.0f}% above 200d | "
         f"{p['benchmarkOffHigh']:.0f}% off 52w high", ""]
    L.append(f"{'sym':<5}{'cat':<14}{'vs200d':>7}{'offHigh':>8}{'RS':>7}  vs sector")
    for r in p["ranking"]:
        L.append(f"{r['symbol']:<5}{r['cat']:<14}{r['aboveB200']:>6.0f}%"
                 f"{r['offHigh']:>7.0f}%{r['relStrength']:>+6.0f}  "
                 f"{'BEATS' if r['beatsSector'] else 'lags'}")
    L.append("")
    L.append(f"{p['namesBeatingSector']}/{p['count']} names beat {p['benchmark']}. "
             f"Equal-weight basket: +{p['basketAvgAbove200']:.0f}% above 200d / "
             f"{p['basketAvgOffHigh']:.0f}% off high vs {p['benchmark']} "
             f"+{p['benchmarkAbove200']:.0f}% / {p['benchmarkOffHigh']:.0f}%.")
    L.append("Basket (equal-weight) beats the ETF: "
             + ("YES" if p["basketBeatsBenchmark"] else "NO — the selection only adds "
                "value if you hold the leaders and cut the laggards."))
    conc = p.get("concentration") or {}
    if conc:
        parts = [f"{v['pct']}% {b}" for b, v in sorted(
            conc.items(), key=lambda kv: -kv[1]["count"])]
        L.append("")
        L.append("Concentration by name count: " + " · ".join(parts) + ".")
    if p.get("byCategory"):
        L.append(f"{'category':<15}{'n':>3}{'%bskt':>7}{'vs200d':>8}{'up':>6}{'RS':>7}")
        for c in p["byCategory"]:
            L.append(f"{c['category']:<15}{c['count']:>3}{c['pctOfBasket']:>6}%"
                     f"{c['avgAbove200']:>7.0f}%{c['namesInUptrend']:>3}/{c['count']}"
                     f"{c['avgRelStrength']:>+7.0f}")
    L.append("Trend-strength proxy, one-day snapshot. Research-only; not advice.")
    return "\n".join(L)


def save(p: dict[str, Any]) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUT_JSON, p)
    atomic_write_text(OUT_TXT, text(p) + "\n")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quotes", required=True, help="batch-quote JSON incl. benchmark")
    ap.add_argument("--benchmark", default="SMH")
    args = ap.parse_args(argv)
    quotes = json.loads(Path(args.quotes).read_text(encoding="utf-8"))
    if isinstance(quotes, dict):
        quotes = quotes.get("data") or quotes.get("quotes") or []
    p = build(quotes, args.benchmark)
    print(text(p))
    if not p.get("error"):
        save(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
