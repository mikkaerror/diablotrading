#!/usr/bin/env python3
"""Holdings x watchlist join — the live portfolio tracker (research-only).

The desk has two different jobs and they were being conflated:

  WATCHLIST tracker  — the 30-name AI/data-center basket. Candidates. Answers
                       "what is strong, what is worth owning?"
  PORTFOLIO tracker  — what is ACTUALLY held, at real weights, from the live
                       broker sync. Answers "what do I own, how concentrated am
                       I, what is breaking?"

This module is the join. It reads the live position review (broker-sourced) and
the basket watchlist, and reports:

  - real holdings with real weights, P/L, and trend state
  - the gap in both directions: watchlist leaders NOT held, and held names NOT
    on the watchlist
  - account-scaled sizing, so target weights become dollar amounts that make
    sense at the actual NLV rather than percentages of an imaginary book

OPERATOR LONG-TERM HOLDS
------------------------
Positions flagged `operatorLongTermHold` are the operator's deliberate
conviction holds. They are EXCLUDED from all trim/exit logic — this module will
never emit an EXIT or TRIM for them.

It still DISPLAYS their trend state. Respecting a hold decision means not
nagging; it does not mean hiding data. The operator asked to hold, not to be
kept in the dark, and a silent tracker is a useless one.

Boundary: research-only, decision-support. Reads broker artifacts; never writes
them. Places no trades, sizes nothing for real, changes no authority.
Not financial advice.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from inferno_ai_basket_config import BASKET, factor_bucket, normalize_symbol
from inferno_io import atomic_write_json, atomic_write_text

ROOT = Path(__file__).resolve().parent
OUT_JSON = ROOT / "data" / "basket_holdings_join.json"
OUT_TXT = ROOT / "reports" / "basket_holdings_join_latest.txt"

JOIN_STAGE = "basket-holdings-join-research-only"


def _trend(q: dict) -> dict[str, Any]:
    p, a50, a200 = q.get("price"), q.get("priceAvg50"), q.get("priceAvg200")
    hi = q.get("yearHigh")
    if None in (p, a50, a200):
        return {"above200": None, "above50": None, "offHigh": None,
                "trendState": "no-data"}
    above200, above50 = p > a200, p > a50
    off = (p / hi - 1) * 100 if hi else None
    if above200 and above50:
        state = "uptrend"
    elif above200:
        state = "below-50d"
    elif above50:
        state = "recovering"
    else:
        state = "below-200d"
    return {"above200": above200, "above50": above50,
            "offHigh": round(off, 1) if off is not None else None,
            "trendState": state}


def build(positions: list[dict], quotes: list[dict], nlv: Optional[float] = None,
          composite: Optional[dict] = None,
          watchlist: Optional[dict[str, str]] = None) -> dict[str, Any]:
    watch = watchlist if watchlist is not None else BASKET
    qmap = {normalize_symbol(q.get("symbol")): q for q in quotes
            if isinstance(q, dict) and q.get("symbol")}

    holdings = []
    for pos in positions:
        sym = normalize_symbol(pos.get("symbol"))
        if not sym:
            continue
        lth = bool(pos.get("operatorLongTermHold"))
        t = _trend(qmap.get(sym, {}))
        # exit logic — deliberately skipped for operator long-term holds
        if lth:
            action = "HOLD-CORE"
            reason = "operator long-term hold — excluded from exit logic"
        elif t["above200"] is None:
            action, reason = "NO-DATA", "no quote available"
        elif not t["above200"]:
            action, reason = "EXIT", "below 200-day — trend broken"
        elif not t["above50"]:
            action, reason = "TRIM", "below 50-day — rolling over"
        else:
            action, reason = "HOLD", "trend intact"
        holdings.append({
            "symbol": sym,
            "qty": pos.get("qty"),
            "markValue": pos.get("markValue"),
            "weightPct": pos.get("weightPct"),
            "plPercent": pos.get("plPercent"),
            "bucket": pos.get("bucket"),
            "longTermHold": lth,
            "onWatchlist": sym in watch,
            "cat": watch.get(sym, ""),
            "factorBucket": factor_bucket(watch.get(sym, "")) if sym in watch else "—",
            **t,
            "action": action,
            "actionReason": reason,
        })
    holdings.sort(key=lambda h: -(h["weightPct"] or 0))

    held = {h["symbol"] for h in holdings}
    leaders = []
    if composite and composite.get("signalsTrusted") is not False:
        leaders = [r["symbol"] for r in (composite.get("ranking") or [])
                   if r.get("tag") == "LEADER"]

    top = holdings[0] if holdings else None
    lth_names = [h["symbol"] for h in holdings if h["longTermHold"]]
    # informational only: long-term holds whose trend is broken. Not an exit call.
    lth_below = [h["symbol"] for h in holdings
                 if h["longTermHold"] and h["above200"] is False]

    scale = None
    if nlv:
        scale = {
            "nlv": round(nlv, 2),
            "onePctDollars": round(nlv * 0.01, 2),
            "minPositionDollars": round(nlv * 0.015, 2),
            "maxPositionDollars": round(nlv * 0.08, 2),
        }

    return {
        "stage": JOIN_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(),
        "nlv": nlv,
        "heldCount": len(holdings),
        "longTermHoldCount": len(lth_names),
        "exitEligibleCount": sum(1 for h in holdings if not h["longTermHold"]),
        "topWeightPct": top["weightPct"] if top else None,
        "topSymbol": top["symbol"] if top else None,
        "holdings": holdings,
        "longTermHolds": lth_names,
        "longTermHoldsBelowTrend": lth_below,
        "gaps": {
            "heldNotOnWatchlist": sorted(held - set(watch)),
            "watchlistLeadersNotHeld": [s for s in leaders if s not in held],
            "watchlistSize": len(watch),
            "overlapCount": len(held & set(watch)),
        },
        "accountScale": scale,
        "citations": ["docs/MOMENTUM_VS_BUYLOW_VERDICT_2026-07-15.md"],
    }


def text(p: dict[str, Any]) -> str:
    L = ["Portfolio tracker — live holdings x watchlist (research-only)",
         f"Generated: {p['generatedAt']}"]
    if p.get("nlv"):
        L.append(f"Net liquidating value: ${p['nlv']:,.2f}")
    L.append("")
    L.append(f"{'sym':<6}{'value':>9}{'wt%':>7}{'P/L%':>8}  {'trend':<12}{'action':<11}why")
    for h in p["holdings"]:
        mv = h["markValue"] or 0
        L.append(f"{h['symbol']:<6}{mv:>9.2f}{(h['weightPct'] or 0):>7.1f}"
                 f"{(h['plPercent'] or 0):>8.1f}  {h['trendState']:<12}"
                 f"{h['action']:<11}{h['actionReason']}")
    L.append("")
    if p["longTermHolds"]:
        L.append(f"Long-term core (excluded from exit logic by operator): "
                 f"{', '.join(p['longTermHolds'])}")
        if p["longTermHoldsBelowTrend"]:
            L.append(f"  ⓘ of those, below their 200-day: "
                     f"{', '.join(p['longTermHoldsBelowTrend'])} "
                     f"(shown for awareness — no action recommended)")
    g = p["gaps"]
    L.append("")
    L.append(f"WATCHLIST vs BOOK: {g['overlapCount']} of {p['heldCount']} holdings "
             f"are on the {g['watchlistSize']}-name watchlist.")
    if g["heldNotOnWatchlist"]:
        L.append(f"  held but NOT tracked: {', '.join(g['heldNotOnWatchlist'])}")
    if g["watchlistLeadersNotHeld"]:
        L.append(f"  watchlist LEADERS not owned: "
                 f"{', '.join(g['watchlistLeadersNotHeld'][:10])}")
    s = p.get("accountScale")
    if s:
        L.append("")
        L.append(f"ACCOUNT SCALE — at ${s['nlv']:,.2f} NLV: 1% = ${s['onePctDollars']:,.2f} · "
                 f"a 1.5% minimum position = ${s['minPositionDollars']:,.2f} · "
                 f"an 8% cap = ${s['maxPositionDollars']:,.2f}")
    L.append("")
    L.append("Decision-support only. Reads the broker book; never trades it. "
             "Not financial advice.")
    return "\n".join(L)


def save(p: dict[str, Any]) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUT_JSON, p)
    atomic_write_text(OUT_TXT, text(p) + "\n")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--positions", default="data/inferno_live_position_review.json")
    ap.add_argument("--quotes", required=True, help="batch-quote JSON for held names")
    ap.add_argument("--composite", help="optional composite JSON for leader gaps")
    ap.add_argument("--nlv", type=float, help="net liquidating value")
    args = ap.parse_args(argv)

    pos_payload = json.loads(Path(args.positions).read_text(encoding="utf-8"))
    positions = pos_payload.get("positions", []) if isinstance(pos_payload, dict) else pos_payload
    quotes = json.loads(Path(args.quotes).read_text(encoding="utf-8"))
    if isinstance(quotes, dict):
        quotes = quotes.get("data") or quotes.get("quotes") or []
    composite = None
    if args.composite:
        composite = json.loads(Path(args.composite).read_text(encoding="utf-8"))
    p = build(positions, quotes, nlv=args.nlv, composite=composite)
    print(text(p))
    save(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
