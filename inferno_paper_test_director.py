from __future__ import annotations

"""Paper-test command director for the Inferno desk.

This module consolidates the paperMoney sandbox, strike plan, authority
manifest, and execution queue into one operator-facing memo. The intent is to
speed up daily paper rehearsals without weakening any safety gates.

It never approves trades, never stages broker orders, and never unlocks live
authority. It simply turns scattered blocker state into one actionable daily
plan.
"""

import argparse
import json
from collections import Counter
from typing import Any

from inferno_config import MAX_SINGLE_TICKET_DOLLARS, local_now
from inferno_doctor import in_current_service_cycle
from inferno_execution_clerk import build_execution_queue
from inferno_io import atomic_write_json, atomic_write_text
from inferno_strike_selector import (
    build_strike_plan,
    build_strike_plan_from_queue,
    effective_paper_rehearsal_item,
    save_strike_plan,
)
from server import APPROVAL_QUEUE_FILE, DATA_DIR, REPORTS_DIR, SNAPSHOT_FILE, ensure_dirs, load_json_file


STRIKE_PLAN_FILE = DATA_DIR / "inferno_strike_plan.json"
EXECUTION_QUEUE_FILE = DATA_DIR / "inferno_execution_queue.json"
TOS_SANDBOX_FILE = DATA_DIR / "inferno_tos_sandbox_session.json"
AUTHORITY_MANIFEST_FILE = DATA_DIR / "inferno_authority_manifest.json"
PERFORMANCE_ANALYTICS_FILE = DATA_DIR / "inferno_performance_analytics.json"
PAPER_TEST_DIRECTOR_FILE = DATA_DIR / "inferno_paper_test_director.json"
PAPER_TEST_DIRECTOR_TEXT_FILE = REPORTS_DIR / "paper_test_director_latest.txt"
PAPER_REHEARSAL_STRIKE_PLAN_FILE = DATA_DIR / "inferno_paper_rehearsal_strike_plan.json"
PAPER_REHEARSAL_STRIKE_PLAN_TEXT_FILE = REPORTS_DIR / "paper_rehearsal_strike_plan_latest.txt"

PROMOTION_TARGET = 30
EXPANDED_REHEARSAL_LIMIT = 12
APPROVAL_ONLY_REASONS = {
    "human approval is missing",
    "human approval missing",
    "human approval still required",
    "execution intent is not approval-ready",
}
GOOD_VERDICTS = {"ready-to-paper-stage", "approval-bottleneck"}


def normalize_reason(reason: Any) -> str:
    """Return a lower-cased normalized blocker reason string."""
    return str(reason or "").strip().lower()


def dedupe(items: list[Any]) -> list[str]:
    """Preserve order while removing blank or duplicate strings."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in items:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return cleaned


def load_payload(path: Any, default: dict[str, Any]) -> dict[str, Any]:
    """Load a JSON artifact with a safe default shell."""
    return load_json_file(path) or default


def expanded_rehearsal_tickers(snapshot: dict[str, Any], primary_queue: dict[str, Any]) -> list[str]:
    """Return a wider paper-only rehearsal ticker slate when the primary queue dies.

    The live queue stays disciplined and small. The paper desk, though, should
    keep learning even when the top-five live queue is a bad micro-slate. We
    widen into the broader eligible universe without mutating the real execution
    queue on disk.
    """
    ordered: list[str] = []
    for source in (primary_queue.get("items") or []):
        ticker = str(source.get("ticker", "")).upper()
        if ticker and ticker not in ordered:
            ordered.append(ticker)
    for ticker in snapshot.get("eligibleTickers") or []:
        normalized = str(ticker or "").upper()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
        if len(ordered) >= EXPANDED_REHEARSAL_LIMIT:
            break
    return ordered[:EXPANDED_REHEARSAL_LIMIT]


def queue_tickers(queue: dict[str, Any]) -> list[str]:
    """Return the current execution-queue tickers in priority order."""
    return [
        str(item.get("ticker", "")).upper()
        for item in (queue.get("items") or [])
        if str(item.get("ticker", "")).strip()
    ]


def strike_plan_tickers(plan: dict[str, Any]) -> list[str]:
    """Return the current strike-plan tickers in plan order."""
    return [
        str(item.get("ticker", "")).upper()
        for item in (plan.get("items") or [])
        if str(item.get("ticker", "")).strip()
    ]


def strike_plan_is_current(plan: dict[str, Any], execution_queue: dict[str, Any]) -> bool:
    """Return True when the strike plan still matches the current intent queue.

    The paper desk must grade the same candidate set that the execution desk is
    staging. If the queue was refreshed after the strike plan was built, or the
    tickers drifted, we should rebuild instead of silently reviewing ghosts.
    """
    plan_generated_at = str(plan.get("generatedAt") or "")
    if not plan_generated_at or not in_current_service_cycle(plan_generated_at, now=local_now()):
        return False

    source_queue_updated_at = str(plan.get("sourceExecutionQueueUpdatedAt") or "")
    current_queue_updated_at = str(execution_queue.get("updatedAt") or "")
    if source_queue_updated_at and current_queue_updated_at and source_queue_updated_at != current_queue_updated_at:
        return False

    return strike_plan_tickers(plan) == queue_tickers(execution_queue)


def load_strike_plan(execution_queue: dict[str, Any], *, refresh_if_stale: bool = True) -> tuple[dict[str, Any], bool]:
    """Load the strike plan and rebuild it when it drifts from the queue.

    This keeps the paper desk aligned with the newest execution intents without
    requiring the operator to remember a separate strike-cycle refresh step.
    """
    plan = load_payload(STRIKE_PLAN_FILE, {"items": []})
    if not refresh_if_stale or strike_plan_is_current(plan, execution_queue):
        return plan, False

    refreshed = build_strike_plan()
    save_strike_plan(refreshed)
    return refreshed, True


def index_by_ticker(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Create a ticker-keyed index for quick cross-artifact joins."""
    index: dict[str, dict[str, Any]] = {}
    for item in items:
        ticker = str(item.get("ticker", "")).upper()
        if ticker:
            index[ticker] = item
    return index


def float_value(value: Any, default: float = 0.0) -> float:
    """Coerce a possibly-missing numeric field into a float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def paper_priority_score(execution_item: dict[str, Any], strike_item: dict[str, Any]) -> float:
    """Score paper candidates for operator focus.

    The weighting favors names that are already highly ranked by the desk while
    gently rewarding cheaper tickets and stronger market-context alignment.
    """
    readiness = float_value(execution_item.get("readiness"))
    alignment = float_value((strike_item.get("marketContext") or {}).get("alignmentScore"))
    max_loss = float_value((strike_item.get("strikePlan") or {}).get("estimatedMaxLoss"), 9999.0)

    # Lower cost gets a modest boost, but cannot overpower the desk's own
    # readiness/alignment stack.
    cost_bonus = max(0.0, 100.0 - min(max_loss, 1000.0) / 10.0)
    score = (readiness * 0.55) + (alignment * 0.30) + (cost_bonus * 0.15)
    return round(score, 2)


def classify_candidate(
    strike_item: dict[str, Any],
    execution_item: dict[str, Any] | None,
    sandbox_ticket: dict[str, Any] | None,
) -> dict[str, Any]:
    """Classify one strike candidate into an actionable paper-test cohort."""
    execution_item = execution_item or {}
    sandbox_ticket = sandbox_ticket or {}
    effective_item = effective_paper_rehearsal_item(strike_item) or strike_item

    ticker = str(strike_item.get("ticker", "")).upper()
    strike_plan = effective_item.get("strikePlan") or {}
    risk_verdict = effective_item.get("riskVerdict") or {}
    liquidity_notes = strike_plan.get("liquidityNotes") or []
    sandbox_reasons = sandbox_ticket.get("reasons") or []
    combined_reasons = dedupe(list(sandbox_reasons) + list(liquidity_notes) + list(risk_verdict.get("blocks") or []))
    non_approval_reasons = [
        reason for reason in combined_reasons if normalize_reason(reason) not in APPROVAL_ONLY_REASONS
    ]

    candidate = {
        "ticker": ticker,
        "setupRec": strike_item.get("setupRec"),
        "strategy": sandbox_ticket.get("strategy") or strike_plan.get("strategy") or strike_item.get("setupRec"),
        "approvalStatus": strike_item.get("approvalStatus"),
        "intentStatus": strike_item.get("intentStatus"),
        "sandboxStatus": sandbox_ticket.get("status"),
        "readiness": execution_item.get("readiness"),
        "daysUntilEarnings": strike_item.get("daysUntilEarnings"),
        "estimatedMaxLoss": strike_plan.get("estimatedMaxLoss"),
        "estimatedDebit": strike_plan.get("estimatedDebit"),
        "capitalGap": round(
            max(0.0, float_value(strike_plan.get("estimatedMaxLoss")) - MAX_SINGLE_TICKET_DOLLARS),
            2,
        ),
        "priorityScore": paper_priority_score(execution_item, strike_item),
        "reasons": combined_reasons,
        "warnings": risk_verdict.get("warnings") or [],
        "marketContextSummary": effective_item.get("marketContextSummary") or strike_item.get("marketContextSummary") or {},
        "nextStep": sandbox_ticket.get("nextStep") or execution_item.get("nextStep"),
        "paperVariantOnly": bool(sandbox_ticket.get("paperVariantOnly") or effective_item.get("paperVariantOnly")),
        "paperVariantFamily": sandbox_ticket.get("paperVariantFamily") or effective_item.get("paperVariantFamily"),
        "paperVariantOfStrategy": sandbox_ticket.get("paperVariantOfStrategy") or effective_item.get("paperVariantOfStrategy"),
        "approveCommand": f"python3 inferno_approval_queue.py approve {ticker}",
        "rejectCommand": f"python3 inferno_approval_queue.py reject {ticker}",
    }

    if not effective_item.get("ok"):
        candidate["category"] = "failed-construction"
        return candidate

    if sandbox_ticket.get("status") == "stage-in-papermoney":
        candidate["category"] = "stageable-now"
        return candidate

    if (
        risk_verdict.get("passed") is True
        and strike_item.get("approvalStatus") != "approved"
        and not non_approval_reasons
    ):
        candidate["category"] = "approval-only"
        return candidate

    if risk_verdict.get("passed") is True and not non_approval_reasons:
        candidate["category"] = "research-watch"
        return candidate

    candidate["category"] = "hard-blocked"
    return candidate


def approval_operator_steps(approval_slate: list[dict[str, Any]]) -> list[str]:
    """Build the shortest safe path from pending approvals to paper rehearsals."""
    if not approval_slate:
        return []
    steps = [
        "Review the approval-only names below and approve only the ones whose thesis still holds.",
    ]
    for candidate in approval_slate[:3]:
        steps.append(candidate["approveCommand"])
    steps.extend(
        [
            "./run_inferno_strike_cycle.sh",
            "Open thinkorswim paperMoney only after the refreshed sandbox says stageable > 0.",
        ]
    )
    return steps


def blocker_table(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate blocker reasons across the current paper-test slate."""
    counts: Counter[str] = Counter()
    for candidate in candidates:
        for reason in candidate.get("reasons") or []:
            counts[reason] += 1
    return [
        {"reason": reason, "count": count}
        for reason, count in counts.most_common()
    ]


def capital_near_miss_slate(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return blocked names that are primarily oversized rather than broken.

    This helps the operator separate "bad trade construction" from "valid
    thesis, wrong ticket size." Near-miss names remain blocked; this is a
    diagnostics lane, not a promotion shortcut.
    """
    near_miss: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.get("category") not in {"hard-blocked", "failed-construction"}:
            continue
        reasons = [normalize_reason(reason) for reason in candidate.get("reasons") or []]
        non_approval = [
            reason
            for reason in reasons
            if reason not in APPROVAL_ONLY_REASONS
        ]
        if not non_approval:
            continue
        if any("spread is wide" in reason or "reward/risk" in reason or "no supported strike plan" in reason for reason in non_approval):
            continue
        if not all("max loss $" in reason or "projected daily max loss $" in reason for reason in non_approval):
            continue
        near_miss.append(candidate)
    return sorted(
        near_miss,
        key=lambda item: (float_value(item.get("capitalGap"), 99999.0), -float_value(item.get("priorityScore"))),
    )


def classify_candidates(
    strike_plan: dict[str, Any],
    execution_queue: dict[str, Any],
    sandbox: dict[str, Any],
) -> list[dict[str, Any]]:
    """Classify a strike plan against a matching execution queue and sandbox."""
    execution_by_ticker = index_by_ticker(execution_queue.get("items") or [])
    sandbox_tickets = list(sandbox.get("stageableTickets") or []) + list(sandbox.get("watchlistTickets") or []) + list(
        sandbox.get("blockedTickets") or []
    )
    sandbox_by_ticker = index_by_ticker(sandbox_tickets)
    return [
        classify_candidate(
            item,
            execution_by_ticker.get(str(item.get("ticker", "")).upper()),
            sandbox_by_ticker.get(str(item.get("ticker", "")).upper()),
        )
        for item in strike_plan.get("items", [])
    ]


def split_candidates(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return the candidate cohorts used by the paper-test director."""
    stageable = sorted(
        [candidate for candidate in candidates if candidate["category"] == "stageable-now"],
        key=lambda item: (-float_value(item.get("priorityScore")), float_value(item.get("estimatedMaxLoss"), 99999.0)),
    )
    approval_only = sorted(
        [candidate for candidate in candidates if candidate["category"] == "approval-only"],
        key=lambda item: (-float_value(item.get("priorityScore")), float_value(item.get("estimatedMaxLoss"), 99999.0)),
    )
    research_watch = sorted(
        [candidate for candidate in candidates if candidate["category"] == "research-watch"],
        key=lambda item: (-float_value(item.get("priorityScore")), float_value(item.get("estimatedMaxLoss"), 99999.0)),
    )
    hard_blocked = sorted(
        [candidate for candidate in candidates if candidate["category"] in {"hard-blocked", "failed-construction"}],
        key=lambda item: (-float_value(item.get("priorityScore")), item.get("ticker", "")),
    )
    near_miss = capital_near_miss_slate(hard_blocked)
    return stageable, approval_only, research_watch, hard_blocked, near_miss


def build_director() -> dict[str, Any]:
    """Build the daily paper-test director packet."""
    snapshot = load_payload(SNAPSHOT_FILE, {"rows": [], "eligibleTickers": [], "reviewQueueTickers": []})
    approval_queue = load_payload(APPROVAL_QUEUE_FILE, {"items": []})
    execution_queue = load_payload(EXECUTION_QUEUE_FILE, {"items": []})
    strike_plan, source_plan_refreshed = load_strike_plan(execution_queue, refresh_if_stale=True)
    sandbox = load_payload(TOS_SANDBOX_FILE, {})
    authority = load_payload(AUTHORITY_MANIFEST_FILE, {"decision": {}, "evidence": {}})
    performance = load_payload(PERFORMANCE_ANALYTICS_FILE, {"closedMetrics": {}, "deskVerdict": {}})

    source_execution_queue = execution_queue
    source_strike_plan = strike_plan
    source_label = "primary-review-queue"
    expanded_tickers: list[str] = []

    candidates = classify_candidates(source_strike_plan, source_execution_queue, sandbox)
    stageable, approval_only, research_watch, hard_blocked, near_miss = split_candidates(candidates)

    if not stageable and not approval_only and not research_watch:
        expanded_tickers = expanded_rehearsal_tickers(snapshot, execution_queue)
        primary_tickers = queue_tickers(execution_queue)
        if expanded_tickers and expanded_tickers != primary_tickers:
            expanded_snapshot = {**snapshot, "reviewQueueTickers": expanded_tickers}
            source_execution_queue = build_execution_queue(
                expanded_snapshot,
                approval_queue,
                limit_override=len(expanded_tickers),
                enforce_capacity_limits=False,
            )
            source_strike_plan = build_strike_plan_from_queue(source_execution_queue, limit=len(expanded_tickers))
            source_label = "expanded-eligible-universe"
            save_rehearsal_strike_plan(source_strike_plan)
            candidates = classify_candidates(source_strike_plan, source_execution_queue, sandbox)
            stageable, approval_only, research_watch, hard_blocked, near_miss = split_candidates(candidates)

    scored_tickets = int(((performance.get("closedMetrics") or {}).get("scoredCount")) or 0)
    remaining_for_promotion = max(0, PROMOTION_TARGET - scored_tickets)

    if stageable:
        verdict = "ready-to-paper-stage"
    elif approval_only:
        verdict = "approval-bottleneck"
    elif research_watch:
        verdict = "research-watch"
    else:
        verdict = "no-viable-paper-tests"

    next_actions: list[str] = []
    if stageable:
        next_actions.append("Paper stageable names exist now. Rehearse only the stageable slate in paperMoney.")
    elif approval_only:
        next_actions.append("The bottleneck is approval, not discovery. Decide the pending paper-safe names first.")
        next_actions.extend(approval_operator_steps(approval_only))
    elif research_watch:
        next_actions.append("No clean paper tickets yet. Keep the watchlist alive and wait for stronger confirmation.")
    else:
        next_actions.append("No viable paper tests are currently clean enough. Preserve capital and keep research running.")
        if near_miss:
            closest = near_miss[0]
            next_actions.append(
                f"Closest capped rehearsal is {closest.get('ticker')} but it still needs "
                f"${float_value(closest.get('capitalGap')):.2f} less max loss before it fits the paper cap."
            )

    for milestone in (authority.get("decision") or {}).get("nextMilestones") or []:
        if milestone not in next_actions:
            next_actions.append(milestone)

    return {
        "generatedAt": local_now().isoformat(),
        "verdict": verdict,
        "paperCycleHealthy": verdict in GOOD_VERDICTS,
        "sourceStrikePlanGeneratedAt": source_strike_plan.get("generatedAt"),
        "sourceStrikePlanRefreshed": source_plan_refreshed,
        "sourceExecutionQueueUpdatedAt": source_execution_queue.get("updatedAt"),
        "sourceUniverse": source_label,
        "expandedUniverseUsed": source_label == "expanded-eligible-universe",
        "expandedUniverseTickers": expanded_tickers,
        "counts": {
            "totalCandidates": len(candidates),
            "stageableNow": len(stageable),
            "approvalOnly": len(approval_only),
            "researchWatch": len(research_watch),
            "hardBlocked": len(hard_blocked),
            "capitalNearMiss": len(near_miss),
            "scoredTickets": scored_tickets,
            "remainingForPromotion": remaining_for_promotion,
        },
        "authorityLevel": (authority.get("decision") or {}).get("authorityLevel"),
        "authorityWarnings": (authority.get("decision") or {}).get("warnings") or [],
        "blockerCounts": blocker_table(candidates),
        "stageableSlate": stageable,
        "approvalSlate": approval_only,
        "researchWatchlist": research_watch,
        "hardBlockedSlate": hard_blocked,
        "capitalNearMissSlate": near_miss,
        "nextActions": next_actions,
    }


def director_text(payload: dict[str, Any]) -> str:
    """Render the paper-test director as a human-readable memo."""
    counts = payload.get("counts") or {}
    lines = [
        "Inferno Paper Test Director",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Authority: {payload.get('authorityLevel')}",
        f"Strike plan refreshed this run: {'yes' if payload.get('sourceStrikePlanRefreshed') else 'no'}",
        f"Strike plan generated: {payload.get('sourceStrikePlanGeneratedAt')}",
        f"Source universe: {payload.get('sourceUniverse')}",
        "",
        "Counts:",
        f"- total candidates: {counts.get('totalCandidates', 0)}",
        f"- stageable now: {counts.get('stageableNow', 0)}",
        f"- approval only: {counts.get('approvalOnly', 0)}",
        f"- research watch: {counts.get('researchWatch', 0)}",
        f"- hard blocked: {counts.get('hardBlocked', 0)}",
        f"- capital near-miss: {counts.get('capitalNearMiss', 0)}",
        f"- scored tickets: {counts.get('scoredTickets', 0)}",
        f"- remaining for promotion: {counts.get('remainingForPromotion', 0)}",
    ]

    if payload.get("expandedUniverseUsed"):
        lines.append("")
        lines.append(
            f"Expanded paper universe used: {', '.join(payload.get('expandedUniverseTickers') or [])}"
        )

    lines.extend(["", "Next actions:"])

    for action in payload.get("nextActions") or []:
        lines.append(f"- {action}")

    lines.extend(["", "Approval slate:"])
    approval_slate = payload.get("approvalSlate") or []
    if not approval_slate:
        lines.append("- none")
    for candidate in approval_slate:
        lines.append(
            f"- {candidate.get('ticker')} | {candidate.get('strategy')} | "
            f"priority {candidate.get('priorityScore')} | max loss ${float_value(candidate.get('estimatedMaxLoss')):.2f}"
        )
        if candidate.get("paperVariantOnly"):
            lines.append(
                f"  paper rehearsal variant: {candidate.get('paperVariantFamily')} | "
                f"maps to {candidate.get('paperVariantOfStrategy')}"
            )
        trend = (candidate.get("marketContextSummary") or {}).get("trend", "Unknown")
        lines.append(
            f"  {candidate.get('daysUntilEarnings')}d to earnings | readiness {candidate.get('readiness')} | "
            f"trend {trend}"
        )
        if candidate.get("warnings"):
            lines.append(f"  warnings: {'; '.join(candidate.get('warnings') or [])}")
        lines.append(f"  approve: {candidate.get('approveCommand')}")

    lines.extend(["", "Stageable now:"])
    stageable = payload.get("stageableSlate") or []
    if not stageable:
        lines.append("- none")
    for candidate in stageable:
        lines.append(
            f"- {candidate.get('ticker')} | {candidate.get('strategy')} | "
            f"priority {candidate.get('priorityScore')} | max loss ${float_value(candidate.get('estimatedMaxLoss')):.2f}"
        )
        if candidate.get("paperVariantOnly"):
            lines.append(
                f"  paper rehearsal variant: {candidate.get('paperVariantFamily')} | "
                f"maps to {candidate.get('paperVariantOfStrategy')}"
            )

    lines.extend(["", "Capital near-miss slate:"])
    near_miss = payload.get("capitalNearMissSlate") or []
    if not near_miss:
        lines.append("- none")
    for candidate in near_miss[:5]:
        lines.append(
            f"- {candidate.get('ticker')} | {candidate.get('strategy')} | "
            f"gap ${float_value(candidate.get('capitalGap')):.2f} above ${MAX_SINGLE_TICKET_DOLLARS:.2f} cap"
        )
        if candidate.get("paperVariantOnly"):
            lines.append(
                f"  paper rehearsal variant: {candidate.get('paperVariantFamily')} | "
                f"maps to {candidate.get('paperVariantOfStrategy')}"
            )

    lines.extend(["", "Hard blocked slate:"])
    blocked = payload.get("hardBlockedSlate") or []
    if not blocked:
        lines.append("- none")
    for candidate in blocked[:8]:
        reasons = "; ".join(candidate.get("reasons") or []) or "unknown block"
        lines.append(f"- {candidate.get('ticker')} | {candidate.get('category')} | {reasons}")

    lines.extend(["", "Top blocker counts:"])
    blocker_counts = payload.get("blockerCounts") or []
    if not blocker_counts:
        lines.append("- none")
    for entry in blocker_counts[:8]:
        lines.append(f"- {entry.get('count')}x {entry.get('reason')}")

    lines.extend(["", "Authority warnings:"])
    warnings = payload.get("authorityWarnings") or []
    if not warnings:
        lines.append("- none")
    for warning in warnings:
        lines.append(f"- {warning}")

    return "\n".join(lines).rstrip() + "\n"


def rehearsal_strike_plan_text(plan: dict[str, Any]) -> str:
    """Render the expanded paper-only strike plan for shadow research review."""
    lines = [
        "Inferno Paper Rehearsal Strike Plan",
        "",
        "Research lane: paper-only / shadow-only / never broker-submit",
        f"Generated: {plan.get('generatedAt')}",
        f"Source universe: {plan.get('sourceUniverse')}",
        f"Live trading allowed: {plan.get('liveTradingAllowed')}",
        f"Plans: {plan.get('okCount')} ok / {plan.get('failedCount')} failed",
        "",
    ]
    for item in plan.get("items") or []:
        status = "OK" if item.get("ok") else "FAILED"
        lines.append(f"- {item.get('ticker')} | {item.get('setupRec')} | {status}")
        if not item.get("ok"):
            lines.append(f"  reason: {item.get('reason')}")
            continue
        strike_plan = item.get("strikePlan") or {}
        lines.append(
            f"  {strike_plan.get('strategy')} | max loss {strike_plan.get('estimatedMaxLoss')} | "
            f"approval {item.get('approvalStatus')}"
        )
        blocks = (item.get("riskVerdict") or {}).get("blocks") or []
        if blocks:
            lines.append(f"  blocks: {'; '.join(blocks[:4])}")
    return "\n".join(lines).rstrip() + "\n"


def save_rehearsal_strike_plan(plan: dict[str, Any]) -> None:
    """Persist the expanded paper-only plan without overwriting the live queue plan."""
    plan = {
        **plan,
        "sourceUniverse": "expanded-eligible-universe",
        "paperOnly": True,
        "shadowOnly": True,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
    }
    atomic_write_json(PAPER_REHEARSAL_STRIKE_PLAN_FILE, plan)
    atomic_write_text(PAPER_REHEARSAL_STRIKE_PLAN_TEXT_FILE, rehearsal_strike_plan_text(plan))


def save_director(payload: dict[str, Any]) -> None:
    """Persist the paper-test director JSON and text artifacts."""
    ensure_dirs()
    PAPER_TEST_DIRECTOR_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    PAPER_TEST_DIRECTOR_TEXT_FILE.write_text(director_text(payload), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for build/status modes."""
    parser = argparse.ArgumentParser(description="Build the daily Inferno paper-test director memo.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint."""
    args = parse_args()
    if args.command == "status" and PAPER_TEST_DIRECTOR_TEXT_FILE.exists():
        print(PAPER_TEST_DIRECTOR_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_director()
    save_director(payload)
    print(director_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
