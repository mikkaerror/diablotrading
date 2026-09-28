from __future__ import annotations

"""Volatility edge: is an option cheap or rich against the stock's own movement?

Selling options pays when implied volatility (IV) exceeds the volatility the
stock then realises; buying pays in the reverse case. That gap, the variance
risk premium, is the main economic reason option strategies win or lose
(Carr & Wu 2009; Bakshi & Kapadia 2003). IV rank alone only says where IV sits
versus its own past, not whether it is expensive versus realised movement.

For each name with a captured Schwab chain this module measures:
  - IV30: mean call/put IV at the strike nearest spot, expiry nearest 35 DTE
    within 21-60 DTE (weeklies are skipped: they are dominated by noise)
  - RV proxy: tracker ATR% converted to annualised volatility
    (ATR ~ 1.6 x daily sigma for a continuous path; label 'atr-proxy')
  - ratio IV30 / RV and a class: rich >= 1.30, cheap <= 0.90, else fair
  - event flag when earnings fall inside the chosen expiry (IV then carries
    an event premium by design)
  - liquidity: ATM bid/ask as % of mid; live <= 10%, paper <= 20%

Thresholds are stated hypotheses. Research-only; feeds instrument choice in
inferno_capex_flow.py. No orders.
"""

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

VOL_EDGE_STAGE = "vol-edge-research-only"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
OUTPUT_FILE = DATA_DIR / "inferno_vol_edge.json"
TEXT_FILE = REPORTS_DIR / "vol_edge_latest.txt"

TARGET_DTE, MIN_DTE, MAX_DTE = 35, 21, 60
ATR_TO_SIGMA = 1.6
RICH, CHEAP = 1.30, 0.90
LIVE_SPREAD_MAX, PAPER_SPREAD_MAX = 0.10, 0.20


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def iv30_from_contracts(contracts: list[dict[str, Any]], spot: float) -> dict[str, Any] | None:
    by_exp: dict[str, list[dict[str, Any]]] = {}
    for c in contracts:
        dte = _num(c.get("daysToExpiration"))
        if dte is None or not (MIN_DTE <= dte <= MAX_DTE):
            continue
        by_exp.setdefault(c.get("expirationDate"), []).append(c)
    if not by_exp:
        return None
    exp = min(by_exp, key=lambda e: abs((_num(by_exp[e][0].get("daysToExpiration")) or 0) - TARGET_DTE))
    chain = by_exp[exp]
    strike = min({_num(c.get("strikePrice")) for c in chain if _num(c.get("strikePrice"))}, key=lambda k: abs(k - spot))
    legs = [c for c in chain if _num(c.get("strikePrice")) == strike]
    vols = [_num(c.get("volatility")) for c in legs]
    vols = [v / 100.0 for v in vols if v is not None and 0 < v < 500]
    spreads = [_num(c.get("spreadPct")) for c in legs]
    spreads = [s for s in spreads if s is not None and s >= 0]
    if not vols:
        return None
    return {
        "expiration": exp,
        "dte": _num(chain[0].get("daysToExpiration")),
        "strike": strike,
        "iv30": round(sum(vols) / len(vols), 4),
        "atmSpreadPct": round(sum(spreads) / len(spreads), 4) if spreads else None,
        "openInterest": sum(int(_num(c.get("openInterest")) or 0) for c in legs),
    }


def rv_from_atr(atr_percent: Any) -> float | None:
    atr = _num(atr_percent)
    if atr is None or atr <= 0:
        return None
    return round(atr / 100.0 / ATR_TO_SIGMA * math.sqrt(252), 4)


def classify(ratio: float | None) -> str:
    if ratio is None:
        return "unknown"
    if ratio >= RICH:
        return "rich"
    if ratio <= CHEAP:
        return "cheap"
    return "fair"


def build_vol_edge(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    options = json.loads((data_dir / "inferno_schwab_options.json").read_text(encoding="utf-8")) \
        if (data_dir / "inferno_schwab_options.json").exists() else {}
    snapshot = json.loads((data_dir / "latest_snapshot.json").read_text(encoding="utf-8")) \
        if (data_dir / "latest_snapshot.json").exists() else {}
    tracker = {r.get("ticker"): r for r in snapshot.get("rows") or []}
    names = {}
    for row in options.get("rows") or []:
        ticker = row.get("symbol")
        spot = _num(row.get("underlyingPrice"))
        if row.get("status") != "ok" or not ticker or not spot:
            continue
        atm = iv30_from_contracts(row.get("contracts") or [], spot)
        track = tracker.get(ticker) or {}
        rv = rv_from_atr(track.get("atrPercent"))
        ratio = round(atm["iv30"] / rv, 3) if atm and rv else None
        days = _num(track.get("daysUntilEarnings"))
        spread = atm.get("atmSpreadPct") if atm else None
        names[ticker] = {
            "iv30": atm["iv30"] if atm else None,
            "expiration": atm["expiration"] if atm else None,
            "dte": atm["dte"] if atm else None,
            "rvProxy": rv,
            "rvSource": "atr-proxy",
            "ivToRv": ratio,
            "volClass": classify(ratio),
            "eventInWindow": bool(atm and days is not None and 0 <= days <= (atm["dte"] or 0)),
            "atmSpreadPct": spread,
            "liveLiquid": spread is not None and spread <= LIVE_SPREAD_MAX,
            "paperLiquid": spread is not None and spread <= PAPER_SPREAD_MAX,
            "ivRank": _num(track.get("ivRank")),
        }
    return {
        "generatedAt": datetime.now().astimezone().isoformat(),
        "sourceChainAsOf": options.get("generatedAt"),
        "stage": VOL_EDGE_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "thresholds": {"rich": RICH, "cheap": CHEAP, "liveSpreadMax": LIVE_SPREAD_MAX, "paperSpreadMax": PAPER_SPREAD_MAX},
        "coverage": len(names),
        "names": names,
        "citations": ["Carr & Wu (2009), Variance Risk Premiums, RFS",
                      "Bakshi & Kapadia (2003), Delta-Hedged Gains and the Negative Market Volatility Risk Premium, RFS"],
    }


def vol_edge_text(p: dict[str, Any]) -> str:
    lines = ["Inferno Vol Edge (IV30 vs realised, research-only)",
             f"Chains as of {p['sourceChainAsOf']} | names covered: {p['coverage']}", ""]
    for t, n in sorted(p["names"].items(), key=lambda kv: -(kv[1]["ivToRv"] or 0)):
        iv = "n/a" if n["iv30"] is None else f"{n['iv30'] * 100:.0f}%"
        rv = "n/a" if n["rvProxy"] is None else f"{n['rvProxy'] * 100:.0f}%"
        spread = "n/a" if n["atmSpreadPct"] is None else f"{n['atmSpreadPct'] * 100:.0f}%"
        lines.append(f"- {t:5} {n['volClass']:7} IV30 {iv:>5} vs RV {rv:>5} (x{n['ivToRv']}) | spread {spread}"
                     f"{' | earnings inside expiry' if n['eventInWindow'] else ''}{'' if n['paperLiquid'] else ' | ILLIQUID'}")
    lines.append("")
    lines.append("Rich = sell premium (defined risk) candidate; cheap = buy premium candidate; fair = shares.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="IV vs realised volatility (research-only).")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    args = parser.parse_args(argv)
    payload = build_vol_edge()
    if args.command == "run":
        from inferno_io import atomic_write_json, atomic_write_text

        atomic_write_json(OUTPUT_FILE, payload)
        atomic_write_text(TEXT_FILE, vol_edge_text(payload))
    print(vol_edge_text(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
