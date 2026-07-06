from __future__ import annotations

"""Shadow evidence ledger for blocked-but-valid strike candidates.

The paper ledger is intentionally strict: a candidate does not become
`paper-staged` unless human approval, execution intent, liquidity, and risk
gates all pass. That is the right safety boundary, but it leaves the desk with
too little data while we are learning.

This module creates a separate research-only lane. It tracks valid strike plans
that were *not* allowed to execute, marks them as non-executable, and later
reviews hypothetical expiration outcomes. Nothing here can promote broker
authority or submit trades; it is a microscope, not a trigger.
"""

import argparse
import json
from collections import Counter, defaultdict
from datetime import date
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_doctor import in_current_service_cycle
from inferno_outcome_reviewer import estimate_expiration_pnl, latest_underlying_price, parse_date
from inferno_paper_execution import entry_score_context, ledger_leg_symbols, strategy_cost, ticket_hash
from inferno_risk_policy import evaluate_strike_item
from inferno_strike_selector import STRIKE_PLAN_FILE, build_strike_plan, save_strike_plan
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


SHADOW_EVIDENCE_FILE = DATA_DIR / "inferno_shadow_evidence.json"
SHADOW_EVIDENCE_TEXT_FILE = REPORTS_DIR / "shadow_evidence_latest.txt"
PAPER_REHEARSAL_STRIKE_PLAN_FILE = DATA_DIR / "inferno_paper_rehearsal_strike_plan.json"

SHADOW_EVIDENCE_VERSION = 1
DEFAULT_LIMIT = 50


def number(value: Any, default: float = 0.0) -> float:
    """Safely coerce loose plan values into floats for research metrics."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_shadow_evidence() -> dict[str, Any]:
    """Load the shadow ledger while tolerating a missing or malformed file."""
    ledger = load_json_file(SHADOW_EVIDENCE_FILE)
    if ledger and isinstance(ledger.get("items"), list):
        return ledger
    return {
        "version": SHADOW_EVIDENCE_VERSION,
        "generatedAt": None,
        "updatedAt": None,
        "stage": "shadow-evidence-research-only",
        "count": 0,
        "items": [],
    }


def strike_plan_is_fresh(plan: dict[str, Any]) -> bool:
    """Return True when the strike plan belongs to the current service cycle.

    Shadow research should not recycle a days-old option chain when we already
    know how to rebuild the plan locally. Using the same service-cycle freshness
    rule as doctor keeps the research lane aligned with the rest of the desk.
    """
    generated_at = str(plan.get("generatedAt") or "")
    items = plan.get("items") or []
    return bool(items) and in_current_service_cycle(generated_at, now=local_now())


def load_strike_plan(*, refresh_if_stale: bool = True) -> tuple[dict[str, Any], bool]:
    """Load the latest strike plan and rebuild it when the current copy is stale.

    Returns a tuple of `(plan, refreshed)` so callers can surface whether a
    shadow run had to regenerate the option chain before analysis.
    """
    plan = load_json_file(STRIKE_PLAN_FILE) or {"items": []}
    rehearsal_plan = load_json_file(PAPER_REHEARSAL_STRIKE_PLAN_FILE) or {}
    if (
        rehearsal_plan.get("sourceUniverse") == "expanded-eligible-universe"
        and strike_plan_is_fresh(rehearsal_plan)
        and len(rehearsal_plan.get("items") or []) >= len(plan.get("items") or [])
    ):
        return rehearsal_plan, False

    if not refresh_if_stale or strike_plan_is_fresh(plan):
        return plan, False

    refreshed = build_strike_plan()
    save_strike_plan(refreshed)
    return refreshed, True


def shadow_ticket_key(entry: dict[str, Any]) -> str:
    """Return a semantic dedupe key for one shadow ticket.

    We intentionally include `shadow-` status in skipped keys because failed
    construction rows do not have durable legs. Valid shadow tickets dedupe on
    ticker, strategy, expiration, and leg symbols, matching the paper ledger's
    same-day refresh behavior without borrowing paper execution authority.
    """
    if entry.get("status") != "shadow-open":
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


def merge_shadow_entry(existing: dict[str, Any], refreshed: dict[str, Any]) -> dict[str, Any]:
    """Refresh candidate/risk fields while preserving outcome history."""
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


def compact_shadow_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate shadow rows created by repeated quote refreshes."""
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in items:
        key = shadow_ticket_key(item)
        if key not in by_key:
            by_key[key] = item
            order.append(key)
            continue
        by_key[key] = merge_shadow_entry(by_key[key], item)
    return [by_key[key] for key in order]


def risk_verdict_for_shadow_item(
    item: dict[str, Any],
    strike_plan_generated_at: str | None,
    ledger: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate risk context for a shadow row without blocking ingestion.

    A shadow candidate should still remember why it would have been blocked, but
    a risk-policy exception should not destroy the research artifact. This is a
    diagnostic side lane, so fail-soft here and fail-closed everywhere else.
    """
    try:
        return evaluate_strike_item(
            item,
            strike_plan_generated_at=strike_plan_generated_at,
            ledger_items=ledger.get("items", []),
            mode="paper",
        ).as_dict()
    except Exception as exc:  # noqa: BLE001
        return {
            "level": "risk-verdict-unavailable",
            "blocks": [str(exc)],
            "warnings": [],
            "metrics": {},
        }


def shadow_status_for_item(item: dict[str, Any]) -> tuple[str, list[str]]:
    """Classify whether a strike-plan item is usable for shadow research."""
    strike_plan = item.get("strikePlan") or {}
    legs = strike_plan.get("legs") or []
    if not item.get("ok"):
        return "shadow-skipped", [str(item.get("reason") or "strike plan failed")]
    if not legs:
        return "shadow-skipped", ["strike plan has no usable option legs"]
    return "shadow-open", []


def build_shadow_entry(
    item: dict[str, Any],
    strike_plan_generated_at: str | None,
    ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert one strike-plan item into a non-executable shadow record."""
    now = local_now()
    ledger = ledger or load_shadow_evidence()
    strike_plan = item.get("strikePlan") or {}
    legs = strike_plan.get("legs") or []
    leg_symbols = [leg.get("symbol") for leg in legs]
    cost_type, cost = strategy_cost(strike_plan)
    status, shadow_reasons = shadow_status_for_item(item)
    risk_verdict = risk_verdict_for_shadow_item(item, strike_plan_generated_at, ledger)
    risk_blocks = list((risk_verdict.get("blocks") or []))
    liquidity_notes = list(strike_plan.get("liquidityNotes") or [])
    block_reasons = sorted(set(shadow_reasons + risk_blocks + liquidity_notes))
    ticket_id = ticket_hash(
        [
            "shadow",
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
        "strategy": strike_plan.get("strategy") or item.get("setupRec"),
        "status": status,
        "blockReasons": block_reasons,
        "researchNotes": [
            "shadow-only candidate; never eligible for broker submission",
            "used only to measure hypothetical edge after expiration",
        ],
        "shadowOnly": True,
        "paperOnly": True,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "authorityEligible": False,
        "intentStatus": item.get("intentStatus"),
        "approvalStatus": item.get("approvalStatus"),
        "riskVerdict": risk_verdict,
        "underlyingPrice": item.get("price"),
        "daysUntilEarnings": item.get("daysUntilEarnings"),
        "riskUnits": item.get("riskUnits"),
        **entry_score_context(item),
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
            "status": "open" if status == "shadow-open" else "not-opened",
            "reviewedAt": None,
            "exitUnderlyingPrice": None,
            "estimatedPnl": None,
            "estimatedReturnOnRisk": None,
            "notes": None,
        },
    }


def merge_shadow_entries(ledger: dict[str, Any], new_entries: list[dict[str, Any]]) -> tuple[dict[str, Any], int]:
    """Merge new shadow rows into an existing ledger without losing outcomes."""
    updated_items = compact_shadow_items(ledger.get("items", []))
    inserted = 0
    existing_by_key = {shadow_ticket_key(item): index for index, item in enumerate(updated_items)}
    existing_ids = {item.get("ticketId") for item in updated_items}
    for entry in new_entries:
        key = shadow_ticket_key(entry)
        if key in existing_by_key:
            index = existing_by_key[key]
            updated_items[index] = merge_shadow_entry(updated_items[index], entry)
            continue
        if entry.get("ticketId") in existing_ids:
            continue
        existing_by_key[key] = len(updated_items)
        existing_ids.add(entry.get("ticketId"))
        updated_items.append(entry)
        inserted += 1

    updated = {
        **ledger,
        "version": SHADOW_EVIDENCE_VERSION,
        "generatedAt": ledger.get("generatedAt") or local_now().isoformat(),
        "updatedAt": local_now().isoformat(),
        "stage": "shadow-evidence-research-only",
        "count": len(updated_items),
        "items": updated_items,
    }
    return updated, inserted


def shadow_ticket_ready_for_review(ticket: dict[str, Any], today: date | None = None) -> tuple[bool, str]:
    """Decide whether an open shadow ticket can be reviewed now."""
    today = today or local_now().date()
    if ticket.get("status") != "shadow-open":
        return False, "ticket was not shadow-open"
    outcome = ticket.get("outcome") or {}
    if outcome.get("status") not in {"open", "review-pending"}:
        return False, "shadow outcome is not open"
    expiration = parse_date(ticket.get("expiration"))
    if not expiration:
        return False, "expiration missing"
    if expiration > today:
        return False, f"expiration has not arrived ({expiration.isoformat()})"
    return True, "ready"


def review_shadow_ticket(ticket: dict[str, Any]) -> tuple[dict[str, Any], bool, str]:
    """Review one eligible shadow ticket using expiration intrinsic value."""
    ready, reason = shadow_ticket_ready_for_review(ticket)
    if not ready:
        return ticket, False, reason

    ticker = str(ticket.get("ticker", "")).upper()
    underlying_price = latest_underlying_price(ticker)
    if underlying_price is None:
        outcome = {
            **(ticket.get("outcome") or {}),
            "status": "review-pending",
            "reviewedAt": local_now().isoformat(),
            "notes": "could not fetch latest underlying price for shadow review",
        }
        return {**ticket, "outcome": outcome}, True, "price unavailable"

    estimated_pnl = estimate_expiration_pnl(ticket, underlying_price)
    max_loss_value = number(ticket.get("estimatedMaxLoss"))
    estimated_return = round(estimated_pnl / max_loss_value, 6) if max_loss_value > 0 else None
    outcome = {
        **(ticket.get("outcome") or {}),
        "status": "closed",
        "reviewedAt": local_now().isoformat(),
        "exitUnderlyingPrice": underlying_price,
        "estimatedPnl": estimated_pnl,
        "estimatedReturnOnRisk": estimated_return,
        "notes": "shadow-only estimate from expiration intrinsic value",
    }
    return {**ticket, "outcome": outcome}, True, "closed"


def review_shadow_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int, list[str]]:
    """Review all eligible shadow tickets and return updated rows plus notes."""
    reviewed = 0
    closed = 0
    updated_items: list[dict[str, Any]] = []
    notes: list[str] = []
    for ticket in items:
        updated, changed, note = review_shadow_ticket(ticket)
        updated_items.append(updated)
        if changed:
            reviewed += 1
            if (updated.get("outcome") or {}).get("status") == "closed":
                closed += 1
            notes.append(f"{ticket.get('ticker')}: {note}")
    return updated_items, reviewed, closed, notes


def summarize_strategy(name: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize research evidence for one shadow strategy family."""
    closed = [item for item in items if (item.get("outcome") or {}).get("status") == "closed"]
    pnls = [number((item.get("outcome") or {}).get("estimatedPnl")) for item in closed]
    returns = [
        number((item.get("outcome") or {}).get("estimatedReturnOnRisk"))
        for item in closed
        if (item.get("outcome") or {}).get("estimatedReturnOnRisk") is not None
    ]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    return {
        "strategy": name,
        "trackedCount": len(items),
        "openCount": sum(1 for item in items if (item.get("outcome") or {}).get("status") == "open"),
        "reviewPendingCount": sum(
            1 for item in items if (item.get("outcome") or {}).get("status") == "review-pending"
        ),
        "closedCount": len(closed),
        "skippedCount": sum(1 for item in items if item.get("status") == "shadow-skipped"),
        "statusCounts": dict(Counter(str(item.get("status") or "unknown") for item in items)),
        "winRate": round(len(wins) / len(pnls), 4) if pnls else None,
        "avgEstimatedPnl": round(sum(pnls) / len(pnls), 2) if pnls else None,
        "avgReturnOnRisk": round(sum(returns) / len(returns), 6) if returns else None,
        "totalEstimatedPnl": round(sum(pnls), 2) if pnls else 0.0,
        "winCount": len(wins),
        "lossCount": len(losses),
        "latestClosed": [
            {
                "ticketId": item.get("ticketId"),
                "ticker": item.get("ticker"),
                "estimatedPnl": (item.get("outcome") or {}).get("estimatedPnl"),
                "estimatedReturnOnRisk": (item.get("outcome") or {}).get("estimatedReturnOnRisk"),
                "reviewedAt": (item.get("outcome") or {}).get("reviewedAt"),
            }
            for item in closed[-8:]
        ],
    }


def summarize_shadow_evidence(ledger: dict[str, Any]) -> dict[str, Any]:
    """Build portfolio-style summary metrics for the shadow ledger."""
    items = ledger.get("items", [])
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[str(item.get("strategy") or item.get("setupRec") or "UNKNOWN")].append(item)
    strategies = [summarize_strategy(name, rows) for name, rows in sorted(grouped.items())]
    overall = summarize_strategy("ALL_SHADOW_CANDIDATES", items)
    return {
        "overall": overall,
        "strategies": strategies,
        "researchVerdict": {
            "level": "research-only",
            "message": "Shadow evidence is diagnostic only and cannot increase broker authority.",
            "brokerSubmitAllowed": False,
            "liveTradingAllowed": False,
        },
    }


def build_shadow_evidence(
    strike_plan: dict[str, Any] | None = None,
    ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ingest the latest strike plan, review expired shadows, and return ledger."""
    source_plan_refreshed = False
    if strike_plan is None:
        strike_plan, source_plan_refreshed = load_strike_plan(refresh_if_stale=True)
    ledger = ledger or load_shadow_evidence()
    entries = [
        build_shadow_entry(item, strike_plan.get("generatedAt"), ledger)
        for item in strike_plan.get("items", [])
    ]
    merged, inserted = merge_shadow_entries(ledger, entries)
    reviewed_items, reviewed, closed, notes = review_shadow_items(merged.get("items", []))
    updated = {
        **merged,
        "updatedAt": local_now().isoformat(),
        "sourceStrikePlanGeneratedAt": strike_plan.get("generatedAt"),
        "sourceStrikePlanRefreshed": source_plan_refreshed,
        "sourceUniverse": strike_plan.get("sourceUniverse") or "primary-review-queue",
        "count": len(reviewed_items),
        "items": reviewed_items,
        "lastRun": {
            "inserted": inserted,
            "reviewed": reviewed,
            "closed": closed,
            "notes": notes,
        },
    }
    updated.update(summarize_shadow_evidence(updated))
    return updated


def review_shadow_evidence(ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    """Review existing shadow tickets without ingesting a possibly stale plan."""
    ledger = ledger or load_shadow_evidence()
    reviewed_items, reviewed, closed, notes = review_shadow_items(ledger.get("items", []))
    updated = {
        **ledger,
        "updatedAt": local_now().isoformat(),
        "count": len(reviewed_items),
        "items": reviewed_items,
        "lastRun": {
            "inserted": 0,
            "reviewed": reviewed,
            "closed": closed,
            "notes": notes,
        },
    }
    updated.update(summarize_shadow_evidence(updated))
    return updated


def shadow_evidence_text(ledger: dict[str, Any], limit: int = DEFAULT_LIMIT) -> str:
    """Render the shadow evidence ledger as a human-readable research report."""
    overall = ledger.get("overall") or {}
    verdict = ledger.get("researchVerdict") or {}
    last_run = ledger.get("lastRun") or {}
    lines = [
        "Inferno Shadow Evidence Lab",
        "",
        "Research lane: shadow-only / paper-only / never broker-submit",
        f"Updated: {ledger.get('updatedAt')}",
        f"Source strike plan: {ledger.get('sourceStrikePlanGeneratedAt')}",
        f"Strike plan refreshed this run: {'yes' if ledger.get('sourceStrikePlanRefreshed') else 'no'}",
        f"Source universe: {ledger.get('sourceUniverse')}",
        f"Verdict: {verdict.get('level')} - {verdict.get('message')}",
        "",
        "Last run:",
        f"- inserted: {last_run.get('inserted', 0)}",
        f"- reviewed: {last_run.get('reviewed', 0)}",
        f"- closed: {last_run.get('closed', 0)}",
        "",
        "Overall shadow evidence:",
        f"- tracked: {overall.get('trackedCount', 0)}",
        f"- open: {overall.get('openCount', 0)}",
        f"- review pending: {overall.get('reviewPendingCount', 0)}",
        f"- closed: {overall.get('closedCount', 0)}",
        f"- skipped: {overall.get('skippedCount', 0)}",
        f"- win rate: {overall.get('winRate')}",
        f"- avg P/L: {overall.get('avgEstimatedPnl')}",
        f"- avg return/risk: {overall.get('avgReturnOnRisk')}",
        "",
        "Strategy research:",
    ]
    strategies = ledger.get("strategies") or []
    if not strategies:
        lines.append("- no shadow candidates recorded yet")
    for item in strategies:
        lines.append(
            f"- {item.get('strategy')}: {item.get('trackedCount')} tracked | "
            f"{item.get('closedCount')} closed | win {item.get('winRate')} | "
            f"avg R {item.get('avgReturnOnRisk')}"
        )
    notes = last_run.get("notes") or []
    if notes:
        lines.append("")
        lines.append("Review notes:")
        lines.extend(f"- {note}" for note in notes[:limit])

    rows = ledger.get("items", [])[-limit:]
    if rows:
        lines.append("")
        lines.append("Recent shadow tickets:")
    for item in rows:
        outcome = item.get("outcome") or {}
        lines.append(
            f"- {item.get('tradeDate')} | {item.get('ticker')} | {item.get('strategy')} | "
            f"{item.get('status')} | {outcome.get('status')} | "
            f"{item.get('entryCostType')} {item.get('entryLimit')}"
        )
        if outcome.get("status") == "closed":
            lines.append(
                f"  shadow outcome: P/L {outcome.get('estimatedPnl')} | "
                f"R {outcome.get('estimatedReturnOnRisk')}"
            )
        reasons = item.get("blockReasons") or []
        if reasons:
            lines.append(f"  remembered blocks: {'; '.join(reasons[:4])}")
    return "\n".join(lines).rstrip() + "\n"


def save_shadow_evidence(ledger: dict[str, Any]) -> None:
    """Persist JSON and text versions of the shadow evidence ledger."""
    ensure_dirs()
    atomic_write_json(SHADOW_EVIDENCE_FILE, ledger)
    atomic_write_text(SHADOW_EVIDENCE_TEXT_FILE, shadow_evidence_text(ledger))


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for local/operator use."""
    parser = argparse.ArgumentParser(description="Build or view shadow-only strike evidence.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status", "review"])
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Number of recent rows to print.")
    return parser.parse_args()


def main() -> int:
    """CLI entry point for building/reviewing the shadow evidence lab."""
    args = parse_args()
    if args.command == "status" and SHADOW_EVIDENCE_TEXT_FILE.exists():
        print(SHADOW_EVIDENCE_TEXT_FILE.read_text(encoding="utf-8"))
        return 0

    ledger = review_shadow_evidence() if args.command == "review" else build_shadow_evidence()
    save_shadow_evidence(ledger)
    print(shadow_evidence_text(ledger, limit=args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
