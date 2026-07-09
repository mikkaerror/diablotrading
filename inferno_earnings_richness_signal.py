#!/usr/bin/env python3
"""Ex-ante earnings-richness selection signal (research-only).

The current strategy research lane and the literature (Liu, AFA - Earnings
Announcements: Ex-ante Risk Premia) converge on one point:
selling premium into earnings is only profitable if you can RANK names ex-ante by
how richly their options are priced relative to how much they actually move.
Naive selling is a wash (+0.39% for rich names vs -0.17% for cheap ones). The edge
lives entirely in the ranking.

This module builds that ranking and, critically, validates it OUT OF SAMPLE, so
we never repeat the look-ahead mistake that made the backward study look good.

Per-name "earnings richness" (the seller's expected edge, normalized to credit):
    richness_event = 1 - (realizedAbsMovePct / impliedMovePct)   # >0 = seller edge
A name's ex-ante score at event T uses ONLY its events strictly before T.

Out-of-sample test (walk-forward):
    For each event T (that has >= MIN_PRIOR_EVENTS earlier same-name events),
    predict with the name's mean richness over events < T, then compare to the
    realized richness at T. If the ex-ante score has positive rank correlation with
    the realized outcome, the signal is predictive (edge is selectable). If not, the
    ranking is noise and the sell side has no capturable edge here.

Depends on a CLEAN realized-move column. If the ledger fails the integrity check
(docs/DATA_INTEGRITY_REALIZED_MOVE_2026-07-07.md) the verdict is
`data-unreliable-cannot-conclude`. Fix the data first (Codex queue #1).

Boundary: research-only. No authority/gate/risk change. Selects nothing on its own;
it produces a ranking and an honest out-of-sample verdict for the campaign to use.
"""

from __future__ import annotations

import json
import os
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_short_premium_study import _find_records, _move_ratio, data_integrity
from server import DATA_DIR, REPORTS_DIR, ensure_dirs

RICHNESS_STAGE = "earnings-richness-signal-research-only"

MIN_PRIOR_EVENTS = 2          # need this many prior same-name events to score a name
MIN_OOS_PAIRS = 20            # need this many walk-forward pairs to judge predictiveness
PREDICTIVE_MIN_RANK_CORR = 0.15  # Spearman-ish threshold to call the signal usable
TAIL_EXCLUDE_RATIO = 1.25     # names whose prior mean realized/implied exceeds this
                              # are chronic over-movers -> never sell (the DELL tail)

LEDGER_FILE = os.environ.get(
    "INFERNO_EXPECTED_MOVE_FILE", "data/inferno_expected_move_ledger.json"
)
EARNINGS_RICHNESS_SIGNAL_FILE = DATA_DIR / "inferno_earnings_richness_signal.json"
EARNINGS_RICHNESS_SIGNAL_TEXT_FILE = REPORTS_DIR / "earnings_richness_signal_latest.txt"


def _event_key(r: dict) -> str:
    ticker = str(r.get("ticker") or "").strip().upper()
    event_id = str(r.get("eventId") or "").strip()
    if event_id:
        return f"{ticker}|event:{event_id}"
    for field in ("earningsDate", "nextEarnings", "reportDate"):
        value = str(r.get(field) or "").strip()
        if value:
            return f"{ticker}|date:{value}"
    reviewed_at = str(r.get("reviewedAt") or "").strip()
    implied = r.get("impliedMovePct")
    realized = r.get("realizedAbsMovePct")
    return f"{ticker}|reviewed:{reviewed_at}|implied:{implied}|realized:{realized}"


def _distinct_events(recs: list) -> list[dict]:
    """Collapse pseudo-replicated snapshots to one row per event key."""
    seen: dict[str, dict] = {}
    for r in recs:
        rm = r.get("realizedAbsMovePct")
        mr = _move_ratio(r)
        if rm is None or mr is None:
            continue
        key = _event_key(r)
        # Keep the earliest snapshot per distinct event key.
        prev = seen.get(key)
        if prev is None or (r.get("reviewedAt") or "") < (prev.get("reviewedAt") or ""):
            seen[key] = r
    return sorted(seen.values(), key=lambda r: (r.get("ticker"), r.get("reviewedAt") or ""))


def _rank_corr(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation (no scipy)."""
    if len(xs) < 3:
        return float("nan")

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0.0] * len(v)
        for pos, idx in enumerate(order):
            rk[idx] = pos
        return rk

    rx, ry = ranks(xs), ranks(ys)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else float("nan")


def build_signal(path: str = LEDGER_FILE) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as fh:
        recs = _find_records(json.load(fh))
    integrity = data_integrity(recs)
    events = _distinct_events(recs)

    # Per-name history in time order (richness per distinct event).
    by_name: dict[str, list[float]] = defaultdict(list)
    order: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        mr = _move_ratio(e)
        by_name[e.get("ticker")].append(1.0 - mr)
        order[e.get("ticker")].append(e)

    # Current ranking: each name's mean richness + tail flag (uses all its history).
    ranking = []
    for nm, rich in by_name.items():
        mean_ratio = st.mean([_move_ratio(e) for e in order[nm]])
        rich_history_candidate = (
            len(rich) >= MIN_PRIOR_EVENTS
            and st.mean(rich) > 0
            and mean_ratio <= TAIL_EXCLUDE_RATIO
        )
        ranking.append({
            "name": nm,
            "events": len(rich),
            "meanRichness": round(st.mean(rich), 3),
            "meanRealizedOverImplied": round(mean_ratio, 3),
            "chronicOverMover": mean_ratio > TAIL_EXCLUDE_RATIO,
            "richHistoryCandidate": rich_history_candidate,
            "sellCandidate": False,
        })
    ranking.sort(key=lambda d: -d["meanRichness"])

    # Walk-forward out-of-sample pairs: predict event T from prior same-name events.
    pred, real = [], []
    for nm, evs in order.items():
        rich = by_name[nm]
        for i in range(len(evs)):
            if i < MIN_PRIOR_EVENTS:
                continue
            prior_mean = st.mean(rich[:i])
            pred.append(prior_mean)
            real.append(rich[i])
    oos_pairs = len(pred)
    oos_corr = _rank_corr(pred, real) if oos_pairs >= 3 else float("nan")

    if not integrity["reliable"]:
        verdict = "data-unreliable-cannot-conclude"
    elif oos_pairs < MIN_OOS_PAIRS:
        verdict = "insufficient-history-for-oos-test"
    elif oos_corr == oos_corr and oos_corr >= PREDICTIVE_MIN_RANK_CORR:
        verdict = "signal-predictive-out-of-sample"
    else:
        verdict = "signal-not-predictive"

    if verdict == "signal-predictive-out-of-sample":
        for row in ranking:
            row["sellCandidate"] = bool(row.get("richHistoryCandidate"))

    return {
        "generatedAt": local_now().isoformat(),
        "stage": RICHNESS_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "ledger": path,
        "dataIntegrity": integrity,
        "distinctEvents": len(events),
        "distinctNames": len(by_name),
        "oosPairs": oos_pairs,
        "oosRankCorr": (round(oos_corr, 3) if oos_corr == oos_corr else None),
        "predictiveThreshold": PREDICTIVE_MIN_RANK_CORR,
        "verdict": verdict,
        "sellCandidates": [r["name"] for r in ranking if r["sellCandidate"]],
        "chronicOverMovers": [r["name"] for r in ranking if r["chronicOverMover"]],
        "ranking": ranking,
        "citations": [
            "data/inferno_expected_move_ledger.json",
            "Liu (AFA) Earnings Announcements: Ex-ante Risk Premia",
        ],
    }


def signal_text(p: dict[str, Any]) -> str:
    L = ["Inferno Earnings-Richness Selection Signal (research-only)",
         f"Ledger: {p['ledger']}",
         f"VERDICT: {p['verdict']}"]
    di = p.get("dataIntegrity", {})
    if not di.get("reliable", True):
        L.append(f"** DATA UNRELIABLE: {di.get('records')} records / "
                 f"{di.get('distinctRealizedValues')} distinct realized values; "
                 f"fix realized-move column first. Ranking below is NOT usable. **")
    L.append(f"Distinct events {p['distinctEvents']} across {p['distinctNames']} "
             f"names | OOS pairs {p['oosPairs']} | OOS rank corr {p['oosRankCorr']} "
             f"(need >= {p['predictiveThreshold']})")
    L.append("")
    L.append(f"{'name':<7}{'ev':>3}{'richness':>10}{'real/impl':>10}  flags")
    for r in p["ranking"]:
        fl = []
        if r["sellCandidate"]:
            fl.append("SELL")
        elif r.get("richHistoryCandidate"):
            fl.append("RICH-HISTORY-WATCH")
        if r["chronicOverMover"]:
            fl.append("TAIL-EXCLUDE")
        L.append(f"{r['name']:<7}{r['events']:>3}{r['meanRichness']:>10.2f}"
                 f"{r['meanRealizedOverImplied']:>10.2f}  {','.join(fl)}")
    L.append("")
    L.append("richness = 1 - realized/implied (seller edge). SELL flags require a "
             "predictive out-of-sample signal, prior history, positive richness, "
             "and no chronic-over-mover tail.")
    L.append("Predictive only if the ex-ante score ranks future outcomes out of "
             "sample. Research-only; selects nothing on its own.")
    return "\n".join(L)


def save_signal(p: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(EARNINGS_RICHNESS_SIGNAL_FILE, p)
    atomic_write_text(EARNINGS_RICHNESS_SIGNAL_TEXT_FILE, signal_text(p))


def main(argv: Optional[list] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    ap.add_argument("--file", default=LEDGER_FILE)
    args = ap.parse_args(argv)
    p = build_signal(args.file)
    print(signal_text(p))
    if args.command == "run":
        save_signal(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
