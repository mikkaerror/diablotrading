"""Read-only reconciliation of recorded paper outcomes to their fill source.

Source reconciliation proves consistency with a saved operator fill log, not
independent broker verification. This module never imports or repairs a fill.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
from typing import Any

from inferno_tos_fill_ingest import (
    TOS_FILL_LOG_WORK_FILE,
    closed_fill_evidence_gaps,
    closed_fill_ticket_identity_gaps,
    fill_pnl_reconciliation,
    normalized_status,
    parse_execution_timestamp,
    row_fingerprint,
)
from inferno_trade_evidence import entry_economics
from inferno_config import local_now


def finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def load_fill_source() -> dict[str, Any]:
    """Read one byte snapshot so the reported hash describes the audited rows."""
    try:
        raw = TOS_FILL_LOG_WORK_FILE.read_bytes()
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
        required = {"ticketId", "ticker", "strategy", "expiration", "status", "environment",
                    "entryPrice", "exitPrice", "contracts", "openedAt", "closedAt"}
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)) or not required.issubset(fields):
            raise ValueError("missing or duplicate fill-log columns")
        rows = list(reader)
        if any(None in row for row in rows):
            raise ValueError("fill row has extra cells")
        return {"status": "ok", "path": str(TOS_FILL_LOG_WORK_FILE),
                "sha256": hashlib.sha256(raw).hexdigest(), "rows": rows}
    except (OSError, UnicodeError, csv.Error, ValueError) as exc:
        return {"status": "unavailable", "path": str(TOS_FILL_LOG_WORK_FILE),
                "sha256": None, "rows": [], "error": f"{type(exc).__name__}: {exc}"}


def outcome_provenance(ticket: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Require source identity, imported fingerprint and matching execution facts.

    A sandbox *template* note is not a synthetic-execution marker. Explicit
    synthetic/proxy evidence types, incomplete fills and mismatches fail closed.
    The saved CSV remains operator-reported evidence, even when it reconciles.
    """
    execution = ticket.get("paperExecution") or {}
    outcome = ticket.get("outcome") or {}
    issues: list[str] = []
    kind = str(execution.get("evidenceType") or ticket.get("evidenceType") or "").lower()
    notes = str(outcome.get("notes") or "").lower()
    if kind in {"synthetic", "simulation", "shadow", "scenario", "intrinsic-proxy"}:
        state = "research-proxy"
        issues.append("explicit-research-evidence-type")
    elif not execution and "estimated from expiration intrinsic value" in notes:
        state = "intrinsic-estimate"
        issues.append("intrinsic-estimate-is-not-execution")
    else:
        state = "unverified-record"
    if ticket.get("status") != "paper-staged":
        issues.append("ticket-not-paper-staged")
    if outcome.get("status") != "closed":
        issues.append("outcome-not-closed")
    if execution.get("source") != "paper-fill-log":
        issues.append("missing-or-unsupported-execution-source")
    if normalized_status(execution.get("status")) != "closed":
        issues.append("execution-not-closed")
    if source.get("status") != "ok":
        issues.append("fill-source-unavailable")

    rows = [row for row in source.get("rows", [])
            if str(row.get("ticketId") or "") == str(ticket.get("ticketId") or "")
            and normalized_status(row.get("status")) == "closed"]
    # Repeated identical exports are one observation; conflicting closes are
    # ambiguous and must not be resolved by choosing the most favorable row.
    unique = {tuple(sorted((str(k), str(v)) for k, v in row.items())): row for row in rows}
    row = next(iter(unique.values())) if len(unique) == 1 else None
    if not unique:
        issues.append("closed-source-row-missing")
    elif len(unique) > 1:
        issues.append("conflicting-closed-source-rows")
    fingerprint = None
    pnl_audit = None
    if row is not None:
        issues.extend(f"source-invalid-{field}" for field in closed_fill_evidence_gaps(row))
        issues.extend(f"source-identity-{field}" for field in closed_fill_ticket_identity_gaps(ticket, row))
        expiration = str(row.get("expiration") or "").strip()
        if not expiration or expiration != str(ticket.get("expiration") or "").strip():
            issues.append("source-identity-expiration")
        fingerprint = row_fingerprint(row)
        if fingerprint not in (ticket.get("importedFillKeys") or []):
            issues.append("source-fingerprint-not-imported")
        for field in ("entryPrice", "exitPrice", "contracts"):
            value, recorded = finite(row.get(field)), finite(execution.get(field))
            if value is None or recorded is None or value != recorded:
                issues.append(f"source-mismatch-{field}")
        if str(execution.get("environment") or "").lower() != str(row.get("environment") or "").lower():
            issues.append("source-mismatch-environment")
        for field in ("openedAt", "closedAt"):
            value = parse_execution_timestamp(row.get(field))
            if value is not None and value > local_now():
                issues.append(f"source-future-{field}")
            if value is None or value != parse_execution_timestamp(execution.get(field)):
                issues.append(f"source-mismatch-{field}")
        pnl_audit = fill_pnl_reconciliation(ticket, row)
        issues.extend(f"source-economics-{issue}" for issue in pnl_audit["issues"])
        for field in ("totalFees", "realizedPnlBasis"):
            source_value, recorded_value = row.get(field), execution.get(field)
            if field == "totalFees":
                match = finite(source_value) == finite(recorded_value)
            else:
                match = str(source_value or "").strip().lower() == str(recorded_value or "").strip().lower()
            if not match:
                issues.append(f"source-mismatch-{field}")
        source_pnl = finite(pnl_audit["reportedOrDerivedPnl"])
        for field, raw_value in (("realizedPnl", execution.get("realizedPnl")),
                                 ("outcomePnl", outcome.get("estimatedPnl"))):
            value = finite(raw_value)
            if value is None or source_pnl is None or not math.isclose(value, source_pnl, abs_tol=0.005, rel_tol=0):
                issues.append(f"source-mismatch-{field}")

    economics = entry_economics(ticket)
    risk = finite(economics.get("estimatedMaxLoss"))
    if not economics.get("valuationBasisValid") or risk is None or risk <= 0:
        issues.append("invalid-fill-adjusted-risk")
    elif finite(outcome.get("estimatedPnl")) is not None and finite(float(outcome["estimatedPnl"]) / risk) is None:
        issues.append("nonfinite-return-on-risk")
    if not issues:
        state = "source-reconciled-paper-fill"
    return {
        "state": state, "sourceReconciled": not issues,
        "independentlyVerified": False,
        "verificationBasis": "saved operator fill log; broker execution and costs not independently verified",
        "issues": sorted(set(issues)), "sourceRowFingerprint": fingerprint,
        "fillAdjustedMaxLoss": risk,
        "pnlBasis": (pnl_audit or {}).get("pnlBasis", "unverified P/L"),
        "pnlReconciliation": pnl_audit,
        "scoringPnl": (pnl_audit or {}).get("scoringPnl"),
    }
