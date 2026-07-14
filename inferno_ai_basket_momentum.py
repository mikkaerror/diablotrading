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
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
OUT_JSON = ROOT / "data" / "ai_basket_momentum.json"
OUT_TXT = ROOT / "reports" / "ai_basket_momentum_latest.txt"

CATS = {
    "NVDA": "Compute", "AVGO": "Compute", "AMD": "Compute", "TXN": "Compute",
    "ASML": "Compute", "QCOM": "Compute", "ARM": "Compute", "MRVL": "Networking Si",
    "DELL": "Server OEM", "HPE": "Server OEM", "SMCI": "Server OEM",
    "VRT": "Power/Cooling", "ETN": "Power/Cooling", "MOD": "Power/Cooling",
    "GLW": "Optical", "LITE": "Optical", "AAOI": "Optical", "ANET": "Networking",
    "VNET": "DC Operator", "STX": "Storage", "WDC": "Storage", "AEHR": "Semi Test",
    "MSFT": "Hyperscaler", "GOOG": "Hyperscaler", "ORCL": "Cloud Rails",
    "FTNT": "Security", "OTEX": "Cloud Rails",
    "RBC": "Bearings", "RRX": "Bearings", "TKR": "Bearings",
}


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def rank(records: list[dict]) -> list[dict]:
    rows = []
    for r in records:
        sym = r.get("symbol")
        m1, m3, m6 = _num(r.get("1M")), _num(r.get("3M")), _num(r.get("6M"))
        if sym is None or m3 is None or m6 is None:
            continue
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


def build(records: list[dict]) -> dict[str, Any]:
    rows = rank(records)
    return {
        "stage": "ai-basket-momentum-research-only",
        "researchOnly": True,
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(),
        "count": len(rows),
        "ranking": rows,
        "leaders": [d["symbol"] for d in rows[:5]],
        "laggards": [d["symbol"] for d in rows[-5:]],
        "accelerating": [d["symbol"] for d in rows if d["accelerating"]],
        "fading": [d["symbol"] for d in rows if d["fading"]],
    }


def text(p: dict[str, Any]) -> str:
    L = ["AI / data-center basket — trailing-return momentum (3M/6M blend)",
         f"Generated: {p['generatedAt']}", ""]
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
    OUT_JSON.write_text(json.dumps(p, indent=2), encoding="utf-8")
    OUT_TXT.write_text(text(p) + "\n", encoding="utf-8")


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
