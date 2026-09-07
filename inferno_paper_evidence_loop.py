from __future__ import annotations

"""Paper evidence-loop auditor for the Inferno desk.

This module asks a narrow operational question:

"What is the next missing link between paper discovery and scored evidence?"

It does not stage tickets, it does not ingest broker exports by itself, and it
does not promote authority. It simply converts the current paper lane into a
single audit that points at the exact bottleneck: approvals, fill capture,
outcome collection, or sample size.
"""

import argparse
import csv
import json
from datetime import date
from typing import Any

from inferno_config import local_now
from inferno_doctor import in_current_service_cycle
from inferno_paper_capture_template import (
    CAPTURE_TEMPLATE_CSV,
    CAPTURE_TEMPLATE_TEXT_FILE,
    build_capture_template,
    save_capture_template,
)
from inferno_paper_test_director import build_director as build_paper_test_director, save_director
from inferno_tos_fill_ingest import TOS_FILL_LOG_WORK_FILE, normalized_status, text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


TOS_SANDBOX_FILE = DATA_DIR / "inferno_tos_sandbox_session.json"
TOS_FILL_INGEST_FILE = DATA_DIR / "inferno_tos_fill_ingest.json"
PAPER_EXECUTION_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
SHADOW_EVIDENCE_FILE = DATA_DIR / "inferno_shadow_evidence.json"
PERFORMANCE_ANALYTICS_FILE = DATA_DIR / "inferno_performance_analytics.json"
STRATEGY_LAB_FILE = DATA_DIR / "inferno_strategy_lab.json"
PAPER_TEST_DIRECTOR_FILE = DATA_DIR / "inferno_paper_test_director.json"
PAPER_EVIDENCE_LOOP_FILE = DATA_DIR / "inferno_paper_evidence_loop.json"
PAPER_EVIDENCE_LOOP_TEXT_FILE = REPORTS_DIR / "paper_evidence_loop_latest.txt"

PROMOTION_TARGET = 30


def parse_date(value: Any) -> date | None:
    """Parse a loose ISO-like date field into a date."""
    raw = text(value)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def load_fill_rows() -> list[dict[str, Any]]:
    """Load the current paper fill log if it exists."""
    if not TOS_FILL_LOG_WORK_FILE.exists():
        return []
    with TOS_FILL_LOG_WORK_FILE.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_paper_director(*, refresh_if_stale: bool = True) -> dict[str, Any]:
    """Return a fresh enough paper director payload for evidence grading.

    The evidence loop depends on the paper director's approval/stageability
    counts. If that artifact is stale, we rebuild it first so the audit points
    at today's actual bottleneck instead of yesterday's.
    """
    director = load_json_file(PAPER_TEST_DIRECTOR_FILE) or {"counts": {}, "approvalSlate": []}
    generated_at = str(director.get("generatedAt") or "")
    if director and (not refresh_if_stale or in_current_service_cycle(generated_at, now=local_now())):
        return director

    refreshed = build_paper_test_director()
    save_director(refreshed)
    return refreshed


def count_fill_status(rows: list[dict[str, Any]], target: str) -> int:
    """Count rows matching one normalized fill status."""
    return sum(1 for row in rows if normalized_status(row.get("status")) == target)


def planned_fill_rows(rows: list[dict[str, Any]]) -> int:
    """Count fill rows that still need operator execution facts."""
    return sum(1 for row in rows if text(row.get("status")).strip().lower() in {"", "planned", "pending"})


def paper_open_tickets(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Return paper-staged tickets with open imported execution state."""
    items = ledger.get("items") or []
    return [
        item
        for item in items
        if text(item.get("status")) == "paper-staged"
        and text(((item.get("paperExecution") or {}).get("status"))) == "open"
    ]


def shadow_ready_for_review(shadow: dict[str, Any]) -> list[dict[str, Any]]:
    """Return shadow tickets whose expiration has arrived but are still unresolved."""
    today = local_now().date()
    ready: list[dict[str, Any]] = []
    for item in shadow.get("items") or []:
        if text(item.get("status")) != "shadow-open":
            continue
        outcome_status = text((item.get("outcome") or {}).get("status"))
        if outcome_status not in {"open", "review-pending"}:
            continue
        expiration = parse_date(item.get("expiration"))
        if expiration and expiration <= today:
            ready.append(item)
    return ready


def build_actions(payload: dict[str, Any]) -> list[str]:
    """Generate the shortest next-step sequence for the current evidence bottleneck."""
    counts = payload.get("counts") or {}
    actions: list[str] = []
    if counts.get("operatorRoutableNow", 0) > 0:
        actions.append("Record the current clean sandbox names for the operator-owned paper workflow; unattended agents must not stage them.")
    elif counts.get("autoPaperSelected", 0) > 0:
        actions.append("Record the model-selected auto slate for the operator-owned paper workflow; do not stage it autonomously.")
    elif counts.get("paperResearchSelected", 0) > 0:
        actions.append(
            "Keep paper-research selections under observation only; they are not operator-routable or stageable "
            "until the final paper workflow gates pass."
        )
    elif counts.get("approvalOnly", 0) > 0:
        actions.append("Review the approval-only slate only for live-style discretion; do not let it block paper evidence throughput.")
    if counts.get("sandboxStageableNow", 0) > counts.get("stageableNow", 0):
        actions.append(
            "TOS sandbox entries exceed the final paper-workflow slate; treat the unmatched sandbox rows as provisional "
            "context, not operator-routable candidates."
        )
    if counts.get("plannedFillRows", 0) > 0:
        actions.append("After the operator stages a paper test, replace planned fill-log placeholders with real paperMoney execution facts.")
    capture_template = payload.get("captureTemplate") or {}
    if capture_template.get("fillableTicketCount", 0) > 0:
        actions.append(
            "Use the current paper-capture worksheet for actual paperMoney execution facts only; "
            "it neither stages nor scores a ticket."
        )
    elif capture_template.get("expiredTicketCount", 0) > 0:
        actions.append(
            "No fillable staged tickets remain: expired staged tickets stay excluded from the capture worksheet; "
            "do not fabricate a fill or close them unattended."
        )
    if counts.get("openFillRows", 0) > 0 or counts.get("paperOpenTickets", 0) > 0:
        actions.append("Operator-owned paper positions need fill or close updates before scoring; unattended agents must not close tickets.")
    if counts.get("shadowReadyForReview", 0) > 0:
        actions.append("Review expired shadow tickets to keep the research lane honest.")
    if counts.get("remainingForPromotion", 0) > 0:
        actions.append(f"Keep accumulating scored paper outcomes; {counts.get('remainingForPromotion')} more are needed for promotion evidence.")
    if not actions:
        actions.append("No immediate paper-evidence action is required.")
    return actions


def build_audit() -> dict[str, Any]:
    """Build the paper evidence-loop audit artifact."""
    sandbox = load_json_file(TOS_SANDBOX_FILE) or {}
    fill_ingest = load_json_file(TOS_FILL_INGEST_FILE) or {}
    ledger = load_json_file(PAPER_EXECUTION_LEDGER_FILE) or {"items": []}
    shadow = load_json_file(SHADOW_EVIDENCE_FILE) or {"items": []}
    performance = load_json_file(PERFORMANCE_ANALYTICS_FILE) or {"closedMetrics": {}}
    strategy_lab = load_json_file(STRATEGY_LAB_FILE) or {"deskVerdict": {}}
    paper_director = load_paper_director(refresh_if_stale=True)
    capture_template = build_capture_template(ledger=ledger)

    fill_rows = load_fill_rows()
    open_tickets = paper_open_tickets(ledger)
    review_ready_shadows = shadow_ready_for_review(shadow)
    scored = int(((strategy_lab.get("overall") or {}).get("scoredCount")) or 0)
    remaining = max(0, PROMOTION_TARGET - scored)
    director_counts = paper_director.get("counts") or {}
    operator_routable_slate = list(paper_director.get("operatorRoutableSlate") or [])
    auto_paper_slate = list(paper_director.get("autoPaperSlate") or [])
    paper_research_slate = [
        candidate
        for candidate in (paper_director.get("pricedPaperVariantWatchlist") or [])
        if candidate.get("paperResearchSelected")
    ]
    sandbox_stageable = list(sandbox.get("stageableTickets") or [])

    counts = {
        # The paper director is the final candidate gate. A raw TOS sandbox row
        # can be provisional, stale, or superseded by pricing, liquidity, and
        # risk checks, so it must never be represented as operator-routable.
        "stageableNow": int(director_counts.get("stageableNow") or 0),
        "operatorRoutableNow": int(director_counts.get("operatorRoutablePaper") or 0),
        "autoPaperSelected": int(director_counts.get("autoPaperSelected") or 0),
        "paperResearchSelected": int(director_counts.get("paperResearchSelected") or 0),
        "sandboxStageableNow": len(sandbox_stageable),
        "approvalOnly": int(director_counts.get("approvalOnly") or 0),
        "plannedFillRows": planned_fill_rows(fill_rows),
        "openFillRows": count_fill_status(fill_rows, "open"),
        "closedFillRows": count_fill_status(fill_rows, "closed"),
        "unmatchedFillRows": len(fill_ingest.get("unmatchedRows") or []),
        "paperOpenTickets": len(open_tickets),
        "shadowReadyForReview": len(review_ready_shadows),
        "scoredTickets": scored,
        "remainingForPromotion": remaining,
    }

    if counts["operatorRoutableNow"] > 0 or counts["autoPaperSelected"] > 0:
        verdict = "operator-paper-candidates"
    elif counts["paperResearchSelected"] > 0:
        verdict = "paper-research-watch"
    elif counts["openFillRows"] > 0 or counts["paperOpenTickets"] > 0 or counts["closedFillRows"] > 0:
        verdict = "collect-paper-outcomes"
    elif counts["approvalOnly"] > 0:
        verdict = "approval-bottleneck"
    else:
        verdict = "evidence-building"

    return {
        "generatedAt": local_now().isoformat(),
        "verdict": verdict,
        "counts": counts,
        "fillLogPath": str(TOS_FILL_LOG_WORK_FILE),
        "strategyLabVerdict": (strategy_lab.get("deskVerdict") or {}).get("level"),
        "latestFillIngest": {
            "generatedAt": fill_ingest.get("generatedAt"),
            "importedRows": fill_ingest.get("importedRows", 0),
            "openedRows": fill_ingest.get("openedRows", 0),
            "closedRows": fill_ingest.get("closedRows", 0),
        },
        "sourceLineage": {
            "paperDirectorGeneratedAt": paper_director.get("generatedAt"),
            "tosSandboxGeneratedAt": sandbox.get("generatedAt"),
        },
        "captureTemplate": capture_template,
        "actions": build_actions({"counts": counts, "captureTemplate": capture_template}),
        "stageableTickers": [ticket.get("ticker") for ticket in operator_routable_slate],
        "autoPaperTickers": [ticket.get("ticker") for ticket in auto_paper_slate],
        "paperResearchTickers": [ticket.get("ticker") for ticket in paper_research_slate],
        "sandboxStageableTickers": [ticket.get("ticker") for ticket in sandbox_stageable],
        "approvalTickers": [ticket.get("ticker") for ticket in (paper_director.get("approvalSlate") or [])],
        "openPaperTickers": [ticket.get("ticker") for ticket in open_tickets],
        "shadowReviewTickers": [ticket.get("ticker") for ticket in review_ready_shadows],
    }


def audit_text(payload: dict[str, Any]) -> str:
    """Render the evidence-loop audit as an operator memo."""
    counts = payload.get("counts") or {}
    capture_template = payload.get("captureTemplate") or {}
    lines = [
        "Inferno Paper Evidence Loop",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Strategy lab: {payload.get('strategyLabVerdict')}",
        "",
        "Counts:",
        f"- final executable paper rows: {counts.get('stageableNow', 0)}",
        f"- operator-routable now: {counts.get('operatorRoutableNow', 0)}",
        f"- auto paper selected: {counts.get('autoPaperSelected', 0)}",
        f"- paper-research selections: {counts.get('paperResearchSelected', 0)}",
        f"- provisional TOS sandbox rows: {counts.get('sandboxStageableNow', 0)}",
        f"- approval only: {counts.get('approvalOnly', 0)}",
        f"- planned fill rows: {counts.get('plannedFillRows', 0)}",
        f"- open fill rows: {counts.get('openFillRows', 0)}",
        f"- closed fill rows: {counts.get('closedFillRows', 0)}",
        f"- unmatched fill rows: {counts.get('unmatchedFillRows', 0)}",
        f"- open paper tickets: {counts.get('paperOpenTickets', 0)}",
        f"- shadow ready for review: {counts.get('shadowReadyForReview', 0)}",
        f"- scored tickets: {counts.get('scoredTickets', 0)}",
        f"- remaining for promotion: {counts.get('remainingForPromotion', 0)}",
        f"- fillable capture-template rows: {capture_template.get('fillableTicketCount', 0)}",
        f"- expired staged tickets excluded from template: {capture_template.get('expiredTicketCount', 0)}",
        "",
        "Actions:",
    ]
    for action in payload.get("actions") or []:
        lines.append(f"- {action}")
    lines.extend(
        [
            "",
            f"Operator-routable tickers: {', '.join(payload.get('stageableTickers') or []) or 'none'}",
            f"Auto-paper tickers: {', '.join(payload.get('autoPaperTickers') or []) or 'none'}",
            f"Paper-research tickers: {', '.join(payload.get('paperResearchTickers') or []) or 'none'}",
            f"Provisional TOS sandbox tickers: {', '.join(payload.get('sandboxStageableTickers') or []) or 'none'}",
            f"Approval tickers: {', '.join(payload.get('approvalTickers') or []) or 'none'}",
            f"Open paper tickers: {', '.join(payload.get('openPaperTickers') or []) or 'none'}",
            f"Shadow review tickers: {', '.join(payload.get('shadowReviewTickers') or []) or 'none'}",
            f"Capture template: {CAPTURE_TEMPLATE_TEXT_FILE}",
            f"Capture CSV: {CAPTURE_TEMPLATE_CSV}",
            f"Fill log: {payload.get('fillLogPath')}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def save_audit(payload: dict[str, Any]) -> None:
    """Persist the audit plus its read-only capture-template artifacts."""
    ensure_dirs()
    capture_template = payload.get("captureTemplate") or {}
    if capture_template:
        save_capture_template(capture_template)
    PAPER_EVIDENCE_LOOP_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    PAPER_EVIDENCE_LOOP_TEXT_FILE.write_text(audit_text(payload), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for build/status use."""
    parser = argparse.ArgumentParser(description="Audit the Inferno paper evidence loop.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint."""
    args = parse_args()
    if args.command == "status" and PAPER_EVIDENCE_LOOP_TEXT_FILE.exists():
        print(PAPER_EVIDENCE_LOOP_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_audit()
    save_audit(payload)
    print(audit_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
