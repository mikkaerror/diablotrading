#!/usr/bin/env python3
"""AI / data-center basket — trailing-return momentum ranking (research-only).

Complements the live tracker's "distance from 52-week high" measure with a
*trailing-return* view (3- and 6-month price change). Distance-from-high favors
names already at highs; trailing return also surfaces names *accelerating toward*
highs. Together they are a stronger relative-strength read.

Input: a JSON list of the market-data MCP `quote-change` records, one per name,
each shaped like:
    {"symbol":"NVDA","1D":..,"5D":..,"1M":5.26,"3M":11.84,"6M":14.12,"1Y":28.56,...}
(The weekly scheduled task fetches these — quote-change is single-symbol, so it
loops the basket — and writes them to one file for this module.)

Score: blended medium-term momentum = mean(3M, 6M) — the classic 3-12 month
momentum zone, skipping the 1-month window that tends to mean-revert. Also flags
whether a name is accelerating (recent 3-month pace faster than its 6-month pace)
or fading (positive over 6M but negative over the last month).

Boundary: research-only, decision-support. Ranks names; places no trades. Not
financial advice.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from inferno_ai_basket_config import BASKET as CATS
from inferno_ai_basket_config import SYMBOLS
from inferno_io import atomic_write_json, atomic_write_text

ROOT = Path(__file__).resolve().parent
OUT_JSON = ROOT / "data" / "ai_basket_momentum.json"
OUT_TXT = ROOT / "reports" / "ai_basket_momentum_latest.txt"

def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def rank(records: list[dict], *, expected_universe: list[str] | None = None) -> list[dict]:
    rows = []
    expected = {
        str(symbol or "").strip().upper()
        for symbol in (expected_universe if expected_universe is not None else SYMBOLS)
        if str(symbol or "").strip()
    }
    seen: set[str] = set()
    for r in records:
        sym = str(r.get("symbol") or "").strip().upper()
        m1, m3, m6 = _num(r.get("1M")), _num(r.get("3M")), _num(r.get("6M"))
        if sym not in expected or sym in seen or m3 is None or m6 is None:
            continue
        seen.add(sym)
        blended = (m3 + m6) / 2.0
        pace3 = m3 / 3.0                     # avg monthly pace over 3 months
        pace6 = m6 / 6.0                     # avg monthly pace over 6 months
        accelerating = pace3 > pace6
        fading = (m6 > 0 and m1 is not None and m1 < 0)
        rows.append({
            "symbol": sym, "cat": CATS.get(sym, ""),
            "m1": m1, "m3": m3, "m6": m6,
            "blended": round(blended, 2),
            "accelerating": accelerating, "fading": fading,
        })
    rows.sort(key=lambda d: -d["blended"])
    for i, d in enumerate(rows, 1):
        d["rank"] = i
    return rows


def build(records: list[dict], *, expected_universe: list[str] | None = None) -> dict[str, Any]:
    expected = [
        str(symbol or "").strip().upper()
        for symbol in (expected_universe if expected_universe is not None else SYMBOLS)
        if str(symbol or "").strip()
    ]
    expected = list(dict.fromkeys(expected))
    rows = rank(records, expected_universe=expected)
    ranked_symbols = {row["symbol"] for row in rows}
    input_symbols = [
        str(row.get("symbol") or "").strip().upper()
        for row in records
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    ]
    duplicate_symbols = sorted(
        symbol for symbol in set(input_symbols) if symbol in set(expected) and input_symbols.count(symbol) > 1
    )
    missing_symbols = sorted(set(expected) - ranked_symbols)
    extra_symbols = sorted(set(input_symbols) - set(expected))
    signals_trusted = bool(expected) and not missing_symbols and not duplicate_symbols
    return {
        "stage": "ai-basket-momentum-research-only",
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
        "coverageCount": len(ranked_symbols),
        "missingSymbols": missing_symbols,
        "extraSymbolsIgnored": extra_symbols,
        "duplicateSymbols": duplicate_symbols,
        "count": len(rows),
        "ranking": rows,
        "leaders": [d["symbol"] for d in rows[:5]] if signals_trusted else [],
        "laggards": [d["symbol"] for d in rows[-5:]] if signals_trusted else [],
        "accelerating": [d["symbol"] for d in rows if d["accelerating"]] if signals_trusted else [],
        "fading": [d["symbol"] for d in rows if d["fading"]] if signals_trusted else [],
    }


def text(p: dict[str, Any]) -> str:
    L = ["AI / data-center basket — trailing-return momentum (3M/6M blend)",
         f"Generated: {p['generatedAt']}",
         f"Verdict: {p.get('verdict')} | signals trusted: {p.get('signalsTrusted')}",
         f"Coverage: {p.get('coverageCount', 0)}/{p.get('expectedCount', 0)}", ""]
    L.append(f"{'#':>2} {'sym':<5}{'cat':<15}{'1M':>7}{'3M':>7}{'6M':>7}{'blend':>7}  flags")
    for d in p["ranking"]:
        fl = []
        if d["accelerating"]:
            fl.append("ACCEL")
        if d["fading"]:
            fl.append("fading")
        m1 = f"{d['m1']:+.0f}%" if d["m1"] is not None else "  NA"
        L.append(f"{d['rank']:>2} {d['symbol']:<5}{d['cat']:<15}{m1:>7}"
                 f"{d['m3']:>+6.0f}%{d['m6']:>+6.0f}%{d['blended']:>+6.0f}%  {','.join(fl)}")
    L.append("")
    L.append("blend = mean(3M, 6M). ACCEL = 3-month pace faster than 6-month "
             "(momentum building). fading = up over 6M but down over the last month.")
    L.append("Pair with the live tracker's distance-from-high view. Research-only; "
             "not a trade instruction.")
    return "\n".join(L)


def save(p: dict[str, Any]) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUT_JSON, p)
    atomic_write_text(OUT_TXT, text(p) + "\n")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--changes", required=True,
                    help="path to JSON list of quote-change records")
    args = ap.parse_args(argv)
    recs = json.loads(Path(args.changes).read_text(encoding="utf-8"))
    if isinstance(recs, dict):
        recs = recs.get("data") or recs.get("records") or []
    p = build(recs)
    print(text(p))
    save(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
