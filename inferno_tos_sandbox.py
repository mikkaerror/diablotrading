from __future__ import annotations

"""thinkorswim paperMoney sandbox session builder.

This module creates a daily simulation packet for the thinkorswim execution
cockpit. It does not place orders and it does not unlock live authority. Its
job is to tell the operator which paperMoney candidates are operator-routable,
what must remain blocked, and how to log simulated fills back into the desk.
"""

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from inferno_config import AUTO_PAPER_SELECTION_ENABLED, BROKER_EXECUTION_SURFACE, local_now
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


AUTHORITY_MANIFEST_FILE = DATA_DIR / "inferno_authority_manifest.json"
EXECUTION_QUEUE_FILE = DATA_DIR / "inferno_execution_queue.json"
BROKER_PREVIEW_FILE = DATA_DIR / "inferno_broker_preview.json"
STRIKE_PLAN_FILE = DATA_DIR / "inferno_strike_plan.json"
PAPER_EXECUTION_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
TOS_SANDBOX_FILE = DATA_DIR / "inferno_tos_sandbox_session.json"
TOS_SANDBOX_TEXT_FILE = REPORTS_DIR / "tos_sandbox_session_latest.txt"
TOS_FILL_LOG_TEMPLATE_FILE = DATA_DIR / "inferno_tos_fill_log_template.csv"
TOS_FILL_LOG_WORK_FILE = DATA_DIR / "inferno_tos_fill_log.csv"

SANDBOX_READY_AUTHORITIES = {"paper-evidence-only", "broker-preview-only", "live-review-required"}
MAX_STAGEABLE_TICKETS = 5
PAPER_AUTO_APPROVAL_REASONS = {
    "human approval is missing",
    "human approval missing",
    "human approval still required",
    "execution intent is not approval-ready",
}
FILL_LOG_COLUMNS = [
    "sessionDate",
    "ticketId",
    "ticker",
    "strategy",
    "expiration",
    "environment",
    "paperAccount",
    "routeFamily",
    "orderType",
    "contracts",
    "entryPrice",
    "exitPrice",
    "realizedPnl",
    "status",
    "openedAt",
    "closedAt",
    "notes",
]


def text(value: Any) -> str:
    """Normalize arbitrary values into trimmed text."""
    return str(value or "").strip()


def normalize_reason(value: Any) -> str:
    """Normalize a blocker reason for approval-only comparisons."""
    return text(value).lower()


def non_approval_reasons(reasons: list[Any]) -> list[str]:
    """Return reasons that should still block automated paper selection.

    Approval-only blockers are allowed to fall away in the paper lane because
    they do not grant live authority. Size, liquidity, stale-data, and risk
    blockers must remain hard stops.
    """
    return [text(reason) for reason in reasons if normalize_reason(reason) not in PAPER_AUTO_APPROVAL_REASONS]


def authority_decision() -> dict[str, Any]:
    """Load the current authority decision block."""
    manifest = load_json_file(AUTHORITY_MANIFEST_FILE) or {}
    return manifest.get("decision") or {}


def sandbox_ready(decision: dict[str, Any]) -> bool:
    """Return whether the desk is allowed to open a paperMoney session."""
    if decision.get("brokerSubmitAllowed"):
        # Even if future policy ever changes, this sandbox builder must stay on
        # the paper-only side of the wall.
        return False
    if decision.get("authorityLevel") not in SANDBOX_READY_AUTHORITIES:
        return False
    if decision.get("blockers"):
        return False
    return True


def preview_orders_by_ticker() -> dict[str, dict[str, Any]]:
    """Index broker-preview orders by ticker for sandbox enrichment."""
    preview = load_json_file(BROKER_PREVIEW_FILE) or {}
    return {
        str(order.get("ticker", "")).upper(): order
        for order in preview.get("orders", [])
        if order.get("ticker")
    }


def strike_plans_by_ticker() -> dict[str, dict[str, Any]]:
    """Index the current strike-plan artifact by ticker.

    The sandbox should inherit the same strike-plan honesty as the paper
    director. Otherwise a ticket can look like it only needs approval while the
    underlying strike plan is already failing size or liquidity gates.
    """
    plan = load_json_file(STRIKE_PLAN_FILE) or {}
    return {
        str(item.get("ticker", "")).upper(): item
        for item in (plan.get("items") or [])
        if item.get("ticker")
    }


def effective_paper_plan_item(strike_plan_item: dict[str, Any] | None) -> dict[str, Any]:
    """Return the paper-safe strike item to stage for rehearsal.

    When the primary long straddle is blocked only because it is too expensive
    for the paper cap, and a capped long-strangle rehearsal variant passed risk
    review, the sandbox should stage that variant instead of leaving the desk
    frozen.
    """
    strike_plan_item = strike_plan_item or {}
    variant = strike_plan_item.get("paperRehearsalVariant") or {}
    primary_blocks = list(((strike_plan_item.get("riskVerdict") or {}).get("blocks") or []))
    variant_verdict = variant.get("riskVerdict") or {}
    if not variant or not primary_blocks or not variant_verdict.get("passed"):
        return strike_plan_item
    for reason in primary_blocks:
        normalized = text(reason).lower()
        if "exceeds single-ticket cap" not in normalized and "projected daily max loss" not in normalized:
            return strike_plan_item
    return {
        **strike_plan_item,
        "paperVariantOnly": True,
        "paperVariantFamily": variant.get("variantFamily"),
        "paperVariantOfStrategy": variant.get("variantForStrategy") or (strike_plan_item.get("strikePlan") or {}).get("strategy"),
        "strikePlan": variant,
        "riskVerdict": variant_verdict,
    }


def latest_ledger_ticket_for_intent(intent: dict[str, Any], strategy_hint: str | None = None) -> dict[str, Any] | None:
    """Return the latest same-day paper ticket that best matches one intent.

    The sandbox packet should carry a stable `ticketId` whenever possible so the
    fill-import step can map simulated paperMoney fills back to the exact paper
    ledger row instead of guessing from a naked ticker symbol.
    """
    ledger = load_json_file(PAPER_EXECUTION_LEDGER_FILE) or {}
    items = ledger.get("items") or []
    ticker = str(intent.get("ticker", "")).upper()
    setup_rec = str(intent.get("setupRec") or "")
    candidates = [
        item
        for item in items
        if str(item.get("ticker", "")).upper() == ticker
        and str(item.get("tradeDate", "")) == local_now().date().isoformat()
    ]
    stageable = [item for item in candidates if text(item.get("status")) == "paper-staged"]
    if stageable:
        candidates = stageable
    if len(candidates) == 1:
        return candidates[0]
    if strategy_hint:
        narrowed = [item for item in candidates if text(item.get("strategy")).upper() == text(strategy_hint).upper()]
        if len(narrowed) == 1:
            return narrowed[0]
        if narrowed:
            candidates = narrowed
    narrowed = [item for item in candidates if str(item.get("setupRec") or "") == setup_rec]
    if len(narrowed) == 1:
        return narrowed[0]
    return None


def intent_stage_status(
    intent: dict[str, Any],
    strike_plan_item: dict[str, Any] | None,
    ready: bool,
) -> tuple[str, list[str]]:
    """Classify an execution intent for the sandbox session."""
    reasons: list[str] = []
    strike_plan_item = effective_paper_plan_item(strike_plan_item)
    risk_verdict = strike_plan_item.get("riskVerdict") or {}
    risk_blocks = list(risk_verdict.get("blocks") or [])
    liquidity_notes = list((strike_plan_item.get("strikePlan") or {}).get("liquidityNotes") or [])
    intent_blocks = list(intent.get("intentBlocks") or [])
    paper_auto_selected = paper_auto_selection_applies(
        intent,
        strike_plan_item,
        ready=ready,
        intent_blocks=intent_blocks,
        risk_blocks=risk_blocks,
        liquidity_notes=liquidity_notes,
    )
    if not ready:
        reasons.append("authority manifest does not allow paperMoney staging today")
    if intent.get("approvalStatus") != "approved" and not paper_auto_selected:
        reasons.append("human approval is missing")
    if intent.get("intentStatus") != "approval-ready":
        blocks = intent_blocks or ["intent is not approval-ready"]
        reasons.extend(non_approval_reasons(blocks) if paper_auto_selected else blocks)
    if not strike_plan_item.get("ok", True):
        reasons.append(str(strike_plan_item.get("reason") or "strike plan failed"))
    reasons.extend(risk_blocks)
    reasons.extend(liquidity_notes)
    if reasons:
        # Preserve order but drop duplicate strings so the sandbox memo stays
        # readable when the same blocker is surfaced by multiple layers.
        seen: set[str] = set()
        deduped: list[str] = []
        for reason in reasons:
            value = text(reason)
            if not value or value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return "blocked", deduped
    return "stage-in-papermoney", []


def paper_auto_selection_applies(
    intent: dict[str, Any],
    strike_plan_item: dict[str, Any],
    *,
    ready: bool,
    intent_blocks: list[Any],
    risk_blocks: list[Any],
    liquidity_notes: list[Any],
) -> bool:
    """Return True when paperMoney can auto-stage an approval-only setup.

    This is the key separation between simulated evidence and live authority:
    the model may pursue paper data if approval is the *only* blocker, but any
    real risk, liquidity, stale-data, failed-construction, or rejected ticket
    reason still blocks the paper stage.
    """
    if not AUTO_PAPER_SELECTION_ENABLED or not ready:
        return False
    if intent.get("approvalStatus") == "approved":
        return False
    if intent.get("approvalStatus") == "rejected":
        return False
    if not strike_plan_item.get("ok", True):
        return False
    if not (strike_plan_item.get("riskVerdict") or {}).get("passed"):
        return False
    if non_approval_reasons(intent_blocks) or non_approval_reasons(risk_blocks) or non_approval_reasons(liquidity_notes):
        return False
    if intent.get("intentStatus") != "approval-ready" and not intent_blocks:
        return False
    return True


def build_stageable_ticket(
    intent: dict[str, Any],
    preview_order: dict[str, Any] | None,
    strike_plan_item: dict[str, Any] | None,
    status: str,
    reasons: list[str],
) -> dict[str, Any]:
    """Build one paperMoney session ticket from an execution intent."""
    strike_plan_item = effective_paper_plan_item(strike_plan_item)
    strike_plan = strike_plan_item.get("strikePlan") or {}
    ledger_ticket = latest_ledger_ticket_for_intent(intent, strategy_hint=strike_plan.get("strategy"))
    ticket = {
        "ticketId": (ledger_ticket or {}).get("ticketId"),
        "ticker": intent.get("ticker"),
        "strategy": (ledger_ticket or {}).get("strategy") or strike_plan.get("strategy"),
        "expiration": (ledger_ticket or {}).get("expiration") or strike_plan.get("expiration") or strike_plan_item.get("expiration"),
        "paperVariantOnly": bool((ledger_ticket or {}).get("paperVariantOnly") or strike_plan_item.get("paperVariantOnly")),
        "paperVariantFamily": (ledger_ticket or {}).get("paperVariantFamily") or strike_plan_item.get("paperVariantFamily"),
        "paperVariantOfStrategy": (ledger_ticket or {}).get("paperVariantOfStrategy") or strike_plan_item.get("paperVariantOfStrategy"),
        "status": status,
        "approvalStatus": intent.get("approvalStatus"),
        "paperAutoSelected": bool(status == "stage-in-papermoney" and intent.get("approvalStatus") != "approved"),
        "routeFamily": intent.get("routeFamily"),
        "setupRec": intent.get("setupRec"),
        "readiness": intent.get("readiness"),
        "daysUntilEarnings": intent.get("daysUntilEarnings"),
        "riskUnits": intent.get("riskUnits"),
        "nextStep": intent.get("nextStep"),
        "reasons": reasons,
        "ticketText": intent.get("ticketText"),
        "brokerSurface": intent.get("brokerSurface"),
        "previewOrder": preview_order,
        "legSymbols": [leg.get("symbol") for leg in (((ledger_ticket or {}).get("legs") or strike_plan.get("legs") or []))],
    }
    if preview_order:
        ticket["orderSummary"] = (
            f"{preview_order.get('ticker')} | {preview_order.get('strategy')} | "
            f"{preview_order.get('orderType')} | limit {preview_order.get('limitPrice')}"
        )
    return ticket


def ensure_fill_log_schema(path: Path) -> None:
    """Upgrade an existing CSV to the latest header layout without data loss."""
    if not path.exists():
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(FILL_LOG_COLUMNS)
        return

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        existing_rows = list(reader)
        existing_fields = reader.fieldnames or []
    if existing_fields == FILL_LOG_COLUMNS:
        return

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FILL_LOG_COLUMNS)
        writer.writeheader()
        for row in existing_rows:
            writer.writerow({column: row.get(column, "") for column in FILL_LOG_COLUMNS})


def load_fill_log_rows() -> list[dict[str, Any]]:
    """Load the current fill-log work file after enforcing schema."""
    ensure_fill_log_schema(TOS_FILL_LOG_WORK_FILE)
    with TOS_FILL_LOG_WORK_FILE.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def save_fill_log_rows(rows: list[dict[str, Any]]) -> None:
    """Persist fill-log rows using the canonical header order."""
    ensure_fill_log_schema(TOS_FILL_LOG_WORK_FILE)
    with TOS_FILL_LOG_WORK_FILE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FILL_LOG_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in FILL_LOG_COLUMNS})


def seed_fill_log_from_stageable(stageable: list[dict[str, Any]], session_date: str) -> dict[str, int]:
    """Seed the paper fill log with stable stub rows for stageable tickets.

    This lowers evidence-friction. When the desk finally produces a clean paper
    ticket, the operator should only need to fill in execution facts rather
    than hand-creating rows from scratch.
    """
    rows = load_fill_log_rows()
    by_ticket_id = {
        text(row.get("ticketId")): row
        for row in rows
        if text(row.get("ticketId"))
    }
    ordered_ticket_ids: list[str] = []
    for row in rows:
        ticket_id = text(row.get("ticketId"))
        if ticket_id and ticket_id not in ordered_ticket_ids:
            ordered_ticket_ids.append(ticket_id)

    inserted = 0
    updated = 0
    seeded_ids: set[str] = set()
    for ticket in stageable:
        ticket_id = text(ticket.get("ticketId"))
        if not ticket_id:
            continue
        seeded_ids.add(ticket_id)
        preview_order = ticket.get("previewOrder") or {}
        existing = by_ticket_id.get(ticket_id, {})
        seeded_row = {
            "sessionDate": existing.get("sessionDate") or session_date,
            "ticketId": ticket_id,
            "ticker": existing.get("ticker") or text(ticket.get("ticker")).upper(),
            "strategy": existing.get("strategy") or text(ticket.get("strategy")),
            "expiration": existing.get("expiration") or text(ticket.get("expiration")),
            "environment": existing.get("environment") or "thinkorswim-paperMoney",
            "paperAccount": existing.get("paperAccount") or "paperMoney",
            "routeFamily": existing.get("routeFamily") or text(ticket.get("routeFamily")),
            "orderType": existing.get("orderType") or text(preview_order.get("orderType")) or "LIMIT",
            "contracts": existing.get("contracts") or "1",
            "entryPrice": existing.get("entryPrice") or "",
            "exitPrice": existing.get("exitPrice") or "",
            "realizedPnl": existing.get("realizedPnl") or "",
            "status": existing.get("status") or "planned",
            "openedAt": existing.get("openedAt") or "",
            "closedAt": existing.get("closedAt") or "",
            "notes": existing.get("notes") or "seeded by inferno_tos_sandbox",
        }
        if ticket_id in by_ticket_id:
            by_ticket_id[ticket_id] = seeded_row
            updated += 1
        else:
            by_ticket_id[ticket_id] = seeded_row
            ordered_ticket_ids.append(ticket_id)
            inserted += 1

    # Keep historical/manual rows that are no longer stageable today. They may
    # still be part of an open or closed evidence trail.
    final_rows: list[dict[str, Any]] = []
    used_ticket_ids: set[str] = set()
    for ticket_id in ordered_ticket_ids:
        row = by_ticket_id.get(ticket_id)
        if not row:
            continue
        final_rows.append(row)
        used_ticket_ids.add(ticket_id)
    for row in rows:
        ticket_id = text(row.get("ticketId"))
        if ticket_id and ticket_id in used_ticket_ids:
            continue
        final_rows.append({column: row.get(column, "") for column in FILL_LOG_COLUMNS})

    save_fill_log_rows(final_rows)
    pending_count = sum(1 for row in final_rows if text(row.get("status")).lower() in {"", "planned", "pending"})
    return {
        "seededRowsInserted": inserted,
        "seededRowsUpdated": updated,
        "pendingFillRows": pending_count,
    }


def write_fill_log_template() -> None:
    """Create a reusable manual fill-log template for paperMoney sessions."""
    ensure_dirs()
    for path in (TOS_FILL_LOG_TEMPLATE_FILE, TOS_FILL_LOG_WORK_FILE):
        ensure_fill_log_schema(path)


def build_tos_sandbox_session() -> dict[str, Any]:
    """Build the current thinkorswim paperMoney sandbox packet."""
    decision = authority_decision()
    queue = load_json_file(EXECUTION_QUEUE_FILE) or {}
    preview_by_ticker = preview_orders_by_ticker()
    strike_plan_by_ticker = strike_plans_by_ticker()
    ready = sandbox_ready(decision)

    stageable: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    watchlist: list[dict[str, Any]] = []

    for intent in queue.get("items", []):
        ticker = str(intent.get("ticker", "")).upper()
        preview_order = preview_by_ticker.get(ticker)
        strike_plan_item = strike_plan_by_ticker.get(ticker)
        status, reasons = intent_stage_status(intent, strike_plan_item, ready)
        ticket = build_stageable_ticket(intent, preview_order, strike_plan_item, status, reasons)
        if status == "stage-in-papermoney" and len(stageable) < MAX_STAGEABLE_TICKETS:
            stageable.append(ticket)
        elif status == "stage-in-papermoney":
            # Keep overflow names visible without letting the session expand into
            # an operator-sprawl morning. The best few get staged; the rest wait.
            ticket["status"] = "watchlist-stage-cap"
            ticket["reasons"] = [f"daily paperMoney stage cap reached ({MAX_STAGEABLE_TICKETS})"]
            watchlist.append(ticket)
        elif intent.get("signalTrigger"):
            watchlist.append(ticket)
        else:
            blocked.append(ticket)

    write_fill_log_template()
    fill_log_sync = seed_fill_log_from_stageable(stageable, local_now().date().isoformat())
    return {
        "generatedAt": local_now().isoformat(),
        "environment": "thinkorswim-paperMoney",
        "brokerSurface": BROKER_EXECUTION_SURFACE,
        "sandboxReady": ready,
        "authorityLevel": decision.get("authorityLevel"),
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "stageableCount": len(stageable),
        "watchlistCount": len(watchlist),
        "blockedCount": len(blocked),
        "stageableTickets": stageable,
        "watchlistTickets": watchlist[:MAX_STAGEABLE_TICKETS],
        "blockedTickets": blocked[:MAX_STAGEABLE_TICKETS],
        "sessionChecklist": [
            "manually open the existing thinkorswim app and verify the account selector is paperMoney, not live",
            "open only the tickets listed as stage-in-papermoney",
            "do not alter risk size outside the manifest",
            "do not route any ticket blocked by authority, approval, or intent status",
            f"log simulated fills in {TOS_FILL_LOG_WORK_FILE.name}",
            "re-run the desk after fills so outcomes stay auditable",
        ],
        "fillLogTemplate": str(TOS_FILL_LOG_TEMPLATE_FILE),
        "fillLogWorkFile": str(TOS_FILL_LOG_WORK_FILE),
        "fillLogSync": fill_log_sync,
        "authorityWarnings": decision.get("warnings", []),
        "authorityBlockers": decision.get("blockers", []),
    }


def tos_sandbox_text(session: dict[str, Any]) -> str:
    """Render the sandbox packet for human execution review."""
    lines = [
        "Inferno thinkorswim paperMoney Sandbox",
        "",
        f"Generated: {session.get('generatedAt')}",
        f"Environment: {session.get('environment')}",
        f"Authority: {session.get('authorityLevel')}",
        f"Sandbox ready: {session.get('sandboxReady')}",
        f"Live trading allowed: {session.get('liveTradingAllowed')}",
        f"Broker submit allowed: {session.get('brokerSubmitAllowed')}",
        f"Operator-routable: {session.get('stageableCount')} | watchlist: {session.get('watchlistCount')} | blocked: {session.get('blockedCount')}",
        "",
        "Session checklist:",
    ]
    for step in session.get("sessionChecklist", []):
        lines.append(f"- {step}")

    lines.extend(["", "Operator-routable tickets:"])
    stageable = session.get("stageableTickets") or []
    if not stageable:
        lines.append("- none")
    for ticket in stageable:
        lines.append(
            f"- {ticket.get('ticker')} | {ticket.get('setupRec')} | "
            f"{ticket.get('routeFamily')} | {ticket.get('readiness')}% | "
            f"{ticket.get('daysUntilEarnings')}d"
        )
        if ticket.get("ticketId"):
            lines.append(f"  ticketId {ticket.get('ticketId')} | strategy {ticket.get('strategy')}")
        if ticket.get("paperVariantOnly"):
            lines.append(
                f"  paper rehearsal variant: {ticket.get('paperVariantFamily')} | "
                f"maps to {ticket.get('paperVariantOfStrategy')}"
            )
        if ticket.get("orderSummary"):
            lines.append(f"  {ticket.get('orderSummary')}")

    lines.extend(["", "Watchlist / blocked:"])
    blocked_like = (session.get("watchlistTickets") or []) + (session.get("blockedTickets") or [])
    if not blocked_like:
        lines.append("- none")
    for ticket in blocked_like[:10]:
        reasons = "; ".join(ticket.get("reasons") or []) or ticket.get("nextStep")
        lines.append(f"- {ticket.get('ticker')} | {ticket.get('status')} | {reasons}")

    lines.extend(["", "Authority warnings:"])
    warnings = session.get("authorityWarnings") or []
    if not warnings:
        lines.append("- none")
    for warning in warnings:
        lines.append(f"- {warning}")

    lines.extend(
        [
            "",
            f"Fill log template: {session.get('fillLogTemplate')}",
            f"Fill log work file: {session.get('fillLogWorkFile')}",
        ]
    )
    fill_log_sync = session.get("fillLogSync") or {}
    lines.extend(
        [
            f"Fill-log seeded rows: +{fill_log_sync.get('seededRowsInserted', 0)} new / "
            f"{fill_log_sync.get('seededRowsUpdated', 0)} refreshed",
            f"Fill-log pending rows: {fill_log_sync.get('pendingFillRows', 0)}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def save_tos_sandbox_session(session: dict[str, Any]) -> None:
    """Persist the sandbox session JSON and text packet."""
    ensure_dirs()
    TOS_SANDBOX_FILE.write_text(json.dumps(session, indent=2), encoding="utf-8")
    TOS_SANDBOX_TEXT_FILE.write_text(tos_sandbox_text(session), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the thinkorswim paperMoney sandbox session packet.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and TOS_SANDBOX_TEXT_FILE.exists():
        print(TOS_SANDBOX_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    session = build_tos_sandbox_session()
    save_tos_sandbox_session(session)
    print(tos_sandbox_text(session))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
