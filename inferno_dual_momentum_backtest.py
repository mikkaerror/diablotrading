#!/usr/bin/env python3
"""Dual-momentum ETF backtest (research-only).

Tests the one accessible edge from docs/STRATEGY_LANDSCAPE_ACCESSIBLE_EDGES: a
simple, cheap, near-passive trend/dual-momentum rule on liquid ETFs — the opposite
of the pre-earnings-vol work, and the only thing that can actually be RUN at a
~$1,100 account (fractional shares, near-zero friction, free data).

Rule (Global-Equities-Momentum style, monthly):
  - Compute each risk asset's trailing LOOKBACK-month total return.
  - Pick the strongest risk asset. If its trailing return exceeds the SAFE asset's
    trailing return (absolute-momentum filter), hold it next month; else hold the
    SAFE asset (bonds/cash). This is what moves you out of stocks in downtrends and
    controls drawdown.
  - Charge COST_BPS per switch (round-trip friction; ETFs are cheap).

Input: a CSV of MONTH-END total-return closes:
    date,SPY,AGG[,EFA,...]      (date YYYY-MM-DD; one row per month; dividend-adj)
The last column-set are asset price levels. Designate the safe asset by name.

Outputs: CAGR, annualized vol, Sharpe, max drawdown for the strategy vs buy&hold of
each asset, plus the $ path on the account. Compares whether the timing overlay
actually earns its keep (return) and/or controls drawdown vs just holding SPY.

Boundary: research-only. Illustrative backtest on historical data; past results are
not future returns. No authority/gate/risk change.
"""

from __future__ import annotations

import argparse
import csv
import statistics as st
from typing import Any, Optional

LOOKBACK = 12          # months of trailing return for momentum
COST_BPS = 5.0         # round-trip switch cost in basis points (liquid ETFs)
ANNUAL_RF = 0.03       # risk-free for Sharpe (approx)


def load_prices(csv_path: str) -> tuple[list[str], dict[str, list[float]]]:
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = [c for c in (reader.fieldnames or []) if c and c != "date"]
        dates: list[str] = []
        series: dict[str, list[float]] = {c: [] for c in cols}
        for row in reader:
            dates.append(row["date"])
            for c in cols:
                series[c].append(float(row[c]))
    return dates, series


def _trailing_return(levels: list[float], i: int, lookback: int) -> Optional[float]:
    if i - lookback < 0:
        return None
    past = levels[i - lookback]
    return (levels[i] / past - 1.0) if past else None


def _stats(monthly_returns: list[float]) -> dict[str, float]:
    if not monthly_returns:
        return {"cagr": 0.0, "vol": 0.0, "sharpe": 0.0, "maxDD": 0.0}
    growth = 1.0
    for r in monthly_returns:
        growth *= (1 + r)
    years = len(monthly_returns) / 12.0
    cagr = growth ** (1 / years) - 1 if years > 0 else 0.0
    vol = (st.pstdev(monthly_returns) * (12 ** 0.5)) if len(monthly_returns) > 1 else 0.0
    sharpe = ((cagr - ANNUAL_RF) / vol) if vol else 0.0
    # max drawdown on the equity curve
    eq = 1.0
    peak = 1.0
    mdd = 0.0
    for r in monthly_returns:
        eq *= (1 + r)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    return {"cagr": round(cagr, 4), "vol": round(vol, 4),
            "sharpe": round(sharpe, 2), "maxDD": round(mdd, 4)}


def backtest(dates: list[str], series: dict[str, list[float]], safe: str,
             lookback: int = LOOKBACK, cost_bps: float = COST_BPS,
             account: float = 1100.0) -> dict[str, Any]:
    assets = list(series.keys())
    risk_assets = [a for a in assets if a != safe]
    n = len(dates)
    strat_returns: list[float] = []
    holdings: list[str] = []
    prev_hold: Optional[str] = None
    switches = 0

    for i in range(lookback, n - 1):
        # rank risk assets by trailing return; apply absolute-momentum filter vs safe
        best, best_ret = None, None
        for a in risk_assets:
            tr = _trailing_return(series[a], i, lookback)
            if tr is None:
                continue
            if best_ret is None or tr > best_ret:
                best, best_ret = a, tr
        safe_ret = _trailing_return(series[safe], i, lookback)
        hold = safe if (best is None or best_ret is None or safe_ret is None
                        or best_ret <= safe_ret) else best
        # next-month realized return of the held asset
        nxt = series[hold][i + 1] / series[hold][i] - 1.0
        if prev_hold is not None and hold != prev_hold:
            nxt -= cost_bps / 10000.0
            switches += 1
        strat_returns.append(nxt)
        holdings.append(hold)
        prev_hold = hold

    # buy & hold benchmarks over the same evaluated window
    span = slice(lookback, n - 1)
    bench = {}
    for a in assets:
        rets = [series[a][i + 1] / series[a][i] - 1.0 for i in range(lookback, n - 1)]
        bench[a] = _stats(rets)

    strat = _stats(strat_returns)
    # $ path on the account
    end_mult = 1.0
    for r in strat_returns:
        end_mult *= (1 + r)
    from collections import Counter
    return {
        "stage": "dual-momentum-backtest-research-only",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "window": [dates[lookback], dates[n - 1]],
        "months": len(strat_returns),
        "lookback": lookback,
        "costBps": cost_bps,
        "safeAsset": safe,
        "riskAssets": risk_assets,
        "switches": switches,
        "holdingsDistribution": dict(Counter(holdings)),
        "strategy": strat,
        "buyHold": bench,
        "account": account,
        "accountEndValueStrategy": round(account * end_mult, 2),
        "accountEndValueHoldSPY": (
            round(account * (1 + bench.get("SPY", {}).get("cagr", 0)) ** (len(strat_returns)/12), 2)
            if "SPY" in bench else None
        ),
    }


def text(p: dict[str, Any]) -> str:
    L = ["Inferno Dual-Momentum ETF Backtest (research-only)",
         f"Window {p['window'][0]} -> {p['window'][1]} | {p['months']} months | "
         f"lookback {p['lookback']}m | cost {p['costBps']}bps/switch | "
         f"safe={p['safeAsset']} | switches={p['switches']}",
         ""]
    s = p["strategy"]
    L.append(f"{'':<14}{'CAGR':>8}{'vol':>8}{'Sharpe':>8}{'maxDD':>8}")
    L.append(f"{'DUAL-MOM':<14}{s['cagr']*100:>7.1f}%{s['vol']*100:>7.1f}%"
             f"{s['sharpe']:>8.2f}{s['maxDD']*100:>7.1f}%")
    for a, b in p["buyHold"].items():
        L.append(f"{'hold '+a:<14}{b['cagr']*100:>7.1f}%{b['vol']*100:>7.1f}%"
                 f"{b['sharpe']:>8.2f}{b['maxDD']*100:>7.1f}%")
    L.append("")
    L.append(f"Holdings over time: {p['holdingsDistribution']}")
    L.append(f"${p['account']:.0f} -> ${p['accountEndValueStrategy']:.0f} "
             f"(dual-mom) vs ${p['accountEndValueHoldSPY']:.0f} (hold SPY)"
             if p.get("accountEndValueHoldSPY") else
             f"${p['account']:.0f} -> ${p['accountEndValueStrategy']:.0f} (dual-mom)")
    L.append("")
    L.append("Read: the timing overlay earns its keep if it either beats hold-SPY "
             "return OR cuts the drawdown materially at similar return. Illustrative "
             "backtest on historical data; not a promise. Research-only.")
    return "\n".join(L)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", required=True, help="month-end price CSV (date,ASSET,...)")
    ap.add_argument("--safe", default="AGG", help="safe asset column name")
    ap.add_argument("--lookback", type=int, default=LOOKBACK)
    ap.add_argument("--cost-bps", type=float, default=COST_BPS)
    ap.add_argument("--account", type=float, default=1100.0)
    args = ap.parse_args(argv)
    dates, series = load_prices(args.csv)
    p = backtest(dates, series, args.safe, args.lookback, args.cost_bps, args.account)
    print(text(p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
