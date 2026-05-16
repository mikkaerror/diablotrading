from __future__ import annotations

"""Import simulated thinkorswim paperMoney fills into the Inferno paper ledger.

This module stays on the paper side of the wall. It reads operator-entered or
future-exported fill rows from the sandbox CSV, matches them back to paper
tickets, and updates the ledger so analytics learn from actual sandbox behavior
instead of static strike plans alone.
"""

import argparse
import csv
import hashlib
import json
from typing import Any

from inferno_config import local_now
from inferno_paper_execution import PAPER_EXECUTION_TEXT_FILE, load_ledger, save_ledger
from inferno_tos_sandbox import TOS_FILL_LOG_WORK_FILE, write_fill_log_template
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


TOS_FILL_INGEST_FILE = DATA_DIR / "inferno_tos_fill_ingest.json"
TOS_FILL_INGEST_TEXT_FILE = REPORTS_DIR / "tos_fill_ingest_latest.txt"
OPEN_STATUSES = {"open", "opened", "filled", "paper-open"}
CLOSED_STATUSES = {"closed", "closed-win", "closed-loss", "exited"}
IGNORED_STATUSES = {"", "pending", "watch", "planned"}
CONTRACT_MULTIPLIER = 100


def number(value: Any, default: float | None = None) -> float | None:
    """Coerce loose CSV values into floats without throwing."""
    try:
        if value in ("", None):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def text(value: Any) -> str:
    """Normalize arbitrary values into trimmed text."""
    return str(value or "").strip()


def normalized_status(value: Any) -> str:
    """Map fill-log statuses onto a small safe state machine."""
    status = text(value).lower().replace("_", "-")
    if status in OPEN_STATUSES:
        return "open"
    if status in CLOSED_STATUSES:
        return "closed"
    if status in {"cancelled", "canceled", "void"}:
        return "canceled"
    if status in IGNORED_STATUSES:
        return "ignored"
    return "unknown"


def row_fingerprint(row: dict[str, Any]) -> str:
    """Build a stable import key so repeated runs remain idempotent."""
    raw = "|".join(
        [
            text(row.get("ticketId")),
            text(row.get("ticker")).upper(),
            text(row.get("strategy")).upper(),
            text(row.get("status")).lower(),
            text(row.get("entryPrice")),
            text(row.get("exitPrice")),
            text(row.get("realizedPnl")),
            text(row.get("openedAt")),
            text(row.get("closedAt")),
            text(row.get("notes")),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def contracts_for_row(row: dict[str, Any]) -> int:
    """Return the contract count, defaulting to one spread/position."""
    value = number(row.get("contracts"), 1.0)
    return max(1, int(value or 1))


def load_fill_rows() -> list[dict[str, Any]]:
    """Load the paperMoney fill log after ensuring the latest schema exists."""
    write_fill_log_template()
    with TOS_FILL_LOG_WORK_FILE.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def candidate_tickets(ledger: dict[str, Any], row: dict[str, Any]) -> list[dict[str, Any]]:
    """Return safe candidate paper tickets for one fill row.

    Matching prefers exact `ticketId`. Fallback matching is intentionally strict:
    ticker plus optional strategy, restricted to the paper-staged lane so we do
    not accidentally mutate blocked or rejected tickets.
    """
    items = ledger.get("items") or []
    ticket_id = text(row.get("ticketId"))
    if ticket_id:
        exact = [
            item
            for item in items
            if text(item.get("ticketId")) == ticket_id and text(item.get("status")) == "paper-staged"
        ]
        if exact:
            return exact

    ticker = text(row.get("ticker")).upper()
    strategy = text(row.get("strategy")).upper()
    candidates = [
        item
        for item in items
        if text(item.get("ticker")).upper() == ticker and text(item.get("status")) == "paper-staged"
    ]
    if strategy:
        narrowed = [item for item in candidates if text(item.get("strategy")).upper() == strategy]
        if narrowed:
            return narrowed
    return candidates


def derived_realized_pnl(ticket: dict[str, Any], row: dict[str, Any]) -> float | None:
    """Estimate realized P/L from entry and exit prices when CSV omits dollars."""
    explicit = number(row.get("realizedPnl"))
    if explicit is not None:
        return round(explicit, 2)
    exit_price = number(row.get("exitPrice"))
    if exit_price is None:
        return None
    entry_price = number(row.get("entryPrice"), number(ticket.get("entryLimit"), 0.0))
    contracts = contracts_for_row(row)
    if ticket.get("entryCostType") == "credit":
        return round(((entry_price or 0.0) - exit_price) * CONTRACT_MULTIPLIER * contracts, 2)
    return round((exit_price - (entry_price or 0.0)) * CONTRACT_MULTIPLIER * contracts, 2)


def merge_notes(*parts: Any) -> str | None:
    """Join non-empty note fragments for audit clarity."""
    cleaned = [text(part) for part in parts if text(part)]
    return " | ".join(cleaned) if cleaned else None


def apply_fill_row(ticket: dict[str, Any], row: dict[str, Any]) -> tuple[dict[str, Any], bool, str]:
    """Apply one normalized fill row to one paper ticket."""
    import_key = row_fingerprint(row)
    imported_keys = set(ticket.get("importedFillKeys") or [])
    if import_key in imported_keys:
        return ticket, False, "duplicate fill row already imported"

    status = normalized_status(row.get("status"))
    if status in {"ignored", "unknown"}:
        return ticket, False, f"status {text(row.get('status')) or 'blank'} ignored"

    paper_execution = {
        **(ticket.get("paperExecution") or {}),
        "environment": text(row.get("environment")) or "thinkorswim-paperMoney",
        "paperAccount": text(row.get("paperAccount")),
        "routeFamily": text(row.get("routeFamily")),
        "orderType": text(row.get("orderType")),
        "contracts": contracts_for_row(row),
        "entryPrice": number(row.get("entryPrice"), number(ticket.get("entryLimit"), 0.0)),
        "exitPrice": number(row.get("exitPrice")),
        "realizedPnl": derived_realized_pnl(ticket, row),
        "openedAt": text(row.get("openedAt")) or text((ticket.get("paperExecution") or {}).get("openedAt")),
        "closedAt": text(row.get("closedAt")) or text((ticket.get("paperExecution") or {}).get("closedAt")),
        "status": status,
        "notes": merge_notes((ticket.get("paperExecution") or {}).get("notes"), row.get("notes")),
        "lastImportedAt": local_now().isoformat(),
        "source": "paper-fill-log",
    }

    outcome = dict(ticket.get("outcome") or {})
    if status == "open":
        outcome = {
            **outcome,
            "status": "open",
            "notes": merge_notes(outcome.get("notes"), "paper fill imported"),
        }
    elif status == "closed":
        outcome = {
            **outcome,
            "status": "closed",
            "reviewedAt": local_now().isoformat(),
            "exitValue": paper_execution.get("exitPrice"),
            "estimatedPnl": paper_execution.get("realizedPnl"),
            "notes": merge_notes(outcome.get("notes"), "realized paper fill imported", row.get("notes")),
        }
    elif status == "canceled":
        outcome = {
            **outcome,
            "status": "not-opened",
            "notes": merge_notes(outcome.get("notes"), "paper fill row marked canceled", row.get("notes")),
        }

    updated_ticket = {
        **ticket,
        "paperExecution": paper_execution,
        "outcome": outcome,
        "importedFillKeys": sorted(imported_keys | {import_key}),
    }
    return updated_ticket, True, status


def ingest_fill_log() -> dict[str, Any]:
    """Import the current paperMoney fill log into the ledger and persist a report."""
    ensure_dirs()
    ledger = load_ledger()
    rows = load_fill_rows()
    updated_items = list(ledger.get("items") or [])
    by_ticket_id = {text(item.get("ticketId")): index for index, item in enumerate(updated_items)}

    imported = 0
    opened = 0
    closed = 0
    ignored = 0
    unmatched: list[str] = []
    notes: list[str] = []

    for row in rows:
        if not any(text(value) for value in row.values()):
            continue
        status = normalized_status(row.get("status"))
        if status in {"ignored", "unknown"}:
            ignored += 1
            notes.append(f"{text(row.get('ticker')).upper() or 'UNKNOWN'}: status ignored")
            continue

        candidates = candidate_tickets({"items": updated_items}, row)
        if len(candidates) != 1:
            reason = "no matching paper-staged ticket" if not candidates else "ambiguous ticket match"
            unmatched.append(
                f"{text(row.get('ticker')).upper() or 'UNKNOWN'} | {text(row.get('ticketId')) or 'no-ticket-id'} | {reason}"
            )
            continue

        candidate = candidates[0]
        index = by_ticket_id.get(text(candidate.get("ticketId")))
        if index is None:
            unmatched.append(f"{text(row.get('ticker')).upper() or 'UNKNOWN'} | internal ledger index missing")
            continue

        updated_ticket, changed, result = apply_fill_row(updated_items[index], row)
        if not changed:
            ignored += 1
            notes.append(f"{text(updated_items[index].get('ticker')).upper()}: {result}")
            continue

        updated_items[index] = updated_ticket
        imported += 1
        if result == "open":
            opened += 1
        elif result == "closed":
            closed += 1
        notes.append(f"{text(updated_ticket.get('ticker')).upper()}: imported {result} fill")

    updated_ledger = {
        **ledger,
        "updatedAt": local_now().isoformat(),
        "count": len(updated_items),
        "items": updated_items,
    }
    save_ledger(updated_ledger)

    report = {
        "generatedAt": local_now().isoformat(),
        "fillLogPath": str(TOS_FILL_LOG_WORK_FILE),
        "sourceLedgerPath": str(PAPER_EXECUTION_TEXT_FILE),
        "processedRows": len([row for row in rows if any(text(value) for value in row.values())]),
        "importedRows": imported,
        "openedRows": opened,
        "closedRows": closed,
        "ignoredRows": ignored,
        "unmatchedRows": unmatched,
        "notes": notes,
        "ledgerUpdatedAt": updated_ledger.get("updatedAt"),
    }
    save_ingest_report(report)
    return report


def ingest_report_text(report: dict[str, Any]) -> str:
    """Render a human-readable fill-ingest report."""
    lines = [
        "Inferno thinkorswim Fill Ingest",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Fill log: {report.get('fillLogPath')}",
        f"Processed rows: {report.get('processedRows', 0)}",
        f"Imported rows: {report.get('importedRows', 0)}",
        f"Opened rows: {report.get('openedRows', 0)}",
        f"Closed rows: {report.get('closedRows', 0)}",
        f"Ignored rows: {report.get('ignoredRows', 0)}",
        "",
        "Notes:",
    ]
    notes = report.get("notes") or []
    if notes:
        lines.extend(f"- {note}" for note in notes[:20])
    else:
        lines.append("- none")
    lines.extend(["", "Unmatched rows:"])
    unmatched = report.get("unmatchedRows") or []
    if unmatched:
        lines.extend(f"- {row}" for row in unmatched[:20])
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def save_ingest_report(report: dict[str, Any]) -> None:
    """Persist JSON and text artifacts for the latest fill-import pass."""
    ensure_dirs()
    TOS_FILL_INGEST_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    TOS_FILL_INGEST_TEXT_FILE.write_text(ingest_report_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for fill ingestion."""
    parser = argparse.ArgumentParser(description="Import thinkorswim paperMoney fills into the Inferno paper ledger.")
    parser.add_argument("command", nargs="?", default="ingest", choices=["ingest", "status"])
    return parser.parse_args()


def main() -> int:
    """Run the fill ingest or show the latest report."""
    args = parse_args()
    if args.command == "status" and TOS_FILL_INGEST_TEXT_FILE.exists():
        print(TOS_FILL_INGEST_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = ingest_fill_log()
    print(ingest_report_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
