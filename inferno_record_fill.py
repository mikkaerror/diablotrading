from __future__ import annotations

from inferno_ledger_ownership import paper_writer

"""Record operator-supplied paperMoney fill facts without CSV surgery.

This is a narrow paper-evidence convenience command. It can only update one
already-seeded fill-log row that maps to one existing ``paper-staged`` ledger
ticket, then delegates scoring to the canonical fill ingest. It never creates
tickets, invents execution facts, approves a ticket, or interacts with a
broker.
"""

import argparse
import math
from typing import Any

import inferno_tos_fill_ingest as fill_ingest
from inferno_config import local_now
from inferno_paper_execution import load_ledger
from inferno_performance_analytics import (
    MIN_SAMPLE_FOR_PROMOTION,
    build_performance_analytics,
    save_performance_analytics,
)
from inferno_tos_sandbox import load_fill_log_rows, save_fill_log_rows


RECORD_FILL_STAGE = "operator-paper-fill-capture-research-only"
PAPER_MONEY_ENVIRONMENT = fill_ingest.PAPER_MONEY_ENVIRONMENT


class RecordFillError(ValueError):
    """Raised when a proposed operator fill is not safe to write."""


def _text(value: Any) -> str:
    """Normalize user and CSV values with the ingest module's semantics."""
    return fill_ingest.text(value)


def _finite_nonnegative_price(value: Any, field: str) -> float:
    """Validate a supplied price using the ingest module's numeric primitive."""
    parsed = fill_ingest.number(value)
    if parsed is None or not math.isfinite(parsed) or parsed < 0:
        raise RecordFillError(f"{field} must be a finite non-negative paperMoney fill price")
    return parsed


def _valid_contract_count(value: Any) -> int:
    """Apply the same positive-integer contract constraint used for close evidence."""
    parsed = fill_ingest.number(value)
    if parsed is None or not math.isfinite(parsed) or parsed <= 0 or not parsed.is_integer():
        raise RecordFillError("contracts must be a positive integer")
    return int(parsed)


def _recordable_pairs(ledger: dict[str, Any], rows: list[dict[str, Any]]) -> list[tuple[dict[str, Any], int]]:
    """Return only rows tied exactly to one currently staged paper ticket.

    A fill-log row is insufficient by itself. The canonical fill-ingest
    matcher must resolve it uniquely to a current ``paper-staged`` ticket, so
    this command can never fabricate a fill for a similarly named ticker.
    """
    pairs: list[tuple[dict[str, Any], int]] = []
    for index, row in enumerate(rows):
        ticket_id = _text(row.get("ticketId"))
        if not ticket_id:
            continue
        candidates = fill_ingest.candidate_tickets(ledger, row)
        if len(candidates) != 1:
            continue
        ticket = candidates[0]
        if _text(ticket.get("ticketId")) != ticket_id or _text(ticket.get("status")) != "paper-staged":
            continue
        if fill_ingest.closed_fill_ticket_identity_gaps(ticket, row):
            continue
        if _text(row.get("environment")).lower() != PAPER_MONEY_ENVIRONMENT:
            continue
        pairs.append((ticket, index))
    return pairs


def resolve_recordable_fill(
    target: str,
    *,
    ledger: dict[str, Any],
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    """Resolve one staged, sandbox-seeded fill row by exact id or ticker."""
    target_text = _text(target)
    if not target_text:
        raise RecordFillError("provide a ticker or ticketId")
    upper_target = target_text.upper()
    matches = [
        (ticket, index)
        for ticket, index in _recordable_pairs(ledger, rows)
        if _text(ticket.get("ticketId")).upper() == upper_target or _text(ticket.get("ticker")).upper() == upper_target
    ]
    if not matches:
        raise RecordFillError(
            f"{target_text} has no matching sandbox-seeded paper-staged ticket; no fill was written"
        )
    if len(matches) != 1:
        ticket_ids = ", ".join(_text(ticket.get("ticketId")) for ticket, _ in matches)
        raise RecordFillError(f"{target_text} matches multiple staged tickets ({ticket_ids}); use the exact ticketId")
    return matches[0]


def _validate_open_row(ticket: dict[str, Any], row: dict[str, Any]) -> None:
    """Validate non-final entry facts before saving an open fill row."""
    if _text(row.get("environment")).lower() != PAPER_MONEY_ENVIRONMENT:
        raise RecordFillError("environment must remain thinkorswim-paperMoney")
    if fill_ingest.closed_fill_ticket_identity_gaps(ticket, row):
        raise RecordFillError("fill-log immutable identity no longer matches the staged ticket")
    _finite_nonnegative_price(row.get("entryPrice"), "entry price")
    _valid_contract_count(row.get("contracts"))
    if fill_ingest.parse_execution_timestamp(row.get("openedAt")) is None:
        raise RecordFillError("openedAt must be a timezone-aware ISO timestamp")


def _validate_closed_row(ticket: dict[str, Any], row: dict[str, Any]) -> None:
    """Reuse the canonical close-evidence validators before saving a close row."""
    gaps = fill_ingest.closed_fill_evidence_gaps(row)
    if gaps:
        raise RecordFillError("closed fill rejected by existing validator: " + ", ".join(gaps))
    identity_gaps = fill_ingest.closed_fill_ticket_identity_gaps(ticket, row)
    if identity_gaps:
        raise RecordFillError("closed fill rejected by existing validator: " + ", ".join(identity_gaps))
    _, changed, result = fill_ingest.apply_fill_row(ticket, row)
    if not changed or result != "closed":
        raise RecordFillError(f"closed fill rejected by existing validator: {result}")


def _updated_row(
    row: dict[str, Any],
    *,
    entry_price: float | None,
    exit_price: float | None,
    contracts: int | None,
) -> tuple[dict[str, Any], str]:
    """Build one legal state transition while preserving all other fill facts."""
    existing_status = fill_ingest.normalized_status(row.get("status"))
    updated = dict(row)
    if entry_price is not None:
        if existing_status != "ignored":
            raise RecordFillError("entry may only be recorded on a seeded planned fill-log row")
        updated["entryPrice"] = f"{entry_price:g}"
        if contracts is not None:
            updated["contracts"] = str(contracts)
        updated["status"] = "open"
        updated["openedAt"] = local_now().isoformat()
        return updated, "open"

    if exit_price is None:
        raise RecordFillError("provide exactly one of entry or exit price")
    if existing_status != "open":
        raise RecordFillError("exit may only be recorded after an imported open fill")
    updated["exitPrice"] = f"{exit_price:g}"
    updated["status"] = "closed"
    updated["closedAt"] = local_now().isoformat()
    return updated, "closed"


@paper_writer
def record_fill(
    target: str,
    *,
    entry_price: float | None = None,
    exit_price: float | None = None,
    contracts: int | None = None,
) -> dict[str, Any]:
    """Record one actual operator fill, ingest it, and refresh scored evidence."""
    from inferno_ledger_ownership import require_paper_writer
    require_paper_writer("operator fill write")
    if (entry_price is None) == (exit_price is None):
        raise RecordFillError("provide exactly one of --entry or --exit")
    if exit_price is not None and contracts is not None:
        raise RecordFillError("contracts can only be supplied when recording an entry")
    if entry_price is not None:
        entry_price = _finite_nonnegative_price(entry_price, "entry price")
    if exit_price is not None:
        exit_price = _finite_nonnegative_price(exit_price, "exit price")
    if contracts is not None:
        contracts = _valid_contract_count(contracts)

    ledger_before = load_ledger()
    rows = load_fill_log_rows()
    ticket, row_index = resolve_recordable_fill(target, ledger=ledger_before, rows=rows)
    updated, action = _updated_row(
        rows[row_index],
        entry_price=entry_price,
        exit_price=exit_price,
        contracts=contracts,
    )
    if action == "open":
        _validate_open_row(ticket, updated)
    else:
        _validate_closed_row(ticket, updated)

    before_analytics = build_performance_analytics(ledger_before)
    rows[row_index] = updated
    save_fill_log_rows(rows)
    ingest_report = fill_ingest.ingest_fill_log(operator_requested=True, ticket_id=_text(ticket.get("ticketId")))
    analytics = build_performance_analytics(load_ledger())
    save_performance_analytics(analytics)
    return {
        "stage": RECORD_FILL_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "action": action,
        "ticketId": _text(ticket.get("ticketId")),
        "ticker": _text(ticket.get("ticker")).upper(),
        "strategy": _text(ticket.get("strategy")),
        "ingest": ingest_report,
        "scoredCountBefore": (before_analytics.get("closedMetrics") or {}).get("scoredCount", 0),
        "scoredCount": (analytics.get("closedMetrics") or {}).get("scoredCount", 0),
        "promotionTarget": MIN_SAMPLE_FOR_PROMOTION,
    }


def record_fill_text(result: dict[str, Any]) -> str:
    """Render the operator confirmation and current promotion-gate count."""
    ingest = result.get("ingest") or {}
    return "\n".join(
        [
            "Inferno record-fill (research-only)",
            "",
            f"Recorded: {result.get('action')} | {result.get('ticker')} | {result.get('ticketId')}",
            f"Fill ingest: {ingest.get('importedRows', 0)} imported | {ingest.get('openedRows', 0)} open | {ingest.get('closedRows', 0)} closed | {ingest.get('rejectedRows', 0)} rejected",
            f"Scored paper outcomes: {result.get('scoredCount', 0)}/{result.get('promotionTarget', MIN_SAMPLE_FOR_PROMOTION)} (was {result.get('scoredCountBefore', 0)})",
            "No ticket, approval, authority, or broker-submit state was changed.",
        ]
    ) + "\n"


def _prompt_price(label: str) -> float:
    """Prompt only when the operator omitted the corresponding short flag."""
    try:
        raw = input(f"{label} paperMoney fill price: ").strip()
    except EOFError as exc:
        raise RecordFillError(f"{label} price is required") from exc
    return _finite_nonnegative_price(raw, f"{label} price")


def _interactive_values(args: argparse.Namespace) -> tuple[float | None, float | None, int | None]:
    """Choose entry/exit interactively only when no price flag was supplied."""
    if args.entry is not None or args.exit is not None:
        return args.entry, args.exit, args.contracts
    try:
        action = input("Record [e]ntry or e[x]it? ").strip().lower()
    except EOFError as exc:
        raise RecordFillError("choose entry or exit, or pass --entry/--exit") from exc
    if action in {"e", "entry", "open"}:
        return _prompt_price("entry"), None, args.contracts
    if action in {"x", "exit", "close"}:
        return None, _prompt_price("exit"), args.contracts
    raise RecordFillError("choose entry or exit")


def parse_args() -> argparse.Namespace:
    """Parse a narrow operator-only fill-recording command."""
    parser = argparse.ArgumentParser(description="Record one operator-supplied thinkorswim paperMoney fill.")
    parser.add_argument("target", help="paper-staged ticker or exact ticketId")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--entry", type=float, help="actual net paperMoney entry fill")
    group.add_argument("--exit", type=float, help="actual net paperMoney exit fill")
    parser.add_argument("--contracts", type=int, help="actual positive integer contracts, for entry only")
    return parser.parse_args()


def main() -> int:
    """Run a manual evidence capture without any broker authority action."""
    args = parse_args()
    try:
        entry_price, exit_price, contracts = _interactive_values(args)
        result = record_fill(
            args.target,
            entry_price=entry_price,
            exit_price=exit_price,
            contracts=contracts,
        )
    except RecordFillError as exc:
        print(f"record-fill rejected: {exc}")
        return 2
    print(record_fill_text(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
