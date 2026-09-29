from __future__ import annotations

"""Forward shadow test for defined-risk short premium (research-only).

docs/SHORT_PREMIUM_PREREG_V2_2026-09-29.md registers this before any data.

Why: the v1 prereg (2026-07-07) needed 60 forward events over 40 names by
2026-10-05, but nothing on the desk ever produced short-premium records, so
it reached its time-box at 0/60. That is a process failure, not evidence.
This collector produces the evidence automatically from real Schwab chains:

  entry   1-7 days before earnings, regular-session quotes only
  expiry  first expiration after the earnings date, <= 21 DTE
  shorts  the ATM straddle (sell the implied move) - the payoff the backward
          study modeled (rawSellR = 1 - realized/implied), so this is its
          faithful forward test
  wings   two implied moves out on each side (iron fly; defined risk, no naked
          short vol). The credit given up for the wings is priced from the
          real chain, which the backward study could not do.
  credit  full crossing: shorts at the bid, wings at the ask
  skip    credit <= 0, max loss > 4x credit, a short-leg spread > 50%, missing quotes
          (skips are logged per event: friction stopping the trade is evidence)
  settle  exact expiration-day close (same intrinsic proxy the shadow ledger uses)
  sizing  equal risk per event: netR = P&L / max loss

One record per eventId = TICKER|earningsDate (first qualifying capture wins).
Records are append-only; settlement fills in the outcome once.

Boundary: shadow-only. Never stages, approves, or submits anything; no
authority, risk-constant, or broker change. A v2 CONFIRM only opens an
operator-paper confirmation phase; it is never a live green light.
"""

import argparse
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
OPTIONS_FILE = DATA_DIR / "inferno_schwab_options.json"
SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
LEDGER_FILE = DATA_DIR / "inferno_short_premium_shadow.json"
REPORT_FILE = REPORTS_DIR / "short_premium_shadow_latest.txt"

STAGE = "short-premium-shadow-research-only"
PROTOCOL = "short-premium-prereg-v2"
MIN_DAYS_TO_EARNINGS = 1
MAX_DAYS_TO_EARNINGS = 7
MAX_DTE = 21
WING_MULTIPLE_OF_MOVE = 2.0
MAX_LOSS_TO_CREDIT = 4.0
MAX_LEG_SPREAD_PCT = 0.5
V2_TIMEBOX_END = date(2027, 2, 28)


# ---------------------------------------------------------------- helpers

def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


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


def earnings_dates(snapshot: dict[str, Any]) -> dict[str, date]:
    out = {}
    for row in snapshot.get("rows") or []:
        ticker = str(row.get("ticker") or "").upper()
        when = _date(row.get("nextEarnings"))
        if ticker and when:
            out[ticker] = when
    return out


def _quote(contract: dict[str, Any]) -> tuple[float, float] | None:
    bid, ask = _num(contract.get("bid")), _num(contract.get("ask"))
    if bid is None or ask is None or ask <= 0 or bid < 0 or ask < bid:
        return None
    return bid, ask


def _spread_pct(bid: float, ask: float) -> float:
    mid = (bid + ask) / 2.0
    return (ask - bid) / mid if mid > 0 else float("inf")


# ---------------------------------------------------------------- construction

def build_iron_fly(
    contracts: list[dict[str, Any]], spot: float, earnings: date, capture_day: date
) -> tuple[dict[str, Any] | None, str]:
    """Return (iron fly, "") or (None, skip reason). Pure; no I/O."""
    expirations = sorted({
        d for d in (_date(c.get("expirationDate")) for c in contracts)
        if d and d > earnings and (d - capture_day).days <= MAX_DTE
    })
    if not expirations:
        return None, "no expiration after earnings within 21 DTE"
    expiry = expirations[0]
    calls: dict[float, tuple[float, float]] = {}
    puts: dict[float, tuple[float, float]] = {}
    for c in contracts:
        if _date(c.get("expirationDate")) != expiry:
            continue
        strike, quote = _num(c.get("strikePrice")), _quote(c)
        if strike is None or quote is None:
            continue
        (calls if str(c.get("putCall")).upper() == "CALL" else puts)[strike] = quote
    both = sorted(set(calls) & set(puts))
    if not both:
        return None, "no paired strikes at expiry"
    atm = min(both, key=lambda k: abs(k - spot))
    straddle = sum((b + a) / 2.0 for b, a in (calls[atm], puts[atm]))
    if straddle <= 0:
        return None, "no ATM straddle price"

    def first_at_or_above(side: dict, level: float) -> float | None:
        cands = [k for k in side if k >= level]
        return min(cands) if cands else None

    def first_at_or_below(side: dict, level: float) -> float | None:
        cands = [k for k in side if k <= level]
        return max(cands) if cands else None

    reach = WING_MULTIPLE_OF_MOVE * straddle
    short_call = short_put = atm
    long_call = first_at_or_above({k: v for k, v in calls.items() if k > atm}, atm + reach)
    long_put = first_at_or_below({k: v for k, v in puts.items() if k < atm}, atm - reach)
    if long_call is None or long_put is None:
        return None, "chain does not reach the wing strikes"
    legs = {
        "shortCall": (short_call, calls[short_call]), "longCall": (long_call, calls[long_call]),
        "shortPut": (short_put, puts[short_put]), "longPut": (long_put, puts[long_put]),
    }
    if legs["shortCall"][1][0] <= 0 or legs["shortPut"][1][0] <= 0:
        return None, "short leg has no bid"
    # Wings are cheap and wide in percent terms; their cost is already charged
    # at the ask, so the spread gate applies to the legs that carry the credit.
    if any(_spread_pct(*legs[name][1]) > MAX_LEG_SPREAD_PCT for name in ("shortCall", "shortPut")):
        return None, "a short leg spread is wider than 50%"
    credit = (legs["shortCall"][1][0] + legs["shortPut"][1][0]
              - legs["longCall"][1][1] - legs["longPut"][1][1])
    mid_credit = sum(((b + a) / 2.0) * s for (_, (b, a)), s in
                     zip(legs.values(), (1, -1, 1, -1)))
    width = max(long_call - short_call, short_put - long_put)
    max_loss = (width - credit) * 100.0
    if credit <= 0:
        return None, f"no credit after crossing the spread (mid credit {mid_credit:.2f})"
    if max_loss / (credit * 100.0) > MAX_LOSS_TO_CREDIT:
        return None, "credit too thin for the wings (max loss > 4x credit)"
    return {
        "expiration": expiry.isoformat(),
        "spot": round(spot, 4),
        "atmStrike": atm,
        "impliedMovePct": round(straddle / spot, 4),
        "strikes": {name: k for name, (k, _) in legs.items()},
        "quotes": {name: {"bid": q[0], "ask": q[1]} for name, (_, q) in legs.items()},
        "entryCredit": round(credit, 4),
        "midCredit": round(mid_credit, 4),
        "entryFrictionDollars": round((mid_credit - credit) * 100.0, 2),
        "maxLossDollars": round(max_loss, 2),
        "maxLossToCredit": round(max_loss / (credit * 100.0), 3),
    }, ""


def settle(record: dict[str, Any], close: float) -> dict[str, Any]:
    k = record["strikes"]
    call_loss = min(max(0.0, close - k["shortCall"]), k["longCall"] - k["shortCall"])
    put_loss = min(max(0.0, k["shortPut"] - close), k["shortPut"] - k["longPut"])
    pnl = (record["entryCredit"] - call_loss - put_loss) * 100.0
    spot = record["spot"]
    mid = record.get("midCredit")
    width = max(k["longCall"] - k["shortCall"], k["shortPut"] - k["longPut"])
    mid_r = None
    if mid is not None and width > mid:
        # Upper bound on what a patient package order could earn; for context only.
        mid_r = round((mid - call_loss - put_loss) / (width - mid), 6)
    return {
        "midFillReturnOnRisk": mid_r,
        "status": "closed",
        "exitUnderlyingPrice": close,
        "realizedAbsMovePct": round(abs(close / spot - 1.0), 4) if spot else None,
        "estimatedPnl": round(pnl, 2),
        "estimatedReturnOnRisk": round(pnl / record["maxLossDollars"], 6),
        "returnOnCredit": round(pnl / (record["entryCredit"] * 100.0), 6),
    }


# ---------------------------------------------------------------- ledger

def capture(
    options: dict[str, Any], snapshot: dict[str, Any], ledger: dict[str, Any]
) -> tuple[int, list[dict[str, str]]]:
    generated = options.get("generatedAt")
    try:
        capture_day = datetime.fromisoformat(str(generated)).date()
    except (TypeError, ValueError):
        return 0, [{"ticker": "*", "reason": "options tape has no timestamp"}]
    dates = earnings_dates(snapshot)
    items = ledger.setdefault("items", [])
    seen = {item["eventId"] for item in items}
    added, skips = 0, []
    for row in options.get("rows") or []:
        ticker = str(row.get("symbol") or "").upper()
        earnings = dates.get(ticker)
        if not earnings or row.get("status") != "ok":
            continue
        days = (earnings - capture_day).days
        if not MIN_DAYS_TO_EARNINGS <= days <= MAX_DAYS_TO_EARNINGS:
            continue
        event_id = f"{ticker}|{earnings.isoformat()}"
        if event_id in seen:
            continue
        if str(row.get("quoteSessionIsRegular")) != "True":
            skips.append({"ticker": ticker, "reason": "quotes not from the regular session"})
            continue
        spot = _num(row.get("underlyingPrice"))
        if not spot:
            skips.append({"ticker": ticker, "reason": "no underlying price"})
            continue
        fly, reason = build_iron_fly(row.get("contracts") or [], spot, earnings, capture_day)
        if fly is None:
            skips.append({"ticker": ticker, "reason": reason})
            # Keep the latest skip per event: if friction is what stops the
            # trade, that is evidence too.
            ledger.setdefault("skipped", {})[event_id] = {"capturedAt": generated, "reason": reason}
            continue
        items.append({
            "eventId": event_id, "ticker": ticker, "earningsDate": earnings.isoformat(),
            "capturedAt": generated, "daysToEarnings": days, "protocol": PROTOCOL,
            "strategy": "IRON_FLY", "arm": "SHORT_PREMIUM_DEFINED", "shadowOnly": True,
            **fly, "outcome": {"status": "open"},
        })
        seen.add(event_id)
        added += 1
    return added, skips


def review(ledger: dict[str, Any], price_for: Callable[[str, date], dict[str, Any] | None],
           today: date) -> int:
    closed = 0
    for item in ledger.get("items") or []:
        if (item.get("outcome") or {}).get("status") == "closed":
            continue
        expiry = _date(item.get("expiration"))
        if not expiry or today <= expiry:
            continue
        evidence = price_for(item["ticker"], expiry)
        if not evidence:
            continue
        item["outcome"] = {**settle(item, float(evidence["price"])), "priceEvidence": evidence,
                           "reviewedAt": datetime.now().astimezone().isoformat()}
        closed += 1
    return closed


def summarize(ledger: dict[str, Any], today: date) -> dict[str, Any]:
    from inferno_short_premium_study import FORWARD_TIMEBOX_END, forward_summary

    records = []
    for item in ledger.get("items") or []:
        outcome = item.get("outcome") or {}
        if outcome.get("status") != "closed":
            continue
        records.append({
            "ticker": item["ticker"], "eventId": item["eventId"],
            "netR": outcome["estimatedReturnOnRisk"],
            "maxLossDollars": 100.0,  # equal risk per event (pre-registered sizing)
        })
    # v1's time-box is not this test's; evaluate v2 on its own clock.
    summary = forward_summary(records, today=min(today, FORWARD_TIMEBOX_END))
    summary["killReasons"] = [r for r in summary["killReasons"] if r != "timebox-expired-without-breadth"]
    if today > V2_TIMEBOX_END and (summary["distinctNames"] < 40 or summary["distinctEvents"] < 60):
        summary["killReasons"].append("v2-timebox-expired-without-breadth")
        if summary["verdict"] != "forward-short-premium-confirmed":
            summary["verdict"] = "forward-short-premium-killed"
    summary["timeboxEnd"] = V2_TIMEBOX_END.isoformat()
    summary["protocol"] = PROTOCOL
    summary["openEvents"] = sum(1 for i in ledger.get("items") or [] if (i.get("outcome") or {}).get("status") == "open")
    credits = [i["outcome"]["returnOnCredit"] for i in ledger.get("items") or []
               if (i.get("outcome") or {}).get("status") == "closed"]
    summary["meanReturnOnCredit"] = round(sum(credits) / len(credits), 3) if credits else None
    mids = [i["outcome"].get("midFillReturnOnRisk") for i in ledger.get("items") or []
            if (i.get("outcome") or {}).get("status") == "closed"]
    mids = [m for m in mids if m is not None]
    summary["meanNetR_midFillContextOnly"] = round(sum(mids) / len(mids), 3) if mids else None
    frictions = [i.get("entryFrictionDollars") for i in ledger.get("items") or [] if i.get("entryFrictionDollars") is not None]
    summary["meanEntryFrictionDollars"] = round(sum(frictions) / len(frictions), 2) if frictions else None
    return summary


def report_text(ledger: dict[str, Any]) -> str:
    s = ledger.get("summary") or {}
    lines = [
        "Short-premium forward shadow (prereg v2, research-only)",
        f"Generated: {ledger.get('generatedAt')}",
        f"Verdict: {s.get('verdict')}",
        f"Closed events {s.get('distinctEvents', 0)}/60 | names {s.get('distinctNames', 0)}/40 | open {s.get('openEvents', 0)} | time-box {s.get('timeboxEnd')}",
        f"Mean net-R {s.get('meanNetR')} | ex-two-best {s.get('meanNetR_exTwoBest')} | cluster CI {s.get('clusterCI95')}",
        f"Worst-2 loss share {s.get('worstTwoShareOfLossPct')}% | mean return on credit {s.get('meanReturnOnCredit')}",
        f"Friction: mean entry cost vs mid ${s.get('meanEntryFrictionDollars')} per fly | "
        f"mid-fill net-R {s.get('meanNetR_midFillContextOnly')} (context only; gates use full crossing)",
    ]
    skips = (ledger.get("lastRun") or {}).get("skips") or []
    if skips:
        lines.append("Skipped this run: " + "; ".join(f"{x['ticker']} ({x['reason']})" for x in skips[:8]))
    lines.append("Shadow iron flies from real chains; entry crosses the full spread; settled on the "
                 "expiration-day close. Not fills. No authority change.")
    return "\n".join(lines) + "\n"


def run(today: date | None = None) -> dict[str, Any]:
    from inferno_io import atomic_write_json, atomic_write_text
    from inferno_shadow_evidence import expiration_price_evidence

    today = today or date.today()
    ledger = _load(LEDGER_FILE) or {"version": 1, "items": []}
    added, skips = capture(_load(OPTIONS_FILE), _load(SNAPSHOT_FILE), ledger)
    closed = review(ledger, expiration_price_evidence, today)
    ledger.update({
        "generatedAt": datetime.now().astimezone().isoformat(),
        "stage": STAGE, "researchOnly": True, "promotable": False, "authorityChanged": False,
        "liveTradingAllowed": False, "brokerSubmitAllowed": False,
        "prereg": "docs/SHORT_PREMIUM_PREREG_V2_2026-09-29.md",
        "lastRun": {"added": added, "closed": closed, "skips": skips},
        "summary": summarize(ledger, today),
    })
    atomic_write_json(LEDGER_FILE, ledger)
    atomic_write_text(REPORT_FILE, report_text(ledger))
    return ledger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Shadow iron flies around earnings (research-only).")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    args = parser.parse_args(argv)
    ledger = run() if args.command == "run" else _load(LEDGER_FILE)
    print(report_text(ledger) if ledger else "No short-premium shadow ledger yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
