from __future__ import annotations

"""Paper order cards: the operator's one screen for keying a paper trade.

Plan W3 (docs/DESK_OPERATING_PLAN_2026-09-30.md). The operator is the only
one who keys an order in thinkorswim paperMoney. This turns every staged,
unfilled or still-open paper ticket into a card with exactly what to enter,
the price not to chase past, and the one command that records the fill so
it counts as a qualified outcome (not an intrinsic estimate).

Reads the paper ledger and the sandbox fill log. Writes only its own
report/JSON. Never stages, approves, closes, or submits anything; no
authority, broker, or risk-constant change.
"""

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
FILL_LOG_FILE = DATA_DIR / "inferno_tos_fill_log.csv"
OUTPUT_FILE = DATA_DIR / "inferno_paper_order_cards.json"
TEXT_FILE = REPORTS_DIR / "paper_order_cards_latest.txt"

STAGE = "paper-order-cards-research-only"
CHASE_FRACTION = 0.05   # never pay more than 5% worse than the planned limit
TICK = 0.05

EXIT_RULE_TEXT = {
    "exit-before-earnings": "close before the earnings report (T-1 close at the latest)",
    "hold-through-earnings": "hold through the report; close the next session",
    "hold-to-expiration": "hold to expiration unless the max-loss plan triggers",
}


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


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _round_tick(value: float) -> float:
    return round(round(value / TICK) * TICK, 2)


def fill_rows(path: Path = FILL_LOG_FILE) -> dict[str, dict[str, str]]:
    import csv

    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return {row.get("ticketId", ""): row for row in csv.DictReader(handle) if row.get("ticketId")}
    except OSError:
        return {}


def _leg_line(leg: dict[str, Any]) -> str:
    action = str(leg.get("instruction") or "").replace("_", " ").title()
    side = str(leg.get("putCall") or "").upper()
    return (f"{action} 1 {leg.get('symbol') or ''}".rstrip()
            + f"  ({side} {leg.get('strike')} exp {leg.get('expiration')}, "
              f"bid {leg.get('bid')} / ask {leg.get('ask')})")


def card_for(ticket: dict[str, Any], fill: dict[str, str] | None, today: date) -> dict[str, Any] | None:
    if ticket.get("status") != "paper-staged":
        return None
    expiry = _date(ticket.get("expiration"))
    execution = ticket.get("paperExecution") or {}
    state = str(execution.get("status") or (fill or {}).get("status") or "planned").lower()
    if state == "closed":
        return None
    entered = bool(_num((fill or {}).get("entryPrice")) or _num(execution.get("entryPrice")))
    ticket_id = ticket.get("ticketId")
    base = {
        "ticketId": ticket_id,
        "ticker": ticket.get("ticker"),
        "strategy": ticket.get("strategy"),
        "expiration": ticket.get("expiration"),
        "seeded": fill is not None,
    }
    if expiry and today > expiry:
        return {**base, "kind": "expired",
                "note": "expired without a recorded fill - clean it up in ./inferno today; it earns no credit"}
    if not entered:
        limit = _num(ticket.get("entryLimit"))
        credit = str(ticket.get("entryCostType") or "").lower() == "credit"
        chase = None
        if limit:
            chase = _round_tick(limit * (1 - CHASE_FRACTION) if credit else limit * (1 + CHASE_FRACTION))
        return {
            **base,
            "kind": "enter",
            "orderType": f"NET {'CREDIT' if credit else 'DEBIT'} LIMIT, DAY",
            "quantity": 1,
            "limit": limit,
            "dontChasePast": chase,
            "maxLossDollars": _num(ticket.get("estimatedMaxLoss")),
            "legs": [_leg_line(leg) for leg in ticket.get("legs") or []],
            "recordCommand": f"python3 inferno_record_fill.py {ticket_id} --entry <your fill price> --contracts 1",
        }
    rule = str(ticket.get("exitRule") or ticket.get("campaignExitRule") or "")
    return {
        **base,
        "kind": "exit",
        "entryPrice": _num((fill or {}).get("entryPrice")) or _num(execution.get("entryPrice")),
        "exitRule": EXIT_RULE_TEXT.get(rule, rule or "follow the ticket's time/loss plan"),
        "recordCommand": f"python3 inferno_record_fill.py {ticket_id} --exit <your closing fill price>",
    }


def build_cards(ledger: dict[str, Any], fills: dict[str, dict[str, str]], today: date,
                ledger_updated: str | None = None) -> dict[str, Any]:
    cards = [c for c in (card_for(t, fills.get(t.get("ticketId") or ""), today)
                         for t in ledger.get("items") or [] if isinstance(t, dict)) if c]
    order = {"exit": 0, "enter": 1, "expired": 2}
    cards.sort(key=lambda c: (order[c["kind"]], str(c.get("expiration") or "")))
    return {
        "generatedAt": datetime.now().astimezone().isoformat(),
        "stage": STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "ledgerUpdatedAt": ledger_updated,
        "cards": cards,
        "counts": {k: sum(c["kind"] == k for c in cards) for k in order},
    }


def cards_text(payload: dict[str, Any]) -> str:
    lines = ["Paper order cards (you key these in thinkorswim paperMoney; nothing is sent for you)",
             f"Ledger last written: {payload.get('ledgerUpdatedAt') or 'unknown'}", ""]
    if not payload["cards"]:
        lines.append("No paper orders to key right now.")
    for c in payload["cards"]:
        head = f"{c['ticker']} {str(c.get('strategy') or '').replace('_', ' ').title()} exp {c.get('expiration')}"
        if c["kind"] == "enter":
            lines.append(f"ENTER  {head}  [{c['ticketId']}]")
            lines.append(f"  {c['orderType']} x{c['quantity']} @ {c['limit']}  (don't chase past {c['dontChasePast']})"
                         + (f" | max loss ${c['maxLossDollars']:,.0f}" if c.get("maxLossDollars") else ""))
            lines.extend(f"  - {leg}" for leg in c["legs"])
            lines.append(f"  After the fill: {c['recordCommand']}")
            lines.append(f"  Also note the mid TOS showed: python3 inferno_fill_quality.py mid {c['ticketId']} --entry-mid <mid>")
            if not c["seeded"]:
                lines.append("  (fill-log row not seeded yet; the next pipeline run seeds it before you can record)")
        elif c["kind"] == "exit":
            lines.append(f"CLOSE  {head}  [{c['ticketId']}]  entered @ {c.get('entryPrice')}")
            lines.append(f"  Exit plan: {c['exitRule']}")
            lines.append(f"  After the close: {c['recordCommand']}  (records the real close, so it qualifies)")
            lines.append(f"  Also note the mid TOS showed: python3 inferno_fill_quality.py mid {c['ticketId']} --exit-mid <mid>")
        else:
            lines.append(f"EXPIRED {head}  [{c['ticketId']}] - {c['note']}")
        lines.append("")
    lines.append("Paper only. Every card is a research ticket; live trading and broker submit stay off.")
    return "\n".join(lines).rstrip() + "\n"


def run(today: date | None = None) -> dict[str, Any]:
    from inferno_io import atomic_write_json, atomic_write_text

    ledger = _load(LEDGER_FILE)
    payload = build_cards(ledger, fill_rows(), today or date.today(),
                          ledger.get("lastSuccessfulAt") or ledger.get("updatedAt"))
    atomic_write_json(OUTPUT_FILE, payload)
    atomic_write_text(TEXT_FILE, cards_text(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paper order cards for the operator (research-only).")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    args = parser.parse_args(argv)
    payload = run() if args.command == "run" else _load(OUTPUT_FILE)
    print(cards_text(payload) if payload else "No order cards yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
