"""Fill quality (TCA) for real paperMoney fills. Research-only, read-only.

Answers one question per fill: what did execution cost versus the market we
staged against, and is the model's friction assumption honest?

For every ticket with a recorded paperMoney entry it compares the fill with:
  * the staged mid   (sum of leg mids when the ticket was staged)
  * the staged natural (pay the ask, receive the bid) = the worst normal fill
  * the model's assumed friction per crossing (estimatedSpreadFrictionPerCrossingDollars)
and, when the operator noted it, the mid thinkorswim showed at fill time
(``mid`` command). A fill-time mid gives a clean read; the staged mid can be
hours old, so the underlying may have moved in between.

Slippage is signed so that positive always means "cost us money":
  debit:  fill - mid          credit: mid - fill
It is also expressed in half-spreads: 0 = filled at mid, 1 = filled at natural,
negative = better than mid.

It never records a fill, edits the ledger or fill log, approves, sizes, or
touches a broker or any authority/risk constant. Marks written by ``mid`` go to
its own append-only file.

CLI:
  python3 inferno_fill_quality.py run
  python3 inferno_fill_quality.py mid TICKET_OR_TICKER --entry-mid 2.35 [--exit-mid 2.10]
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / "data" / "inferno_paper_execution_ledger.json"
FILLS = ROOT / "data" / "inferno_tos_fill_log.csv"
MARKS = ROOT / "data" / "inferno_fill_quality_marks.jsonl"
OUT = ROOT / "data" / "inferno_fill_quality.json"
TEXT = ROOT / "reports" / "fill_quality_latest.txt"

STAGE = "fill-quality-research-only"
MIN_CLEAN_FOR_VERDICT = 5      # fills with a fill-time mid before we judge the model
OPTIMISTIC_RATIO = 1.3         # realized cost / modeled cost above this = model too rosy
CONSERVATIVE_RATIO = 0.7       # below this = model overcharges itself


def _num(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_credit(ticket: dict[str, Any]) -> bool:
    return str(ticket.get("entryCostType") or "").lower() == "credit"


def staged_market(ticket: dict[str, Any]) -> dict[str, float] | None:
    """Net mid / natural / far side of the staged legs, as positive magnitudes."""
    legs = ticket.get("legs") or []
    if not legs:
        return None
    mid = nat_debit = far_debit = 0.0
    for leg in legs:
        bid, ask = _num(leg.get("bid")), _num(leg.get("ask"))
        m = _num(leg.get("mid"))
        if bid is None or ask is None:
            return None
        if m is None:
            m = (bid + ask) / 2
        buy = str(leg.get("instruction") or "").upper().startswith("BUY")
        qty = _num(leg.get("quantity")) or 1.0
        sign = 1.0 if buy else -1.0
        mid += sign * m * qty
        nat_debit += (ask if buy else -bid) * qty     # what a debit pays at natural
        far_debit += (bid if buy else -ask) * qty     # what a debit pays at the far side
    if _is_credit(ticket):
        # credit magnitudes: natural receives the least, far side receives the most
        return {"mid": round(-mid, 4), "natural": round(-nat_debit, 4), "far": round(-far_debit, 4)}
    return {"mid": round(mid, 4), "natural": round(nat_debit, 4), "far": round(far_debit, 4)}


def _slip(fill: float, mid: float, credit: bool) -> float:
    return (mid - fill) if credit else (fill - mid)


def load_marks(path: Path = MARKS) -> dict[str, dict[str, float]]:
    marks: dict[str, dict[str, float]] = {}
    if not path.exists():
        return marks
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        tid = row.get("ticketId")
        if not tid:
            continue
        slot = marks.setdefault(tid, {})
        for key in ("entryMid", "exitMid"):
            if _num(row.get(key)) is not None:
                slot[key] = float(row[key])   # latest note wins
    return marks


def assess(ticket: dict[str, Any], fill_row: dict[str, str], marks: dict[str, float]) -> dict[str, Any] | None:
    entry = _num(fill_row.get("entryPrice"))
    if entry is None:
        return None
    credit = _is_credit(ticket)
    contracts = _num(fill_row.get("contracts")) or 1.0
    market = staged_market(ticket)
    flags: list[str] = []
    row: dict[str, Any] = {
        "ticketId": ticket.get("ticketId"),
        "ticker": ticket.get("ticker"),
        "strategy": ticket.get("strategy"),
        "side": "credit" if credit else "debit",
        "contracts": contracts,
        "entryFill": entry,
        "entryLimit": _num(ticket.get("entryLimit")),
        "stagedAt": ticket.get("sourceStrikePlanGeneratedAt") or ticket.get("createdAt"),
        "filledAt": fill_row.get("openedAt") or None,
    }
    limit = row["entryLimit"]
    if limit is not None and ((entry > limit + 1e-9) if not credit else (entry < limit - 1e-9)):
        flags.append("filled past the staged limit")
    if market:
        half = abs(market["natural"] - market["mid"])
        slip = _slip(entry, market["mid"], credit)
        row.update({
            "stagedMid": market["mid"], "stagedNatural": market["natural"], "stagedFar": market["far"],
            "slipVsStagedMid": round(slip, 4),
            "slipVsStagedMidDollars": round(slip * 100 * contracts, 2),
            "halfSpreadsVsStagedMid": round(slip / half, 2) if half > 0 else None,
        })
        outside = (entry < market["far"] - 1e-9) if not credit else (entry > market["far"] + 1e-9)
        if outside:
            flags.append("fill is outside the staged market (price moved, or check the confirmation)")
        elif slip < 0:
            flags.append("better than staged mid - likely moved between staging and fill; note the fill-time mid")
    fill_mid = _num(marks.get("entryMid"))
    if fill_mid is not None:
        slip = _slip(entry, fill_mid, credit)
        row.update({"entryMidAtFill": fill_mid, "slipVsFillMid": round(slip, 4),
                    "slipVsFillMidDollars": round(slip * 100 * contracts, 2), "clean": True})
    else:
        row["clean"] = False
    exit_fill = _num(fill_row.get("exitPrice"))
    exit_mid = _num(marks.get("exitMid"))
    if exit_fill is not None:
        row["exitFill"] = exit_fill
        if exit_mid is not None:
            # closing a debit = selling (cost = mid - fill); closing a credit = buying (cost = fill - mid)
            slip = (exit_fill - exit_mid) if credit else (exit_mid - exit_fill)
            row.update({"exitMidAtFill": exit_mid, "exitSlip": round(slip, 4),
                        "exitSlipDollars": round(slip * 100 * contracts, 2)})
    modeled = _num(ticket.get("estimatedSpreadFrictionPerCrossingDollars"))
    if modeled is not None:
        row["modeledFrictionPerCrossingDollars"] = round(modeled * contracts, 2)
    row["flags"] = flags
    return row


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    clean = [r for r in rows if r.get("clean")]
    halves = [r["halfSpreadsVsStagedMid"] for r in rows if r.get("halfSpreadsVsStagedMid") is not None]
    realized = [r["slipVsFillMidDollars"] for r in clean if r.get("modeledFrictionPerCrossingDollars")]
    modeled = [r["modeledFrictionPerCrossingDollars"] for r in clean if r.get("modeledFrictionPerCrossingDollars")]
    ratio = None
    if modeled and sum(modeled) > 0:
        ratio = round(sum(realized) / sum(modeled), 2)
    if len(clean) < MIN_CLEAN_FOR_VERDICT:
        verdict = f"collecting ({len(clean)}/{MIN_CLEAN_FOR_VERDICT} fills with a fill-time mid)"
    elif ratio is None:
        verdict = "no modeled friction to compare"
    elif ratio > OPTIMISTIC_RATIO:
        verdict = "model friction is too optimistic - real fills cost more than the backtests assume"
    elif ratio < CONSERVATIVE_RATIO:
        verdict = "model friction is conservative - real fills cost less than assumed"
    else:
        verdict = "model friction is about right"
    return {
        "fills": len(rows),
        "cleanFills": len(clean),
        "medianHalfSpreadsVsStagedMid": round(statistics.median(halves), 2) if halves else None,
        "realizedEntryCostDollars": round(sum(realized), 2) if realized else None,
        "modeledEntryCostDollars": round(sum(modeled), 2) if modeled else None,
        "realizedToModeled": ratio,
        "pastLimit": sum("filled past the staged limit" in r["flags"] for r in rows),
        "verdict": verdict,
    }


def model_check(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Staged half-spread vs the model's friction per crossing, by strategy.

    Needs no fills: every staged or blocked ticket with legs shows what one
    crossing at natural would cost against what the backtests charge. A ratio
    above 1 means the model under-charges that structure.
    """
    groups: dict[str, list[float]] = {}
    for t in ledger.get("items") or []:
        if not isinstance(t, dict):
            continue
        market = staged_market(t)
        modeled = _num(t.get("estimatedSpreadFrictionPerCrossingDollars"))
        if not market or not modeled or modeled <= 0:
            continue
        half = abs(market["natural"] - market["mid"]) * 100
        groups.setdefault(str(t.get("strategy") or "?"), []).append(half / modeled)
    out = []
    for strategy, ratios in sorted(groups.items()):
        med = statistics.median(ratios)
        out.append({
            "strategy": strategy,
            "tickets": len(ratios),
            "medianHalfSpreadToModeled": round(med, 2),
            "read": ("model under-charges" if med > OPTIMISTIC_RATIO
                     else "model over-charges" if med < CONSERVATIVE_RATIO else "model about right"),
        })
    return out


def build(ledger: dict[str, Any], fills: list[dict[str, str]], marks: dict[str, dict[str, float]]) -> dict[str, Any]:
    tickets = {t.get("ticketId"): t for t in ledger.get("items") or [] if isinstance(t, dict)}
    rows = []
    for fr in fills:
        t = tickets.get(fr.get("ticketId"))
        if not t:
            continue
        r = assess(t, fr, marks.get(fr.get("ticketId") or "", {}))
        if r:
            rows.append(r)
    return {
        "generatedAt": datetime.now().astimezone().isoformat(),
        "stage": STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "summary": summarize(rows),
        "modelCheck": model_check(ledger),
        "fills": rows,
    }


def _money(v: Any) -> str:
    return "n/a" if v is None else f"${v:,.2f}"


def text(payload: dict[str, Any]) -> str:
    s = payload["summary"]
    lines = ["Fill quality (TCA) - research-only; records nothing, sends nothing",
             f"Generated: {payload['generatedAt']}", "",
             f"Fills: {s['fills']} ({s['cleanFills']} with a fill-time mid) | verdict: {s['verdict']}"]
    if s["medianHalfSpreadsVsStagedMid"] is not None:
        lines.append(f"Median entry vs staged mid: {s['medianHalfSpreadsVsStagedMid']:+.2f} half-spreads "
                     "(0 = mid, 1 = natural, negative = better than mid)")
    if s["realizedToModeled"] is not None:
        lines.append(f"Real entry cost {_money(s['realizedEntryCostDollars'])} vs modeled {_money(s['modeledEntryCostDollars'])} "
                     f"(x{s['realizedToModeled']})")
    checks = payload.get("modelCheck") or []
    if checks:
        lines.append("")
        lines.append("Model friction check (staged half-spread / modeled cost per crossing; >1 = model under-charges):")
        for c in checks:
            lines.append(f"- {c['strategy'].replace('_', ' ').title()}: x{c['medianHalfSpreadToModeled']} "
                         f"over {c['tickets']} ticket(s) - {c['read']}")
    lines.append("")
    for r in payload["fills"]:
        head = f"{r['ticker']} {str(r.get('strategy') or '').replace('_', ' ').title()} [{r['ticketId']}]"
        lines.append(head)
        staged = ""
        if r.get("stagedMid") is not None:
            hs = r.get("halfSpreadsVsStagedMid")
            staged = (f" | staged mid {r['stagedMid']:.2f}, natural {r['stagedNatural']:.2f} -> "
                      f"{_money(r['slipVsStagedMidDollars'])} vs mid" + ("" if hs is None else f" ({hs:+.2f} half-spreads)"))
        lines.append(f"  entry {r['entryFill']:.2f} ({r['side']}, limit {r.get('entryLimit')}){staged}")
        if r.get("clean"):
            lines.append(f"  fill-time mid {r['entryMidAtFill']:.2f} -> {_money(r['slipVsFillMidDollars'])} real cost")
        if r.get("modeledFrictionPerCrossingDollars") is not None:
            lines.append(f"  model assumed {_money(r['modeledFrictionPerCrossingDollars'])} per crossing")
        if r.get("exitSlipDollars") is not None:
            lines.append(f"  exit {r['exitFill']:.2f} vs fill-time mid {r['exitMidAtFill']:.2f} -> {_money(r['exitSlipDollars'])}")
        for f in r["flags"]:
            lines.append(f"  ! {f}")
        if not r.get("clean") and r.get("exitFill") is None:
            lines.append(f"  next time: python3 inferno_fill_quality.py mid {r['ticketId']} --entry-mid <mid TOS showed>")
        lines.append("")
    if not payload["fills"]:
        lines.append("No recorded paperMoney fills yet. The first real fill starts this log.")
    return "\n".join(lines).rstrip() + "\n"


def _read_fills(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def run(ledger_path: Path = LEDGER, fills_path: Path = FILLS, marks_path: Path = MARKS,
        out: Path = OUT, text_out: Path = TEXT) -> dict[str, Any]:
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    payload = build(ledger, _read_fills(fills_path), load_marks(marks_path))
    out.parent.mkdir(parents=True, exist_ok=True)
    text_out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    text_out.write_text(text(payload))
    return payload


def note_mid(target: str, entry_mid: float | None, exit_mid: float | None,
             ledger_path: Path = LEDGER, marks_path: Path = MARKS) -> dict[str, Any]:
    if entry_mid is None and exit_mid is None:
        raise SystemExit("give --entry-mid and/or --exit-mid")
    for v in (entry_mid, exit_mid):
        if v is not None and v <= 0:
            raise SystemExit("mid must be a positive price")
    items = (json.loads(ledger_path.read_text()) if ledger_path.exists() else {}).get("items") or []
    hits = [t for t in items if t.get("ticketId") == target]
    if not hits:
        hits = [t for t in items if str(t.get("ticker") or "").upper() == target.upper()
                and t.get("status") == "paper-staged"]
    if len(hits) != 1:
        raise SystemExit(f"{target}: need exactly one matching paper-staged ticket (found {len(hits)}); use the ticket id")
    row = {"ticketId": hits[0]["ticketId"], "ticker": hits[0].get("ticker"),
           "notedAt": datetime.now().astimezone().isoformat()}
    if entry_mid is not None:
        row["entryMid"] = entry_mid
    if exit_mid is not None:
        row["exitMid"] = exit_mid
    marks_path.parent.mkdir(parents=True, exist_ok=True)
    with marks_path.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    m = sub.add_parser("mid", help="note the mid thinkorswim showed when you filled")
    m.add_argument("target")
    m.add_argument("--entry-mid", type=float)
    m.add_argument("--exit-mid", type=float)
    a = p.parse_args(argv)
    if a.cmd == "mid":
        print(json.dumps(note_mid(a.target, a.entry_mid, a.exit_mid)))
        payload = run()
    else:
        payload = run()
    print(text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
