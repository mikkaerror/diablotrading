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
import math
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime
from typing import Any

from inferno_artifact_lifecycle import successful_lifecycle
from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_paper_execution import PAPER_EXECUTION_TEXT_FILE, load_ledger, save_ledger
from inferno_tos_sandbox import TOS_FILL_LOG_WORK_FILE, write_fill_log_template
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


TOS_FILL_INGEST_FILE = DATA_DIR / "inferno_tos_fill_ingest.json"
TOS_FILL_INGEST_TEXT_FILE = REPORTS_DIR / "tos_fill_ingest_latest.txt"
OPEN_STATUSES = {"open", "opened", "filled", "paper-open"}
CLOSED_STATUSES = {"closed", "closed-win", "closed-loss", "exited"}
IGNORED_STATUSES = {"", "pending", "watch", "planned"}
CONTRACT_MULTIPLIER = 100
PAPER_MONEY_ENVIRONMENT = "thinkorswim-papermoney"
CLOSED_FILL_IMMUTABLE_FIELDS = (
    "ticketId",
    "ticker",
    "strategy",
    "environment",
    "contracts",
    "entryPrice",
    "exitPrice",
    "openedAt",
    "closedAt",
)


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
    # Preserve legacy keys when optional economics metadata is absent. Once
    # supplied, costs and basis must participate in idempotency/provenance.
    if any(text(row.get(field)) for field in ("totalFees", "realizedPnlBasis")):
        raw += "|economics-v1|" + json.dumps({field: text(row.get(field)) for field in
                 ("totalFees", "realizedPnlBasis", "contracts", "environment", "expiration")}, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def contracts_for_row(row: dict[str, Any]) -> int:
    """Return the contract count, defaulting to one spread/position."""
    value = number(row.get("contracts"), 1.0)
    return max(1, int(value or 1))


def parse_execution_timestamp(value: Any) -> datetime | None:
    """Parse a timezone-aware paper execution timestamp without guessing."""
    raw = text(value)
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def closed_fill_evidence_gaps(row: dict[str, Any]) -> list[str]:
    """Return immutable execution facts that a closed fill must supply.

    Closed rows cannot inherit prices, contracts, timestamps, or environment
    from the planned ticket.  This keeps a CSV row as evidence of an actual
    paper execution rather than a way to turn a plan into a completed outcome.
    """
    gaps = [field for field in ("ticketId", "ticker", "strategy") if not text(row.get(field))]
    environment = text(row.get("environment")).lower()
    if environment != PAPER_MONEY_ENVIRONMENT:
        gaps.append("environment")
    contracts = number(row.get("contracts"))
    if contracts is None or not math.isfinite(contracts) or contracts <= 0 or not contracts.is_integer():
        gaps.append("contracts")
    for field in ("entryPrice", "exitPrice"):
        price = number(row.get(field))
        if price is None or not math.isfinite(price) or price < 0:
            gaps.append(field)
    opened_at = parse_execution_timestamp(row.get("openedAt"))
    closed_at = parse_execution_timestamp(row.get("closedAt"))
    if opened_at is None:
        gaps.append("openedAt")
    if closed_at is None or (opened_at is not None and closed_at is not None and closed_at < opened_at):
        gaps.append("closedAt")
    return [field for field in CLOSED_FILL_IMMUTABLE_FIELDS if field in gaps]


def closed_fill_ticket_identity_gaps(ticket: dict[str, Any], row: dict[str, Any]) -> list[str]:
    """Return closed-fill identity facts that disagree with the matched ticket."""
    comparisons = (
        ("ticketId", text(row.get("ticketId")), text(ticket.get("ticketId"))),
        ("ticker", text(row.get("ticker")).upper(), text(ticket.get("ticker")).upper()),
        ("strategy", text(row.get("strategy")).upper(), text(ticket.get("strategy")).upper()),
    )
    return [field for field, supplied, expected in comparisons if supplied != expected]


def load_fill_rows(*, read_only: bool = False) -> list[dict[str, Any]]:
    """Load the paperMoney fill log after ensuring the latest schema exists."""
    if not read_only:
        write_fill_log_template()
    if not TOS_FILL_LOG_WORK_FILE.exists():
        return []
    with TOS_FILL_LOG_WORK_FILE.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def candidate_tickets(ledger: dict[str, Any], row: dict[str, Any]) -> list[dict[str, Any]]:
    """Return safe candidate paper tickets for one fill row.

    Closed rows require an exact ``ticketId`` match. Fallback matching is only
    available to non-final rows, using ticker plus optional strategy and the
    paper-staged lane so a closed fill cannot be attached to the wrong plan.
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

    if normalized_status(row.get("status")) == "closed":
        return []

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


def fill_pnl_reconciliation(ticket: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """Reconcile a complete standard-multiplier position in USD.

    Entry/exit are net premium per position unit; quantity is the number of
    identical positions, not a sum of legs. totalFees is the total round-trip
    commissions plus fees for all units and legs. Missing costs remain unknown.
    This is arithmetic reconciliation of operator data, never broker proof.
    """
    issues = []

    def amount(field: str, *, required: bool = False) -> Decimal | None:
        value = row.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            if required:
                issues.append(f"missing-{field}")
            return None
        try:
            parsed = Decimal(str(value))
            if isinstance(value, bool) or not parsed.is_finite() or not math.isfinite(float(parsed)):
                raise InvalidOperation
            return parsed
        except (InvalidOperation, ValueError, OverflowError):
            issues.append(f"invalid-{field}")
            return None

    entry, exit_price = amount("entryPrice", required=True), amount("exitPrice", required=True)
    quantity = amount("contracts", required=True)
    supplied = amount("realizedPnl")
    fees = amount("totalFees")
    basis = text(row.get("realizedPnlBasis")).lower()
    if basis not in {"", "gross", "net"}:
        issues.append("unsupported-pnl-basis")
    if fees is not None and fees < 0:
        issues.append("negative-totalFees")
    if fees is not None and not basis:
        issues.append("pnl-basis-required-with-fees")
    if basis == "net" and fees is None:
        issues.append("net-pnl-requires-totalFees")
    cost_type = text(ticket.get("entryCostType")).lower()
    if cost_type not in {"debit", "credit"}:
        issues.append("unsupported-entry-cost-type")
    for field, value in (("entryPrice", entry), ("exitPrice", exit_price)):
        if value is not None and value < 0:
            issues.append(f"negative-{field}")
    if quantity is not None and (quantity <= 0 or quantity != quantity.to_integral_value()):
        issues.append("invalid-contracts")
    gross = net = expected = None
    if not issues:
        try:
            change = entry - exit_price if cost_type == "credit" else exit_price - entry
            gross = (change * CONTRACT_MULTIPLIER * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            net = (gross-fees).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if fees is not None else None
            expected = net if basis == "net" else gross
            if supplied is not None and supplied.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) != expected:
                issues.append("reported-pnl-does-not-reconcile")
        except (InvalidOperation, OverflowError):
            issues.append("invalid-pnl-arithmetic")
    valid = not issues
    return {"arithmeticReconciled": valid, "issues": sorted(set(issues)),
            "grossPnl": float(gross) if gross is not None else None,
            "netPnl": float(net) if valid and net is not None else None,
            "totalFees": float(fees) if fees is not None and fees >= 0 else None,
            "reportedBasis": basis or "legacy-gross-assumption",
            "reportedOrDerivedPnl": float(expected) if valid else None,
            "scoringPnl": float(net if net is not None else gross) if valid else None,
            "costStatus": "operator-reported-costs" if valid and fees is not None else "unknown",
            "pnlBasis": "net of operator-reported fees" if valid and fees is not None else "gross; fees unknown",
            "independentlyVerified": False,
            "contractMultiplier": CONTRACT_MULTIPLIER}


def derived_realized_pnl(ticket: dict[str, Any], row: dict[str, Any]) -> float | None:
    """Return reconciled closed P/L; never trust a contradictory supplied value."""
    return fill_pnl_reconciliation(ticket, row)["reportedOrDerivedPnl"]


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
    if status == "closed":
        if text(ticket.get("status")) != "paper-staged":
            return ticket, False, "closed fill rejected: matched ticket is not paper-staged"
        gaps = closed_fill_evidence_gaps(row)
        if gaps:
            return ticket, False, "closed fill rejected: immutable evidence missing or invalid: " + ", ".join(gaps)
        identity_gaps = closed_fill_ticket_identity_gaps(ticket, row)
        if identity_gaps:
            return ticket, False, "closed fill rejected: immutable identity does not match ticket: " + ", ".join(identity_gaps)

        reconciliation = fill_pnl_reconciliation(ticket, row)
        if not reconciliation["arithmeticReconciled"]:
            return ticket, False, "closed fill rejected: P/L evidence invalid: " + ", ".join(reconciliation["issues"])

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
        "totalFees": number(row.get("totalFees")),
        "realizedPnlBasis": text(row.get("realizedPnlBasis")) or None,
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


def ingest_fill_log(*, operator_requested: bool = False, ticket_id: str | None = None) -> dict[str, Any]:
    """Preview by default; only explicit operator entrypoints may persist fills."""
    if operator_requested:
        from inferno_ledger_ownership import require_paper_writer
        require_paper_writer("fill ingestion")
    ensure_dirs()
    ledger = load_ledger()
    rows = load_fill_rows(read_only=not operator_requested)
    if ticket_id is not None:
        rows = [row for row in rows if text(row.get("ticketId")) == ticket_id]
    updated_items = list(ledger.get("items") or [])
    by_ticket_id = {text(item.get("ticketId")): index for index, item in enumerate(updated_items)}

    imported = 0
    opened = 0
    closed = 0
    ignored = 0
    rejected = 0
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
        if status == "closed":
            gaps = closed_fill_evidence_gaps(row)
            if gaps:
                rejected += 1
                notes.append(
                    f"{text(row.get('ticker')).upper() or 'UNKNOWN'}: closed fill rejected: "
                    f"immutable evidence missing or invalid: {', '.join(gaps)}"
                )
                continue

        candidates = candidate_tickets({"items": updated_items}, row)
        if len(candidates) != 1:
            if status == "closed":
                rejected += 1
                notes.append(
                    f"{text(row.get('ticker')).upper() or 'UNKNOWN'}: closed fill rejected: "
                    "exact paper-staged ticketId match required"
                )
                continue
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
            if result.startswith("closed fill rejected:"):
                rejected += 1
            else:
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

    if not operator_requested:
        # Never advance lifecycle timestamps, rewrite the fill log, or overwrite
        # the last actual ingest report for observational background work.
        return {
            "generatedAt": local_now().isoformat(),
            "researchOnly": True,
            "liveTradingAllowed": False,
            "brokerSubmitAllowed": False,
            "authorityChanged": False,
            "mode": "preview",
            "processedRows": len(rows),
            "importedRows": 0,
            "openedRows": 0,
            "closedRows": 0,
            "acceptedProgressUnits": 0,
            "proposedImportedRows": imported,
            "proposedOpenedRows": opened,
            "proposedClosedRows": closed,
            "rejectedRows": rejected,
            "ignoredRows": ignored,
            "unmatchedRows": unmatched,
            "notes": ["Preview only; no ticket or fill-log changes.", *notes],
            "outcome": "operator-ingest-required" if imported else "no-progress-preview",
            "outcomeReason": "Only explicit operator fill commands may apply these rows.",
        }

    updated_ledger = successful_lifecycle(
        {
            **ledger,
            "count": len(updated_items),
            "items": updated_items,
        },
        producer="inferno-tos-fill-ingest",
        source_data_as_of=ledger.get("sourceDataAsOf"),
        freshness_ttl_hours=36,
        schedule="operator paper-fill ingest",
    )
    save_ledger(updated_ledger)

    if imported:
        outcome = "accepted-progress"
        outcome_reason = "at least one paper fill was matched and applied to a staged ticket"
    elif rejected:
        outcome = "no-progress-invalid-evidence"
        outcome_reason = "closed fill rows were rejected; immutable evidence remains incomplete or mismatched"
    elif unmatched:
        outcome = "no-progress-unmatched-ticket"
        outcome_reason = "fill rows did not map to exactly one paper-staged ticket"
    elif ignored:
        outcome = "no-progress-planned-or-ignored"
        outcome_reason = "the fill log contains planning/stub rows, not accepted execution evidence"
    else:
        outcome = "no-progress-empty-log"
        outcome_reason = "the fill log contains no nonblank rows"

    report = {
        "generatedAt": local_now().isoformat(),
        "fillLogPath": str(TOS_FILL_LOG_WORK_FILE),
        "sourceLedgerPath": str(PAPER_EXECUTION_TEXT_FILE),
        "processedRows": len([row for row in rows if any(text(value) for value in row.values())]),
        "importedRows": imported,
        "openedRows": opened,
        "closedRows": closed,
        "ignoredRows": ignored,
        "rejectedRows": rejected,
        "unmatchedRows": unmatched,
        "notes": notes,
        "acceptedProgressUnits": imported,
        "outcome": outcome,
        "outcomeReason": outcome_reason,
        "ledgerUpdatedAt": updated_ledger.get("updatedAt"),
        "ledgerLastSuccessfulAt": updated_ledger.get("lastSuccessfulAt"),
        "ledgerLifecycleStatus": updated_ledger.get("lifecycleStatus"),
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
        f"Proposed imports (unapplied): {report.get('proposedImportedRows', 0)}",
        f"Opened rows: {report.get('openedRows', 0)}",
        f"Closed rows: {report.get('closedRows', 0)}",
        f"Ignored rows: {report.get('ignoredRows', 0)}",
        f"Rejected rows: {report.get('rejectedRows', 0)}",
        f"Outcome: {report.get('outcome') or '-'} | accepted progress: {report.get('acceptedProgressUnits', 0)}",
        f"Reason: {report.get('outcomeReason') or '-'}",
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
    atomic_write_json(TOS_FILL_INGEST_FILE, report)
    atomic_write_text(TOS_FILL_INGEST_TEXT_FILE, ingest_report_text(report))


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for fill ingestion."""
    parser = argparse.ArgumentParser(description="Import thinkorswim paperMoney fills into the Inferno paper ledger.")
    parser.add_argument("command", nargs="?", default="ingest", choices=["ingest", "preview", "status"])
    parser.add_argument("--operator-requested", action="store_true",
                        help="Apply reviewed fills; reserved for the operator, never scheduled jobs.")
    return parser.parse_args()


def main() -> int:
    """Run the fill ingest or show the latest report."""
    args = parse_args()
    if args.command == "status" and TOS_FILL_INGEST_TEXT_FILE.exists():
        print(TOS_FILL_INGEST_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = ingest_fill_log(operator_requested=args.command == "ingest" and args.operator_requested)
    print(ingest_report_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
