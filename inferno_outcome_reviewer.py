from __future__ import annotations

"""Outcome reviewer for paper execution tickets.

Signals are cheap. Evidence is expensive. This module closes eligible paper
tickets after expiration and estimates P/L so the desk can measure expectancy
before any broker adapter earns more authority.
"""

import argparse
from datetime import date
from typing import Any

import pandas as pd
import yfinance as yf

from inferno_config import local_now
from inferno_paper_execution import load_ledger, save_ledger
from server import REPORTS_DIR, ensure_dirs


OUTCOME_REVIEW_TEXT_FILE = REPORTS_DIR / "paper_outcome_review_latest.txt"
CONTRACT_MULTIPLIER = 100


def number(value: Any, default: float = 0.0) -> float:
    """Safely coerce arbitrary values into floats for payoff math."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_date(value: Any) -> date | None:
    """Parse a date string into a local date."""
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def latest_underlying_price(ticker: str) -> float | None:
    """Fetch a latest close/regular-market price for outcome approximation."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.fast_info
        for field in ("last_price", "regular_market_price", "previous_close"):
            value = getattr(info, field, None)
            if value:
                return round(float(value), 4)
        history = stock.history(period="5d", interval="1d")
        if not history.empty:
            return round(float(history["Close"].dropna().iloc[-1]), 4)
    except Exception:  # noqa: BLE001
        return None
    return None


def leg_payoff_at_expiration(leg: dict[str, Any], underlying_price: float) -> float:
    """Estimate option intrinsic value at expiration for one contract leg."""
    put_call = str(leg.get("putCall", "")).upper()
    strike = number(leg.get("strike"))
    if put_call == "CALL":
        intrinsic = max(0.0, underlying_price - strike)
    elif put_call == "PUT":
        intrinsic = max(0.0, strike - underlying_price)
    else:
        intrinsic = 0.0
    signed = intrinsic if str(leg.get("instruction", "")).upper().startswith("BUY") else -intrinsic
    return signed * CONTRACT_MULTIPLIER


def estimated_entry_cashflow(ticket: dict[str, Any]) -> float:
    """Return entry cash flow from the trader's perspective.

    Debits are money paid out, so they are negative. Credits are money received,
    so they are positive.
    """
    entry = number(ticket.get("entryLimit"))
    if ticket.get("entryCostType") == "credit":
        return entry * CONTRACT_MULTIPLIER
    if ticket.get("entryCostType") == "debit":
        return -entry * CONTRACT_MULTIPLIER
    return 0.0


def estimate_expiration_pnl(ticket: dict[str, Any], underlying_price: float) -> float:
    """Estimate paper P/L from entry to expiration intrinsic value."""
    exit_value = sum(leg_payoff_at_expiration(leg, underlying_price) for leg in ticket.get("legs", []))
    return round(estimated_entry_cashflow(ticket) + exit_value, 2)


def ticket_ready_for_review(ticket: dict[str, Any], today: date | None = None) -> tuple[bool, str]:
    """Decide whether an open paper ticket can be reviewed now."""
    today = today or local_now().date()
    if ticket.get("status") != "paper-staged":
        return False, "ticket was not paper-staged"
    outcome = ticket.get("outcome") or {}
    if outcome.get("status") != "open":
        return False, "ticket is not open"
    expiration = parse_date(ticket.get("expiration"))
    if not expiration:
        return False, "expiration missing"
    if expiration > today:
        return False, f"expiration has not arrived ({expiration.isoformat()})"
    return True, "ready"


def review_ticket(ticket: dict[str, Any]) -> tuple[dict[str, Any], bool, str]:
    """Review one paper ticket and return the updated ticket."""
    ready, reason = ticket_ready_for_review(ticket)
    if not ready:
        return ticket, False, reason

    ticker = str(ticket.get("ticker", "")).upper()
    underlying_price = latest_underlying_price(ticker)
    if underlying_price is None:
        outcome = {
            **(ticket.get("outcome") or {}),
            "status": "review-pending",
            "reviewedAt": local_now().isoformat(),
            "notes": "could not fetch latest underlying price",
        }
        return {**ticket, "outcome": outcome}, True, "price unavailable"

    estimated_pnl = estimate_expiration_pnl(ticket, underlying_price)
    outcome = {
        **(ticket.get("outcome") or {}),
        "status": "closed",
        "reviewedAt": local_now().isoformat(),
        "exitUnderlyingPrice": underlying_price,
        "estimatedPnl": estimated_pnl,
        "notes": "estimated from expiration intrinsic value",
    }
    return {**ticket, "outcome": outcome}, True, "closed"


def review_ledger() -> dict[str, Any]:
    """Review all eligible paper tickets and persist the updated ledger."""
    ledger = load_ledger()
    reviewed = 0
    closed = 0
    updated_items: list[dict[str, Any]] = []
    notes: list[str] = []

    for ticket in ledger.get("items", []):
        updated, changed, note = review_ticket(ticket)
        updated_items.append(updated)
        if changed:
            reviewed += 1
            if (updated.get("outcome") or {}).get("status") == "closed":
                closed += 1
            notes.append(f"{ticket.get('ticker')}: {note}")

    updated_ledger = {
        **ledger,
        "updatedAt": local_now().isoformat(),
        "items": updated_items,
        "count": len(updated_items),
    }
    save_ledger(updated_ledger)
    report = {
        "reviewed": reviewed,
        "closed": closed,
        "open": sum(1 for item in updated_items if (item.get("outcome") or {}).get("status") == "open"),
        "notes": notes,
        "ledger": updated_ledger,
    }
    save_outcome_report(report)
    return report


def outcome_report_text(report: dict[str, Any]) -> str:
    """Render an operator-friendly outcome review report."""
    lines = [
        "Inferno Paper Outcome Review",
        "",
        f"Reviewed: {report.get('reviewed', 0)}",
        f"Closed: {report.get('closed', 0)}",
        f"Still open: {report.get('open', 0)}",
        "",
    ]
    notes = report.get("notes") or []
    if notes:
        lines.extend(notes)
    else:
        lines.append("No eligible open paper tickets needed review.")
    return "\n".join(lines).rstrip() + "\n"


def save_outcome_report(report: dict[str, Any]) -> None:
    """Persist the latest paper outcome review report."""
    ensure_dirs()
    OUTCOME_REVIEW_TEXT_FILE.write_text(outcome_report_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review paper execution tickets after expiration.")
    parser.add_argument("command", nargs="?", default="review", choices=["review", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and OUTCOME_REVIEW_TEXT_FILE.exists():
        print(OUTCOME_REVIEW_TEXT_FILE.read_text(encoding="utf-8"))
        return 0

    report = review_ledger()
    print(outcome_report_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
