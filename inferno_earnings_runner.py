from __future__ import annotations

"""Earnings Runner Campaign collector (research-only, shadow).

Pre-registered in docs/EARNINGS_RUNNER_PREREG_2026-09-30.md. Three arms,
scored separately, full bid/ask crossing both ways, never estimated:

  A  run-up   buy the ATM straddle 3-10 days before earnings on a quiet day,
              sell at the last capture before the report (never held through)
  B  runner   after a gap that held, a debit spread in the gap's direction,
              exit +50% / 10 trading days / expiry
  C  calls    Mikka's tagged ticker + direction, same structure as B

Reads the Schwab chain tape, the snapshot, and Schwab price history. Writes
only its own ledger/report. Never stages, approves, or submits; no authority,
broker, or risk-constant change.
"""

import argparse
import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
OPTIONS_FILE = DATA_DIR / "inferno_schwab_options.json"
SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
HISTORY_FILE = DATA_DIR / "inferno_schwab_price_history.json"
CALLS_FILE = DATA_DIR / "operator_earnings_calls.csv"
LEDGER_FILE = DATA_DIR / "inferno_earnings_runner.json"
REPORT_FILE = REPORTS_DIR / "earnings_runner_latest.txt"

STAGE = "earnings-runner-research-only"
PREREG = "docs/EARNINGS_RUNNER_PREREG_2026-09-30.md"
RUNUP_MIN_DAYS, RUNUP_MAX_DAYS = 3, 10
RUNUP_MAX_DTE = 21
QUIET_ATR_FRACTION = 0.5
GAP_IM_FRACTION, GAP_MIN = 0.75, 0.05
SPREAD_DTE_TARGET, SPREAD_DTE_MIN, SPREAD_DTE_MAX = 35, 21, 60
TAKE_PROFIT = 0.5
MAX_HOLD_TRADING_DAYS = 10
LONG_LEG_MAX_SPREAD, SHORT_LEG_MAX_SPREAD = 0.25, 0.50
ARMS = {"A": "run-up", "B": "runner", "C": "your calls"}


# ---------------------------------------------------------------- helpers

def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def trading_days_between(start: date, end: date) -> int:
    days, cur = 0, start
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


def _spread_ok(quote: tuple[float, float], limit: float) -> bool:
    bid, ask = quote
    mid = (bid + ask) / 2
    return mid > 0 and (ask - bid) / mid <= limit


def chain_index(contracts: list[dict[str, Any]]) -> dict[tuple[str, date, float], tuple[float, float]]:
    out = {}
    for c in contracts:
        exp, strike = _date(c.get("expirationDate")), _num(c.get("strikePrice"))
        bid, ask = _num(c.get("bid")), _num(c.get("ask"))
        if exp is None or strike is None or bid is None or ask is None or ask <= 0 or bid < 0 or ask < bid:
            continue
        out[(str(c.get("putCall")).upper(), exp, strike)] = (bid, ask)
    return out


def candles_by_date(history_row: dict[str, Any] | None) -> dict[date, dict[str, float]]:
    out = {}
    for c in (history_row or {}).get("candles") or []:
        d = _date(c.get("datetime") or c.get("date"))
        if d:
            out[d] = {k: _num(c.get(k)) for k in ("open", "high", "low", "close")}
    return out


# ---------------------------------------------------------------- structures

def build_straddle(chain: dict, spot: float, earnings: date, today: date) -> tuple[dict | None, str]:
    exps = sorted({e for (_, e, _) in chain if e > earnings and (e - today).days <= RUNUP_MAX_DTE})
    if not exps:
        return None, "no expiration after earnings within 21 DTE"
    exp = exps[0]
    strikes = sorted({k for (s, e, k) in chain if e == exp and ("CALL", e, k) in chain and ("PUT", e, k) in chain})
    if not strikes:
        return None, "no paired strikes"
    k = min(strikes, key=lambda x: abs(x - spot))
    call, put = chain[("CALL", exp, k)], chain[("PUT", exp, k)]
    if not (_spread_ok(call, LONG_LEG_MAX_SPREAD) and _spread_ok(put, LONG_LEG_MAX_SPREAD)):
        return None, "ATM spreads wider than 25%"
    return {"structure": "LONG_STRADDLE", "expiration": exp.isoformat(), "strike": k,
            "legs": [["CALL", k, "long"], ["PUT", k, "long"]],
            "entry": round(call[1] + put[1], 4),
            "impliedMovePct": round(((call[0] + call[1]) / 2 + (put[0] + put[1]) / 2) / spot, 4)}, ""


def build_debit_spread(chain: dict, spot: float, direction: str, move: float, today: date) -> tuple[dict | None, str]:
    side = "CALL" if direction == "up" else "PUT"
    exps = [e for (s, e, _) in chain if s == side and SPREAD_DTE_MIN <= (e - today).days <= SPREAD_DTE_MAX]
    if not exps:
        return None, "no 21-60 DTE expiration"
    exp = min(set(exps), key=lambda e: abs((e - today).days - SPREAD_DTE_TARGET))
    strikes = sorted(k for (s, e, k) in chain if s == side and e == exp)
    long_k = min(strikes, key=lambda x: abs(x - spot))
    distance = max(move, GAP_MIN) * spot
    if direction == "up":
        shorts = [k for k in strikes if k >= long_k + distance]
        short_k = min(shorts) if shorts else None
    else:
        shorts = [k for k in strikes if k <= long_k - distance]
        short_k = max(shorts) if shorts else None
    if short_k is None:
        return None, "chain does not reach the short strike"
    lq, sq = chain[(side, exp, long_k)], chain[(side, exp, short_k)]
    if not _spread_ok(lq, LONG_LEG_MAX_SPREAD) or not _spread_ok(sq, SHORT_LEG_MAX_SPREAD):
        return None, "leg spreads too wide"
    debit = lq[1] - sq[0]
    width = abs(short_k - long_k)
    if debit <= 0 or debit >= width:
        return None, "no sensible debit after crossing"
    return {"structure": f"{side}_DEBIT_SPREAD", "expiration": exp.isoformat(), "direction": direction,
            "legs": [[side, long_k, "long"], [side, short_k, "short"]], "width": width,
            "entry": round(debit, 4)}, ""


def mark(record: dict[str, Any], chain: dict) -> float | None:
    """Natural exit value: longs sold at the bid, shorts bought at the ask."""
    exp = _date(record["expiration"])
    value = 0.0
    for side, strike, role in record["legs"]:
        q = chain.get((side, exp, float(strike)))
        if q is None:
            return None
        value += q[0] if role == "long" else -q[1]
    return round(value, 4)


def intrinsic(record: dict[str, Any], close: float) -> float:
    value = 0.0
    for side, strike, role in record["legs"]:
        iv = max(0.0, close - strike) if side == "CALL" else max(0.0, strike - close)
        value += iv if role == "long" else -iv
    return round(value, 4)


# ---------------------------------------------------------------- calendar & triggers

def update_calendar(ledger: dict, snapshot_rows: dict, options_rows: dict, today: date) -> list[dict]:
    """Track each name's upcoming report; return reports that have just passed."""
    cal = ledger.setdefault("calendar", {})
    passed = []
    for ticker, row in snapshot_rows.items():
        nxt = _date(row.get("nextEarnings"))
        prev = cal.get(ticker) or {}
        prev_date = _date(prev.get("earnings"))
        if prev_date and prev_date < today and (nxt is None or nxt != prev_date) and not prev.get("reported"):
            passed.append({"ticker": ticker, "earnings": prev_date, "impliedMovePct": prev.get("impliedMovePct")})
            prev["reported"] = True
            ledger.setdefault("reported", {})[f"{ticker}|{prev_date.isoformat()}"] = prev
        if nxt and (not prev_date or nxt != prev_date):
            cal[ticker] = {"earnings": nxt.isoformat()}
        opt = options_rows.get(ticker)
        if opt and nxt and 0 <= (nxt - today).days <= RUNUP_MAX_DAYS:
            im = _num(opt.get("atmImpliedMovePct"))
            if im:
                cal[ticker]["impliedMovePct"] = im
    return passed


def gap_that_held(candles: dict[date, dict], earnings: date) -> dict | None:
    before = [d for d in candles if d < earnings]
    after = [d for d in candles if d > earnings]
    if not before or not after:
        return None
    b, a = candles[max(before)], candles[min(after)]
    if not b.get("close") or not a.get("close") or a.get("high") is None or a.get("low") is None:
        return None
    move = a["close"] / b["close"] - 1
    rng = a["high"] - a["low"]
    loc = (a["close"] - a["low"]) / rng if rng > 0 else 0.5
    return {"move": round(move, 4), "closeLocation": round(loc, 3), "reactionDate": min(after).isoformat()}


# ---------------------------------------------------------------- run

def _new(ledger: dict, arm: str, ticker: str, event: str, today: date, captured: str, spot: float, built: dict, **extra) -> dict:
    rec = {"arm": arm, "ticker": ticker, "eventId": event, "enteredOn": today.isoformat(), "capturedAt": captured,
           "spot": spot, **built, **extra, "status": "open", "shadowOnly": True}
    ledger.setdefault("records", []).append(rec)
    return rec


def load_calls(path: Path = CALLS_FILE) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8") as h:
            return list(csv.DictReader(h))
    except OSError:
        return []


def collect(ledger: dict, options: dict, snapshot: dict, history: dict, calls: list[dict], today: date) -> dict:
    captured = options.get("generatedAt")
    orows = {str(r.get("symbol")).upper(): r for r in options.get("rows") or [] if r.get("status") == "ok"}
    srows = {str(r.get("ticker")).upper(): r for r in snapshot.get("rows") or [] if r.get("ticker")}
    hrows = {str(r.get("symbol")).upper(): r for r in history.get("rows") or []}
    chains = {t: chain_index(r.get("contracts") or []) for t, r in orows.items()}
    seen = {(r["arm"], r["eventId"]) for r in ledger.get("records") or []}
    skips: list[str] = []
    added = 0

    # exits first (so a record never enters and exits on the same tape)
    for rec in ledger.get("records") or []:
        if rec["status"] != "open":
            continue
        entered = _date(rec["enteredOn"])
        chain = chains.get(rec["ticker"])
        exp = _date(rec["expiration"])
        if rec["arm"] == "A":
            earnings = _date(rec["earnings"])
            if chain is not None and today < earnings and today > entered:
                value = mark(rec, chain)
                if value is not None:
                    rec["lastMark"] = {"on": today.isoformat(), "value": value}
            if today >= earnings:
                last = rec.get("lastMark")
                if last:
                    _close(rec, last["value"], last["on"], "sold at the last capture before the report")
                else:
                    rec["status"] = "unscored"
                    rec["note"] = "no chain capture between entry and the report"
            continue
        if today <= entered:
            continue
        if exp and today > exp:
            candles = candles_by_date(hrows.get(rec["ticker"]))
            close = (candles.get(exp) or {}).get("close")
            if close:
                _close(rec, intrinsic(rec, close), exp.isoformat(), "expired: intrinsic at the expiration close")
            else:
                rec["status"] = "unscored"
                rec["note"] = "expired without a close in price history"
            continue
        value = mark(rec, chain) if chain is not None else None
        held = trading_days_between(entered, today)
        if value is not None and value >= rec["entry"] * (1 + TAKE_PROFIT):
            _close(rec, value, today.isoformat(), "take-profit +50%")
        elif held >= MAX_HOLD_TRADING_DAYS:
            if value is not None:
                _close(rec, value, today.isoformat(), "time exit (10 trading days)")
            else:
                rec["status"] = "unscored"
                rec["note"] = "no chain quote on the time-exit day"

    # Arm A entries
    for ticker, row in srows.items():
        earnings = _date(row.get("nextEarnings"))
        chain = chains.get(ticker)
        if not earnings or chain is None:
            continue
        days = (earnings - today).days
        event = f"{ticker}|{earnings.isoformat()}"
        if not RUNUP_MIN_DAYS <= days <= RUNUP_MAX_DAYS or ("A", event) in seen:
            continue
        candles = candles_by_date(hrows.get(ticker))
        prior = sorted(d for d in candles if d < today)
        atr = _num(row.get("atrPercent"))
        if len(prior) >= 2 and atr:
            last, before = candles[prior[-1]]["close"], candles[prior[-2]]["close"]
            if last and before and abs(last / before - 1) * 100 >= QUIET_ATR_FRACTION * atr:
                skips.append(f"A {ticker}: not a quiet day")
                continue
        spot = _num(orows[ticker].get("underlyingPrice"))
        built, reason = build_straddle(chain, spot, earnings, today) if spot else (None, "no spot")
        if not built:
            skips.append(f"A {ticker}: {reason}")
            continue
        _new(ledger, "A", ticker, event, today, captured, spot, built, earnings=earnings.isoformat())
        seen.add(("A", event))
        added += 1

    # Arm B triggers: reports that just passed
    passed = update_calendar(ledger, srows, orows, today)
    pending = ledger.setdefault("runnerWatch", {})
    for p in passed:
        pending[f"{p['ticker']}|{p['earnings'].isoformat()}"] = {
            "ticker": p["ticker"], "earnings": p["earnings"].isoformat(), "impliedMovePct": p.get("impliedMovePct")}
    for event, w in list(pending.items()):
        ticker, earnings = w["ticker"], _date(w["earnings"])
        if trading_days_between(earnings, today) > 3:
            pending.pop(event)
            skips.append(f"B {ticker}: no chain within 2 trading days of the reaction")
            continue
        gap = gap_that_held(candles_by_date(hrows.get(ticker)), earnings)
        if gap is None:
            continue  # reaction candle not in yet
        im = _num(w.get("impliedMovePct")) or 0.0
        need = max(GAP_IM_FRACTION * im, GAP_MIN)
        up = gap["move"] >= need and gap["closeLocation"] >= 2 / 3
        down = gap["move"] <= -need and gap["closeLocation"] <= 1 / 3
        if not (up or down):
            pending.pop(event)
            ledger.setdefault("nonTriggers", []).append({"eventId": event, **gap, "needed": round(need, 4)})
            continue
        chain = chains.get(ticker)
        if chain is None or ("B", event) in seen:
            continue
        spot = _num(orows[ticker].get("underlyingPrice"))
        built, reason = build_debit_spread(chain, spot, "up" if up else "down", im or GAP_MIN, today)
        pending.pop(event)
        if not built:
            skips.append(f"B {ticker}: {reason}")
            continue
        _new(ledger, "B", ticker, event, today, captured, spot, built, gap=gap)
        seen.add(("B", event))
        added += 1

    # Arm C: operator calls
    for i, call in enumerate(calls):
        ticker = str(call.get("ticker") or "").upper()
        event = f"{ticker}|call-{call.get('recordedAt', i)}"
        if ("C", event) in seen or ticker not in chains:
            continue
        spot = _num(orows[ticker].get("underlyingPrice"))
        im = _num(orows[ticker].get("atmImpliedMovePct")) or GAP_MIN
        built, reason = build_debit_spread(chains[ticker], spot, str(call.get("direction")).lower(), im, today)
        if not built:
            skips.append(f"C {ticker}: {reason}")
            continue
        _new(ledger, "C", ticker, event, today, captured, spot, built, why=call.get("why"))
        seen.add(("C", event))
        added += 1
    return {"added": added, "skips": skips}


def _close(rec: dict, value: float, on: str, how: str) -> None:
    rec.update({"status": "closed", "exit": value, "exitOn": on, "exitHow": how,
                "returnOnDebit": round((value - rec["entry"]) / rec["entry"], 4)})


def scoreboard(ledger: dict) -> dict[str, Any]:
    from inferno_short_premium_study import _cluster_bootstrap_ci

    out = {}
    for arm, label in ARMS.items():
        recs = [r for r in ledger.get("records") or [] if r["arm"] == arm]
        closed = [r for r in recs if r["status"] == "closed"]
        vals = [r["returnOnDebit"] for r in closed]
        by_name: dict[str, list[float]] = {}
        for r in closed:
            by_name.setdefault(r["ticker"], []).append(r["returnOnDebit"])
        best2 = sorted(by_name, key=lambda n: sum(by_name[n]), reverse=True)[:2]
        ex = [v for n, xs in by_name.items() if n not in best2 for v in xs]
        out[arm] = {
            "label": label, "open": sum(r["status"] == "open" for r in recs), "closed": len(closed),
            "unscored": sum(r["status"] == "unscored" for r in recs),
            "winRate": round(sum(v > 0 for v in vals) / len(vals), 3) if vals else None,
            "mean": round(sum(vals) / len(vals), 4) if vals else None,
            "median": round(sorted(vals)[len(vals) // 2], 4) if vals else None,
            "meanExTwoBest": round(sum(ex) / len(ex), 4) if ex else None,
            "clusterCI95": _cluster_bootstrap_ci(by_name) if len(by_name) >= 2 else (None, None),
            "best": max(closed, key=lambda r: r["returnOnDebit"])["ticker"] if closed else None,
        }
    return out


def upcoming(snapshot: dict, today: date, limit: int = 8) -> list[dict]:
    rows = []
    for r in snapshot.get("rows") or []:
        d = _date(r.get("nextEarnings"))
        if d and 0 <= (d - today).days <= 14:
            rows.append({"ticker": r.get("ticker"), "earnings": d.isoformat(), "days": (d - today).days})
    return sorted(rows, key=lambda x: x["days"])[:limit]


def report_text(ledger: dict) -> str:
    lines = ["Earnings Runner Campaign (paper/shadow, research-only)", f"Pre-registered: {PREREG}", ""]
    for arm, sb in (ledger.get("scoreboard") or {}).items():
        res = ""
        if sb["mean"] is not None:
            ex = "n/a" if sb["meanExTwoBest"] is None else f"{sb['meanExTwoBest'] * 100:+.0f}%"
            res = f" | win {sb['winRate'] * 100:.0f}% | mean {sb['mean'] * 100:+.0f}% | ex-best-2 {ex}"
        lines.append(f"Arm {arm} ({sb['label']}): {sb['closed']} closed, {sb['open']} open, {sb['unscored']} unscored{res}")
    ups = ledger.get("upcoming") or []
    if ups:
        lines += ["", "Reporting in the next 14 days: " + ", ".join(f"{u['ticker']} {u['earnings']}" for u in ups)]
    opens = [r for r in ledger.get("records") or [] if r["status"] == "open"]
    if opens:
        lines += ["", "Open:"]
        lines += [f"- {r['arm']} {r['ticker']} {r['structure']} exp {r['expiration']} @ {r['entry']}" for r in opens[:10]]
    skips = (ledger.get("lastRun") or {}).get("skips") or []
    if skips:
        lines += ["", "Skipped this run: " + "; ".join(skips[:8])]
    lines += ["", "Full bid/ask both ways. Shadow records, not fills. Never held through a report in arm A."]
    return "\n".join(lines) + "\n"


def run(today: date | None = None) -> dict:
    from inferno_io import atomic_write_json, atomic_write_text

    today = today or date.today()
    ledger = _load(LEDGER_FILE) or {"version": 1, "records": []}
    snapshot = _load(SNAPSHOT_FILE)
    result = collect(ledger, _load(OPTIONS_FILE), snapshot, _load(HISTORY_FILE), load_calls(), today)
    ledger.update({
        "generatedAt": datetime.now().astimezone().isoformat(), "stage": STAGE, "prereg": PREREG,
        "researchOnly": True, "promotable": False, "authorityChanged": False,
        "liveTradingAllowed": False, "brokerSubmitAllowed": False,
        "lastRun": result, "scoreboard": scoreboard(ledger), "upcoming": upcoming(snapshot, today),
    })
    atomic_write_json(LEDGER_FILE, ledger)
    atomic_write_text(REPORT_FILE, report_text(ledger))
    return ledger


def record_call(ticker: str, direction: str, why: str, path: Path = CALLS_FILE) -> dict:
    direction = direction.lower()
    if direction not in {"up", "down"}:
        raise SystemExit("direction must be up or down")
    row = {"recordedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
           "ticker": ticker.upper(), "direction": direction, "why": why}
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Earnings Runner Campaign (research-only).")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run")
    sub.add_parser("status")
    c = sub.add_parser("call", help="record your call: TICKER up|down \"why\"")
    c.add_argument("ticker")
    c.add_argument("direction")
    c.add_argument("why", nargs="?", default="")
    args = parser.parse_args(argv)
    if args.command == "call":
        row = record_call(args.ticker, args.direction, args.why)
        print(f"Recorded: {row['ticker']} {row['direction']} ({row['why'] or 'no note'}). "
              "The desk builds the defined-risk ticket at the next chain capture.")
        return 0
    ledger = _load(LEDGER_FILE) if args.command == "status" else run()
    print(report_text(ledger) if ledger else "No campaign ledger yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
