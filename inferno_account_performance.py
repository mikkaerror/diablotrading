from __future__ import annotations

"""Flow-adjusted account performance: the number the desk never measured.

NLV alone mixes trading results with deposits and withdrawals. This module
builds a time-weighted return (TWR) index from data/nlv_history.csv, removing
external cash flows, and reports:

  - TWR since the first snapshot and over the benchmark window
  - money-weighted P/L (end - start - net external flows)
  - high-water drawdown on the TWR index (deposits cannot "heal" it)
  - SPY over the same window, when benchmark anchors exist
  - peak integrity: whether the drawdown stepper's stored peak NLV is
    supported by the NLV history at all

External flows come from the Schwab transaction ledger (CASH_RECEIPT /
CASH_DISBURSEMENT) plus data/inferno_external_flows.csv for flows older than
the ledger window (each row carries its own provenance, e.g. "inferred").

Research/reporting only. It does not change the drawdown stepper, any risk
constant, or authority; Codex's capital lane may consume `twrDrawdown`.
"""

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

ACCOUNT_PERFORMANCE_STAGE = "account-performance-research-only"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
OUTPUT_FILE = DATA_DIR / "inferno_account_performance.json"
TEXT_FILE = REPORTS_DIR / "account_performance_latest.txt"
BENCHMARK_FILE = DATA_DIR / "inferno_benchmark_prices.csv"
FLOWS_FILE = DATA_DIR / "inferno_external_flows.csv"
PEAK_OUTLIER_RATIO = 1.25  # stored peak > 125% of the highest recorded NLV

CITATIONS = [
    "CFA Institute GIPS: time-weighted return removes external cash flows",
    "docs/DESK_AUDIT_2026-09-28.md (measurement gaps M1-M2)",
]


def _num(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def load_nlv_series(path: Path) -> list[tuple[date, float]]:
    """Last valid NLV per date, in date order."""
    by_day: dict[date, float] = {}
    try:
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                day, nlv = _date(row.get("date")), _num(row.get("nlv"))
                if day and nlv is not None and nlv > 0:
                    by_day[day] = nlv
    except OSError:
        return []
    return sorted(by_day.items())


def load_flows(ledger: dict[str, Any], flows_path: Path) -> dict[date, float]:
    flows: dict[date, float] = {}
    for tx in ledger.get("transactions") or []:
        if tx.get("transactionType") not in {"CASH_RECEIPT", "CASH_DISBURSEMENT"}:
            continue
        day, amount = _date(tx.get("occurredAt")), _num(tx.get("netAmount"))
        if day and amount:
            flows[day] = flows.get(day, 0.0) + amount
    try:
        with flows_path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                day, amount = _date(row.get("date")), _num(row.get("amount"))
                if day and amount and day not in flows:
                    flows[day] = amount
    except OSError:
        pass
    return flows


def load_benchmark(path: Path, symbol: str = "SPY") -> list[tuple[date, float]]:
    points: dict[date, float] = {}
    try:
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("symbol") != symbol:
                    continue
                day, close = _date(row.get("date")), _num(row.get("close"))
                if day and close:
                    points[day] = close
    except OSError:
        return []
    return sorted(points.items())


def twr_index(series: list[tuple[date, float]], flows: dict[date, float]) -> list[tuple[date, float]]:
    """Chain sub-period returns; a flow dated in (prev, day] is added to the start value."""
    if not series:
        return []
    index = [(series[0][0], 1.0)]
    level = 1.0
    for (prev_day, prev_nlv), (day, nlv) in zip(series, series[1:]):
        flow = sum(amount for when, amount in flows.items() if prev_day < when <= day)
        base = prev_nlv + flow
        if base <= 0:
            continue
        level *= nlv / base
        index.append((day, level))
    return index


def max_drawdown(index: list[tuple[date, float]]) -> tuple[float, date | None, date | None]:
    peak, peak_day, worst, worst_peak, worst_day = 0.0, None, 0.0, None, None
    for day, level in index:
        if level > peak:
            peak, peak_day = level, day
        drawdown = level / peak - 1.0 if peak else 0.0
        if drawdown < worst:
            worst, worst_peak, worst_day = drawdown, peak_day, day
    return worst, worst_peak, worst_day


def build_account_performance(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    series = load_nlv_series(data_dir / "nlv_history.csv")
    ledger = {}
    try:
        ledger = json.loads((data_dir / "inferno_schwab_transaction_ledger.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    flows = load_flows(ledger, data_dir / FLOWS_FILE.name)
    payload: dict[str, Any] = {
        "stage": ACCOUNT_PERFORMANCE_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "citations": CITATIONS,
    }
    if len(series) < 2:
        payload.update(verdict="insufficient-history", snapshots=len(series))
        return payload
    index = twr_index(series, flows)
    start_day, start_nlv = series[0]
    end_day, end_nlv = series[-1]
    net_flows = sum(amount for when, amount in flows.items() if start_day < when <= end_day)
    drawdown, dd_peak, dd_trough = max_drawdown(index)
    current_dd = index[-1][1] / max(level for _, level in index) - 1.0

    bench = load_benchmark(data_dir / BENCHMARK_FILE.name)
    bench_return = None
    bench_window = None
    if len(bench) >= 2:
        b0 = next(((d, p) for d, p in bench if d >= start_day), None)
        b1 = [(d, p) for d, p in bench if d <= end_day]
        if b0 and b1 and b1[-1][0] > b0[0]:
            bench_return = b1[-1][1] / b0[1] - 1.0
            bench_window = [b0[0].isoformat(), b1[-1][0].isoformat()]
    acct_in_window = None
    if bench_window:
        lvl = dict(index)
        s = max((d for d in lvl if d <= date.fromisoformat(bench_window[0])), default=None)
        e = max((d for d in lvl if d <= date.fromisoformat(bench_window[1])), default=None)
        if s and e and e > s:
            acct_in_window = lvl[e] / lvl[s] - 1.0

    state = {}
    try:
        state = json.loads((data_dir / "inferno_capital_scaling_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    stored_peak = _num(state.get("peakNlv"))
    recorded_max = max(nlv for _, nlv in series)
    peak_ok = stored_peak is None or stored_peak <= recorded_max * PEAK_OUTLIER_RATIO

    payload.update(
        verdict="measured",
        window=[start_day.isoformat(), end_day.isoformat()],
        snapshots=len(series),
        startNlv=start_nlv,
        endNlv=end_nlv,
        netExternalFlows=round(net_flows, 2),
        flows=[{"date": d.isoformat(), "amount": round(a, 2)} for d, a in sorted(flows.items())],
        moneyWeightedPnl=round(end_nlv - start_nlv - net_flows, 2),
        twrSinceStart=round(index[-1][1] - 1.0, 4),
        twrDrawdownMax=round(drawdown, 4),
        twrDrawdownPeak=dd_peak.isoformat() if dd_peak else None,
        twrDrawdownTrough=dd_trough.isoformat() if dd_trough else None,
        twrDrawdownCurrent=round(current_dd, 4),
        benchmark={"symbol": "SPY", "window": bench_window,
                   "return": None if bench_return is None else round(bench_return, 4),
                   "accountTwrSameWindow": None if acct_in_window is None else round(acct_in_window, 4)},
        peakIntegrity={
            "storedPeakNlv": stored_peak,
            "storedPeakAt": state.get("peakNlvAt"),
            "highestRecordedNlv": recorded_max,
            "supported": peak_ok,
            "note": None if peak_ok else
            "stored peak is not supported by NLV history; drawdown stepper is measuring from an outlier",
        },
    )
    return payload


def _pct(value: Any) -> str:
    return "n/a" if value is None else f"{value * 100:+.1f}%"


def account_performance_text(p: dict[str, Any]) -> str:
    lines = ["Inferno Account Performance (flow-adjusted, research-only)", ""]
    if p.get("verdict") != "measured":
        return "\n".join(lines + [f"Verdict: {p.get('verdict')}"]) + "\n"
    b = p["benchmark"]
    pk = p["peakIntegrity"]
    lines += [
        f"Window: {p['window'][0]} -> {p['window'][1]} ({p['snapshots']} snapshots)",
        f"NLV: ${p['startNlv']:,.2f} -> ${p['endNlv']:,.2f} | net external flows ${p['netExternalFlows']:+,.2f}",
        f"Money-weighted P/L: ${p['moneyWeightedPnl']:+,.2f}",
        f"Time-weighted return: {_pct(p['twrSinceStart'])}",
        f"TWR drawdown: max {_pct(p['twrDrawdownMax'])} ({p['twrDrawdownPeak']} -> {p['twrDrawdownTrough']}), "
        f"current {_pct(p['twrDrawdownCurrent'])}",
        f"SPY same window: {_pct(b['return'])} vs account {_pct(b['accountTwrSameWindow'])}"
        + (f" ({b['window'][0]} -> {b['window'][1]})" if b["window"] else " (no benchmark anchors)"),
        f"Peak integrity: {'OK' if pk['supported'] else 'OUTLIER'} | stored ${pk['storedPeakNlv']} at "
        f"{pk['storedPeakAt']} vs highest recorded ${pk['highestRecordedNlv']:,.2f}",
    ]
    if pk["note"]:
        lines.append(f"  -> {pk['note']}")
    lines.append("")
    lines.append("Flows used: " + ", ".join(f"{f['date']} {f['amount']:+,.0f}" for f in p["flows"]))
    lines.append("Research only. Does not change the drawdown stepper or any risk constant.")
    return "\n".join(lines) + "\n"


def record_benchmark_close(data_dir: Path = DATA_DIR) -> None:
    """Append today's SPY close from exposure analytics (local artifact, no network)."""
    try:
        exposure = json.loads((data_dir / "inferno_exposure_analytics.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    regime = exposure.get("marketRegime") or {}
    close = _num(regime.get("spyClose"))
    day = _date(exposure.get("generatedAt"))
    if not close or not day:
        return
    path = data_dir / BENCHMARK_FILE.name
    existing = {(d.isoformat(), round(p, 2)) for d, p in load_benchmark(path)}
    if any(d == day.isoformat() for d, _ in existing):
        return
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(["date", "symbol", "close", "source"])
        writer.writerow([day.isoformat(), "SPY", close, "exposure-analytics"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Flow-adjusted account performance (research-only).")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    args = parser.parse_args(argv)
    if args.command == "run":
        record_benchmark_close()
    payload = build_account_performance()
    if args.command == "run":
        from inferno_io import atomic_write_json, atomic_write_text

        atomic_write_json(OUTPUT_FILE, payload)
        atomic_write_text(TEXT_FILE, account_performance_text(payload))
    print(account_performance_text(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
