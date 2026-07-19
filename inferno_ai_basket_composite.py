#!/usr/bin/env python3
"""AI / data-center basket — composite relative-strength + action tag (research-only).

Fuses the two momentum views into one decision surface per name:
  - TREND (from batch quotes): price vs 50 & 200-day averages, distance from
    52-week high  -> where the name sits structurally.
  - TRAILING MOMENTUM (from quote-change): 3M/6M blended return -> whether it's
    accelerating.

Produces a single 0-100 composite relative-strength score and one action tag:
  LEADER  — above both averages AND top-tier composite (strength + trend)
  HOLD    — above the 200-day, mid-pack (constructive, not leading)
  REDUCE  — above 200-day but below the 50-day, or fading (rolling over)
  AVOID   — below the 200-day (long-term trend broken)

Inputs (both produced by the weekly task):
  --quotes    data/ai_basket_quotes_latest.json   (batch-quote list)
  --momentum  data/ai_basket_momentum.json         (inferno_ai_basket_momentum output)

Boundary: research-only, decision-support. Assigns tags; never trades. The tags are
mechanical trend/strength labels, not a recommendation to buy or sell any security.
Not financial advice.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from inferno_ai_basket_config import BASKET as CATS
from inferno_ai_basket_config import (
    SYMBOLS, data_contract_trusted, load_data_contract, normalize_symbol,
)
from inferno_io import atomic_write_json, atomic_write_text

ROOT = Path(__file__).resolve().parent
OUT_JSON = ROOT / "data" / "ai_basket_composite.json"
OUT_TXT = ROOT / "reports" / "ai_basket_composite_latest.txt"


def _pctile_map(values: dict[str, float], higher_is_better: bool = True) -> dict[str, float]:
    """Map each key to a 0-100 percentile among the values."""
    # best item first, so index 0 earns the top (~100) percentile
    items = sorted(values.items(), key=lambda kv: kv[1], reverse=higher_is_better)
    n = len(items)
    out = {}
    for i, (k, _) in enumerate(items):
        out[k] = 100.0 * (n - 1 - i) / (n - 1) if n > 1 else 100.0
    return out  # rank position -> percentile (best gets ~100)


def _expected_symbols(expected_universe: list[str] | None = None) -> list[str]:
    return list(dict.fromkeys(
        normalize_symbol(symbol)
        for symbol in (expected_universe if expected_universe is not None else SYMBOLS)
        if normalize_symbol(symbol)
    ))


def build(
    quotes: list[dict], momentum: dict[str, Any], *, expected_universe: list[str] | None = None,
    data_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    expected = _expected_symbols(expected_universe)
    expected_set = set(expected)
    raw_momentum = momentum.get("ranking") or []
    mom = {
        normalize_symbol(row.get("symbol")): row
        for row in raw_momentum
        if isinstance(row, dict) and normalize_symbol(row.get("symbol")) in expected_set
    }
    trend = {}
    dist = {}
    blend = {}
    base = {}
    seen: set[str] = set()
    input_symbols: list[str] = []
    for q in quotes:
        if not isinstance(q, dict):
            continue
        sym = normalize_symbol(q.get("symbol"))
        if sym:
            input_symbols.append(sym)
        if sym not in expected_set or sym in seen:
            continue
        seen.add(sym)
        p, a50, a200, hi = q.get("price"), q.get("priceAvg50"), q.get("priceAvg200"), q.get("yearHigh")
        if None in (p, a50, a200):
            continue
        above200 = p > a200
        above50 = p > a50
        cross = a50 > a200
        tscore = int(above200) + int(above50) + int(cross)
        offHigh = (p / hi - 1) * 100 if hi else -100.0
        m = mom.get(sym, {})
        blended = m.get("blended")
        base[sym] = {
            "cat": CATS.get(sym, ""), "price": p, "above200": above200,
            "above50": above50, "trendScore": tscore, "offHigh": round(offHigh, 1),
            "blended": blended, "accelerating": bool(m.get("accelerating")),
            "fading": bool(m.get("fading")),
        }
        trend[sym] = tscore
        dist[sym] = offHigh            # higher (closer to 0) is better
        if blended is not None:
            blend[sym] = blended

    dist_pct = _pctile_map(dist, higher_is_better=True)
    blend_pct = _pctile_map(blend, higher_is_better=True) if blend else {}

    rows = []
    for sym, b in base.items():
        dp = dist_pct.get(sym, 50.0)
        bp = blend_pct.get(sym, 50.0)
        tp = b["trendScore"] / 3.0 * 100.0
        composite = round(0.40 * bp + 0.35 * dp + 0.25 * tp, 1)
        b["composite"] = composite
        rows.append((sym, b))
    rows.sort(key=lambda kv: -kv[1]["composite"])

    n = len(rows)
    ranked = []
    for i, (sym, b) in enumerate(rows):
        top_tier = i < max(1, n // 3)
        if not b["above200"]:
            tag = "AVOID"
        elif not b["above50"] or b["fading"]:
            tag = "REDUCE"
        elif top_tier:
            tag = "LEADER"
        else:
            tag = "HOLD"
        b["rank"] = i + 1
        b["tag"] = tag
        b["symbol"] = sym
        ranked.append(b)

    duplicate_symbols = sorted(
        symbol for symbol in set(input_symbols)
        if symbol in expected_set and input_symbols.count(symbol) > 1
    )
    missing_quote_symbols = sorted(expected_set - set(base))
    missing_momentum_symbols = sorted(expected_set - set(mom))
    momentum_trusted = momentum.get("signalsTrusted") is not False
    contract = load_data_contract() if data_contract is None else data_contract
    contract_trusted = data_contract_trusted(contract)
    signals_trusted = (
        bool(expected)
        and not missing_quote_symbols
        and not missing_momentum_symbols
        and not duplicate_symbols
        and momentum_trusted
        and contract_trusted
    )
    public_ranking = ranked if signals_trusted else []
    return {
        "stage": "ai-basket-composite-research-only",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(),
        "verdict": "trusted" if signals_trusted else "fail-closed",
        "signalsTrusted": signals_trusted,
        "expectedUniverse": expected,
        "expectedCount": len(expected),
        "coverageCount": len(base),
        "missingQuoteSymbols": missing_quote_symbols,
        "missingMomentumSymbols": missing_momentum_symbols,
        "extraSymbolsIgnored": sorted(set(input_symbols) - expected_set),
        "duplicateSymbols": duplicate_symbols,
        "momentumTrusted": momentum_trusted,
        "dataContractTrusted": contract_trusted,
        "dataContractVerdict": contract.get("verdict") if isinstance(contract, dict) else None,
        "count": len(public_ranking),
        "ranking": public_ranking,
        "leaders": [r["symbol"] for r in public_ranking if r["tag"] == "LEADER"],
        "reduce": [r["symbol"] for r in public_ranking if r["tag"] == "REDUCE"],
        "avoid": [r["symbol"] for r in public_ranking if r["tag"] == "AVOID"],
    }


def text(p: dict[str, Any]) -> str:
    L = ["AI / data-center basket — composite relative strength + action tag",
         f"Generated: {p['generatedAt']}",
         f"Verdict: {p.get('verdict')} | signals trusted: {p.get('signalsTrusted')}",
         f"Coverage: {p.get('coverageCount', 0)}/{p.get('expectedCount', 0)} | "
         f"input contract trusted: {p.get('dataContractTrusted')}", ""]
    if not p.get("signalsTrusted"):
        L.append("No action labels: composite inputs failed closed.")
        return "\n".join(L)
    L.append(f"{'#':>2} {'sym':<5}{'cat':<15}{'RS':>5}{'offHigh':>8}{'3/6mo':>7}{'trend':>6}  TAG")
    for r in p["ranking"]:
        bl = f"{r['blended']:+.0f}%" if r.get("blended") is not None else "  NA"
        fl = ""
        if r["accelerating"]:
            fl = " ▲"
        elif r["fading"]:
            fl = " ▼"
        L.append(f"{r['rank']:>2} {r['symbol']:<5}{r['cat']:<15}{r['composite']:>5.0f}"
                 f"{r['offHigh']:>7.0f}%{bl:>7}{r['trendScore']:>5}/3  {r['tag']}{fl}")
    L.append("")
    L.append("RS = 0-100 composite (0.4 trailing-return + 0.35 distance-from-high + "
             "0.25 trend). ▲ accelerating, ▼ fading.")
    L.append("LEADER=strong+uptrend · HOLD=above 200d, mid · REDUCE=below 50d or "
             "fading · AVOID=below 200d. Mechanical labels, not advice.")
    return "\n".join(L)


def save(p: dict[str, Any]) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUT_JSON, p)
    atomic_write_text(OUT_TXT, text(p) + "\n")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quotes", required=True)
    ap.add_argument("--momentum", required=True)
    args = ap.parse_args(argv)
    quotes = json.loads(Path(args.quotes).read_text(encoding="utf-8"))
    if isinstance(quotes, dict):
        quotes = quotes.get("data") or quotes.get("quotes") or []
    momentum = json.loads(Path(args.momentum).read_text(encoding="utf-8"))
    p = build(quotes, momentum)
    print(text(p))
    save(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
