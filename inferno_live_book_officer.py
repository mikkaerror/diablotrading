from __future__ import annotations

"""Live-book risk officer (plan W6): report-only review of real holdings.

Two tiers, kept visibly separate:
  binding   rules already in force: never average down (playbook §5.4),
            the drawdown protocol, the operator-hold declaration.
  if signed what the draft Conviction Plan would add (survival test, sleeve
            targets, 200-day rule, thesis-card checks, deposit routing).
            Shown as "if signed" until an ack file exists; never enforced
            before Mikka signs off (plan D1).

Never sells, trims, stages, or places anything. Operator holds are never
sold by the desk (Conviction Plan: "your quarterly review decides").
"""

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RESEARCH_DIR = ROOT / "research"
REPORTS_DIR = ROOT / "reports"
OUTPUT_FILE = DATA_DIR / "inferno_live_book_officer.json"
TEXT_FILE = REPORTS_DIR / "live_book_officer_latest.txt"
ACK_FILE = DATA_DIR / "inferno_conviction_plan_ack.json"

STAGE = "live-book-officer-research-only"
LOSS_RULE_PCT = -20.0
BELOW_200D_SESSIONS = 10  # "two weeks" in the draft rule


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


def sma200_state(candles: list[dict[str, Any]]) -> dict[str, Any] | None:
    closes = [_num(c.get("close")) for c in candles]
    closes = [c for c in closes if c is not None]
    if len(closes) < 200 + BELOW_200D_SESSIONS:
        return None
    below = 0
    for offset in range(BELOW_200D_SESSIONS):
        end = len(closes) - offset
        sma = sum(closes[end - 200:end]) / 200
        if closes[end - 1] < sma:
            below += 1
    sma_now = sum(closes[-200:]) / 200
    return {"sma200": round(sma_now, 4), "pctVs200": round((closes[-1] / sma_now - 1) * 100, 1),
            "sessionsBelowOfLast10": below}


def review_holding(pos: dict[str, Any], nlv: float | None, row: dict[str, Any], history: dict[str, Any] | None,
                   declared: set[str], card: dict[str, Any] | None, signed: bool) -> dict[str, Any]:
    sym = str(pos.get("symbol") or "").upper()
    value = _num(pos.get("markValue"))
    pl = _num(pos.get("plPercent"))
    weight = round(value / nlv, 4) if value is not None and nlv else None
    trend = row.get("trend")
    ma = sma200_state(history.get("candles") or []) if history else None
    earnings = row.get("nextEarnings")
    check_on = None
    if earnings:
        try:
            check_on = (date.fromisoformat(str(earnings)[:10]) + timedelta(days=1)).isoformat()
        except ValueError:
            check_on = None

    binding = []
    if pl is not None and pl < 0:
        binding.append("no adding while under water (playbook 5.4, binding)")
    if pl is not None and pl <= LOSS_RULE_PCT:
        binding.append(f"past the {LOSS_RULE_PCT:.0f}% rule: hold or close, never add")
    if sym in declared:
        binding.append("operator long-term hold: the desk never sells it; your review decides")

    draft = []
    if weight is not None and weight > 0.07:
        draft.append(f"survival test: {weight * 100:.0f}% of the account vs a 7% limit - no new money until below")
    if ma and ma["sessionsBelowOfLast10"] >= BELOW_200D_SESSIONS:
        draft.append(f"below its 200-day for {BELOW_200D_SESSIONS}+ sessions ({ma['pctVs200']:+.0f}%): "
                     + ("displayed only (operator hold)" if sym in declared else "cut to half, buy back on a new up-trend"))
    if card and check_on:
        draft.append(f"thesis check after earnings on {check_on}: breaks if {card['breaks'].lower()}")
    return {
        "symbol": sym, "value": value, "weight": weight, "plPercent": pl, "trend": trend,
        "movingAverage": ma, "nextEarnings": earnings, "thesisCheckOn": check_on,
        "declaredHold": sym in declared, "thesisCard": card,
        "binding": binding, "ifSigned": draft, "enforced": signed,
    }


def _conviction_pick(flow: dict[str, Any]) -> dict[str, Any]:
    """Top Capex Flow BUY that isn't exhausted; extended names get a 1/3 tranche."""
    for n in flow.get("names") or []:
        if n.get("action") != "BUY":
            continue
        state = (n.get("entryTiming") or {}).get("state")
        if state == "exhaustion":
            continue
        return {"convictionName": n.get("ticker"), "convictionTranche": "1/3 now, rest on a pullback" if state == "extended" else "full"}
    return {"convictionName": None, "convictionTranche": None}


def next_deposit_date(deposit: dict[str, Any], today: date) -> str | None:
    """Roll the anchor date forward by the cadence so it never goes stale."""
    try:
        anchor = date.fromisoformat(str(deposit.get("nextExpected"))[:10])
    except ValueError:
        return None
    every = int(deposit.get("everyDays") or 0)
    while every > 0 and anchor < today:
        anchor += timedelta(days=every)
    return anchor.isoformat()


def build(data_dir: Path = DATA_DIR, research_dir: Path = RESEARCH_DIR, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    review = _load(data_dir / "inferno_live_position_review.json")
    sync = _load(data_dir / "inferno_live_account_sync.json")
    snapshot = _load(data_dir / "latest_snapshot.json")
    history = {r.get("symbol"): r for r in _load(data_dir / "inferno_schwab_price_history.json").get("rows") or []}
    plan = _load(research_dir / "conviction_plan_draft.json")
    ack = _load(data_dir / "inferno_conviction_plan_ack.json")
    signed = bool(ack.get("active"))
    declared = {str(s).upper() for s in _load(data_dir / "operator_long_term_holds.json").get("symbols") or []}
    rows = {r.get("ticker"): r for r in snapshot.get("rows") or [] if r.get("ticker")}
    nlv = _num(sync.get("netLiquidatingValue"))
    cash = _num(sync.get("totalCash"))
    cards = plan.get("thesisCards") or {}

    holdings = [review_holding(p, nlv, rows.get(str(p.get("symbol")).upper(), {}),
                               history.get(str(p.get("symbol")).upper()), declared,
                               cards.get(str(p.get("symbol")).upper()), signed)
                for p in review.get("positions") or []]
    holdings.sort(key=lambda h: -(h["value"] or 0))
    holds_weight = sum(h["weight"] or 0 for h in holdings if h["declaredHold"])
    cash_weight = round(cash / nlv, 4) if cash is not None and nlv else None
    targets = plan.get("sleeveTargets") or {}
    deposit = plan.get("deposit") or {}

    book = {
        "nlv": nlv, "cashWeight": cash_weight, "holdsWeight": round(holds_weight, 4),
        "holdsTarget": targets.get("operatorHolds"), "reserveTarget": targets.get("reserve"),
        "nextDeposit": next_deposit_date(deposit, today),
    }
    routing = None
    if deposit.get("amount") and cash_weight is not None and targets.get("reserve") is not None:
        split = deposit.get("splitWhileCashAboveReserve") or {}
        routing = {
            "amount": deposit["amount"],
            "core": round(deposit["amount"] * split.get("core", 0), 2),
            "conviction": round(deposit["amount"] * split.get("conviction", 0), 2),
            "coreVehicle": plan.get("coreVehicle"),
            **_conviction_pick(_load(data_dir / "inferno_capex_flow.json")),
            "reason": f"cash {cash_weight * 100:.0f}% is above the {targets['reserve'] * 100:.0f}% reserve target",
        } if cash_weight > targets["reserve"] else None
    upcoming = sorted((h for h in holdings if h["thesisCheckOn"]), key=lambda h: h["thesisCheckOn"])
    return {
        "generatedAt": datetime.now().astimezone().isoformat(),
        "stage": STAGE, "researchOnly": True, "promotable": False, "authorityChanged": False,
        "liveTradingAllowed": False, "brokerSubmitAllowed": False,
        "planStatus": "signed" if signed else (plan.get("status") or "missing"),
        "book": book, "holdings": holdings, "depositRouting": routing,
        "nextThesisCheck": ({"symbol": upcoming[0]["symbol"], "on": upcoming[0]["thesisCheckOn"]} if upcoming else None),
        "citations": ["docs/TRADE_MANAGEMENT_PLAYBOOK.md 5.2, 5.4", plan.get("source") or "research/conviction_plan_draft.json"],
    }


def officer_text(p: dict[str, Any]) -> str:
    b = p["book"]
    tag = "" if p["planStatus"] == "signed" else " (Conviction Plan NOT signed: 'if signed' lines are not enforced)"
    lines = [f"Live-book officer - report only{tag}", ""]
    if b["nlv"]:
        lines.append(f"Account ${b['nlv']:,.2f} | cash {(b['cashWeight'] or 0) * 100:.0f}% | operator holds "
                     f"{b['holdsWeight'] * 100:.0f}%" + (f" ({'plan' if p['planStatus'] == 'signed' else 'draft'} target <= {b['holdsTarget'] * 100:.0f}%)" if b.get("holdsTarget") else ""))
    lines.append("")
    for h in p["holdings"]:
        pl = "" if h["plPercent"] is None else f" {h['plPercent']:+.1f}%"
        wt = "" if h["weight"] is None else f" | {h['weight'] * 100:.0f}% of account"
        ma = "" if not h["movingAverage"] else f" | {h['movingAverage']['pctVs200']:+.0f}% vs 200-day"
        lines.append(f"{h['symbol']}{pl}{wt} | trend {h['trend'] or 'n/a'}{ma} | earnings {h['nextEarnings'] or '?'}")
        lines.extend(f"  binding: {x}" for x in h["binding"])
        label = "plan rule" if p["planStatus"] == "signed" else "if signed"
        lines.extend(f"  {label}: {x}" for x in h["ifSigned"])
    r = p.get("depositRouting")
    if r:
        lines.append("")
        lead = "Plan" if p["planStatus"] == "signed" else "If signed"
        lines.append(f"{lead}: the {b['nextDeposit']} deposit of ${r['amount']}: ${r['core']:.0f} {r['coreVehicle']}, "
                     f"${r['conviction']:.0f} {r['convictionName'] or 'top Capex Flow BUY'}"
                     + (f" [{r['convictionTranche']}]" if r.get("convictionTranche") and r["convictionTranche"] != "full" else "")
                     + f" ({r['reason']}); nothing to the holds.")
    lines.append("")
    lines.append("Report only. The desk never sells, trims, or buys for you.")
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    from inferno_io import atomic_write_json, atomic_write_text

    payload = build()
    atomic_write_json(OUTPUT_FILE, payload)
    atomic_write_text(TEXT_FILE, officer_text(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live-book risk officer (report only).")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    args = parser.parse_args(argv)
    payload = run() if args.command == "run" else _load(OUTPUT_FILE)
    print(officer_text(payload) if payload else "No live-book review yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
