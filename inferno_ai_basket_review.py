#!/usr/bin/env python3
"""Basket weekly review — one runner that chains all four engines (research-only).

Consolidates the pipeline so the scheduled task makes one call instead of four.
Given the data files the task fetches from the market-data MCP, it runs:
  1. trend-crossing alerts (200d/50d)      -> optional email via .env.smtp
  2. trailing-return momentum (3M/6M)
  3. composite relative-strength + tags
  4. vs-SMH sector benchmark
and prints ONE combined digest (also saved to reports/ai_basket_review_latest.txt).

Usage (files produced by the weekly task):
  python3 inferno_ai_basket_review.py \
     --quotes data/ai_basket_quotes_latest.json \
     --changes data/ai_basket_changes_latest.json \
     --bench-quotes data/ai_basket_bench_quotes.json [--send]

Boundary: research-only, decision-support. Places no trades. Not financial advice.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

import inferno_ai_basket_alerts as alerts
import inferno_ai_basket_momentum as momentum
import inferno_ai_basket_composite as composite
import inferno_ai_basket_vs_benchmark as benchmark
import inferno_ai_basket_sizing as sizing
import inferno_basket_holdings_join as holdings
import inferno_ai_basket_signal_history as signal_history
import inferno_ai_basket_regime as regime
from inferno_ai_basket_config import load_data_contract

ROOT = Path(__file__).resolve().parent
OUT_TXT = ROOT / "reports" / "ai_basket_review_latest.txt"


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_nlv() -> Optional[float]:
    """Best-effort NLV from the broker-sourced heat artifact (read-only)."""
    for path in (ROOT / "data" / "inferno_portfolio_heat.json",
                 ROOT / "data" / "inferno_live_account_sync.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        nlv = payload.get("netLiquidatingValue") or payload.get("nlv")
        if isinstance(nlv, (int, float)) and nlv > 0:
            return float(nlv)
    return None


def run(quotes_path: str, changes_path: Optional[str], bench_quotes_path: str,
        send: bool = False, momentum_path: Optional[str] = None,
        current_weights: Optional[dict[str, float]] = None,
        positions_path: Optional[str] = None,
        held_quotes_path: Optional[str] = None) -> dict[str, Any]:
    contract = load_data_contract()
    # 1) crossings (also updates saved state, optional email)
    al = alerts.run(quotes_path, send=send, data_contract=contract)

    # 2) momentum.
    # Preferred source is the Schwab-derived artifact from
    # inferno_ai_basket_refresh.py. The FMP `quote-change` endpoint is
    # plan-limited to a handful of large caps, so building momentum from it
    # silently covers only a few names — use it only as a fallback.
    if momentum_path:
        mp = _load(momentum_path)
    else:
        recs = _load(changes_path) if changes_path else []
        if isinstance(recs, dict):
            recs = recs.get("data") or recs.get("records") or []
        mp = momentum.build(recs)
        momentum.save(mp)

    # 3) composite
    quotes = _load(quotes_path)
    if isinstance(quotes, dict):
        quotes = quotes.get("data") or quotes.get("quotes") or []
    cp = composite.build(quotes, mp, data_contract=contract)
    composite.save(cp)

    # 4) vs-benchmark
    bq = _load(bench_quotes_path)
    if isinstance(bq, dict):
        bq = bq.get("data") or bq.get("quotes") or []
    bp = benchmark.build(bq, "SMH", data_contract=contract)
    if not bp.get("error"):
        benchmark.save(bp)

    # 5) regime read (needs composite + benchmark). Computed before sizing so it
    # can throttle deployment.
    rg = regime.score({"composite": cp, "benchmark": bp})
    if rg.get("score") is not None:
        regime.save(rg)

    # 6) position sizing off the composite, throttled by the regime. Inherits the
    # composite's trust verdict, so a failed-closed contract produces no weights
    # rather than confident-looking nonsense.
    sp = sizing.build(cp, current_weights, nlv=_read_nlv(),
                      regime_score=rg.get("score"))
    if sp.get("signalsTrusted"):
        sizing.save(sp)

    # 6) the live book, joined against the watchlist. Optional: only runs when
    # broker position data is supplied, so the review still works standalone.
    hp = None
    if positions_path and held_quotes_path:
        try:
            pos_payload = _load(positions_path)
            positions = (pos_payload.get("positions", [])
                         if isinstance(pos_payload, dict) else pos_payload)
            hq = _load(held_quotes_path)
            if isinstance(hq, dict):
                hq = hq.get("data") or hq.get("quotes") or []
            hp = holdings.build(positions, hq, nlv=_read_nlv(), composite=cp)
            holdings.save(hp)
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            hp = {"error": f"holdings join unavailable: {type(exc).__name__}: {exc}"}

    result = {"alerts": al, "momentum": mp, "composite": cp,
              "benchmark": bp, "sizing": sp, "holdings": hp, "regime": rg}

    # 8) record this run and derive week-over-week trend (the memory layer).
    # Only log when the composite is trusted, so throttled/failed runs do not
    # poison the history with empty snapshots.
    if cp.get("signalsTrusted") is not False and (cp.get("ranking") or []):
        try:
            result["signalTrend"] = signal_history.record_and_trend(result)
        except OSError as exc:
            result["signalTrend"] = {"error": f"history unavailable: {exc}"}

    return result


def discipline_watch(al: dict[str, Any], cp: dict[str, Any]) -> dict[str, list]:
    """Operationalize the momentum verdict (docs/MOMENTUM_VS_BUYLOW_VERDICT).

    - doNotAverageDown: AVOID-tagged names (below their 200-day). On this basket,
      'cheap and falling' persisted lower — these are stand-asides, not discounts.
    - reentryConfirmed: names that reclaimed their 200-day this week. The
      disciplined way to buy a fallen name back: after the turn confirms, not by
      guessing the low.
    """
    avoid = [x["symbol"] for x in cp.get("ranking", []) if x.get("tag") == "AVOID"]
    reentry = [e["sym"] for e in al.get("events", []) if e.get("kind") == "REENTRY"]
    return {"doNotAverageDown": avoid, "reentryConfirmed": reentry}


def digest(r: dict[str, Any]) -> str:
    al, cp, bp = r["alerts"], r["composite"], r["benchmark"]
    L = ["===== AI / data-center basket — weekly review =====", ""]

    # regime headline — the one-glance weather read, up top
    rg = r.get("regime")
    if rg and rg.get("score") is not None:
        c = rg["components"]
        L.append(f"REGIME: {rg['label']} ({rg['score']:.0f}/100) — "
                 f"breadth {c['breadth200']:.0f}% >200d / {c['breadth50']:.0f}% >50d, "
                 f"leaders {c['leaderFraction']:.0f}%, beating-SMH {c['beatingSector']:.0f}%")
        L.append("")

    # THE BOOK FIRST — what is actually owned outranks what is merely watched.
    hp = r.get("holdings")
    if hp:
        if hp.get("error"):
            L.append(f"PORTFOLIO: {hp['error']}")
        else:
            nlv = hp.get("nlv")
            L.append("PORTFOLIO (live book):"
                     + (f"  NLV ${nlv:,.2f}" if nlv else ""))
            for h in hp["holdings"]:
                flag = " [core]" if h["longTermHold"] else ""
                L.append(f"  {h['symbol']:<5}{(h['weightPct'] or 0):>6.1f}%  "
                         f"P/L {(h['plPercent'] or 0):>+6.1f}%  {h['trendState']:<12}"
                         f"{h['action']}{flag}")
            if hp.get("longTermHoldsBelowTrend"):
                L.append(f"  ⓘ core holds below their 200-day: "
                         f"{', '.join(hp['longTermHoldsBelowTrend'])} "
                         f"(awareness only — excluded from exit logic)")
            g = hp.get("gaps") or {}
            L.append(f"  book vs watchlist: {g.get('overlapCount', 0)} of "
                     f"{hp['heldCount']} holdings are tracked"
                     + (f"; not tracked: {', '.join(g['heldNotOnWatchlist'])}"
                        if g.get("heldNotOnWatchlist") else ""))
            s = hp.get("accountScale")
            if s:
                L.append(f"  at this NLV a 1.5% position = ${s['minPositionDollars']:,.2f}, "
                         f"an 8% cap = ${s['maxPositionDollars']:,.2f}")
        L.append("")

    # crossings
    ev = al.get("events", [])
    if not ev:
        L.append("CROSSINGS: none this week — basket unchanged.")
    else:
        L.append(f"CROSSINGS ({len(ev)}):")
        for e in ev:
            L.append(f"  [{e['kind']}] {e['sym']} ${e['price']:.2f} — {e['msg']}")
        em = al.get("emailed", {})
        L.append(f"  email: {'sent to '+em.get('recipient','') if em.get('ok') else em.get('reason','not sent')}")
    L.append("")

    # composite tags
    lead = [x["symbol"] for x in cp["ranking"] if x["tag"] == "LEADER"]
    red = [x["symbol"] for x in cp["ranking"] if x["tag"] == "REDUCE"]
    avoid = [x["symbol"] for x in cp["ranking"] if x["tag"] == "AVOID"]
    # single mutually-exclusive direction — a name can't be both
    accel = [x["symbol"] for x in cp["ranking"] if x.get("direction") == "accelerating"]
    fade = [x["symbol"] for x in cp["ranking"] if x.get("direction") == "fading"]
    ranking = cp.get("ranking") or []
    b200 = sum(1 for x in ranking if x.get("above200"))
    b50 = sum(1 for x in ranking if x.get("above50"))
    L.append("COMPOSITE TAGS:")
    if ranking:
        L.append(f"  breadth: {b200}/{len(ranking)} above 200-day · "
                 f"{b50}/{len(ranking)} above 50-day")
    L.append(f"  LEADERS: {', '.join(lead) or '—'}")
    L.append(f"  REDUCE:  {', '.join(red) or '—'}")
    L.append(f"  AVOID:   {', '.join(avoid) or '—'}")
    if accel:
        L.append(f"  ▲ accelerating: {', '.join(accel)}")
    if fade:
        L.append(f"  ▼ fading: {', '.join(fade)}")
    L.append("")

    # vs sector
    if bp.get("error"):
        L.append(f"VS SECTOR: {bp['error']}")
    else:
        beats_basket = "BEATS SMH" if bp["basketBeatsBenchmark"] else "LAGS SMH"
        top = [x["symbol"] for x in bp["ranking"][:3]]
        bot = [x["symbol"] for x in bp["ranking"][-3:]]
        L.append(f"VS SECTOR (SMH): {bp['namesBeatingSector']}/{bp['count']} names beat the sector; "
                 f"equal-weight basket {beats_basket}.")
        L.append(f"  strongest vs sector: {', '.join(top)}   weakest: {', '.join(bot)}")
        conc = bp.get("concentration") or {}
        if conc:
            parts = [f"{v['pct']}% {b}" for b, v in sorted(
                conc.items(), key=lambda kv: -kv[1]["count"])]
            L.append("  concentration: " + " · ".join(parts))
        for c in (bp.get("byCategory") or [])[:3]:
            L.append(f"    ▲ {c['category']}: {c['count']} names, "
                     f"{c['avgRelStrength']:+.0f} vs SMH")
    L.append("")

    # discipline watch — enforces the momentum lane (no averaging down)
    dw = discipline_watch(al, cp)
    L.append("DISCIPLINE WATCH (momentum lane — see MOMENTUM_VS_BUYLOW_VERDICT):")
    L.append(f"  ⛔ do NOT average down (below 200-day / AVOID): "
             f"{', '.join(dw['doNotAverageDown']) or '—'}")
    L.append(f"  ✅ confirmed re-entry (reclaimed 200-day this week): "
             f"{', '.join(dw['reentryConfirmed']) or '—'}")
    L.append("  Rule: weakness is a stand-aside, not a discount. Re-enter only on a "
             "confirmed 200-day reclaim.")
    # sizing (compact — full table lives in reports/ai_basket_sizing_latest.txt)
    sp = r.get("sizing") or {}
    if sp:
        L.append("")
        L.append("TARGET SIZING:")
        if not sp.get("signalsTrusted"):
            L.append(f"  fail-closed — {sp.get('reason', 'inputs not trusted')}")
        else:
            funded = [t for t in sp["targets"] if t["targetWeight"] > 0]
            top = ", ".join(f"{t['symbol']} {t['targetWeight']*100:.1f}%"
                            for t in funded[:6])
            L.append(f"  invested {sp['investedWeight']*100:.0f}% · "
                     f"cash {sp['cashWeight']*100:.0f}% · {len(funded)} funded names")
            L.append(f"  largest: {top}")
            for b, w in sorted(sp["bucketTotals"].items(), key=lambda kv: -kv[1]):
                if w > 1e-9:
                    L.append(f"    {b:<28}{w*100:>6.1f}%")
            acts = [t for t in sp["targets"] if t["action"] in ("ADD", "TRIM", "EXIT")]
            if acts:
                L.append("  actions vs current book:")
                for t in acts[:12]:
                    L.append(f"    [{t['action']:<4}] {t['symbol']:<5} "
                             f"{(t['currentWeight'] or 0)*100:>5.1f}% -> "
                             f"{t['targetWeight']*100:.1f}%")
            if sp.get("unclassifiedSymbols"):
                L.append(f"  ⚠ uncategorized (check universe): "
                         f"{', '.join(sp['unclassifiedSymbols'])}")
        L.append("")

    # signal trend — week-over-week movement in the aggregate signals
    st = r.get("signalTrend")
    if st and not st.get("error"):
        d = st.get("deltas")
        if d and d.get("changes"):
            labels = {"regimeScore": "regime", "breadth200": "above 200-day",
                      "leaders": "leaders", "reduce": "reduce", "avoid": "avoid",
                      "avgRS": "avg RS", "cashPct": "cash%",
                      "namesBeatingSector": "beating SMH", "topBucketPct": "top-bucket%"}
            moves = []
            for f, lab in labels.items():
                v = (d["changes"] or {}).get(f)
                if v is not None and abs(v) >= 1e-9:
                    moves.append(f"{lab} {'+' if v > 0 else ''}{v:g}")
            if moves:
                L.append(f"SIGNAL TREND (since {d['from']}): " + " · ".join(moves))
                L.append("")
        elif st.get("historyLen", 0) < 2:
            L.append("SIGNAL TREND: first run recorded — trend appears next run.")
            L.append("")

    L.append("Decision-support only — hold the leaders, cut the AVOIDs. Not financial advice.")
    return "\n".join(L)


def email_digest(out: str, r: dict[str, Any]) -> dict[str, Any]:
    """Email the whole weekly digest.

    The crossing alerts only fire when something crosses a moving average, so a
    quiet week sent nothing at all and the regime / sizing / portfolio layers
    never reached the inbox. This sends the full picture every run, with the
    regime read in the subject so it is readable without opening the mail.
    """
    from html import escape
    rg = r.get("regime") or {}
    label, sc = rg.get("label"), rg.get("score")
    subject = "[Basket] Weekly review"
    if label and sc is not None:
        subject += f" — {label} ({sc:.0f}/100)"
    body_html = ("<pre style=\"font:13px ui-monospace,SFMono-Regular,Menlo,monospace;"
                 "line-height:1.45\">" + escape(out) + "</pre>"
                 "<p style='color:#667;font-size:12px'>Decision-support only. "
                 "Places no trades, changes no authority. Not financial advice.</p>")
    return alerts.send_email(subject, out, body_html)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quotes", required=True)
    ap.add_argument("--changes", help="FMP quote-change records (fallback only; "
                                      "the endpoint is plan-limited)")
    ap.add_argument("--momentum", help="prebuilt momentum artifact from "
                                       "inferno_ai_basket_refresh.py (preferred, Schwab-derived)")
    ap.add_argument("--bench-quotes", required=True)
    ap.add_argument("--send", action="store_true",
                    help="email the crossing alerts (only fires if something crossed)")
    ap.add_argument("--email", action="store_true",
                    help="email the FULL weekly digest every run, crossings or not")
    ap.add_argument("--current", help="optional JSON of current weights, "
                                      "e.g. {\"NVDA\": 0.10, \"DELL\": 0.05} "
                                      "(percent-style values like 10 are accepted too)")
    ap.add_argument("--positions", help="broker position review JSON (live book)")
    ap.add_argument("--held-quotes", help="batch-quote JSON covering the held names")
    args = ap.parse_args(argv)
    current = None
    if args.current:
        current = json.loads(Path(args.current).read_text(encoding="utf-8"))
    if not args.changes and not args.momentum:
        ap.error("supply --momentum (preferred) or --changes")
    r = run(args.quotes, args.changes, args.bench_quotes, send=args.send,
            momentum_path=args.momentum,
            current_weights=current, positions_path=args.positions,
            held_quotes_path=args.held_quotes)
    out = digest(r)
    print(out)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.write_text(out + "\n", encoding="utf-8")
    if args.email:
        res = email_digest(out, r)
        print("\nDigest email: "
              + (f"sent to {res.get('recipient')}" if res.get("ok")
                 else f"NOT sent — {res.get('reason')}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
