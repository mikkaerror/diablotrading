#!/usr/bin/env python3
"""Strategy economics / scale-viability model (research-only).

The tooling can now test whether the sell-side edge is real. This module asks the
question that matters even if it IS real: at this account size, what does the
strategy realistically EARN, and is that worth the data cost and the effort?

It models a defined-risk short-premium book with honest inputs and runs a Monte
Carlo over earnings events per year. Per-event outcome (in R, where 1R = capital at
risk per event) is drawn from a distribution with:
  - a mean edge `edge_R` (swept across pessimistic..optimistic),
  - frequent small wins and a capped-but-real loss tail (short-vol shape).

Outputs: expected annual $ P&L and its distribution vs (a) the data subscription
cost and (b) the account itself; and the break-even account size where the
strategy clears its own costs.

Grounding: the literature puts the *selected* single-name earnings short edge at a
fraction of a percent of notional per event (Liu, AFA: +0.39% vs -0.17% day-0 for
rich vs cheap names). Translated to R on a defined-risk condor, that is a small
positive edge for well-selected names, a wash-or-worse otherwise. We sweep it.

Boundary: research-only. No authority/gate/risk change. Illustrative model, not a
promise; real numbers come from the forward test.
"""

from __future__ import annotations

import argparse
import random
import statistics as st
from typing import Any

from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs

# Honest default assumptions (overridable via CLI).
ACCOUNT = 1100.0
RISK_PCT_PER_EVENT = 0.05      # 5% of account at risk per event (aggressive for the size)
EVENTS_PER_YEAR = 50          # selected rich-name sells across a ~40-name universe
DATA_COST_PER_MONTH = 99.0    # Reverify before spend; observed accessible plans start near this
WIN_RATE = 0.64               # short-vol frequent-small-win shape (from the desk's data)
LOSS_CAP_R = 3.0              # defined-risk wing cap
SIMS = 20000
DATA_FILE = DATA_DIR / "inferno_strategy_economics.json"
TEXT_FILE = REPORTS_DIR / "strategy_economics_latest.txt"

# Edge scenarios in R (mean net per-event outcome AFTER friction).
EDGE_SCENARIOS = {
    "pessimistic (-0.10R)": -0.10,
    "breakeven (0.00R)": 0.00,
    "thin edge (+0.05R)": 0.05,
    "best feasible (+0.10R)": 0.10,
}


def mean_loss_r() -> float:
    return -LOSS_CAP_R / 2.0


def max_feasible_edge_r() -> float:
    return WIN_RATE * 1.0 + (1 - WIN_RATE) * mean_loss_r()


def win_magnitude_for_edge(edge_R: float) -> float:
    mean_loss = -LOSS_CAP_R / 2.0
    w = (edge_R - (1 - WIN_RATE) * mean_loss) / WIN_RATE
    if w > 1.0:
        raise ValueError(
            f"edge_R={edge_R:.2f} requires wins of {w:.2f}R, above the +1R credit cap"
        )
    if w < 0.0:
        raise ValueError(f"edge_R={edge_R:.2f} requires negative winning trades")
    return w


def _event_r(edge_R: float, rng: random.Random) -> float:
    """Draw one short-vol event in R while preserving the requested mean edge."""
    w = win_magnitude_for_edge(edge_R)
    if rng.random() < WIN_RATE:
        return w
    return -rng.uniform(0.0, LOSS_CAP_R)


def simulate(edge_R: float, account: float, risk_pct: float,
             events: int, sims: int, seed: int = 11) -> dict[str, Any]:
    rng = random.Random(seed)
    risk_dollars = account * risk_pct
    year_pnls = []
    max_dd = []
    for _ in range(sims):
        pnl = 0.0
        peak = 0.0
        trough = 0.0
        for _ in range(events):
            pnl += _event_r(edge_R, rng) * risk_dollars
            peak = max(peak, pnl)
            trough = min(trough, pnl - peak)
        year_pnls.append(pnl)
        max_dd.append(trough)
    year_pnls.sort()
    def pct(p): return year_pnls[int(p * len(year_pnls))]
    return {
        "edgeR": edge_R,
        "riskDollarsPerEvent": round(risk_dollars, 2),
        "meanAnnualPnl": round(st.mean(year_pnls), 2),
        "medianAnnualPnl": round(st.median(year_pnls), 2),
        "p10": round(pct(0.10), 2),
        "p90": round(pct(0.90), 2),
        "probLossYear": round(sum(1 for x in year_pnls if x < 0) / len(year_pnls), 3),
        "meanMaxDrawdown": round(st.mean(max_dd), 2),
        "worst1pct": round(pct(0.01), 2),
    }


def breakeven_account(edge_R: float, risk_pct: float, events: int,
                      data_cost_year: float) -> Optional[float]:
    """Account size at which mean annual P&L == annual data cost."""
    # mean annual pnl = account * risk_pct * events * edge_R  (linear in account)
    per_dollar = risk_pct * events * edge_R
    if per_dollar <= 0:
        return None
    return round(data_cost_year / per_dollar, 0)


def build(account: float = ACCOUNT, risk_pct: float = RISK_PCT_PER_EVENT,
          events: int = EVENTS_PER_YEAR, data_cost_month: float = DATA_COST_PER_MONTH,
          sims: int = SIMS) -> dict[str, Any]:
    data_year = data_cost_month * 12
    scenarios = {name: simulate(e, account, risk_pct, events, sims)
                 for name, e in EDGE_SCENARIOS.items()}
    breakevens = {name: breakeven_account(e, risk_pct, events, data_year)
                  for name, e in EDGE_SCENARIOS.items()}
    return {
        "stage": "strategy-economics-research-only",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "assumptions": {
            "account": account, "riskPctPerEvent": risk_pct,
            "eventsPerYear": events, "dataCostPerYear": data_year,
            "winRate": WIN_RATE, "lossCapR": LOSS_CAP_R, "sims": sims,
            "maxFeasibleEdgeR": round(max_feasible_edge_r(), 4),
        },
        "scenarios": scenarios,
        "breakevenAccountForDataCost": breakevens,
    }


def save_strategy_economics(payload: dict[str, Any]) -> dict[str, str]:
    ensure_dirs()
    atomic_write_json(DATA_FILE, payload)
    atomic_write_text(TEXT_FILE, text(payload) + "\n")
    return {"data": str(DATA_FILE), "report": str(TEXT_FILE)}


def text(p: dict[str, Any]) -> str:
    a = p["assumptions"]
    L = ["Inferno Strategy Economics / Scale Viability (research-only)",
         f"Account ${a['account']:.0f} | risk {a['riskPctPerEvent']*100:.0f}%/event "
         f"(${a['account']*a['riskPctPerEvent']:.0f}) | {a['eventsPerYear']} events/yr "
         f"| data ${a['dataCostPerYear']:.0f}/yr | win {a['winRate']*100:.0f}% | "
         f"tail cap -{a['lossCapR']:.0f}R",
         ""]
    L.append(f"{'scenario':<22}{'meanP&L':>9}{'medP&L':>8}{'p10':>8}{'p90':>8}"
             f"{'lossYr%':>9}{'meanMaxDD':>10}")
    for name, s in p["scenarios"].items():
        L.append(f"{name:<22}{s['meanAnnualPnl']:>9.0f}{s['medianAnnualPnl']:>8.0f}"
                 f"{s['p10']:>8.0f}{s['p90']:>8.0f}{s['probLossYear']*100:>8.0f}%"
                 f"{s['meanMaxDrawdown']:>10.0f}")
    L.append("")
    L.append("Break-even account size to cover data cost alone "
             f"(${a['dataCostPerYear']:.0f}/yr):")
    for name, be in p["breakevenAccountForDataCost"].items():
        L.append(f"  {name:<22} " + (f"${be:,.0f}" if be else "never (no edge)"))
    L.append("")
    L.append("Read: all dollar figures are ANNUAL. At this account size the edge, "
             "even if real, produces small dollars and the data can cost more than "
             "the strategy makes. Pricing must be reverified before spend. "
             "Research-only; illustrative, not a promise.")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--account", type=float, default=ACCOUNT)
    ap.add_argument("--risk-pct", type=float, default=RISK_PCT_PER_EVENT)
    ap.add_argument("--events", type=int, default=EVENTS_PER_YEAR)
    ap.add_argument("--data-cost-month", type=float, default=DATA_COST_PER_MONTH)
    ap.add_argument("--sims", type=int, default=SIMS)
    ap.add_argument("--write", action="store_true", help="Write data/report artifacts")
    args = ap.parse_args(argv)
    p = build(args.account, args.risk_pct, args.events, args.data_cost_month, args.sims)
    if args.write:
        save_strategy_economics(p)
    print(text(p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
