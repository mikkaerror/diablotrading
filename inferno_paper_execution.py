from __future__ import annotations

"""Paper-only execution ledger for Inferno strike tickets.

This module is the safety airlock between "the desk found an options setup" and
"a human or future broker adapter is allowed to act." It never places orders. It
records every strike ticket as rejected, blocked, or staged so the system can
build evidence before any live automation earns authority.
"""

import argparse
import hashlib
import json
from typing import Any

from inferno_config import AUTO_PAPER_SELECTION_ENABLED, local_now
from inferno_risk_policy import evaluate_strike_item
from inferno_trade_evidence import decision_card
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


STRIKE_PLAN_FILE = DATA_DIR / "inferno_strike_plan.json"
PAPER_EXECUTION_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
PAPER_EXECUTION_TEXT_FILE = REPORTS_DIR / "paper_execution_ledger_latest.txt"
SCHWAB_ACCOUNT_FILE = DATA_DIR / "inferno_schwab_account_sync.json"
PROCESS_COMPLIANCE_FILE = DATA_DIR / "inferno_process_compliance.json"

LEDGER_VERSION = 1
DEFAULT_LIMIT = 50
PAPER_VARIANT_ONLY = True
PAPER_AUTO_APPROVAL_REASONS = {
    "human approval is missing",
    "human approval missing",
    "human approval still required",
    "execution intent is not approval-ready",
}


def load_strike_plan() -> dict[str, Any]:
    """Load the latest strike plan, returning an empty shell if none exists."""
    return load_json_file(STRIKE_PLAN_FILE) or {"items": []}


def load_ledger() -> dict[str, Any]:
    """Load the paper ledger while tolerating a missing or malformed file."""
    ledger = load_json_file(PAPER_EXECUTION_LEDGER_FILE)
    if ledger and isinstance(ledger.get("items"), list):
        return ledger
    return {
        "version": LEDGER_VERSION,
        "generatedAt": None,
        "updatedAt": None,
        "count": 0,
        "items": [],
    }


def ticket_hash(parts: list[Any]) -> str:
    """Build a stable short id for duplicate-proof paper execution tickets."""
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def ledger_leg_symbols(entry: dict[str, Any]) -> str:
    """Return a stable leg signature for deduping refreshed tickets."""
    return ",".join(str(leg.get("symbol", "")) for leg in entry.get("legs", []))


def semantic_ticket_key(entry: dict[str, Any]) -> str:
    """Group refreshed quotes for the same same-day ticket together."""
    if entry.get("status") != "paper-staged":
        return "|".join(
            [
                str(entry.get("tradeDate")),
                str(entry.get("ticker")),
                str(entry.get("strategy") or entry.get("setupRec")),
                str(entry.get("status")),
            ]
        )
    return "|".join(
        [
            str(entry.get("tradeDate")),
            str(entry.get("ticker")),
            str(entry.get("strategy")),
            str(entry.get("expiration")),
            ledger_leg_symbols(entry),
        ]
    )


def merge_refreshed_entry(existing: dict[str, Any], refreshed: dict[str, Any]) -> dict[str, Any]:
    """Refresh quote/risk fields without losing original outcome history."""
    duplicate_ids = list(existing.get("mergedDuplicateTicketIds", []))
    if refreshed.get("ticketId") and refreshed.get("ticketId") != existing.get("ticketId"):
        duplicate_ids.append(refreshed["ticketId"])
    return {
        **existing,
        **refreshed,
        "ticketId": existing.get("ticketId") or refreshed.get("ticketId"),
        "createdAt": existing.get("createdAt") or refreshed.get("createdAt"),
        "refreshedAt": refreshed.get("createdAt"),
        "mergedDuplicateTicketIds": sorted(set(duplicate_ids)),
        "outcome": existing.get("outcome") or refreshed.get("outcome"),
    }


def compact_ledger_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse older duplicate rows created by repeated quote refreshes."""
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in items:
        key = semantic_ticket_key(item)
        if key not in by_key:
            by_key[key] = item
            order.append(key)
            continue
        by_key[key] = merge_refreshed_entry(by_key[key], item)
    return [by_key[key] for key in order]


def strategy_cost(strike_plan: dict[str, Any]) -> tuple[str, float]:
    """Return whether a strategy enters for debit, credit, or unknown cost."""
    if "estimatedDebit" in strike_plan:
        return "debit", float(strike_plan.get("estimatedDebit") or 0)
    if "estimatedCredit" in strike_plan:
        return "credit", float(strike_plan.get("estimatedCredit") or 0)
    return "unknown", 0.0


def normalize_reason(value: Any) -> str:
    """Normalize a blocker reason for approval-only paper checks."""
    return str(value or "").strip().lower()


def non_approval_reasons(reasons: list[Any]) -> list[str]:
    """Return blocker reasons that cannot be bypassed for paper evidence."""
    return [str(reason or "").strip() for reason in reasons if normalize_reason(reason) not in PAPER_AUTO_APPROVAL_REASONS]


def first_present(*values: Any) -> Any:
    """Return the first non-None value from a loose artifact field list."""
    for value in values:
        if value is not None:
            return value
    return None


def entry_score_context(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize entry-time ranking/provenance fields for paper/shadow records."""
    strike_plan = item.get("strikePlan") or {}
    return {
        "rank": first_present(item.get("rank"), strike_plan.get("rank")),
        "readiness": first_present(item.get("readiness"), strike_plan.get("readiness")),
        "confidence": first_present(item.get("confidence"), strike_plan.get("confidence")),
        "priority": first_present(item.get("priority"), strike_plan.get("priority")),
        "priorityScore": first_present(
            item.get("priorityScore"),
            item.get("priority"),
            strike_plan.get("priorityScore"),
            strike_plan.get("priority"),
        ),
        "scenarioScore": first_present(item.get("scenarioScore"), strike_plan.get("scenarioScore")),
        "setupFamily": first_present(
            item.get("setupFamily"),
            item.get("routeFamily"),
            item.get("sourceFamily"),
            strike_plan.get("setupFamily"),
            strike_plan.get("variantForStrategy"),
        ),
        "routeFamily": first_present(item.get("routeFamily"), strike_plan.get("routeFamily")),
        "primaryRoute": first_present(item.get("primaryRoute"), strike_plan.get("primaryRoute")),
        "secondaryRoute": first_present(item.get("secondaryRoute"), strike_plan.get("secondaryRoute")),
        "sourceLane": first_present(item.get("sourceLane"), strike_plan.get("sourceLane")),
        "sourceFamily": first_present(
            item.get("sourceFamily"),
            strike_plan.get("sourceFamily"),
            strike_plan.get("variantForStrategy"),
        ),
        "sourceRecommendedStrategy": first_present(
            item.get("sourceRecommendedStrategy"),
            strike_plan.get("sourceRecommendedStrategy"),
        ),
        "sourceAlternativeScore": first_present(
            item.get("sourceAlternativeScore"),
            strike_plan.get("sourceAlternativeScore"),
        ),
        "sourceAlternativeRawScore": first_present(
            item.get("sourceAlternativeRawScore"),
            strike_plan.get("sourceAlternativeRawScore"),
        ),
        "sourceAlternativeEdgeVsLongVol": first_present(
            item.get("sourceAlternativeEdgeVsLongVol"),
            strike_plan.get("sourceAlternativeEdgeVsLongVol"),
        ),
        "sourceAlternativeWarnings": first_present(
            item.get("sourceAlternativeWarnings"),
            strike_plan.get("sourceAlternativeWarnings"),
            [],
        ),
        "currentSetupRec": first_present(item.get("currentSetupRec"), strike_plan.get("currentSetupRec")),
    }


def size_cap_only_primary_blocks(item: dict[str, Any]) -> bool:
    """Return whether the primary strike item is blocked only by size limits."""
    blocks = list(((item.get("riskVerdict") or {}).get("blocks") or []))
    if not blocks:
        return False
    for reason in blocks:
        text = str(reason or "").lower()
        if "exceeds single-ticket cap" not in text and "projected daily max loss" not in text:
            return False
    return True


def rehearsal_variant_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Return a paper-only synthetic strike item when the capped variant is viable."""
    variant = item.get("paperRehearsalVariant") or {}
    verdict = variant.get("riskVerdict") or {}
    if not variant or not size_cap_only_primary_blocks(item) or not verdict.get("passed"):
        return None
    return {
        **item,
        "paperVariantOnly": True,
        "paperVariantFamily": variant.get("variantFamily"),
        "paperVariantOfStrategy": variant.get("variantForStrategy") or (item.get("strikePlan") or {}).get("strategy"),
        "strikePlan": variant,
        "riskVerdict": verdict,
    }


def paper_status_for_item(
    item: dict[str, Any],
    strike_plan_generated_at: str | None = None,
    ledger: dict[str, Any] | None = None,
) -> tuple[str, list[str], dict[str, Any], str]:
    """Classify a strike ticket without allowing unsafe tickets to pass.

    `paper-staged` means the idea is eligible for simulated tracking only. It
    still does not mean live trading is allowed. Liquidity, size, stale-data, or
    failed strike construction fail closed. Human approval can be bypassed only
    in the paper lane when it is the sole blocker.

    Returns a 4-tuple of (status, blockReasons, riskVerdictDict,
    paperAutoBlockReason). The last element is the specific reason the
    auto-paper gate refused (or "ok" if it allowed the ticket through, or
    "not-evaluated" when the strike plan itself failed and auto-paper was
    never consulted). It is diagnostic only -- the desk needs to see why
    auto-paper isn't firing on tickets that otherwise look clean.
    """
    reasons: list[str] = []
    risk_verdict = evaluate_strike_item(
        item,
        strike_plan_generated_at=strike_plan_generated_at,
        ledger_items=(ledger or {}).get("items", []),
        mode="paper",
    )
    if not item.get("ok"):
        reasons.append(str(item.get("reason") or "strike plan failed"))
        reasons.extend(reason for reason in risk_verdict.blocks if reason not in reasons)
        return "paper-rejected", reasons, risk_verdict.as_dict(), "not-evaluated"

    strike_plan = item.get("strikePlan") or {}
    card = item.get("decisionCard") or decision_card(item)
    if not card.get("paperComparisonAllowed"):
        reasons.append(card.get("noTradeReason") or "decision card is incomplete")
    if item.get("processEntryAllowed") is False:
        reasons.append("process circuit breaker is active; resolve hard breaches before new paper entries")
    liquidity_notes = strike_plan.get("liquidityNotes") or []
    intent_blocks = list(item.get("intentBlocks") or [])
    paper_auto_selected, auto_block_reason = paper_auto_selection_decision(
        item, risk_verdict, liquidity_notes, intent_blocks
    )
    if item.get("intentStatus") != "approval-ready":
        blocks = intent_blocks or ["execution intent is not approval-ready"]
        reasons.extend(non_approval_reasons(blocks) if paper_auto_selected else blocks)
    if item.get("approvalStatus") != "approved" and not paper_auto_selected:
        reasons.append("human approval missing")
    if liquidity_notes:
        reasons.extend(liquidity_notes)
    reasons.extend(reason for reason in risk_verdict.blocks if reason not in reasons)

    if reasons:
        return "paper-blocked", reasons, risk_verdict.as_dict(), auto_block_reason
    return "paper-staged", [], risk_verdict.as_dict(), auto_block_reason


def paper_auto_selection_decision(
    item: dict[str, Any],
    risk_verdict: Any,
    liquidity_notes: list[Any],
    intent_blocks: list[Any],
) -> tuple[bool, str]:
    """Return (eligible, reason) for whether a pending ticket may auto-stage.

    The reason is a stable short string identifying which gate decided.
    ``"ok"`` means the ticket cleared every condition; any other string is
    the specific block reason. This is the diagnostic surface for the
    auto-paper path -- if it keeps refusing tickets that look clean, the
    reason field will tell the operator why.
    """
    if not AUTO_PAPER_SELECTION_ENABLED:
        return False, "auto-paper-disabled-globally"
    approval_status = item.get("approvalStatus")
    if approval_status in {"approved", "rejected"}:
        return False, f"approval-status-is-{approval_status}"
    if not item.get("ok"):
        return False, "item-not-ok"
    if not getattr(risk_verdict, "passed", False):
        return False, "risk-verdict-failed"
    intent_non_approval = non_approval_reasons(intent_blocks)
    if intent_non_approval:
        return False, f"intent-has-non-approval-block: {intent_non_approval[0]}"
    liquidity_non_approval = non_approval_reasons(liquidity_notes)
    if liquidity_non_approval:
        return False, f"liquidity-has-non-approval-note: {liquidity_non_approval[0]}"
    intent_status = item.get("intentStatus")
    if intent_status not in {"approval-ready", "blocked"}:
        return False, f"intent-status-not-eligible: {intent_status!r}"
    # Legacy strike plans did not carry `intentBlocks`; risk/liquidity gates are
    # still enforced, so a pending blocked intent can be paper-staged only when
    # nothing except approval remains visible.
    return True, "ok"


def paper_auto_selection_applies(
    item: dict[str, Any],
    risk_verdict: Any,
    liquidity_notes: list[Any],
    intent_blocks: list[Any],
) -> bool:
    """Return True when a pending ticket may become paper evidence automatically.

    Thin backward-compatibility shim over ``paper_auto_selection_decision``.
    Prefer the decision variant in new code so the reason is captured.
    """
    eligible, _ = paper_auto_selection_decision(item, risk_verdict, liquidity_notes, intent_blocks)
    return eligible


def build_ledger_entry(
    item: dict[str, Any],
    strike_plan_generated_at: str | None,
    ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert one strike-plan item into a durable paper execution record."""
    now = local_now()
    strike_plan = item.get("strikePlan") or {}
    account = load_json_file(SCHWAB_ACCOUNT_FILE) or {}
    card = decision_card(item, account_nlv=account.get("netLiquidatingValue"))
    item = {**item, "decisionCard": card}
    legs = strike_plan.get("legs") or []
    leg_symbols = [leg.get("symbol") for leg in legs]
    cost_type, cost = strategy_cost(strike_plan)
    status, block_reasons, risk_verdict, paper_auto_block_reason = paper_status_for_item(
        item, strike_plan_generated_at, ledger
    )
    ticket_id = ticket_hash(
        [
            now.date().isoformat(),
            item.get("ticker"),
            strike_plan.get("strategy"),
            strike_plan.get("expiration"),
            ",".join(str(symbol) for symbol in leg_symbols),
        ]
    )

    return {
        "ticketId": ticket_id,
        "createdAt": now.isoformat(),
        "tradeDate": now.date().isoformat(),
        "sourceStrikePlanGeneratedAt": strike_plan_generated_at,
        "ticker": item.get("ticker"),
        "setupRec": item.get("setupRec"),
        "strategy": strike_plan.get("strategy"),
        "paperVariantOnly": bool(item.get("paperVariantOnly") or strike_plan.get("paperVariantOnly")),
        "paperVariantFamily": item.get("paperVariantFamily") or strike_plan.get("variantFamily"),
        "paperVariantOfStrategy": item.get("paperVariantOfStrategy") or strike_plan.get("variantForStrategy"),
        "status": status,
        "blockReasons": block_reasons,
        "paperOnly": True,
        "liveTradingAllowed": False,
        "paperAutoSelected": bool(status == "paper-staged" and item.get("approvalStatus") != "approved"),
        "paperAutoBlockReason": paper_auto_block_reason,
        "intentStatus": item.get("intentStatus"),
        "approvalStatus": item.get("approvalStatus"),
        "riskVerdict": risk_verdict,
        "underlyingPrice": item.get("price"),
        "daysUntilEarnings": item.get("daysUntilEarnings"),
        "riskUnits": item.get("riskUnits"),
        **entry_score_context(item),
        "ivRank": item.get("ivRank"),
        "ivRankChange": item.get("ivRankChange"),
        "atrPercent": item.get("atrPercent"),
        "marketContextSummary": item.get("marketContextSummary") or {},
        "schwabOptions": item.get("schwabOptions") or {},
        "decisionCard": card,
        "expiration": strike_plan.get("expiration"),
        "entryCostType": cost_type,
        "entryLimit": round(cost, 4),
        "estimatedMaxLoss": strike_plan.get("estimatedMaxLoss"),
        "estimatedMaxProfit": strike_plan.get("estimatedMaxProfit"),
        "breakEven": strike_plan.get("breakEven"),
        "lowerBreakEven": strike_plan.get("lowerBreakEven"),
        "upperBreakEven": strike_plan.get("upperBreakEven"),
        "legs": legs,
        "outcome": {
            "status": "open" if status == "paper-staged" else "not-opened",
            "reviewedAt": None,
            "exitValue": None,
            "estimatedPnl": None,
            "notes": None,
        },
    }


def merge_entries(ledger: dict[str, Any], new_entries: list[dict[str, Any]]) -> tuple[dict[str, Any], int]:
    """Append new paper tickets while preserving existing outcome history."""
    updated_items = compact_ledger_items(ledger.get("items", []))
    inserted = 0
    existing_by_key = {semantic_ticket_key(item): index for index, item in enumerate(updated_items)}
    existing_ids = {item.get("ticketId") for item in updated_items}
    for entry in new_entries:
        key = semantic_ticket_key(entry)
        if key in existing_by_key:
            index = existing_by_key[key]
            updated_items[index] = merge_refreshed_entry(updated_items[index], entry)
            continue
        if entry.get("ticketId") in existing_ids:
            continue
        existing_by_key[key] = len(updated_items)
        existing_ids.add(entry.get("ticketId"))
        updated_items.append(entry)
        inserted += 1
    updated = {
        **ledger,
        "version": LEDGER_VERSION,
        "generatedAt": ledger.get("generatedAt") or local_now().isoformat(),
        "updatedAt": local_now().isoformat(),
        "count": len(updated_items),
        "items": updated_items,
    }
    return updated, inserted


def record_from_strike_plan(strike_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Record all tickets from a strike plan into the paper ledger.

    Passing the in-memory strike plan is safest because it prevents accidentally
    recording stale disk data after a failed selector run.
    """
    strike_plan = strike_plan or load_strike_plan()
    ledger = load_ledger()
    compliance = load_json_file(PROCESS_COMPLIANCE_FILE) or {}
    process_entry_allowed = compliance.get("newPaperEntriesAllowed", True)
    entries: list[dict[str, Any]] = []
    for item in strike_plan.get("items", []):
        guarded_item = {**item, "processEntryAllowed": process_entry_allowed}
        entries.append(build_ledger_entry(guarded_item, strike_plan.get("generatedAt"), ledger))
        variant_item = rehearsal_variant_item(item)
        if variant_item:
            guarded_variant = {**variant_item, "processEntryAllowed": process_entry_allowed}
            entries.append(build_ledger_entry(guarded_variant, strike_plan.get("generatedAt"), ledger))
    updated, inserted = merge_entries(ledger, entries)
    save_ledger(updated)
    return {
        "inserted": inserted,
        "total": updated.get("count", 0),
        "staged": sum(1 for item in updated.get("items", []) if item.get("status") == "paper-staged"),
        "blocked": sum(1 for item in updated.get("items", []) if item.get("status") == "paper-blocked"),
        "rejected": sum(1 for item in updated.get("items", []) if item.get("status") == "paper-rejected"),
        "ledger": updated,
    }


def ledger_summary(ledger: dict[str, Any], limit: int = DEFAULT_LIMIT) -> str:
    """Render the latest paper ledger as a human-readable desk report."""
    items = ledger.get("items", [])
    lines = [
        "Inferno Paper Execution Ledger",
        "",
        f"Updated: {ledger.get('updatedAt')}",
        f"Tickets: {ledger.get('count', len(items))}",
        f"Staged: {sum(1 for item in items if item.get('status') == 'paper-staged')}",
        f"Blocked: {sum(1 for item in items if item.get('status') == 'paper-blocked')}",
        f"Rejected: {sum(1 for item in items if item.get('status') == 'paper-rejected')}",
        "",
    ]

    for item in items[-limit:]:
        lines.append(
            f"{item.get('tradeDate')} | {item.get('ticker')} | {item.get('strategy')} | "
            f"{item.get('status')} | {item.get('entryCostType')} {item.get('entryLimit')}"
        )
        reasons = item.get("blockReasons") or []
        if reasons:
            lines.append(f"  Blocks: {'; '.join(reasons)}")
        verdict = item.get("riskVerdict") or {}
        metrics = verdict.get("metrics") or {}
        if metrics:
            lines.append(
                "  Risk: "
                f"max loss ${metrics.get('maxLossDollars', 0):.2f} | "
                f"projected day ${metrics.get('projectedDailyLossDollars', 0):.2f} | "
                f"RR {metrics.get('debitSpreadRewardRisk')}"
            )
        paper_execution = item.get("paperExecution") or {}
        if paper_execution:
            lines.append(
                "  Fill: "
                f"{paper_execution.get('status')} | "
                f"opened {paper_execution.get('openedAt') or '-'} | "
                f"closed {paper_execution.get('closedAt') or '-'} | "
                f"realized {paper_execution.get('realizedPnl')}"
            )
        outcome = item.get("outcome") or {}
        if outcome.get("status") == "closed":
            lines.append(
                f"  Outcome: closed | P/L {outcome.get('estimatedPnl')} | "
                f"{outcome.get('notes') or 'no notes'}"
            )
        leg_text = ", ".join(leg.get("symbol", "") for leg in item.get("legs", []))
        if leg_text:
            lines.append(f"  Legs: {leg_text}")
    return "\n".join(lines).rstrip() + "\n"


def save_ledger(ledger: dict[str, Any]) -> None:
    """Persist JSON and text versions of the paper execution ledger."""
    ensure_dirs()
    PAPER_EXECUTION_LEDGER_FILE.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    PAPER_EXECUTION_TEXT_FILE.write_text(ledger_summary(ledger), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record paper-only option tickets from the latest Inferno strike plan.")
    parser.add_argument("command", nargs="?", default="record", choices=["record", "status"])
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Number of recent ledger rows to print.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "record":
        result = record_from_strike_plan()
        print(
            f"Paper execution ledger updated: {result['inserted']} inserted, "
            f"{result['total']} total."
        )
        print(ledger_summary(result["ledger"], limit=args.limit))
        return 0

    ledger = load_ledger()
    print(ledger_summary(ledger, limit=args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
