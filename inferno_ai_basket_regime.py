#!/usr/bin/env python3
"""AI / data-center basket — regime read (research-only).

The top of the number stack. The engines produce many aggregate signals —
breadth above the 200- and 50-day, how many names lead, how many beat the
sector, whether the equal-weight basket beats the ETF. On their own they are a
scatter. This module collapses them into ONE 0-100 regime score and ONE label,
so "is this a tape to be leaning into or standing aside from?" is a single glance
that trends over time.

It is a weighted blend, fully transparent:

    breadth 200-day   30%   long-term participation
    breadth 50-day    25%   short-term momentum
    leader fraction   20%   depth of leadership
    beating sector    15%   selection actually paying off
    basket>benchmark  10%   the equal-weight book earning its concentration

Bands:
    >= 70  RISK-ON       broad, led, beating the sector — lean in
    55-70  CONSTRUCTIVE  more good than bad
    40-55  NEUTRAL       mixed; no edge either way
    25-40  CAUTION       thin leadership / lagging — trim and wait
    <  25  RISK-OFF      broken tape — cash is a position

This is a regime read on the WATCHLIST, not advice on the book. It never tells
you to buy or sell anything; it describes the weather.

Boundary: research-only, decision-support. Not financial advice.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
OUT_JSON = ROOT / "data" / "ai_basket_regime.json"
OUT_TXT = ROOT / "reports" / "ai_basket_regime_latest.txt"

WEIGHTS = {
    "breadth200": 0.30,
    "breadth50": 0.25,
    "leaderFraction": 0.20,
    "beatingSector": 0.15,
    "basketBeats": 0.10,
}

BANDS = [
    (70.0, "RISK-ON"),
    (55.0, "CONSTRUCTIVE"),
    (40.0, "NEUTRAL"),
    (25.0, "CAUTION"),
    (0.0, "RISK-OFF"),
]


def label_for(score: float) -> str:
    for threshold, name in BANDS:
        if score >= threshold:
            return name
    return "RISK-OFF"


def score(review: dict[str, Any]) -> dict[str, Any]:
    cp = review.get("composite") or {}
    bp = review.get("benchmark") or {}
    ranking = cp.get("ranking") or []
    n = len(ranking)
    if not n or cp.get("signalsTrusted") is False:
        return {"stage": "ai-basket-regime-research-only", "researchOnly": True,
                "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(),
                "verdict": "fail-closed", "score": None, "label": "unknown",
                "reason": "composite not trusted or empty — no regime read"}

    b200 = sum(1 for r in ranking if r.get("above200"))
    b50 = sum(1 for r in ranking if r.get("above50"))
    leaders = sum(1 for r in ranking if r.get("tag") == "LEADER")
    beating = bp.get("namesBeatingSector")
    basket_beats = bool(bp.get("basketBeatsBenchmark"))

    comps = {
        "breadth200": 100.0 * b200 / n,
        "breadth50": 100.0 * b50 / n,
        "leaderFraction": 100.0 * leaders / n,
        "beatingSector": (100.0 * beating / n) if isinstance(beating, (int, float)) else 0.0,
        "basketBeats": 100.0 if basket_beats else 0.0,
    }
    total = round(sum(WEIGHTS[k] * v for k, v in comps.items()), 1)
    lab = label_for(total)

    return {
        "stage": "ai-basket-regime-research-only",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(),
        "verdict": "trusted",
        "score": total,
        "label": lab,
        "components": {k: round(v, 1) for k, v in comps.items()},
        "weights": WEIGHTS,
        "inputs": {"universe": n, "above200": b200, "above50": b50,
                   "leaders": leaders, "beatingSector": beating,
                   "basketBeatsBenchmark": basket_beats},
        "citations": ["docs/MOMENTUM_VS_BUYLOW_VERDICT_2026-07-15.md"],
    }


def text(p: dict[str, Any]) -> str:
    if p.get("score") is None:
        return f"Regime: {p.get('label', 'unknown')} — {p.get('reason', '')}"
    c = p["components"]
    L = [f"REGIME: {p['label']}  ({p['score']:.0f}/100)",
         f"  breadth {c['breadth200']:.0f}% >200d · {c['breadth50']:.0f}% >50d · "
         f"leaders {c['leaderFraction']:.0f}% · beating-SMH {c['beatingSector']:.0f}%"]
    i = p["inputs"]
    L.append(f"  ({i['above200']}/{i['universe']} above 200-day, "
             f"{i['leaders']} leaders, {i['beatingSector']}/{i['universe']} beat the sector)")
    return "\n".join(L)


def save(p: dict[str, Any]) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(p, indent=2), encoding="utf-8")
    OUT_TXT.write_text(text(p) + "\n", encoding="utf-8")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--review", required=True, help="a review result JSON")
    args = ap.parse_args(argv)
    review = json.loads(Path(args.review).read_text(encoding="utf-8"))
    p = score(review)
    print(text(p))
    save(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
