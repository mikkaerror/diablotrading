from __future__ import annotations

"""Deposit clerk: the deposit-day order card for the signed Conviction Plan.

Real-money SHARES that Mikka keys himself. The desk never buys anything.
The card appears from the day before an expected deposit through three days
after, and only once the plan is signed (data/inferno_conviction_plan_ack.json).

Rules come from the signed plan (research/conviction_plan_draft.json and the
live-book officer's routing):
  - while cash is above the 15% reserve target: 55% core (SMH), 45% the top
    Capex Flow BUY that isn't exhausted
  - an "extended" pick gets a 1/3 tranche now; the rest stays in cash,
    earmarked for a pullback
  - nothing to the four operator holds; no name above 7% of the account at cost
Schwab takes dollar-based fractional orders for most US stocks and ETFs, so
the card is written in dollars.

`python3 inferno_deposit_card.py done` records what was bought (audit trail).
"""

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
OFFICER_FILE = DATA_DIR / "inferno_live_book_officer.json"
ACK_FILE = DATA_DIR / "inferno_conviction_plan_ack.json"
LOG_FILE = DATA_DIR / "inferno_deposit_log.jsonl"
OUTPUT_FILE = DATA_DIR / "inferno_deposit_card.json"
TEXT_FILE = REPORTS_DIR / "deposit_card_latest.txt"

STAGE = "deposit-card-research-only"
SHOW_BEFORE_DAYS, SHOW_AFTER_DAYS = 1, 3
SINGLE_NAME_MAX = 0.07


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def logged_dates(path: Path = LOG_FILE) -> set[str]:
    try:
        return {json.loads(line).get("depositDate") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
    except (OSError, ValueError):
        return set()


def build_card(officer: dict[str, Any], ack: dict[str, Any], today: date, done: set[str]) -> dict[str, Any]:
    base = {"generatedAt": datetime.now().astimezone().isoformat(), "stage": STAGE, "researchOnly": True,
            "liveTradingAllowed": False, "brokerSubmitAllowed": False, "show": False}
    book = officer.get("book") or {}
    deposit_on = book.get("nextDeposit")
    if not ack.get("active"):
        return {**base, "reason": "Conviction Plan not signed"}
    if not deposit_on:
        return {**base, "reason": "no deposit date in the plan"}
    d = date.fromisoformat(deposit_on)
    if not (d - timedelta(days=SHOW_BEFORE_DAYS) <= today <= d + timedelta(days=SHOW_AFTER_DAYS)):
        return {**base, "depositDate": deposit_on, "reason": f"next deposit {deposit_on}"}
    if deposit_on in done:
        return {**base, "depositDate": deposit_on, "reason": "already recorded"}
    routing = officer.get("depositRouting")
    if not routing:
        return {**base, "show": True, "depositDate": deposit_on, "lines": [],
                "note": "Cash is at or below the 15% reserve target: keep 15% of this deposit as reserve and split the rest 55/45 (plan rule 2)."}
    nlv = book.get("nlv") or 0
    pick = routing.get("convictionName")
    tranche = routing.get("convictionTranche")
    conviction = float(routing.get("conviction") or 0)
    now_amount = round(conviction / 3, 2) if tranche and tranche != "full" else conviction
    earmark = round(conviction - now_amount, 2)
    lines = [{"symbol": routing.get("coreVehicle") or "SMH", "dollars": float(routing.get("core") or 0), "role": "core"}]
    if pick and now_amount > 0:
        cap_note = None
        if nlv and now_amount / (nlv + float(routing.get("amount") or 0)) > SINGLE_NAME_MAX:
            cap_note = f"above the {SINGLE_NAME_MAX:.0%} single-name limit at cost - trim to fit"
        lines.append({"symbol": pick, "dollars": now_amount, "role": "conviction", "note": cap_note})
    return {**base, "show": True, "depositDate": deposit_on, "amount": routing.get("amount"), "lines": lines,
            "earmark": {"symbol": pick, "dollars": earmark} if earmark > 0 else None,
            "reason": routing.get("reason")}


def card_text(card: dict[str, Any]) -> str:
    if not card.get("show"):
        return f"No deposit card today ({card.get('reason')}).\n"
    out = [f"DEPOSIT DAY {card['depositDate']} - you key these; the desk never buys (signed Conviction Plan)"]
    for line in card.get("lines") or []:
        extra = f" - {line['note']}" if line.get("note") else ""
        out.append(f"- Buy ${line['dollars']:.2f} of {line['symbol']} ({line['role']}): dollar-based fractional order{extra}")
    if card.get("earmark"):
        e = card["earmark"]
        out.append(f"- Keep ${e['dollars']:.2f} in cash earmarked for {e['symbol']} on a pullback toward support (it's extended)")
    if card.get("note"):
        out.append(card["note"])
    out.append("Place after the first 30 minutes of trading; fractional orders fill at market. Nothing goes to IREN, HIVE, CLSK or TE.")
    out.append('When done: python3 inferno_deposit_card.py done "what you bought"')
    return "\n".join(out) + "\n"


def run(today: date | None = None) -> dict[str, Any]:
    from inferno_io import atomic_write_json, atomic_write_text

    card = build_card(_load(OFFICER_FILE), _load(ACK_FILE), today or date.today(), logged_dates())
    atomic_write_json(OUTPUT_FILE, card)
    atomic_write_text(TEXT_FILE, card_text(card))
    return card


def record_done(note: str, path: Path = LOG_FILE) -> dict[str, Any]:
    card = _load(OUTPUT_FILE)
    entry = {"recordedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
             "depositDate": card.get("depositDate"), "planned": card.get("lines"), "earmark": card.get("earmark"),
             "operatorNote": note}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deposit-day order card (research-only; you key the orders).")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status", "done"])
    parser.add_argument("note", nargs="?", default="")
    args = parser.parse_args(argv)
    if args.command == "done":
        entry = record_done(args.note)
        print(f"Recorded deposit {entry['depositDate']}: {args.note or 'as planned'}")
        return 0
    card = run() if args.command == "run" else _load(OUTPUT_FILE)
    print(card_text(card) if card else "No deposit card yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
