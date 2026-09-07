from __future__ import annotations

"""Audit whether closed staged paper outcomes have fill-backed provenance.

The strategy lab scores source-reconciled recorded paper fills. This audit
keeps unverified numeric outcomes visible without granting them sample credit.
A source match is not independent verification against broker history.
"""

import argparse
import csv
from collections import Counter
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_paper_execution import PAPER_EXECUTION_LEDGER_FILE, paper_event_id
from inferno_strategy_lab import closed_trade_records, reported_closed_trade_records
from inferno_paper_provenance import load_fill_source, outcome_provenance
from inferno_tos_fill_ingest import (
    TOS_FILL_INGEST_FILE,
    closed_fill_evidence_gaps,
    closed_fill_ticket_identity_gaps,
    normalized_status,
)
from inferno_tos_sandbox import FILL_LOG_COLUMNS, TOS_FILL_LOG_WORK_FILE
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


PAPER_OUTCOME_COMPLETENESS_FILE = DATA_DIR / "inferno_paper_outcome_completeness.json"
PAPER_OUTCOME_COMPLETENESS_TEXT_FILE = REPORTS_DIR / "paper_outcome_completeness_latest.txt"
def _text(value: Any) -> str:
    return str(value or "").strip()


def _present(value: Any) -> bool:
    """Treat zero P/L or price as present; only null/blank values are missing."""
    return value is not None and _text(value) != ""


def _positive(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def fill_intake_readiness(ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    """Inspect the canonical paper-fill intake path without running an ingest.

    Reading the CSV is intentionally separate from ``ingest_fill_log``.  This
    audit must never update a paper ticket, alter an outcome, or turn a pending
    fill row into a closed result merely to make the evidence dashboard look
    healthier.
    """
    ledger = ledger if ledger is not None else (load_json_file(PAPER_EXECUTION_LEDGER_FILE) or {})
    staged_by_ticket_id: dict[str, list[dict[str, Any]]] = {}
    for ticket in ledger.get("items") or []:
        if not isinstance(ticket, dict) or _text(ticket.get("status")) != "paper-staged":
            continue
        ticket_id = _text(ticket.get("ticketId"))
        if ticket_id:
            staged_by_ticket_id.setdefault(ticket_id, []).append(ticket)

    report = {
        "path": str(TOS_FILL_LOG_WORK_FILE),
        "exists": TOS_FILL_LOG_WORK_FILE.exists(),
        "schemaValid": False,
        "schemaMissingColumns": list(FILL_LOG_COLUMNS),
        "schemaUnexpectedColumns": [],
        "readError": None,
        "rowCount": 0,
        "nonblankRows": 0,
        "statusCounts": {},
        "rawStatusCounts": {},
        "plannedStubRows": 0,
        "openRows": 0,
        "closedRows": 0,
        "closedRowsFormatComplete": 0,
        "closeReadyRows": 0,
        "closedRowsMissingEvidence": 0,
        "closedRowsUnmatchedTicket": 0,
        "closedRowsAmbiguousTicket": 0,
        "closedRowsIdentityMismatch": 0,
        "closedMissingFieldCounts": {},
        "closedIdentityMismatchCounts": {},
        "ignoredRows": 0,
        "unknownStatusRows": 0,
        "lastIngest": {
            "present": False,
            "generatedAt": None,
            "processedRows": None,
            "importedRows": None,
            "closedRows": None,
            "rejectedRows": None,
            "unmatchedRows": None,
            "outcome": None,
            "acceptedProgressUnits": None,
        },
    }
    ingest = load_json_file(TOS_FILL_INGEST_FILE) or {}
    report["lastIngest"] = {
        "present": bool(ingest),
        "generatedAt": ingest.get("generatedAt"),
        "processedRows": ingest.get("processedRows"),
        "importedRows": ingest.get("importedRows"),
        "closedRows": ingest.get("closedRows"),
        "rejectedRows": ingest.get("rejectedRows"),
        "unmatchedRows": len(ingest.get("unmatchedRows") or []),
        "outcome": ingest.get("outcome"),
        "acceptedProgressUnits": ingest.get("acceptedProgressUnits"),
    }
    if not TOS_FILL_LOG_WORK_FILE.exists():
        return report

    try:
        with TOS_FILL_LOG_WORK_FILE.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = reader.fieldnames or []
            field_set = set(fields)
            expected_set = set(FILL_LOG_COLUMNS)
            report["schemaMissingColumns"] = [column for column in FILL_LOG_COLUMNS if column not in field_set]
            report["schemaUnexpectedColumns"] = [column for column in fields if column not in expected_set]
            report["schemaValid"] = not report["schemaMissingColumns"] and not report["schemaUnexpectedColumns"]
            rows = list(reader)
    except (OSError, csv.Error) as exc:
        report["readError"] = str(exc)
        return report

    report["rowCount"] = len(rows)
    status_counts: Counter[str] = Counter()
    raw_status_counts: Counter[str] = Counter()
    missing_counts: Counter[str] = Counter()
    identity_counts: Counter[str] = Counter()
    for row in rows:
        if not any(_present(value) for value in row.values()):
            continue
        report["nonblankRows"] += 1
        status = normalized_status(row.get("status"))
        raw_status = _text(row.get("status")).lower() or "blank"
        status_counts[status] += 1
        raw_status_counts[raw_status] += 1
        if raw_status in {"planned", "pending", "watch"}:
            report["plannedStubRows"] += 1
        if status == "open":
            report["openRows"] += 1
        elif status == "closed":
            report["closedRows"] += 1
            missing = closed_fill_evidence_gaps(row)
            if missing:
                report["closedRowsMissingEvidence"] += 1
                missing_counts.update(missing)
                continue
            report["closedRowsFormatComplete"] += 1
            candidates = staged_by_ticket_id.get(_text(row.get("ticketId"))) or []
            if not candidates:
                report["closedRowsUnmatchedTicket"] += 1
                continue
            if len(candidates) != 1:
                report["closedRowsAmbiguousTicket"] += 1
                continue
            identity_gaps = closed_fill_ticket_identity_gaps(candidates[0], row)
            if identity_gaps:
                report["closedRowsIdentityMismatch"] += 1
                identity_counts.update(identity_gaps)
                continue
            report["closeReadyRows"] += 1
        elif status == "ignored":
            report["ignoredRows"] += 1
        elif status == "unknown":
            report["unknownStatusRows"] += 1
    report["statusCounts"] = dict(sorted(status_counts.items()))
    report["rawStatusCounts"] = dict(sorted(raw_status_counts.items()))
    report["closedMissingFieldCounts"] = dict(sorted(missing_counts.items()))
    report["closedIdentityMismatchCounts"] = dict(sorted(identity_counts.items()))
    return report


def fill_intake_verdict(intake: dict[str, Any]) -> str:
    """Classify intake readiness without treating a valid file as evidence."""
    if intake.get("readError"):
        return "fill-log-read-error"
    if not intake.get("exists"):
        return "fill-log-missing"
    if not intake.get("schemaValid"):
        return "fill-log-schema-invalid"
    if intake.get("closeReadyRows", 0):
        return "closed-fill-ready-for-operator-ingest"
    if any(
        intake.get(field, 0)
        for field in ("closedRowsUnmatchedTicket", "closedRowsAmbiguousTicket", "closedRowsIdentityMismatch")
    ):
        return "closed-fill-ticket-unmatched"
    if intake.get("closedRowsMissingEvidence", 0):
        return "closed-fill-provenance-incomplete"
    if intake.get("openRows", 0):
        return "open-fill-awaiting-close"
    if intake.get("plannedStubRows", 0):
        return "fill-log-stubbed-awaiting-operator-execution"
    if intake.get("ignoredRows", 0):
        return "fill-log-populated-but-no-accepted-status"
    return "fill-log-empty"


def operator_work_items(audits: list[dict[str, Any]], intake: dict[str, Any]) -> list[dict[str, Any]]:
    """Name the minimum evidence work without generating or importing a fill."""
    items: list[dict[str, Any]] = []
    for audit in audits:
        if audit.get("state") != "reported-outcome-provenance-debt":
            continue
        items.append(
            {
                "kind": "recover-closed-paper-fill-provenance",
                "ticketId": audit.get("ticketId"),
                "ticker": audit.get("ticker"),
                "missingFields": audit.get("missingFields") or [],
                "provenanceIssues": audit.get("provenanceIssues") or [],
                "instruction": "Use actual paperMoney order/fill history only; do not infer or backfill missing execution facts.",
            }
        )
    if intake.get("plannedStubRows", 0):
        items.append(
            {
                "kind": "complete-paper-fill-stubs-after-actual-execution",
                "rowCount": intake.get("plannedStubRows"),
                "instruction": "Planned rows are templates, not evidence. Update one only after its actual paperMoney fill and keep the exact ticketId.",
            }
        )
    if intake.get("closeReadyRows", 0):
        items.append(
            {
                "kind": "operator-review-before-fill-ingest",
                "rowCount": intake.get("closeReadyRows"),
                "instruction": "Review the matched closed fill evidence, then run the explicit fill-ingest command; this audit never imports it automatically.",
            }
        )
    return items


def audit_closed_staged_ticket(ticket: dict[str, Any], source: dict[str, Any] | None = None, counted_ids: set[str] | None = None) -> dict[str, Any]:
    """Evaluate one closed staged row without mutating it or its outcome."""
    paper_execution = ticket.get("paperExecution") or {}
    outcome = ticket.get("outcome") or {}
    metrics = (ticket.get("riskVerdict") or {}).get("metrics") or {}
    max_loss = metrics.get("maxLossDollars", ticket.get("estimatedMaxLoss"))
    source = load_fill_source() if source is None else source
    provenance = outcome_provenance(ticket, source)
    lab_scorable = (ticket.get("ticketId") in counted_ids if counted_ids is not None
                    else bool(closed_trade_records([ticket], source)))
    reported_scorable = bool(reported_closed_trade_records([ticket]))
    missing: list[str] = []

    for field, value in (
        ("ticketId", ticket.get("ticketId")),
        ("ticker", ticket.get("ticker")),
        ("strategy", ticket.get("strategy") or ticket.get("setupRec")),
        ("outcome.reviewedAt", outcome.get("reviewedAt")),
        ("outcome.estimatedPnl", outcome.get("estimatedPnl")),
        ("paperExecution.environment", paper_execution.get("environment")),
        ("paperExecution.source", paper_execution.get("source")),
        ("paperExecution.contracts", paper_execution.get("contracts")),
        ("paperExecution.entryPrice", paper_execution.get("entryPrice")),
        ("paperExecution.exitPrice", paper_execution.get("exitPrice")),
        ("paperExecution.openedAt", paper_execution.get("openedAt")),
        ("paperExecution.closedAt", paper_execution.get("closedAt")),
        ("paperExecution.realizedPnl", paper_execution.get("realizedPnl")),
    ):
        if not _present(value):
            missing.append(field)
    if not _positive(max_loss):
        missing.append("maxLossDollars/estimatedMaxLoss")

    provenance_issues: list[str] = []
    if _present(paper_execution.get("environment")) and _text(paper_execution.get("environment")).lower() != "thinkorswim-papermoney":
        provenance_issues.append("paperExecution.environment is not thinkorswim-paperMoney")
    if _present(paper_execution.get("source")) and _text(paper_execution.get("source")) != "paper-fill-log":
        provenance_issues.append("paperExecution.source is not paper-fill-log")

    provenance_issues.extend(provenance["issues"])
    audit_complete = lab_scorable and not missing and not provenance_issues
    if audit_complete:
        state = "audit-complete"
    elif reported_scorable:
        state = "reported-outcome-provenance-debt"
    else:
        state = "closed-unscorable"

    return {
        "ticketId": _text(ticket.get("ticketId")) or None,
        "ticker": _text(ticket.get("ticker") or ticket.get("symbol")).upper() or None,
        "strategy": _text(ticket.get("strategy") or ticket.get("setupRec")) or None,
        "eventId": paper_event_id(ticket),
        "status": _text(ticket.get("status")) or None,
        "outcomeStatus": _text(outcome.get("status")) or None,
        "labScorable": lab_scorable,
        "reportedScorable": reported_scorable,
        "provenance": provenance,
        "auditComplete": audit_complete,
        "state": state,
        "missingFields": missing,
        "provenanceIssues": provenance_issues,
        "outcomeNotes": _text(outcome.get("notes")) or None,
    }


def build_paper_outcome_completeness(ledger: dict[str, Any] | None = None, source: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a strictly read-only completeness report for closed staged tickets."""
    ledger = ledger if ledger is not None else (load_json_file(PAPER_EXECUTION_LEDGER_FILE) or {})
    items = [item for item in ledger.get("items", []) if isinstance(item, dict)]
    closed_staged = [
        item
        for item in items
        if _text(item.get("status")) == "paper-staged"
        and _text((item.get("outcome") or {}).get("status")) == "closed"
    ]
    source = load_fill_source() if source is None else source
    counted_ids = {row["ticketId"] for row in closed_trade_records(items, source)}
    audits = [audit_closed_staged_ticket(ticket, source, counted_ids) for ticket in closed_staged]
    state_counts = Counter(audit.get("state") or "unknown" for audit in audits)
    missing_counts = Counter(
        field
        for audit in audits
        for field in (audit.get("missingFields") or [])
    )
    provenance_counts = Counter(
        issue
        for audit in audits
        for issue in (audit.get("provenanceIssues") or [])
    )
    lab_scorable = sum(1 for audit in audits if audit.get("labScorable"))
    audit_complete = sum(1 for audit in audits if audit.get("auditComplete"))
    intake = fill_intake_readiness(ledger)

    return {
        "generatedAt": local_now().isoformat(),
        "stage": "paper-outcome-completeness-research-only",
        "researchOnly": True,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "sourceLedgerUpdatedAt": ledger.get("updatedAt"),
        "fillSource": {key: value for key, value in source.items() if key != "rows"},
        "counts": {
            "ledgerRows": len(items),
            "closedStagedRows": len(audits),
            "labScorableRows": lab_scorable,
            "auditCompleteRows": audit_complete,
            "labScorableWithProvenanceDebt": lab_scorable - audit_complete,
            "reportedScorableRows": sum(bool(row["reportedScorable"]) for row in audits),
            "reportedRowsWithProvenanceDebt": sum(bool(row["reportedScorable"]) and not row["auditComplete"] for row in audits),
            "independentlyVerifiedRows": 0,
        },
        "stateCounts": dict(sorted(state_counts.items())),
        "missingFieldCounts": dict(sorted(missing_counts.items())),
        "provenanceIssueCounts": dict(sorted(provenance_counts.items())),
        "outcomes": audits,
        "fillIntake": {
            **intake,
            "verdict": fill_intake_verdict(intake),
            "operatorIngestNeeded": bool(intake.get("closeReadyRows")),
            "ingestRunsAutomaticallyFromThisAudit": False,
        },
        "operatorWorkItems": operator_work_items(audits, intake),
        "reminders": [
            "strategy-lab scoring eligibility is unchanged by this diagnostic",
            "audit-complete means source-reconciled fields; it is not independent broker verification or a promotion action",
            "the diagnostic never changes ticket, outcome, fill-log, approval, risk, or authority data",
            "fill-log readiness is observational; this audit never runs the fill importer",
        ],
        "citations": [PAPER_EXECUTION_LEDGER_FILE.name],
    }


def paper_outcome_completeness_text(payload: dict[str, Any]) -> str:
    """Render the quality gap without disguising it as a promotion decision."""
    counts = payload.get("counts") or {}
    intake = payload.get("fillIntake") or {}
    lines = [
        "Inferno Paper Outcome Completeness",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        "Authority: research-only; broker submit OFF; live trading OFF",
        "",
        "Scoring versus provenance:",
        f"- closed staged rows: {counts.get('closedStagedRows', 0)}",
        f"- strategy-lab scorable: {counts.get('labScorableRows', 0)}",
        f"- audit-complete source-reconciled outcomes: {counts.get('auditCompleteRows', 0)}",
        f"- reported numeric rows with provenance debt: {counts.get('reportedRowsWithProvenanceDebt', 0)}",
        "- independent broker execution and costs verification: not established",
        "",
        "Missing field counts:",
    ]
    for field, count in (payload.get("missingFieldCounts") or {}).items():
        lines.append(f"- {field}: {count}")
    if not (payload.get("missingFieldCounts") or {}):
        lines.append("- none")
    lines.extend(
        [
            "",
            "Paper fill intake readiness:",
            f"- verdict: {intake.get('verdict') or '-'}",
            f"- canonical log present / schema valid: {intake.get('exists')} / {intake.get('schemaValid')}",
            f"- rows: {intake.get('nonblankRows', 0)} nonblank of {intake.get('rowCount', 0)} total",
            f"- open / closed / format-complete / close-ready: {intake.get('openRows', 0)} / {intake.get('closedRows', 0)} / {intake.get('closedRowsFormatComplete', 0)} / {intake.get('closeReadyRows', 0)}",
            f"- exact ticket unmatched / ambiguous / identity mismatch: {intake.get('closedRowsUnmatchedTicket', 0)} / {intake.get('closedRowsAmbiguousTicket', 0)} / {intake.get('closedRowsIdentityMismatch', 0)}",
            f"- ignored / unknown status: {intake.get('ignoredRows', 0)} / {intake.get('unknownStatusRows', 0)}",
            f"- planned template rows: {intake.get('plannedStubRows', 0)}",
            f"- raw statuses: {', '.join(f'{status}={count}' for status, count in (intake.get('rawStatusCounts') or {}).items()) or '-'}",
            f"- latest ingest: {((intake.get('lastIngest') or {}).get('generatedAt')) or '-'} | "
            f"processed {((intake.get('lastIngest') or {}).get('processedRows')) if ((intake.get('lastIngest') or {}).get('processedRows')) is not None else '-'} | "
            f"imported {((intake.get('lastIngest') or {}).get('importedRows')) if ((intake.get('lastIngest') or {}).get('importedRows')) is not None else '-'} | "
            f"rejected {((intake.get('lastIngest') or {}).get('rejectedRows')) if ((intake.get('lastIngest') or {}).get('rejectedRows')) is not None else '-'}",
            f"- latest ingest outcome: {((intake.get('lastIngest') or {}).get('outcome')) or '-'} | "
            f"accepted progress {((intake.get('lastIngest') or {}).get('acceptedProgressUnits')) if ((intake.get('lastIngest') or {}).get('acceptedProgressUnits')) is not None else '-'}",
        ]
    )
    if intake.get("schemaMissingColumns"):
        lines.append(f"- missing schema columns: {', '.join(intake.get('schemaMissingColumns') or [])}")
    if intake.get("closedMissingFieldCounts"):
        lines.append(
            "- missing closed-fill fields: "
            + ", ".join(f"{field}={count}" for field, count in (intake.get("closedMissingFieldCounts") or {}).items())
        )
    if intake.get("closedIdentityMismatchCounts"):
        lines.append(
            "- closed-fill identity mismatches: "
            + ", ".join(
                f"{field}={count}" for field, count in (intake.get("closedIdentityMismatchCounts") or {}).items()
            )
        )
    lines.extend(["", "Closed staged outcomes:"])
    outcomes = payload.get("outcomes") or []
    if not outcomes:
        lines.append("- none")
    for outcome in outcomes:
        debt = ", ".join(outcome.get("missingFields") or []) or "none"
        lines.append(
            f"- {outcome.get('ticker') or 'UNKNOWN'} | {outcome.get('ticketId') or 'missing-id'} | "
            f"{outcome.get('state')} | missing: {debt}"
        )
    lines.extend(["", "Operator work queue:"])
    work_items = payload.get("operatorWorkItems") or []
    if not work_items:
        lines.append("- none")
    for item in work_items:
        target = " | ".join(
            value
            for value in (item.get("ticker"), item.get("ticketId"))
            if value
        )
        fields = ", ".join(item.get("missingFields") or [])
        count = item.get("rowCount")
        suffix = f" | missing: {fields}" if fields else (f" | rows: {count}" if count else "")
        lines.append(f"- {item.get('kind')}{f' | {target}' if target else ''}{suffix}")
        lines.append(f"  {item.get('instruction')}")
    lines.extend(["", "Reminders:"])
    lines.extend(f"- {reminder}" for reminder in (payload.get("reminders") or []))
    return "\n".join(lines).rstrip() + "\n"


def save_paper_outcome_completeness(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(PAPER_OUTCOME_COMPLETENESS_FILE, payload)
    atomic_write_text(PAPER_OUTCOME_COMPLETENESS_TEXT_FILE, paper_outcome_completeness_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit promotion-paper outcome completeness without mutation.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and PAPER_OUTCOME_COMPLETENESS_TEXT_FILE.exists():
        print(PAPER_OUTCOME_COMPLETENESS_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_paper_outcome_completeness()
    save_paper_outcome_completeness(payload)
    print(paper_outcome_completeness_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
