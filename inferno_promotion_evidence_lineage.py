from __future__ import annotations

"""Trace exactly what does and does not count toward promotion evidence.

The desk has several useful research datasets (the operator paper ledger,
fast isolated simulations, and shadow observations).  They have intentionally
different authority and promotion semantics.  This diagnostic makes those
boundaries explicit without modifying a ticket, a threshold, or authority.
"""

import argparse
from collections import Counter
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_paper_execution import PAPER_EXECUTION_LEDGER_FILE, paper_event_id
from inferno_paper_provenance import load_fill_source, outcome_provenance
from inferno_performance_analytics import outcome_status, strategy_key
from inferno_strategy_lab import (
    MIN_SCORED_TRADES_FOR_PROMOTION,
    STRATEGY_LAB_FILE,
    closed_trade_records,
    reported_closed_trade_records,
)
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


FAST_PAPER_LEDGER_FILE = DATA_DIR / "inferno_fast_paper_ledger.json"
SHADOW_EVIDENCE_FILE = DATA_DIR / "inferno_shadow_evidence.json"
PROMOTION_EVIDENCE_LINEAGE_FILE = DATA_DIR / "inferno_promotion_evidence_lineage.json"
PROMOTION_EVIDENCE_LINEAGE_TEXT_FILE = REPORTS_DIR / "promotion_evidence_lineage_latest.txt"

PAPER_SOURCE = "paper-execution-ledger"
FAST_SOURCE = "fast-isolated-simulation"
SHADOW_SOURCE = "shadow-evidence"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _items(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [item for item in (payload or {}).get("items", []) if isinstance(item, dict)]


def _ticket_id(item: dict[str, Any], source: str, index: int) -> str:
    value = _text(item.get("ticketId") or item.get("id"))
    return value or f"{source}:{index}"


def _paper_record(item: dict[str, Any], index: int, source: dict[str, Any], counted_ids: set[str]) -> dict[str, Any]:
    """Classify one operator-paper-ledger row against the actual lab rule.

    ``closed_trade_records`` is the strategy lab's source of truth.  Keeping
    this diagnostic coupled to that predicate makes a divergence visible
    instead of letting a parallel approximation falsely claim promotion
    progress.
    """
    status = _text(item.get("status")).lower() or "missing"
    outcome = outcome_status(item) or "missing"
    provenance = outcome_provenance(item, source)
    counted_by_strategy_lab = item.get("ticketId") in counted_ids
    staged = status == "paper-staged"

    if counted_by_strategy_lab and staged:
        promotion_state = "promotion-qualified"
        reason = None
    elif counted_by_strategy_lab:
        promotion_state = "integrity-attention"
        reason = "strategy-lab-counts-nonstaged-paper-row"
    elif not staged:
        promotion_state = "excluded"
        reason = f"paper-status-{status}"
    elif outcome != "closed":
        promotion_state = "pending"
        reason = f"paper-outcome-{outcome}"
    else:
        promotion_state = "excluded"
        reason = "; ".join(provenance["issues"]) or "duplicate-ticket-identity"

    return {
        "source": PAPER_SOURCE,
        "recordId": _ticket_id(item, PAPER_SOURCE, index),
        "ticker": _text(item.get("ticker") or item.get("symbol")).upper() or None,
        "strategy": strategy_key(item) or None,
        "eventId": paper_event_id(item),
        "sourceStatus": status,
        "outcomeStatus": outcome,
        "promotionState": promotion_state,
        "promotionEligible": promotion_state == "promotion-qualified",
        "countedByStrategyLab": counted_by_strategy_lab,
        "exclusionReason": reason,
        "provenance": provenance,
        "reportedScorable": bool(reported_closed_trade_records([item])),
        "outcomeLabel": "estimate — no credit" if provenance.get("state") == "intrinsic-estimate" else promotion_state,
    }


def _quarantined_record(item: dict[str, Any], source: str, index: int) -> dict[str, Any]:
    """Record a non-paper source without implying it can earn promotion credit."""
    outcome = outcome_status(item) or "missing"
    if source == FAST_SOURCE:
        reason = "isolated-fast-simulations-never-earn-promotion-credit"
    else:
        reason = "shadow-observations-never-earn-promotion-credit"
    return {
        "source": source,
        "recordId": _ticket_id(item, source, index),
        "ticker": _text(item.get("ticker") or item.get("symbol")).upper() or None,
        "strategy": strategy_key(item) or None,
        "eventId": paper_event_id(item),
        "sourceStatus": _text(item.get("status")).lower() or "missing",
        "outcomeStatus": outcome,
        "promotionState": "quarantined",
        "promotionEligible": False,
        "countedByStrategyLab": False,
        "exclusionReason": reason,
    }


def _count(records: list[dict[str, Any]], **criteria: Any) -> int:
    return sum(all(record.get(key) == value for key, value in criteria.items()) for record in records)


def _source_summary(records: list[dict[str, Any]], source: str) -> dict[str, Any]:
    selected = [record for record in records if record.get("source") == source]
    outcome_counts = Counter(record.get("outcomeStatus") or "missing" for record in selected)
    state_counts = Counter(record.get("promotionState") or "missing" for record in selected)
    exclusion_counts = Counter(record.get("exclusionReason") for record in selected if record.get("exclusionReason"))
    return {
        "records": len(selected),
        "closedOutcomes": _count(selected, outcomeStatus="closed"),
        "promotionQualified": _count(selected, promotionState="promotion-qualified"),
        "states": dict(sorted(state_counts.items())),
        "outcomes": dict(sorted(outcome_counts.items())),
        "exclusionReasons": dict(sorted(exclusion_counts.items())),
    }


def build_promotion_evidence_lineage(
    paper_ledger: dict[str, Any] | None = None,
    fast_ledger: dict[str, Any] | None = None,
    shadow_evidence: dict[str, Any] | None = None,
    strategy_lab: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a source-labelled, read-only promotion-evidence reconciliation."""
    paper_ledger = paper_ledger if paper_ledger is not None else (load_json_file(PAPER_EXECUTION_LEDGER_FILE) or {})
    fast_ledger = fast_ledger if fast_ledger is not None else (load_json_file(FAST_PAPER_LEDGER_FILE) or {})
    shadow_evidence = shadow_evidence if shadow_evidence is not None else (load_json_file(SHADOW_EVIDENCE_FILE) or {})
    strategy_lab = strategy_lab if strategy_lab is not None else (load_json_file(STRATEGY_LAB_FILE) or {})

    source = load_fill_source() if source is None else source
    counted_ids = {row["ticketId"] for row in closed_trade_records(_items(paper_ledger), source)}
    records = [
        _paper_record(item, index, source, counted_ids)
        for index, item in enumerate(_items(paper_ledger), start=1)
    ]
    records.extend(
        _quarantined_record(item, FAST_SOURCE, index)
        for index, item in enumerate(_items(fast_ledger), start=1)
    )
    records.extend(
        _quarantined_record(item, SHADOW_SOURCE, index)
        for index, item in enumerate(_items(shadow_evidence), start=1)
    )

    counted = _count(records, countedByStrategyLab=True)
    qualified = _count(records, promotionState="promotion-qualified")
    lab_scored = int(((strategy_lab.get("overall") or {}).get("scoredCount")) or 0)
    integrity_attention = [
        record for record in records if record.get("promotionState") == "integrity-attention"
    ]
    source_summaries = {
        source: _source_summary(records, source)
        for source in (PAPER_SOURCE, FAST_SOURCE, SHADOW_SOURCE)
    }
    remaining = max(0, MIN_SCORED_TRADES_FOR_PROMOTION - qualified)

    from inferno_paper_funnel import weekly_funnel
    funnel = weekly_funnel(paper_ledger, {"records": records})
    return {
        "weeklyFunnel": funnel,
        "generatedAt": local_now().isoformat(),
        "stage": "promotion-evidence-lineage-research-only",
        "researchOnly": True,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "promotionTarget": MIN_SCORED_TRADES_FOR_PROMOTION,
        "promotionTruth": {
            "qualified": qualified,
            "target": MIN_SCORED_TRADES_FOR_PROMOTION,
            "remaining": remaining,
            "reported": sum(bool(row.get("reportedScorable")) for row in records),
            "estimatesNoCredit": sum(row.get("provenance", {}).get("state") == "intrinsic-estimate" for row in records),
            "source": "promotion-evidence-lineage",
            "basis": "source-reconciled operator-paper outcomes; sample count alone grants no authority",
        },
        "fillSource": {key: value for key, value in source.items() if key != "rows"},
        "promotion": {
            "qualifiedPaperOutcomes": qualified,
            "independentlyVerifiedOutcomes": 0,
            "reportedScorableOutcomes": sum(bool(row.get("reportedScorable")) for row in records),
            "remainingForPromotion": remaining,
            "strategyLabScoredOutcomes": lab_scored,
            "strategyLabCountedRecords": counted,
            "strategyLabCountMatchesLineage": lab_scored == counted,
            "strictPolicyMatchesStrategyLab": qualified == counted,
            "integrityAttentionCount": len(integrity_attention),
        },
        "sources": source_summaries,
        "integrityAttention": integrity_attention,
        "records": records,
        "reminders": [
            "source-reconciled operator fill records count toward the paper sample; broker history and costs remain unverified",
            "isolated fast simulations and shadow observations remain useful research but never earn promotion credit",
            "this diagnostic does not mutate tickets, approvals, thresholds, broker state, or authority",
        ],
        "citations": [
            PAPER_EXECUTION_LEDGER_FILE.name,
            FAST_PAPER_LEDGER_FILE.name,
            SHADOW_EVIDENCE_FILE.name,
            STRATEGY_LAB_FILE.name,
        ],
    }


def promotion_evidence_lineage_text(payload: dict[str, Any]) -> str:
    """Render a concise, source-separated evidence truth memo."""
    promotion = payload.get("promotion") or {}
    sources = payload.get("sources") or {}
    paper = sources.get(PAPER_SOURCE) or {}
    fast = sources.get(FAST_SOURCE) or {}
    shadow = sources.get(SHADOW_SOURCE) or {}
    lines = [
        "Inferno Promotion Evidence Lineage",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        "Authority: research-only; broker submit OFF; live trading OFF",
        "",
        "Promotion truth:",
        f"- source-reconciled operator-paper outcomes: {promotion.get('qualifiedPaperOutcomes', 0)}/{payload.get('promotionTarget', 0)}",
        f"- estimate — no credit: {(payload.get('promotionTruth') or {}).get('estimatesNoCredit', 'unavailable')}",
        "- source match proves recorded-fill consistency, not independent broker verification",
        f"- remaining for promotion: {promotion.get('remainingForPromotion', 0)}",
        f"- strategy-lab scored outcomes: {promotion.get('strategyLabScoredOutcomes', 0)}",
        f"- strategy-lab / lineage count match: {promotion.get('strategyLabCountMatchesLineage')}",
        f"- source-qualified paper policy / lab match: {promotion.get('strictPolicyMatchesStrategyLab')}",
        f"- integrity attention rows: {promotion.get('integrityAttentionCount', 0)}",
        "",
        "Source boundaries:",
        f"- operator paper ledger: {paper.get('records', 0)} rows | qualified {paper.get('promotionQualified', 0)} | closed {paper.get('closedOutcomes', 0)}",
        f"- fast isolated simulations: {fast.get('records', 0)} rows | closed {fast.get('closedOutcomes', 0)} | promotion credit OFF",
        f"- shadow observations: {shadow.get('records', 0)} rows | closed {shadow.get('closedOutcomes', 0)} | promotion credit OFF",
        "",
        "Paper-ledger exclusion reasons:",
    ]
    for reason, count in (paper.get("exclusionReasons") or {}).items():
        lines.append(f"- {reason}: {count}")
    if not (paper.get("exclusionReasons") or {}):
        lines.append("- none")
    lines.extend(["", "Weekly funnel (creation cohorts; reasons overlap):"])
    for row in payload.get("weeklyFunnel", []):
        lines.append(f"- {row['week']} {row['strategy']}: {row['proposed']} proposed -> {row['blocked']} blocked -> {row['staged']} staged -> {row['filled']} filled -> {row['qualified']} qualified; reasons={row['blockedByReason']}")
    lines.extend(["", "Reminders:"])
    lines.extend(f"- {reminder}" for reminder in (payload.get("reminders") or []))
    return "\n".join(lines).rstrip() + "\n"


def save_promotion_evidence_lineage(payload: dict[str, Any]) -> None:
    """Persist the diagnostic artifacts with the shared atomic write contract."""
    ensure_dirs()
    atomic_write_json(PROMOTION_EVIDENCE_LINEAGE_FILE, payload)
    atomic_write_text(PROMOTION_EVIDENCE_LINEAGE_TEXT_FILE, promotion_evidence_lineage_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the read-only promotion evidence lineage ledger.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and PROMOTION_EVIDENCE_LINEAGE_TEXT_FILE.exists():
        print(PROMOTION_EVIDENCE_LINEAGE_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_promotion_evidence_lineage()
    save_promotion_evidence_lineage(payload)
    print(promotion_evidence_lineage_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
