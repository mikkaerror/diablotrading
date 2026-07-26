#!/usr/bin/env python3
"""AI / data-center basket — signal history & trend-of-signals (research-only).

The rest of the basket system is stateless: every run sees only today. It can
tell you "2 leaders, 64% cash" but not "leaders fell 7 -> 2 over two weeks" or
"cash climbed 40 points" — and the second-order move is usually the more
important number. This module gives the system a memory.

Each run appends a compact SNAPSHOT of the key aggregate signals to a CSV, then
computes DELTAS against the previous run(s). Appending is idempotent per date:
re-running on the same day replaces that day's row rather than duplicating it.

This is the "numbers on top of numbers" layer — derived changes stacked on the
aggregate signals the engines already produce. Pure computation, no market-data
API, so it works even when the data plan is throttled.

Boundary: research-only, decision-support. Records and compares signals; places
no trades, changes no authority. Not financial advice.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
HISTORY_FILE = ROOT / "data" / "ai_basket_signal_history.csv"
OUT_TXT = ROOT / "reports" / "ai_basket_signal_trend_latest.txt"

# Column order is the schema. Append-only; add new columns at the END so old
# rows stay readable (they just carry blanks for columns added later).
FIELDS = [
    "date", "nlv", "leaders", "hold", "reduce", "avoid",
    "avgRS", "investedPct", "cashPct",
    "namesBeatingSector", "basketBeatsBenchmark", "topBucketPct",
    "breadth200", "breadth50",   # added 2026-07-21: market breadth
    "regimeScore", "regimeLabel",  # added 2026-07-21: one-glance regime read
]


def _count(ranking: list[dict], tag: str) -> int:
    return sum(1 for r in ranking if r.get("tag") == tag)


def snapshot(review: dict[str, Any], *, when: Optional[str] = None) -> dict[str, Any]:
    """Extract the scalar signals worth tracking from a review result dict."""
    cp = review.get("composite") or {}
    bp = review.get("benchmark") or {}
    sp = review.get("sizing") or {}
    hp = review.get("holdings") or {}
    ranking = cp.get("ranking") or []
    rs_vals = [r.get("composite") for r in ranking if isinstance(r.get("composite"), (int, float))]
    conc = bp.get("concentration") or {}
    top_bucket = max((v.get("pct", 0) for v in conc.values()), default=None)

    date = (when or cp.get("generatedAt")
            or datetime.now(timezone.utc).astimezone().isoformat())[:10]
    nlv = hp.get("nlv") or (sp.get("params") or {}).get("nlv")

    # breadth — how many names are above their trend lines. Prefer the explicit
    # booleans on the composite rows; fall back to tag arithmetic (AVOID = below
    # 200-day) when they are absent.
    has_flags = any("above200" in r for r in ranking)
    if has_flags:
        breadth200 = sum(1 for r in ranking if r.get("above200"))
        breadth50 = sum(1 for r in ranking if r.get("above50"))
    else:
        breadth200 = len(ranking) - _count(ranking, "AVOID") if ranking else ""
        breadth50 = ""

    return {
        "date": date,
        "nlv": round(nlv, 2) if isinstance(nlv, (int, float)) else "",
        "leaders": _count(ranking, "LEADER"),
        "hold": _count(ranking, "HOLD"),
        "reduce": _count(ranking, "REDUCE"),
        "avoid": _count(ranking, "AVOID"),
        "avgRS": round(sum(rs_vals) / len(rs_vals), 1) if rs_vals else "",
        "investedPct": round(sp.get("investedWeight", 0) * 100, 1) if sp.get("investedWeight") is not None else "",
        "cashPct": round(sp.get("cashWeight", 0) * 100, 1) if sp.get("cashWeight") is not None else "",
        "namesBeatingSector": bp.get("namesBeatingSector", ""),
        "basketBeatsBenchmark": bool(bp.get("basketBeatsBenchmark")) if "basketBeatsBenchmark" in bp else "",
        "topBucketPct": top_bucket if top_bucket is not None else "",
        "breadth200": breadth200,
        "breadth50": breadth50,
        "regimeScore": (review.get("regime") or {}).get("score", ""),
        "regimeLabel": (review.get("regime") or {}).get("label", ""),
    }


def load(path: Path = HISTORY_FILE) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def append(snap: dict[str, Any], path: Path = HISTORY_FILE) -> list[dict[str, Any]]:
    """Append a snapshot, replacing any existing row for the same date."""
    rows = [r for r in load(path) if r.get("date") != snap["date"]]
    rows.append({k: snap.get(k, "") for k in FIELDS})
    rows.sort(key=lambda r: r.get("date", ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")
    return rows


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def deltas(history: list[dict[str, Any]], lookback: int = 1) -> Optional[dict[str, Any]]:
    """Compare the latest row to the one `lookback` runs earlier."""
    if len(history) < 2:
        return None
    latest = history[-1]
    prior = history[-(1 + min(lookback, len(history) - 1))]
    out: dict[str, Any] = {"from": prior.get("date"), "to": latest.get("date"), "changes": {}}
    for f in ("regimeScore", "leaders", "reduce", "avoid", "avgRS",
              "investedPct", "cashPct", "namesBeatingSector", "topBucketPct",
              "breadth200", "breadth50"):
        a, b = _num(prior.get(f)), _num(latest.get(f))
        if a is not None and b is not None:
            out["changes"][f] = round(b - a, 1)
    return out


def text(history: list[dict[str, Any]], d: Optional[dict[str, Any]]) -> str:
    L = ["AI / data-center basket — signal trend (research-only)"]
    if not history:
        return "\n".join(L + ["(no history yet)"])
    latest = history[-1]
    L.append(f"Latest ({latest.get('date')}): "
             f"{latest.get('leaders')} leaders / {latest.get('reduce')} reduce / "
             f"{latest.get('avoid')} avoid · invested {latest.get('investedPct')}% · "
             f"cash {latest.get('cashPct')}%")
    if d and d["changes"]:
        L.append(f"Change since {d['from']}:")
        arrows = {"regimeScore": "regime", "breadth200": "above 200-day",
                  "leaders": "leaders", "reduce": "reduce", "avoid": "avoid",
                  "avgRS": "avg RS", "investedPct": "invested%", "cashPct": "cash%",
                  "namesBeatingSector": "beating SMH", "topBucketPct": "top-bucket%"}
        for f, label in arrows.items():
            if f in d["changes"]:
                v = d["changes"][f]
                if abs(v) < 1e-9:
                    continue
                sign = "+" if v > 0 else ""
                L.append(f"  {label}: {sign}{v:g}")
    else:
        L.append("(need at least two runs for a trend)")
    L.append(f"History: {len(history)} runs recorded.")
    return "\n".join(L)


def record_and_trend(review: dict[str, Any], *, path: Path = HISTORY_FILE,
                     when: Optional[str] = None) -> dict[str, Any]:
    """Append this run and return {snapshot, deltas, historyLen} for the digest."""
    snap = snapshot(review, when=when)
    history = append(snap, path)
    d = deltas(history)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.write_text(text(history, d) + "\n", encoding="utf-8")
    return {"stage": "ai-basket-signal-history-research-only", "researchOnly": True,
            "snapshot": snap, "deltas": d, "historyLen": len(history)}


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--review", help="a review result JSON to record")
    ap.add_argument("--show", action="store_true", help="print the current trend")
    args = ap.parse_args(argv)
    if args.review:
        review = json.loads(Path(args.review).read_text(encoding="utf-8"))
        r = record_and_trend(review)
        print(text(load(), r["deltas"]))
    elif args.show:
        h = load()
        print(text(h, deltas(h)))
    else:
        ap.error("supply --review <file> or --show")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
