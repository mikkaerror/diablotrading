from __future__ import annotations

"""Paper exit auditor for the Inferno evidence lane.

This module focuses on the part of the rehearsal loop that is easiest to
neglect: getting paper positions back out of the market and into the evidence
engine. A paper trade that never gets reconciled is just theater. The auditor
keeps us honest by flagging open positions that are due today, stale, or
missing enough execution facts to score later.
"""

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from inferno_config import local_now
from inferno_tos_fill_ingest import TOS_FILL_LOG_WORK_FILE, normalized_status, text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


PAPER_EXECUTION_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
PAPER_EXIT_AUDIT_FILE = DATA_DIR / "inferno_paper_exit_audit.json"
PAPER_EXIT_AUDIT_TEXT_FILE = REPORTS_DIR / "paper_exit_audit_latest.txt"

REVIEW_AFTER_OPEN_DAYS = 2
OVERDUE_AFTER_OPEN_DAYS = 4


def parse_date(value: Any) -> date | None:
    """Parse a loose ISO-like value into a date when possible."""
    raw = text(value)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def load_fill_rows() -> list[dict[str, Any]]:
    """Load the canonical paper fill log if it exists."""
    if not TOS_FILL_LOG_WORK_FILE.exists():
        return []
    with TOS_FILL_LOG_WORK_FILE.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def open_fill_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only rows that currently represent open paper positions."""
    return [row for row in rows if normalized_status(row.get("status")) == "open"]


def load_open_ledger_tickets() -> list[dict[str, Any]]:
    """Return open paper tickets from the execution ledger."""
    ledger = load_json_file(PAPER_EXECUTION_LEDGER_FILE) or {"items": []}
    open_items: list[dict[str, Any]] = []
    for item in ledger.get("items") or []:
        paper_status = text(((item.get("paperExecution") or {}).get("status")))
        outcome_status = text(((item.get("outcome") or {}).get("status")))
        if paper_status == "open" or outcome_status == "open":
            open_items.append(item)
    return open_items


def audit_ticket(ticket: dict[str, Any], *, today: date) -> dict[str, Any]:
    """Summarize one open paper ticket for exit follow-up.

    We intentionally keep the logic simple and explainable:
    - expiration day or later means close now
    - a ticket open for several days deserves a review even if it is not
      expiring yet
    - missing timestamps are treated as reconciliation debt
    """
    paper_execution = ticket.get("paperExecution") or {}
    opened_date = parse_date(paper_execution.get("openedAt")) or parse_date(ticket.get("tradeDate"))
    expiration = parse_date(ticket.get("expiration"))
    days_open = (today - opened_date).days if opened_date else None
    days_to_expiration = (expiration - today).days if expiration else None

    reasons: list[str] = []
    urgency = "monitor"

    if opened_date is None:
        urgency = "reconcile"
        reasons.append("missing openedAt/tradeDate for open paper ticket")
    if days_to_expiration is not None and days_to_expiration <= 0:
        urgency = "close-now"
        reasons.append("expiration is today or already passed")
    elif days_to_expiration == 1 and urgency != "reconcile":
        urgency = "review-today"
        reasons.append("expiration is tomorrow")

    if (
        days_open is not None
        and days_open >= OVERDUE_AFTER_OPEN_DAYS
        and urgency not in {"close-now", "reconcile"}
    ):
        urgency = "review-today"
        reasons.append(
            f"paper position has been open {days_open} days; consult trade-management before closing"
        )
    elif days_open is not None and days_open >= REVIEW_AFTER_OPEN_DAYS and urgency == "monitor":
        urgency = "review-today"
        reasons.append(f"paper position has been open {days_open} days")

    if not reasons:
        reasons.append("no immediate exit pressure detected")

    return {
        "ticker": ticket.get("ticker"),
        "ticketId": ticket.get("ticketId"),
        "strategy": ticket.get("strategy"),
        "status": text(ticket.get("status")) or "paper-staged",
        "urgency": urgency,
        "daysOpen": days_open,
        "daysToExpiration": days_to_expiration,
        "openedAt": paper_execution.get("openedAt") or ticket.get("tradeDate"),
        "expiration": ticket.get("expiration"),
        "reasons": reasons,
    }


def build_actions(counts: dict[str, int]) -> list[str]:
    """Translate exit counts into the shortest safe next actions."""
    actions: list[str] = []
    if counts.get("closeNow", 0) > 0:
        actions.append("Close or update the due-now paper positions before opening new rehearsals.")
    if counts.get("reviewToday", 0) > 0:
        actions.append("Review the aging paper positions and decide whether to log exits or keep monitoring.")
    if counts.get("reconcile", 0) > 0 or counts.get("orphanOpenFillRows", 0) > 0:
        actions.append("Reconcile the open fill log with the paper ledger so exits can be scored cleanly.")
    if not actions:
        actions.append("No paper exits need attention right now.")
    return actions


def build_audit() -> dict[str, Any]:
    """Build the current paper exit audit payload."""
    today = local_now().date()
    fill_rows = load_fill_rows()
    ledger_tickets = load_open_ledger_tickets()
    ticket_summaries = [audit_ticket(ticket, today=today) for ticket in ledger_tickets]

    by_ticket_id = {text(ticket.get("ticketId")) for ticket in ledger_tickets if text(ticket.get("ticketId"))}
    open_rows = open_fill_rows(fill_rows)
    orphan_open_rows = [
        row
        for row in open_rows
        if text(row.get("ticketId")) and text(row.get("ticketId")) not in by_ticket_id
    ]

    counts = {
        "openLedgerTickets": len(ledger_tickets),
        "openFillRows": len(open_rows),
        "orphanOpenFillRows": len(orphan_open_rows),
        "closeNow": sum(1 for ticket in ticket_summaries if ticket.get("urgency") == "close-now"),
        "reviewToday": sum(1 for ticket in ticket_summaries if ticket.get("urgency") == "review-today"),
        "reconcile": sum(1 for ticket in ticket_summaries if ticket.get("urgency") == "reconcile"),
    }

    if counts["closeNow"] > 0:
        verdict = "close-today"
    elif counts["reconcile"] > 0 or counts["orphanOpenFillRows"] > 0:
        verdict = "reconcile-open-rows"
    elif counts["reviewToday"] > 0:
        verdict = "review-open-exits"
    else:
        verdict = "clean"

    return {
        "generatedAt": local_now().isoformat(),
        "verdict": verdict,
        "counts": counts,
        "fillLogPath": str(TOS_FILL_LOG_WORK_FILE),
        "openTickets": ticket_summaries,
        "orphanOpenFillRows": [
            {
                "ticketId": text(row.get("ticketId")),
                "ticker": text(row.get("ticker")).upper(),
                "status": text(row.get("status")),
                "openedAt": text(row.get("openedAt")),
            }
            for row in orphan_open_rows
        ],
        "actions": build_actions(counts),
    }


def audit_text(payload: dict[str, Any]) -> str:
    """Render the paper exit audit into a concise operator memo."""
    counts = payload.get("counts") or {}
    lines = [
        "Inferno Paper Exit Audit",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        "",
        "Counts:",
        f"- open ledger tickets: {counts.get('openLedgerTickets', 0)}",
        f"- open fill rows: {counts.get('openFillRows', 0)}",
        f"- orphan open fill rows: {counts.get('orphanOpenFillRows', 0)}",
        f"- close now: {counts.get('closeNow', 0)}",
        f"- review today: {counts.get('reviewToday', 0)}",
        f"- reconcile: {counts.get('reconcile', 0)}",
        "",
        "Actions:",
    ]
    for action in payload.get("actions") or []:
        lines.append(f"- {action}")

    lines.extend(["", "Open tickets:"])
    open_tickets = payload.get("openTickets") or []
    if not open_tickets:
        lines.append("- none")
    for ticket in open_tickets:
        lines.append(
            f"- {ticket.get('ticker')} | {ticket.get('urgency')} | "
            f"open {ticket.get('daysOpen')}d | exp {ticket.get('daysToExpiration')}d | "
            f"{'; '.join(ticket.get('reasons') or [])}"
        )

    orphan_rows = payload.get("orphanOpenFillRows") or []
    lines.extend(["", "Orphan open fill rows:"])
    if not orphan_rows:
        lines.append("- none")
    for row in orphan_rows:
        lines.append(
            f"- {row.get('ticker') or 'UNKNOWN'} | ticket {row.get('ticketId') or 'missing'} | "
            f"opened {row.get('openedAt') or '-'}"
        )

    lines.append("")
    lines.append(f"Fill log: {payload.get('fillLogPath')}")
    return "\n".join(lines).rstrip() + "\n"


def save_audit(payload: dict[str, Any]) -> None:
    """Persist JSON and text artifacts for the exit audit."""
    ensure_dirs()
    PAPER_EXIT_AUDIT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    PAPER_EXIT_AUDIT_TEXT_FILE.write_text(audit_text(payload), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for build/status usage."""
    parser = argparse.ArgumentParser(description="Audit open paper exits for the Inferno desk.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint."""
    args = parse_args()
    if args.command == "status" and PAPER_EXIT_AUDIT_TEXT_FILE.exists():
        print(PAPER_EXIT_AUDIT_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_audit()
    save_audit(payload)
    print(audit_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
