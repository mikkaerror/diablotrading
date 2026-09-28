from __future__ import annotations

"""Capex Flow lane: follow the hyperscaler capex dollars to the names they reach.

Three layers, one instrument choice (research-only, forward-tested):

1. Tap (top-down): is capex still accelerating, and is it funded by operating
   cash or by capital markets? Read from research/capex_tape.json, updated each
   earnings season with sourced figures. Regimes:
     accelerating-funded   growth >= 10% and >= 3 of 4 spenders FCF-positive
     accelerating-stretched growth >= 10% but spending outruns cash flow
     plateau               growth < 10%
     cut                   >= 2 spenders cut guidance  -> lane off
2. Pipes (value chain): research/capex_value_chain.json maps names to the layer
   the dollars reach and how directly (order 1-3), and whether the business is
   a paid supplier or capital-dependent (developers need open capital markets,
   which is exactly what a stretched regime puts at risk).
3. Flow confirmation (bottom-up, point-in-time): trend state, relative strength
   vs the tracker universe from frozen scorecard cohorts, support distance and
   a valuation guard. The desk's own verdict is buy strength, manage by trend,
   never average down (docs/MOMENTUM_VS_BUYLOW_VERDICT_2026-07-15.md).

Instrument follows conditions, not a fixed structure: shares are the core;
IV-rich names can be entered by selling a defined-risk put spread at support;
IV-cheap names can carry a longer-dated call spread as a paper test. Pre-earnings
long straddles are excluded (docs/INFERNO_FINAL_FINDINGS_2026-07-09.md).

Weights are stated hypotheses, not fitted values. Results are scored forward
by inferno_pick_scorecard.py (lane "capexFlow"). No orders, no authority.
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from statistics import median
from typing import Any

CAPEX_FLOW_STAGE = "capex-flow-research-only"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RESEARCH_DIR = ROOT / "research"
REPORTS_DIR = ROOT / "reports"
OUTPUT_FILE = DATA_DIR / "inferno_capex_flow.json"
TEXT_FILE = REPORTS_DIR / "capex_flow_latest.txt"

GROWTH_ACCELERATING = 0.10
THROTTLE = {"accelerating-funded": 1.0, "accelerating-stretched": 0.8, "plateau": 0.5, "cut": 0.0}
STRETCHED_CAPITAL_DEPENDENT = 0.6  # extra haircut for developers when spending outruns cash
ORDER_WEIGHT = {0: 0.0, 1: 1.0, 2: 0.85, 3: 0.7}
TREND_POINTS = {"Uptrend": 20, "Bullish": 15, "Neutral": 0, "Basing": -5, "Bearish": -25}
RS_POINTS_PER_PCT = 2.0
RS_POINTS_CAP = 20.0
IV_RICH, IV_CHEAP = 60.0, 30.0
EARNINGS_CAUTION_DAYS = 7
BUY_SCORE, WATCH_SCORE = 60.0, 45.0
RS_MIN_DAYS, RS_MAX_DAYS = 15, 100
TOP_N = 5


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def tap_regime(tape: dict[str, Any], today: date) -> dict[str, Any]:
    spenders = tape.get("spenders") or {}
    last = sum(_num(s.get("lastYearCapex")) or 0 for s in spenders.values())
    nxt = sum(((_num(s.get("guidanceLow")) or 0) + (_num(s.get("guidanceHigh")) or 0)) / 2 for s in spenders.values())
    ocf = sum(_num(s.get("lastYearOcf")) or 0 for s in spenders.values())
    raised = sum(1 for s in spenders.values() if s.get("guidanceDirection") == "raised")
    cut = sum(1 for s in spenders.values() if s.get("guidanceDirection") == "cut")
    funded = sum(1 for s in spenders.values() if s.get("fcfPositive"))
    growth = nxt / last - 1.0 if last else None
    if not spenders or growth is None:
        regime = "unknown"
    elif cut >= 2:
        regime = "cut"
    elif growth < GROWTH_ACCELERATING:
        regime = "plateau"
    elif funded >= 3:
        regime = "accelerating-funded"
    else:
        regime = "accelerating-stretched"
    review_after = tape.get("reviewAfter")
    stale = bool(review_after) and today.isoformat() > str(review_after)
    return {
        "regime": regime,
        "throttle": THROTTLE.get(regime, 0.0),
        "lastYearCapexBn": round(last, 1),
        "nextYearGuidanceBn": round(nxt, 1),
        "growth": None if growth is None else round(growth, 3),
        "capexToOcfLastYear": round(last / ocf, 3) if ocf else None,
        "raised": raised, "cut": cut, "fcfPositive": funded, "spenders": len(spenders),
        "tapeUpdatedAt": tape.get("updatedAt"), "tapeStale": stale,
        "outlook": (tape.get("outlookSignals") or {}).get("nextYearDirection"),
    }


def relative_strength(cohorts: list[dict[str, Any]], today_prices: dict[str, float], today: date) -> tuple[dict[str, float], int | None]:
    """Return per-ticker return minus universe median since the oldest usable frozen cohort."""
    base = None
    for c in cohorts:
        age = (today - date.fromisoformat(c["date"])).days
        if RS_MIN_DAYS <= age <= RS_MAX_DAYS:
            base = c
            break
    if not base:
        return {}, None
    rets = {t: today_prices[t] / p - 1.0 for t, p in base["prices"].items() if t in today_prices and p}
    if not rets:
        return {}, None
    mid = median(rets.values())
    return {t: r - mid for t, r in rets.items()}, (today - date.fromisoformat(base["date"])).days


def instrument_for(row: dict[str, Any], action: str, funding: str) -> str:
    if action not in {"BUY", "WATCH"}:
        return "none"
    iv = _num(row.get("ivRank"))
    days = _num(row.get("daysUntilEarnings"))
    near_earnings = days is not None and 0 <= days <= EARNINGS_CAUTION_DAYS
    if action == "WATCH":
        if iv is not None and iv >= IV_RICH and not near_earnings and funding == "paid-supplier":
            return "optional: sell a defined-risk put spread at support (30-45 DTE) - paid to wait for confirmation"
        return "wait for trend confirmation"
    parts = ["shares (core; add on strength, never average down)"]
    if iv is not None and iv >= IV_RICH and not near_earnings:
        parts.append("or enter via defined-risk put spread at support (30-45 DTE)")
    elif iv is not None and iv <= IV_CHEAP:
        parts.append("paper-test: call spread 60-120 DTE")
    if near_earnings:
        parts.append(f"earnings in {int(days)}d: half size or wait")
    return "; ".join(parts)


def score_name(row: dict[str, Any], layer: dict[str, Any], regime: dict[str, Any], rs: float | None) -> dict[str, Any]:
    trend_label = str(row.get("trend") or "")
    points = 50.0 + TREND_POINTS.get(trend_label, 0)
    reasons = [f"trend {trend_label or 'n/a'}"]
    if rs is not None:
        rs_points = max(-RS_POINTS_CAP, min(RS_POINTS_CAP, rs * 100 * RS_POINTS_PER_PCT))
        points += rs_points
        reasons.append(f"RS {rs * 100:+.1f}% vs universe")
    support = _num(row.get("distanceToSupportPct"))
    if support is not None and 0 <= support <= 3:
        points += 5
        reasons.append("near support")
    pe = _num(row.get("pe"))
    if layer["funding"] == "paid-supplier" and pe is not None and (pe <= 0 or pe > 150):
        points -= 10
        reasons.append(f"valuation guard (P/E {pe:.0f})")
    weight = ORDER_WEIGHT.get(layer["order"], 0.7) * regime["throttle"]
    if regime["regime"] == "accelerating-stretched" and layer["funding"] == "capital-dependent":
        weight *= STRETCHED_CAPITAL_DEPENDENT
        reasons.append("capital-dependent in stretched regime")
    score = round(points * weight, 1)

    if regime["regime"] in {"cut", "unknown"}:
        action = "NO-NEW"
    elif trend_label == "Bearish":
        action = "AVOID"
    elif score >= BUY_SCORE and trend_label in {"Uptrend", "Bullish"} and (rs is None or rs > 0):
        action = "BUY"
    elif score >= WATCH_SCORE:
        action = "WATCH"
    else:
        action = "PASS"
    return {
        "ticker": row.get("ticker"),
        "layer": layer["name"],
        "order": layer["order"],
        "funding": layer["funding"],
        "score": score,
        "action": action,
        "instrument": instrument_for(row, action, layer["funding"]),
        "price": _num(row.get("price")),
        "ivRank": _num(row.get("ivRank")),
        "daysUntilEarnings": row.get("daysUntilEarnings"),
        "relativeStrength": None if rs is None else round(rs, 4),
        "reasons": reasons,
    }


def build_capex_flow(data_dir: Path = DATA_DIR, research_dir: Path = RESEARCH_DIR, today: date | None = None) -> dict[str, Any]:
    snapshot = _load(data_dir / "latest_snapshot.json")
    today = today or (date.fromisoformat(str(snapshot.get("generatedAt"))[:10]) if snapshot.get("generatedAt") else date.today())
    regime = tap_regime(_load(research_dir / "capex_tape.json"), today)
    chain = _load(research_dir / "capex_value_chain.json").get("layers") or {}
    by_ticker = {}
    for name, layer in chain.items():
        for ticker in layer.get("tickers") or []:
            by_ticker[ticker] = {"name": name, "funding": layer.get("funding"), "order": layer.get("order", 3)}
    rows = {r.get("ticker"): r for r in snapshot.get("rows") or [] if r.get("ticker")}
    prices = {t: _num(r.get("price")) for t, r in rows.items() if _num(r.get("price"))}

    cohorts = []
    try:
        from inferno_pick_scorecard import load_cohorts

        cohorts = load_cohorts(data_dir / "inferno_pick_scorecard_cohorts.jsonl")
    except Exception:
        cohorts = []
    rs_map, rs_days = relative_strength(cohorts, prices, today)

    names = []
    for ticker, layer in by_ticker.items():
        if layer["funding"] == "spender" or ticker not in rows:
            continue
        names.append(score_name(rows[ticker], layer, regime, rs_map.get(ticker)))
    names.sort(key=lambda n: (-n["score"], -(n["relativeStrength"] or 0)))
    spenders_rs = [rs_map[t] for t, l in by_ticker.items() if l["funding"] == "spender" and t in rs_map]
    layer_summary = {}
    for n in names:
        s = layer_summary.setdefault(n["layer"], {"names": 0, "buy": 0, "avoid": 0, "meanScore": 0.0})
        s["names"] += 1
        s["buy"] += n["action"] == "BUY"
        s["avoid"] += n["action"] == "AVOID"
        s["meanScore"] += n["score"]
    for s in layer_summary.values():
        s["meanScore"] = round(s["meanScore"] / s["names"], 1)
    return {
        "generatedAt": datetime.now().astimezone().isoformat(),
        "asOf": today.isoformat(),
        "stage": CAPEX_FLOW_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "regime": regime,
        "customerMomentum": None if not spenders_rs else round(sum(spenders_rs) / len(spenders_rs), 4),
        "relativeStrengthDays": rs_days,
        "topPicks": [n["ticker"] for n in names if n["action"] == "BUY"][:TOP_N],
        "layers": layer_summary,
        "names": names,
        "citations": [
            "Cohen & Frazzini (2008), Economic Links and Predictable Returns, JF",
            "Titman, Wei & Xie (2004), Capital Investments and Stock Returns, JFQA",
            "docs/CAPEX_FLOW_STRATEGY_2026-09-28.md",
        ],
    }


def capex_flow_text(p: dict[str, Any]) -> str:
    r = p["regime"]
    growth = "n/a" if r["growth"] is None else f"{r['growth'] * 100:+.0f}%"
    lines = [
        "Inferno Capex Flow (research-only, forward-tested)",
        f"As of {p['asOf']} | tape updated {r['tapeUpdatedAt']}{' (STALE - update after earnings)' if r['tapeStale'] else ''}",
        f"Tap: {r['regime']} | spender capex ${r['lastYearCapexBn']}bn -> ${r['nextYearGuidanceBn']}bn guided ({growth}) | "
        f"raised {r['raised']}/{r['spenders']} | FCF-positive {r['fcfPositive']}/{r['spenders']} | throttle {r['throttle']}",
    ]
    if p["customerMomentum"] is not None:
        lines.append(f"Customer momentum (spenders vs universe, {p['relativeStrengthDays']}d): {p['customerMomentum'] * 100:+.1f}%")
    lines.append("")
    lines.append("Layers (names | buy | avoid | mean score):")
    for name, s in sorted(p["layers"].items(), key=lambda kv: -kv[1]["meanScore"]):
        lines.append(f"- {name}: {s['names']} | {s['buy']} | {s['avoid']} | {s['meanScore']}")
    lines.append("")
    lines.append("Top of the flow:")
    shown = [n for n in p["names"] if n["action"] in {"BUY", "WATCH"}][:10]
    if not shown:
        lines.append("- nothing clears the bar today")
    for n in shown:
        lines.append(f"- {n['action']:5} {n['ticker']:5} {n['score']:5.1f} [{n['layer']}] {', '.join(n['reasons'])}")
        lines.append(f"        -> {n['instrument']}")
    lines.append("")
    lines.append("Research only. Scored forward by the pick scorecard (lane capexFlow). No orders placed.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capex Flow lane (research-only).")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    args = parser.parse_args(argv)
    if args.command == "status":
        payload = _load(OUTPUT_FILE)
        if not payload:
            print("No capex flow run yet.")
            return 1
    else:
        payload = build_capex_flow()
        from inferno_io import atomic_write_json, atomic_write_text

        atomic_write_json(OUTPUT_FILE, payload)
        atomic_write_text(TEXT_FILE, capex_flow_text(payload))
    print(capex_flow_text(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
