from __future__ import annotations

from inferno_ledger_ownership import paper_writer

"""Paper-only execution ledger for Inferno strike tickets.

This module is the safety airlock between "the desk found an options setup" and
"a human or future broker adapter is allowed to act." It never places orders. It
records every strike ticket as rejected, blocked, or staged so the system can
build evidence before any live automation earns authority.
"""

import argparse
import hashlib
import math
import sys
from datetime import date, datetime, timedelta
from typing import Any

from inferno_artifact_lifecycle import failed_lifecycle, successful_lifecycle
from inferno_config import (
    AUTO_PAPER_SELECTION_ENABLED,
    MAX_SINGLE_TICKET_DOLLARS,
    MIN_DEBIT_SPREAD_REWARD_RISK,
    local_now,
)
from inferno_io import atomic_write_json, atomic_write_text
from inferno_risk_policy import evaluate_strike_item
from inferno_trade_evidence import decision_card
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


STRIKE_PLAN_FILE = DATA_DIR / "inferno_strike_plan.json"
PAPER_EXECUTION_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
PAPER_EXECUTION_TEXT_FILE = REPORTS_DIR / "paper_execution_ledger_latest.txt"
SCHWAB_ACCOUNT_FILE = DATA_DIR / "inferno_schwab_account_sync.json"
PROCESS_COMPLIANCE_FILE = DATA_DIR / "inferno_process_compliance.json"
STRATEGY_ALTERNATIVE_PRICING_FILE = DATA_DIR / "inferno_strategy_alternative_pricing.json"

LEDGER_VERSION = 1
DEFAULT_LIMIT = 50
PAPER_VARIANT_ONLY = True
PAPER_AUTO_APPROVAL_REASONS = {
    "human approval is missing",
    "human approval missing",
    "human approval still required",
    "execution intent is not approval-ready",
}
EVENT_DATE_FIELDS = ("nextEarnings", "earningsDate", "reportDate")
EVENT_CONTEXT_FIELDS = ("trackerContext", "marketContext", "marketContextSummary")
COUNTED_EVENT_STATUSES = {"paper-staged"}
COUNTED_OUTCOME_STATUSES = {"open", "closed", "scored", "reviewed"}
CAMPAIGN_ARMS = {"A", "B", "C", "D"}
SHORT_PREMIUM_DEFINED_ARM = "SHORT_PREMIUM_DEFINED"
EXPLICIT_CAMPAIGN_ARMS = CAMPAIGN_ARMS | {SHORT_PREMIUM_DEFINED_ARM}
HOLD_THROUGH_EXIT_RULE = "hold-through"
EXIT_BEFORE_EARNINGS_RULE = "exit-before-earnings"
CONTRACT_MULTIPLIER = 100.0
CAP_FIT_DEFINED_RISK_STRATEGIES = {"CALL_DEBIT_SPREAD", "PUT_DEBIT_SPREAD"}


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


def _text(value: Any) -> str:
    """Return compact text for event-id fields."""
    return str(value or "").strip()


def _parse_event_date(value: Any) -> str:
    """Normalize loose date/datetime values to YYYY-MM-DD when possible."""
    raw = _text(value)
    if not raw:
        return ""
    if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
        return raw[:10]
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.date().isoformat()
    except ValueError:
        return raw


def _base_date_for_item(item: dict[str, Any]) -> date:
    """Return the date used to reconstruct legacy days-to-earnings events."""
    for field in ("tradeDate", "createdAt", "generatedAt"):
        raw = _text(item.get(field))
        if not raw:
            continue
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
                try:
                    return date.fromisoformat(raw[:10])
                except ValueError:
                    continue
    return local_now().date()


def _days_until_earnings_event(item: dict[str, Any]) -> str:
    """Derive an event date from days-until-earnings for legacy artifacts."""
    try:
        days = int(float(item.get("daysUntilEarnings")))
    except (TypeError, ValueError):
        return ""
    return (_base_date_for_item(item) + timedelta(days=days)).isoformat()


def _event_date(item: dict[str, Any]) -> str:
    """Return the best available earnings event date for a ticket-like item."""
    for field in EVENT_DATE_FIELDS:
        parsed = _parse_event_date(item.get(field))
        if parsed:
            return parsed
    for context_field in EVENT_CONTEXT_FIELDS:
        context = item.get(context_field) or {}
        if not isinstance(context, dict):
            continue
        for field in EVENT_DATE_FIELDS:
            parsed = _parse_event_date(context.get(field))
            if parsed:
                return parsed
    derived = _days_until_earnings_event(item)
    if derived:
        return derived
    return _parse_event_date(item.get("expiration") or (item.get("strikePlan") or {}).get("expiration")) or "unknown-event"


def paper_event_id(item: dict[str, Any]) -> str:
    """Return the distinct paper evidence event id for a ticket-like item."""
    existing = _text(item.get("eventId"))
    if existing:
        return existing.upper()
    ticker = _text(item.get("ticker") or item.get("symbol")).upper() or "UNKNOWN"
    return f"{ticker}|{_event_date(item)}"


def paper_event_ticket_count(event_id: str, ledger_items: list[dict[str, Any]]) -> int:
    """Count existing open or scored paper tickets on a distinct event."""
    target = _text(event_id).upper()
    if not target:
        return 0
    count = 0
    for item in ledger_items:
        if not isinstance(item, dict):
            continue
        outcome_status = _text((item.get("outcome") or {}).get("status")).lower()
        status = _text(item.get("status")).lower()
        if status not in COUNTED_EVENT_STATUSES and outcome_status not in COUNTED_OUTCOME_STATUSES:
            continue
        if paper_event_id(item) == target:
            count += 1
    return count


def _strategy_text(item: dict[str, Any]) -> str:
    """Return a normalized strategy label from a ticket-like item."""
    return _text(
        item.get("strategy")
        or (item.get("strikePlan") or {}).get("strategy")
        or item.get("setupRec")
    ).upper()


def _campaign_pair_for_strategy(strategy: str) -> tuple[str, str]:
    """Return the hold/exit arm pair for the campaign structure bucket."""
    normalized = strategy.replace("_", " ")
    if strategy == SHORT_PREMIUM_DEFINED_ARM:
        return SHORT_PREMIUM_DEFINED_ARM, SHORT_PREMIUM_DEFINED_ARM
    if "STRADDLE" in normalized or "STRANGLE" in normalized:
        return "A", "B"
    return "C", "D"


def _stable_variant_index(event_id: str, strategy: str) -> int:
    """Return a deterministic 0/1 assignment without randomness."""
    digest = hashlib.sha256(f"{event_id}|{strategy}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 2


def campaign_arm_for_ticket(item: dict[str, Any], event_id: str) -> dict[str, Any]:
    """Return pre-registered campaign arm metadata for a paper ticket."""
    explicit_arm = _text(item.get("arm") or item.get("campaignArm")).upper()
    explicit_exit = _text(item.get("exitRule") or item.get("campaignExitRule"))
    if explicit_arm in EXPLICIT_CAMPAIGN_ARMS:
        if not explicit_exit:
            explicit_exit = (
                HOLD_THROUGH_EXIT_RULE
                if explicit_arm in {"A", "C", SHORT_PREMIUM_DEFINED_ARM}
                else EXIT_BEFORE_EARNINGS_RULE
            )
        return {
            "arm": explicit_arm,
            "campaignArm": explicit_arm,
            "exitRule": explicit_exit,
            "campaignExitRule": explicit_exit,
            "campaignArmAssignment": "explicit",
        }

    strategy = _strategy_text(item)
    if strategy == SHORT_PREMIUM_DEFINED_ARM:
        return {
            "arm": SHORT_PREMIUM_DEFINED_ARM,
            "campaignArm": SHORT_PREMIUM_DEFINED_ARM,
            "exitRule": explicit_exit or HOLD_THROUGH_EXIT_RULE,
            "campaignExitRule": explicit_exit or HOLD_THROUGH_EXIT_RULE,
            "campaignArmAssignment": "strategy",
        }
    hold_arm, exit_arm = _campaign_pair_for_strategy(strategy)
    exit_variant = _stable_variant_index(event_id, strategy) == 1
    arm = exit_arm if exit_variant else hold_arm
    exit_rule = EXIT_BEFORE_EARNINGS_RULE if exit_variant else HOLD_THROUGH_EXIT_RULE
    return {
        "arm": arm,
        "campaignArm": arm,
        "exitRule": exit_rule,
        "campaignExitRule": exit_rule,
        "campaignArmAssignment": "event-hash",
    }


def friction_crossings_for_exit_rule(exit_rule: Any) -> int:
    """Return how many spread crossings the campaign charges."""
    normalized = _text(exit_rule).lower()
    if normalized in {EXIT_BEFORE_EARNINGS_RULE, "exit-before", "sell-ramp"}:
        return 2
    return 1


def _spread_pct(value: Any) -> float | None:
    """Normalize a decimal/percentage spread input to a decimal fraction."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed / 100.0 if parsed > 1 else parsed


def paper_fill_friction_model(
    item: dict[str, Any],
    *,
    entry_limit: float,
    exit_rule: Any,
) -> dict[str, Any]:
    """Estimate campaign spread friction from the full ATM spread per crossing."""
    schwab = item.get("schwabOptions") if isinstance(item.get("schwabOptions"), dict) else {}
    spread_pct = None
    for value in (
        item.get("paperFillFrictionPct"),
        item.get("atmSpreadPctAtEntry"),
        schwab.get("paperFillFrictionPct"),
        schwab.get("atmWindowMedianSpreadPct"),
        schwab.get("atmSpreadPct"),
    ):
        spread_pct = _spread_pct(value)
        if spread_pct is not None:
            break
    crossings = friction_crossings_for_exit_rule(exit_rule)
    per_crossing = round(entry_limit * spread_pct * CONTRACT_MULTIPLIER, 4) if spread_pct is not None else 0.0
    total = round(per_crossing * crossings, 4)
    return {
        "paperFillFrictionPct": spread_pct,
        "paperFrictionCrossings": crossings,
        "estimatedSpreadFrictionPerCrossingDollars": per_crossing,
        "estimatedTotalSpreadFrictionDollars": total,
        "frictionModel": "full-atm-spread-per-crossing" if spread_pct is not None else "spread-unavailable",
    }


def paper_ledger_schwab_summary(value: Any) -> dict[str, Any]:
    """Keep decision metrics without copying the full option chain into the ledger.

    The selected ticket already persists its exact legs and quotes. Raw Schwab
    contract arrays remain in the source options artifact, while the canonical
    paper ledger retains the compact quality, liquidity, Greek, and provenance
    fields used by downstream evaluators.
    """
    if not isinstance(value, dict):
        return {}
    summary = {
        key: field_value
        for key, field_value in value.items()
        if key not in {"contracts", "topLiquidContracts"}
    }
    contracts = value.get("contracts")
    top_liquid = value.get("topLiquidContracts")
    summary["fullContractArraysPersisted"] = False
    summary["omittedContractCount"] = len(contracts) if isinstance(contracts, list) else 0
    summary["omittedTopLiquidContractCount"] = len(top_liquid) if isinstance(top_liquid, list) else 0
    return summary


def ledger_leg_symbols(entry: dict[str, Any]) -> str:
    """Return a stable leg signature for deduping refreshed tickets."""
    return ",".join(str(leg.get("symbol", "")) for leg in entry.get("legs", []))


def planned_ticket_id(item: dict[str, Any], trade_date: str | None = None) -> str:
    """Return the stable id a strike item will receive in the paper ledger."""
    strike_plan = item.get("strikePlan") or {}
    leg_symbols = [leg.get("symbol") for leg in strike_plan.get("legs") or []]
    return ticket_hash(
        [
            trade_date or local_now().date().isoformat(),
            item.get("ticker"),
            strike_plan.get("strategy"),
            strike_plan.get("expiration"),
            ",".join(str(symbol) for symbol in leg_symbols),
        ]
    )


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
        # A refreshed rank must never masquerade as the original prediction.
        # Missing legacy snapshots stay missing; a refresh cannot backfill them.
        "entryScoreSnapshot": existing.get("entryScoreSnapshot"),
        "entryScoreSnapshotVersion": existing.get("entryScoreSnapshotVersion", 0),
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


def number(value: Any, default: float = 0.0) -> float:
    """Safely normalize a numeric artifact field for route qualification."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


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
    context = {
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
    context["entryScoreSnapshot"] = {
        field: context.get(field) for field in ("scenarioScore", "readiness", "priorityScore")
    }
    context["entryScoreSnapshotVersion"] = 1
    return context


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


def cap_fit_defined_risk_variant_item(
    item: dict[str, Any],
    strategy_pricing: dict[str, Any],
) -> dict[str, Any] | None:
    """Return one already-passed cap-fit debit spread for a blocked primary.

    Strategy-alternative pricing is a research artifact, so this bridge is
    intentionally much narrower than its general candidate list.  It accepts
    only the same fully passed cap-fit debit-spread route that the paper-test
    director can expose to an operator, then hands the reconstructed item back
    to ``paper_status_for_item`` for a fresh normal paper-risk evaluation.
    It never copies an approval, weakens a gate, or turns on broker authority.
    """
    primary_plan = item.get("strikePlan") or {}
    primary_strategy = str(primary_plan.get("strategy") or "").upper()
    ticker = str(item.get("ticker") or "").upper()
    if not item.get("ok") or not ticker or not primary_strategy:
        return None

    for priced in strategy_pricing.get("items") or []:
        if not isinstance(priced, dict) or str(priced.get("ticker") or "").upper() != ticker:
            continue
        if not (
            priced.get("status") == "priced"
            and priced.get("combinedPassed")
            and priced.get("optimizerPassed")
            and priced.get("paperRiskPassed")
            and priced.get("capFitFallback")
            and priced.get("paperVariantOnly")
            and priced.get("paperOnly")
            and priced.get("liveTradingAllowed") is False
            and priced.get("brokerSubmitAllowed") is False
        ):
            continue

        plan = priced.get("strikePlan") or {}
        pricing_risk = priced.get("riskVerdict") or {}
        pricing_metrics = pricing_risk.get("metrics") or {}
        chain = pricing_metrics.get("schwabOptions") or {}
        strategy = str(plan.get("strategy") or priced.get("recommendedStrategy") or "").upper()
        max_loss = number(plan.get("estimatedMaxLoss"), -1.0)
        reward_risk = number(pricing_metrics.get("debitSpreadRewardRisk"), -1.0)
        if (
            strategy not in CAP_FIT_DEFINED_RISK_STRATEGIES
            or str(priced.get("capFitFallbackOfStrategy") or "").upper() != primary_strategy
            or not pricing_risk.get("passed")
            or not plan.get("legs")
            or max_loss <= 0
            or max_loss > MAX_SINGLE_TICKET_DOLLARS
            or reward_risk < MIN_DEBIT_SPREAD_REWARD_RISK
            or not chain.get("attached")
            or str(chain.get("sourceStatus") or "").lower() != "ok"
            or not chain.get("paperLiquidityPass")
        ):
            continue

        # Preserve the primary execution intent's approval state and only
        # replace the structure and its supporting market facts.  In
        # particular, do not inherit the pricing artifact's research-only
        # pseudo-approval; the normal paper-auto-selection rule will accept
        # only an approval-only block after re-evaluation.
        return {
            **item,
            "ticker": ticker,
            "ok": True,
            "setupRec": strategy,
            "price": priced.get("price") or item.get("price"),
            "sourcePrice": priced.get("sourcePrice") or item.get("sourcePrice") or item.get("price"),
            "daysUntilEarnings": priced.get("daysUntilEarnings") or item.get("daysUntilEarnings"),
            "marketContext": priced.get("marketContext") or item.get("marketContext") or {},
            "marketContextSummary": priced.get("marketContextSummary") or item.get("marketContextSummary") or {},
            "schwabOptions": priced.get("schwabOptions") or item.get("schwabOptions") or {},
            "paperOnly": True,
            "liveTradingAllowed": False,
            "brokerSubmitAllowed": False,
            "paperVariantOnly": True,
            "routeFamily": "cap-fit-defined-risk",
            "setupFamily": "cap-fit-defined-risk",
            "paperVariantFamily": plan.get("variantFamily") or priced.get("paperVariantFamily"),
            "paperVariantOfStrategy": priced.get("capFitFallbackOfStrategy"),
            "capFitFallback": True,
            "capFitFallbackStructure": priced.get("capFitFallbackStructure"),
            "sourceStrategyPricingGeneratedAt": priced.get("generatedAt") or strategy_pricing.get("generatedAt"),
            "strikePlan": plan,
        }
    return None


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
    from inferno_ledger_ownership import ownership
    if (item.get("requiresDelegateApproval") or ownership().get("status") == "active") and item.get("approvalStatus") != "approved":
        return False, "delegate-or-operator-approval-required"
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
    cost_type, cost = strategy_cost(strike_plan)
    status, block_reasons, risk_verdict, paper_auto_block_reason = paper_status_for_item(
        item, strike_plan_generated_at, ledger
    )
    event_id = paper_event_id({**item, "expiration": strike_plan.get("expiration")})
    arm = campaign_arm_for_ticket(item, event_id)
    friction = paper_fill_friction_model(item, entry_limit=cost, exit_rule=arm["exitRule"])
    ticket_id = planned_ticket_id(item, now.date().isoformat())

    return {
        "ticketId": ticket_id,
        **({"approvalRouteKey": item["approvalRouteKey"], "approvalToken": item.get("approvalToken"),
            "approvalCandidate": {k: v for k, v in item.items() if k != "decisionCard"}}
           if item.get("approvalRouteKey") else {}),
        "createdAt": now.isoformat(),
        "tradeDate": now.date().isoformat(),
        "sourceStrikePlanGeneratedAt": strike_plan_generated_at,
        "paperOwnership": {"host": __import__("platform").node(), "owner": "mac",
                           "budgetAckSha256": __import__("os").environ.get("INFERNO_PAPER_BUDGET_ACK_SHA256"),
                           "mode": "paper"},
        "ticker": item.get("ticker"),
        "eventId": event_id,
        **arm,
        "setupRec": item.get("setupRec"),
        "strategy": strike_plan.get("strategy"),
        "paperVariantOnly": bool(item.get("paperVariantOnly") or strike_plan.get("paperVariantOnly")),
        "paperVariantFamily": item.get("paperVariantFamily") or strike_plan.get("variantFamily"),
        "paperVariantOfStrategy": item.get("paperVariantOfStrategy") or strike_plan.get("variantForStrategy"),
        "capFitFallback": bool(item.get("capFitFallback")),
        "capFitFallbackStructure": item.get("capFitFallbackStructure"),
        "sourceStrategyPricingGeneratedAt": item.get("sourceStrategyPricingGeneratedAt"),
        "shortPremiumDefined": bool(item.get("shortPremiumDefined") or strike_plan.get("shortPremiumDefined")),
        "preRegisteredCampaign": item.get("preRegisteredCampaign") or strike_plan.get("preRegisteredCampaign"),
        "status": status,
        "blockReasons": block_reasons,
        "paperOnly": True,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
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
        "schwabOptions": paper_ledger_schwab_summary(item.get("schwabOptions")),
        "decisionCard": card,
        "expiration": strike_plan.get("expiration"),
        "entryCostType": cost_type,
        "entryLimit": round(cost, 4),
        **friction,
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
            # The same blocked construction may become staged after its own
            # approval. Never rewrite an opened, filled or closed outcome.
            index = next(i for i, old in enumerate(updated_items) if old.get("ticketId") == entry.get("ticketId"))
            old = updated_items[index]
            if (old.get("status") in {"paper-blocked", "paper-rejected"}
                    and (old.get("outcome") or {}).get("status") in {None, "not-opened"}
                    and not old.get("paperExecution")):
                updated_items[index] = {**merge_refreshed_entry(old, entry), "outcome": entry.get("outcome")}
                existing_by_key[key] = index
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


@paper_writer
def record_from_strike_plan(
    strike_plan: dict[str, Any] | None = None,
    strategy_pricing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record all tickets from a strike plan into the paper ledger.

    Passing the in-memory strike plan is safest because it prevents accidentally
    recording stale disk data after a failed selector run.
    """
    from inferno_ledger_ownership import require_paper_writer
    require_paper_writer("paper staging")
    strike_plan = strike_plan or load_strike_plan()
    ledger = load_ledger()
    strategy_pricing = strategy_pricing or load_json_file(STRATEGY_ALTERNATIVE_PRICING_FILE) or {"items": []}
    compliance = load_json_file(PROCESS_COMPLIANCE_FILE) or {}
    process_entry_allowed = compliance.get("newPaperEntriesAllowed", True)
    from inferno_ledger_ownership import ownership
    from inferno_paper_approval_routes import apply_route_approval, queue_from_entries
    from inferno_approval_queue import load_queue, save_queue
    scoped = ownership().get("status") == "active"
    approvals = load_queue() if scoped else {}
    def route(candidate):
        return apply_route_approval(candidate, approvals, strike_plan.get("generatedAt")) if scoped else candidate
    entries: list[dict[str, Any]] = []
    # A priced alternate can still supply a cap-fit variant when the primary
    # display slot was taken by an iron fly. The shadow primary stays shadow.
    candidate_sources = [(i, False) for i in strike_plan.get("items", [])]
    candidate_sources += [(i, True) for i in strike_plan.get("shadowItems", [])
                          if i.get("primaryExclusionReason") == "alternate-to-primary"]
    for item, variants_only in candidate_sources:
        guarded_item = {**route(item), "processEntryAllowed": process_entry_allowed}
        primary_entry = build_ledger_entry(
            guarded_item,
            strike_plan.get("generatedAt"),
            {"items": list(ledger.get("items", [])) + entries},
        )
        if not variants_only:
            entries.append(primary_entry)
        variant_item = rehearsal_variant_item(item)
        if variant_item:
            guarded_variant = {**route(variant_item), "processEntryAllowed": process_entry_allowed}
            entries.append(
                build_ledger_entry(
                    guarded_variant,
                    strike_plan.get("generatedAt"),
                    {"items": list(ledger.get("items", [])) + entries},
                )
            )
        cap_fit_variant = cap_fit_defined_risk_variant_item(item, strategy_pricing)
        if cap_fit_variant and primary_entry.get("status") == "paper-blocked":
            guarded_variant = {**route(cap_fit_variant), "processEntryAllowed": process_entry_allowed}
            variant_ticket_id = planned_ticket_id(guarded_variant)
            # A refresh must not reject the same already-open cap-fit ticket as
            # a duplicate of itself.  Keep every other open ticket in the
            # evaluator input so ticker, event, and daily-exposure guards stay
            # fully active.
            variant_ledger_items = [
                entry
                for entry in list(ledger.get("items", [])) + entries
                if entry.get("ticketId") != variant_ticket_id
            ]
            entries.append(
                build_ledger_entry(
                    guarded_variant,
                    cap_fit_variant.get("sourceStrategyPricingGeneratedAt") or strike_plan.get("generatedAt"),
                    {"items": variant_ledger_items},
                )
            )
    updated, inserted = merge_entries(ledger, entries)
    updated = successful_lifecycle(
        updated,
        producer="inferno-paper-execution",
        source_data_as_of=strike_plan.get("generatedAt"),
        freshness_ttl_hours=36,
        schedule="post-open strike cycle",
    )
    save_ledger(updated)
    if scoped:
        current_keys = {entry.get("approvalRouteKey") for entry in entries}
        current = [entry for entry in updated.get("items", []) if entry.get("approvalRouteKey") in current_keys]
        save_queue(queue_from_entries(current, approvals, strike_plan.get("generatedAt")))
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
        f"Created: {ledger.get('createdAt') or ledger.get('generatedAt')}",
        f"Updated: {ledger.get('updatedAt')}",
        f"Last successful: {ledger.get('lastSuccessfulAt') or ledger.get('updatedAt')}",
        f"Last attempt: {ledger.get('lastAttemptAt') or ledger.get('updatedAt')}",
        f"Source strike plan: {ledger.get('sourceDataAsOf') or '-'}",
        f"Lifecycle: {ledger.get('lifecycleStatus') or 'legacy'}",
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


@paper_writer
def save_ledger(ledger: dict[str, Any]) -> None:
    """Persist JSON and text versions of the paper execution ledger."""
    from inferno_ledger_ownership import require_paper_writer
    require_paper_writer("paper ledger write")
    ensure_dirs()
    atomic_write_json(PAPER_EXECUTION_LEDGER_FILE, ledger)
    atomic_write_text(PAPER_EXECUTION_TEXT_FILE, ledger_summary(ledger))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record paper-only option tickets from the latest Inferno strike plan.")
    parser.add_argument("command", nargs="?", default="record", choices=["record", "status"])
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Number of recent ledger rows to print.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "record":
        try:
            result = record_from_strike_plan()
        except Exception as exc:  # noqa: BLE001 - preserve evidence freshness after a failed run.
            failed = failed_lifecycle(
                load_ledger(),
                producer="inferno-paper-execution",
                error=f"{type(exc).__name__}: {exc}"[:500],
            )
            save_ledger(failed)
            print("Paper execution ledger refresh failed; prior evidence was preserved.", file=sys.stderr)
            return 1
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
