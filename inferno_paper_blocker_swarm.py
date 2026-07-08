from __future__ import annotations

"""Research-only blocker swarm for the Inferno paper-test lane.

The swarm applies the agent-swarm pattern to diagnostics, not trading:
independent lanes classify the same blocked paper candidates, then a small
orchestrator aggregates lane verdicts into safe next research actions.

It never approves tickets, changes risk policy, mutates the universe, stages
orders, or submits to a broker.
"""

import argparse
import json
from collections import Counter
from datetime import datetime
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


PAPER_DIRECTOR_FILE = DATA_DIR / "inferno_paper_test_director.json"
UNIVERSE_CAP_FIT_FILE = DATA_DIR / "inferno_universe_cap_fit.json"
EXPECTED_MOVE_FILE = DATA_DIR / "inferno_expected_move_ledger.json"
STRATEGY_ALTERNATIVE_SCORER_FILE = DATA_DIR / "inferno_strategy_alternative_scorer.json"
STRATEGY_ALTERNATIVE_PRICING_FILE = DATA_DIR / "inferno_strategy_alternative_pricing.json"
STRATEGY_SHADOW_COMPARISON_FILE = DATA_DIR / "inferno_strategy_shadow_comparison.json"

PAPER_BLOCKER_SWARM_FILE = DATA_DIR / "inferno_paper_blocker_swarm.json"
PAPER_BLOCKER_SWARM_TEXT_FILE = REPORTS_DIR / "paper_blocker_swarm_latest.txt"

STAGE = "paper-blocker-swarm-research-only"

LANES: tuple[dict[str, str], ...] = (
    {
        "id": "operator_action",
        "label": "Operator action",
        "purpose": "Separate human approval from research/tooling blockers.",
    },
    {
        "id": "data_freshness",
        "label": "Data freshness",
        "purpose": "Detect stale or divergent source/Schwab prices.",
    },
    {
        "id": "liquidity",
        "label": "Liquidity",
        "purpose": "Detect poor quote quality, thin ATM liquidity, or no liquid contracts.",
    },
    {
        "id": "strike_construction",
        "label": "Strike construction",
        "purpose": "Detect unsupported strategy or strike-plan construction failures.",
    },
    {
        "id": "premium_hurdle",
        "label": "Premium/evidence hurdle",
        "purpose": "Detect incomplete decision cards, premium hurdles, and greek/risk gaps.",
    },
    {
        "id": "capital_fit",
        "label": "Capital fit",
        "purpose": "Detect whether the blocker is current cap fit rather than construction quality.",
    },
    {
        "id": "alternative_structure",
        "label": "Alternative structure",
        "purpose": "Look for bounded-risk fallback structures without changing risk policy.",
    },
    {
        "id": "concentration_process",
        "label": "Concentration/process",
        "purpose": "Detect concentration or process warnings that should fail closed.",
    },
)

LANE_PRIORITY = {
    "data_freshness": 0,
    "strike_construction": 1,
    "liquidity": 2,
    "premium_hurdle": 3,
    "alternative_structure": 4,
    "capital_fit": 5,
    "concentration_process": 6,
    "operator_action": 7,
}


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def _dedupe(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def _load(path: Any) -> dict[str, Any]:
    return load_json_file(path) or {}


def candidate_key(candidate: dict[str, Any]) -> str:
    ticker = _ticker(candidate.get("ticker"))
    category = str(candidate.get("category") or "")
    strategy = str(candidate.get("strategy") or candidate.get("setupRec") or "")
    return f"{ticker}|{category}|{strategy}"


def blocked_candidates(director: dict[str, Any]) -> list[dict[str, Any]]:
    """Return candidates that need blocker diagnosis, preserving director order."""
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for slate in ("hardBlockedSlate", "approvalSlate", "researchWatchlist", "capitalNearMissSlate"):
        for candidate in director.get(slate) or []:
            if not isinstance(candidate, dict):
                continue
            key = candidate_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            candidates.append({**candidate, "sourceSlate": slate})
    return candidates


def reason_lanes(candidate: dict[str, Any]) -> dict[str, list[str]]:
    """Classify candidate reasons into independent diagnostic lanes."""
    reasons = _dedupe(
        list(candidate.get("reasons") or [])
        + list(candidate.get("warnings") or [])
        + list((candidate.get("decisionCard") or {}).get("disconfirmingEvidence") or [])
    )
    by_lane: dict[str, list[str]] = {lane["id"]: [] for lane in LANES}
    unknown: list[str] = []
    for reason in reasons:
        raw = _normalize(reason)
        matched = False
        if "human approval" in raw or "approval missing" in raw or "approval still required" in raw:
            by_lane["operator_action"].append(reason)
            matched = True
        if (
            "source price" in raw
            or "diverge" in raw
            or "refresh tracker" in raw
            or "stale" in raw
            or "underlying" in raw
        ):
            by_lane["data_freshness"].append(reason)
            matched = True
        if (
            "liquidity" in raw
            or "no-liquid" in raw
            or "quote quality" in raw
            or "spread" in raw
            or "thin" in raw
            or "open interest" in raw
        ):
            by_lane["liquidity"].append(reason)
            matched = True
        if (
            "no supported strike plan" in raw
            or "failed construction" in raw
            or "construction" in raw
            or "strike plan" in raw
            or "no supported" in raw
        ):
            by_lane["strike_construction"].append(reason)
            matched = True
        if (
            "premium" in raw
            or "maximum-loss" in raw
            or "net-greeks" in raw
            or "long-vol" in raw
            or "decision card incomplete" in raw
            or "expected move" in raw
            or "reward/risk" in raw
        ):
            by_lane["premium_hurdle"].append(reason)
            matched = True
        if (
            "max loss $" in raw
            or "daily max loss" in raw
            or "above $" in raw
            or "size cap" in raw
            or "capital gap" in raw
        ):
            by_lane["capital_fit"].append(reason)
            matched = True
        if "concentration" in raw or "sector" in raw or "theme" in raw:
            by_lane["concentration_process"].append(reason)
            matched = True
        if not matched:
            unknown.append(reason)

    if candidate.get("category") == "failed-construction":
        by_lane["strike_construction"].append("candidate category is failed-construction")
    if unknown:
        by_lane.setdefault("unknown", []).extend(unknown)
    return {lane_id: _dedupe(values) for lane_id, values in by_lane.items()}


def cap_fit_index(cap_fit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in cap_fit.get("perTicker") or []:
        if not isinstance(row, dict):
            continue
        ticker = _ticker(row.get("ticker"))
        if ticker:
            index[ticker] = row
    return index


def bounded_fit_structures(cap_row: dict[str, Any] | None) -> list[str]:
    if not cap_row:
        return []
    fits = cap_row.get("fits") or {}
    return [
        label
        for key, label in (
            ("debit_5w", "5-wide debit spread"),
            ("credit_1w", "1-wide credit spread"),
            ("long_leg", "single long leg"),
        )
        if bool(fits.get(key))
    ]


def alternative_context(
    scorer: dict[str, Any],
    pricing: dict[str, Any],
    shadow: dict[str, Any],
    expected_move: dict[str, Any],
) -> dict[str, Any]:
    return {
        "scorerVerdict": scorer.get("verdict"),
        "scorerCounts": scorer.get("counts") or {},
        "pricingVerdict": pricing.get("verdict"),
        "pricingCounts": pricing.get("counts") or {},
        "shadowVerdict": shadow.get("verdict"),
        "shadowCounts": shadow.get("counts") or {},
        "expectedMoveVerdict": expected_move.get("verdict"),
        "expectedMoveCounts": expected_move.get("counts") or {},
    }


def classify_candidate(
    candidate: dict[str, Any],
    *,
    cap_index: dict[str, dict[str, Any]],
    alt_context: dict[str, Any],
) -> dict[str, Any]:
    ticker = _ticker(candidate.get("ticker"))
    lanes = reason_lanes(candidate)
    cap_row = cap_index.get(ticker)
    bounded_fits = bounded_fit_structures(cap_row)
    has_structure_pressure = bool(
        lanes.get("strike_construction") or lanes.get("premium_hurdle")
    )
    has_data_or_liquidity_pressure = bool(
        lanes.get("data_freshness") or lanes.get("liquidity")
    )
    fallback_suggested = bool(bounded_fits and (has_structure_pressure or has_data_or_liquidity_pressure))
    operator_only = bool(lanes.get("operator_action")) and not any(
        lanes.get(lane_id)
        for lane_id in (
            "data_freshness",
            "liquidity",
            "strike_construction",
            "premium_hurdle",
            "capital_fit",
            "concentration_process",
        )
    )

    lane_findings: list[dict[str, Any]] = []
    for lane in LANES:
        lane_id = lane["id"]
        evidence = list(lanes.get(lane_id) or [])
        status = "clear"
        next_step = "No blocker detected in this lane."
        if lane_id == "alternative_structure":
            if fallback_suggested:
                status = "research-route"
                next_step = (
                    "Audit bounded-risk fallback structures that already fit the current cap; "
                    "do not change risk constants or the eligible universe."
                )
                evidence = [
                    f"cap-fit alternatives for {ticker}: {', '.join(bounded_fits)}",
                    f"alternative scorer={alt_context.get('scorerVerdict')}",
                    f"alternative pricing={alt_context.get('pricingVerdict')}",
                    f"shadow comparison={alt_context.get('shadowVerdict')}",
                ]
            elif bounded_fits:
                status = "available"
                next_step = "Fallback structures fit cap, but current blockers do not require rerouting yet."
                evidence = [f"cap-fit alternatives for {ticker}: {', '.join(bounded_fits)}"]
            else:
                status = "blocked"
                next_step = "No bounded cap-fit fallback was found for this ticker."
                evidence = ["no bounded fallback structure fit the current cap"]
        elif evidence:
            if lane_id == "operator_action":
                if operator_only:
                    status = "blocked"
                    next_step = "Leave approval with the operator; unattended code cannot approve or reject."
                else:
                    status = "context"
                    next_step = (
                        "Approval remains operator-owned, but it is not the current research blocker; "
                        "resolve the non-approval lanes first."
                    )
            elif lane_id == "data_freshness":
                status = "blocked"
                next_step = "Refresh tracker, execution queue, and Schwab option-chain truth before regrading."
            elif lane_id == "liquidity":
                status = "blocked"
                next_step = "Do not stage poor quote quality; wait for liquid contracts or record market-quality block."
            elif lane_id == "strike_construction":
                status = "blocked"
                next_step = "Rebuild strike plan only after source data is clean; otherwise route to bounded fallback audit."
            elif lane_id == "premium_hurdle":
                status = "blocked"
                next_step = "Keep shadow-only until premium, max-loss, and net-greeks evidence clears the decision card."
            elif lane_id == "capital_fit":
                status = "blocked"
                next_step = "Respect the current cap; only bounded structures that already fit may be researched."
            elif lane_id == "concentration_process":
                status = "blocked"
                next_step = "Fail closed until concentration or process warnings clear."

        lane_findings.append(
            {
                "lane": lane_id,
                "label": lane["label"],
                "status": status,
                "completed": True,
                "evidence": evidence,
                "nextStep": next_step,
            }
        )

    active_lanes = [
        finding["lane"]
        for finding in lane_findings
        if finding.get("status") in {"blocked", "research-route"}
    ]
    non_operator_active = [
        lane_id for lane_id in active_lanes if lane_id != "operator_action"
    ]
    refreshable_data = bool(lanes.get("data_freshness"))
    tooling_fixable = bool(refreshable_data or fallback_suggested)
    market_quality_blocked = bool(lanes.get("liquidity") or lanes.get("premium_hurdle"))
    if operator_only:
        fixability = "operator-action"
        dominant = "operator_action"
        next_action = "Wait for operator approval decision; no unattended action is allowed."
    elif refreshable_data:
        fixability = "data-refresh"
        dominant = "data_freshness"
        next_action = "Refresh divergent source/Schwab data, then rebuild strike and paper director artifacts."
    elif fallback_suggested:
        fixability = "research-tooling"
        dominant = "alternative_structure"
        next_action = "Run a bounded fallback audit for cap-fitting alternatives after data quality is clean."
    elif market_quality_blocked:
        fixability = "market-quality"
        dominant = "liquidity" if lanes.get("liquidity") else "premium_hurdle"
        next_action = "Do not stage; keep as market-quality or premium-edge blocker."
    elif lanes.get("strike_construction"):
        fixability = "structure-construction"
        dominant = "strike_construction"
        next_action = "Do not stage; construction failed under the current strategy."
    elif lanes.get("capital_fit"):
        fixability = "capital-fit"
        dominant = "capital_fit"
        next_action = "Do not widen the cap; research only structures that already fit."
    elif non_operator_active:
        dominant = sorted(non_operator_active, key=lambda item: LANE_PRIORITY.get(item, 99))[0]
        fixability = "not-fixable-now"
        next_action = "Record blocker and wait for a measurable state change."
    else:
        dominant = "clear"
        fixability = "clear"
        next_action = "No active blocker was detected by the swarm."

    return {
        "ticker": ticker,
        "sourceSlate": candidate.get("sourceSlate"),
        "category": candidate.get("category"),
        "strategy": candidate.get("strategy") or candidate.get("setupRec"),
        "readiness": candidate.get("readiness"),
        "priorityScore": candidate.get("priorityScore"),
        "estimatedMaxLoss": candidate.get("estimatedMaxLoss"),
        "reasons": _dedupe(candidate.get("reasons") or []),
        "warnings": _dedupe(candidate.get("warnings") or []),
        "laneFindings": lane_findings,
        "activeLanes": active_lanes,
        "dominantLane": dominant,
        "fixability": fixability,
        "toolingFixable": tooling_fixable,
        "operatorApprovalMentioned": bool(lanes.get("operator_action")),
        "operatorActionRequired": operator_only,
        "marketDataBlocked": refreshable_data,
        "marketQualityBlocked": market_quality_blocked,
        "strategyFallbackSuggested": fallback_suggested,
        "capFit": {
            "verdict": (cap_row or {}).get("verdict"),
            "boundedFits": bounded_fits,
            "fits": (cap_row or {}).get("fits") or {},
            "structures": (cap_row or {}).get("structures") or {},
        },
        "nextResearchAction": next_action,
    }


def lane_summaries(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for lane in LANES:
        lane_id = lane["id"]
        affected = [
            finding
            for finding in findings
            if any(item.get("lane") == lane_id and item.get("status") in {"blocked", "research-route"} for item in finding.get("laneFindings") or [])
        ]
        route_count = sum(
            1
            for finding in findings
            for item in finding.get("laneFindings") or []
            if item.get("lane") == lane_id and item.get("status") == "research-route"
        )
        if route_count:
            verdict = "research-route"
        elif affected:
            verdict = "active-blocker"
        elif findings:
            verdict = "clear"
        else:
            verdict = "not-applicable"
        summaries.append(
            {
                "lane": lane_id,
                "label": lane["label"],
                "purpose": lane["purpose"],
                "verdict": verdict,
                "affectedCandidates": len(affected),
                "examples": [item.get("ticker") for item in affected[:5]],
                "completed": True,
            }
        )
    return summaries


def blocker_counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for finding in findings:
        for lane_id in finding.get("activeLanes") or []:
            counts[lane_id] += 1
    return dict(counts)


def dominant_lane(counts: dict[str, int]) -> str | None:
    if not counts:
        return None
    return sorted(
        counts.items(),
        key=lambda item: (-item[1], LANE_PRIORITY.get(item[0], 99), item[0]),
    )[0][0]


def verdict_for(findings: list[dict[str, Any]], counts: dict[str, int]) -> str:
    if not findings:
        return "no-blocked-candidates"
    if any(item.get("toolingFixable") for item in findings):
        return "fixable-blockers-present"
    if all(item.get("fixability") == "operator-action" for item in findings):
        return "operator-action-required"
    if counts.get("data_freshness"):
        return "market-data-blocked"
    if counts.get("liquidity") or counts.get("premium_hurdle"):
        return "market-quality-blocked"
    if counts.get("strike_construction"):
        return "structure-blocked"
    return "no-tooling-fix"


def build_swarm(
    *,
    paper_director: dict[str, Any] | None = None,
    universe_cap_fit: dict[str, Any] | None = None,
    expected_move: dict[str, Any] | None = None,
    alternative_scorer: dict[str, Any] | None = None,
    alternative_pricing: dict[str, Any] | None = None,
    shadow_comparison: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the paper blocker swarm artifact."""
    director = paper_director if paper_director is not None else _load(PAPER_DIRECTOR_FILE)
    cap_fit = universe_cap_fit if universe_cap_fit is not None else _load(UNIVERSE_CAP_FIT_FILE)
    expected = expected_move if expected_move is not None else _load(EXPECTED_MOVE_FILE)
    scorer = alternative_scorer if alternative_scorer is not None else _load(STRATEGY_ALTERNATIVE_SCORER_FILE)
    pricing = alternative_pricing if alternative_pricing is not None else _load(STRATEGY_ALTERNATIVE_PRICING_FILE)
    shadow = shadow_comparison if shadow_comparison is not None else _load(STRATEGY_SHADOW_COMPARISON_FILE)
    generated = now or local_now()

    cap_index = cap_fit_index(cap_fit)
    alt_ctx = alternative_context(scorer, pricing, shadow, expected)
    candidates = blocked_candidates(director)
    findings = [
        classify_candidate(candidate, cap_index=cap_index, alt_context=alt_ctx)
        for candidate in candidates
    ]
    summaries = lane_summaries(findings)
    lane_counts = blocker_counts(findings)
    assigned_subtasks = len(findings) * len(LANES)
    completed_subtasks = sum(
        1
        for finding in findings
        for item in finding.get("laneFindings") or []
        if item.get("completed") is True
    )
    completed_lanes = sum(1 for item in summaries if item.get("completed") is True)
    finish_reward = 1.0 if assigned_subtasks == 0 else round(completed_subtasks / assigned_subtasks, 4)
    coverage_reward = round(completed_lanes / len(LANES), 4)
    outcome_reward = 0.0

    counts = {
        "totalCandidates": (director.get("counts") or {}).get("totalCandidates", 0),
        "blockedCandidatesAnalyzed": len(findings),
        "hardBlocked": (director.get("counts") or {}).get("hardBlocked", 0),
        "stageableNow": (director.get("counts") or {}).get("stageableNow", 0),
        "autoPaperSelected": (director.get("counts") or {}).get("autoPaperSelected", 0),
        "approvalOnly": (director.get("counts") or {}).get("approvalOnly", 0),
        "operatorApprovalMentioned": sum(1 for item in findings if item.get("operatorApprovalMentioned")),
        "operatorActionRequired": sum(1 for item in findings if item.get("operatorActionRequired")),
        "marketDataBlocked": sum(1 for item in findings if item.get("marketDataBlocked")),
        "marketQualityBlocked": sum(1 for item in findings if item.get("marketQualityBlocked")),
        "fixableByTooling": sum(1 for item in findings if item.get("toolingFixable")),
        "strategyFallbackSuggested": sum(1 for item in findings if item.get("strategyFallbackSuggested")),
        "noToolingFix": sum(1 for item in findings if item.get("fixability") in {"market-quality", "structure-construction", "capital-fit", "not-fixable-now"}),
        "assignedSubtasks": assigned_subtasks,
        "completedSubtasks": completed_subtasks,
        "laneCount": len(LANES),
        "completedLanes": completed_lanes,
    }
    verdict = verdict_for(findings, lane_counts)
    dominant = dominant_lane(lane_counts)

    next_actions: list[str] = []
    if not findings:
        next_actions.append("No blocked paper candidates need swarm diagnosis right now.")
    if counts["marketDataBlocked"]:
        next_actions.append("Refresh tracker/execution queue and Schwab option-chain truth, then rerun strike cycle and paper director.")
    if counts["strategyFallbackSuggested"]:
        tickers = sorted(
            item.get("ticker") for item in findings if item.get("strategyFallbackSuggested")
        )
        next_actions.append(
            "Research-only fallback audit: evaluate current-cap bounded alternatives for "
            + ", ".join(tickers)
            + "; do not change risk constants or the eligible universe."
        )
    if counts["marketQualityBlocked"]:
        next_actions.append("Keep poor quote-quality names out of paper staging; record liquidity/premium blockers until market data improves.")
    if counts["operatorActionRequired"]:
        next_actions.append("Leave all approvals with the operator; this report cannot approve, reject, close, or promote tickets.")
    next_actions.append("Outcome reward remains zero until the fixed evaluator sees a verified candidate, blocker reduction, or scored evidence delta.")

    return {
        "generatedAt": generated.isoformat(),
        "stage": STAGE,
        "verdict": verdict,
        "researchOnly": True,
        "diagnosticOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "authorityLevel": director.get("authorityLevel"),
        "sourcePaperDirectorVerdict": director.get("verdict"),
        "sourcePaperDirectorGeneratedAt": director.get("generatedAt"),
        "sourceCapFitVerdict": cap_fit.get("verdict"),
        "sourceCapFitGeneratedAt": cap_fit.get("generatedAt"),
        "alternativeContext": alt_ctx,
        "counts": counts,
        "blockerCounts": lane_counts,
        "dominantLane": dominant,
        "lanes": summaries,
        "candidateFindings": findings,
        "rewards": {
            "coverageReward": coverage_reward,
            "finishReward": finish_reward,
            "outcomeReward": outcome_reward,
            "acceptedOutcome": False,
            "notes": [
                "coverage rewards lane decomposition only",
                "finish rewards completed lane verdicts only",
                "outcome reward stays zero until an external fixed evaluator records real evidence progress",
            ],
        },
        "nextActions": next_actions,
        "citations": [
            "Kimi K2.5 Agent Swarm / PARL: dynamic decomposition, subagent instantiation, finish reward, outcome reward",
            "0xCodez loop engineering roadmap: state files, verifiers, hard stops, human gate before irreversible action",
            "Sai Rahul agentic engineering concepts: router/specialist, map-reduce, state, tracing, metrics, permissions",
        ],
        "reminders": [
            "research-only; not approval, staging, promotion, or broker authority",
            "do not change risk constants or eligible universe from this artifact",
            "human approval remains an operator decision",
        ],
    }


def render_text(payload: dict[str, Any]) -> str:
    counts = payload.get("counts") or {}
    rewards = payload.get("rewards") or {}
    if counts.get("operatorActionRequired", 0):
        approval_context_line = f"- operator approval required: {counts.get('operatorApprovalMentioned', 0)}"
    else:
        approval_context_line = (
            f"- approval text present on non-actionable blockers: {counts.get('operatorApprovalMentioned', 0)}"
        )
    lines = [
        "Inferno Paper Blocker Swarm",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Authority: {payload.get('authorityLevel')}",
        "Contract: research-only; broker submit OFF; live trading OFF",
        "",
        "Reward model:",
        f"- coverage reward: {rewards.get('coverageReward')}",
        f"- finish reward: {rewards.get('finishReward')}",
        f"- outcome reward: {rewards.get('outcomeReward')} (fixed evaluator owns accepted progress)",
        "",
        "Counts:",
        f"- total director candidates: {counts.get('totalCandidates', 0)}",
        f"- blocked candidates analyzed: {counts.get('blockedCandidatesAnalyzed', 0)}",
        f"- hard blocked: {counts.get('hardBlocked', 0)}",
        f"- fixable by tooling/research: {counts.get('fixableByTooling', 0)}",
        approval_context_line,
        f"- operator action required: {counts.get('operatorActionRequired', 0)}",
        f"- market data blocked: {counts.get('marketDataBlocked', 0)}",
        f"- market quality blocked: {counts.get('marketQualityBlocked', 0)}",
        f"- fallback audits suggested: {counts.get('strategyFallbackSuggested', 0)}",
        f"- assigned/completed lane subtasks: {counts.get('assignedSubtasks', 0)}/{counts.get('completedSubtasks', 0)}",
        f"- dominant lane: {payload.get('dominantLane') or 'none'}",
        "",
        "Lane summaries:",
    ]
    for lane in payload.get("lanes") or []:
        examples = ", ".join(str(item) for item in lane.get("examples") or []) or "none"
        lines.append(
            f"- {lane.get('lane')}: {lane.get('verdict')} | affected {lane.get('affectedCandidates', 0)} | examples {examples}"
        )

    lines.extend(["", "Candidate findings:"])
    findings = payload.get("candidateFindings") or []
    if not findings:
        lines.append("- none")
    for finding in findings:
        lanes = ", ".join(finding.get("activeLanes") or []) or "none"
        lines.append(
            f"- {finding.get('ticker')} | {finding.get('strategy')} | "
            f"{finding.get('fixability')} | lanes {lanes}"
        )
        lines.append(f"  next: {finding.get('nextResearchAction')}")
        bounded = ((finding.get("capFit") or {}).get("boundedFits") or [])
        if bounded:
            lines.append(f"  cap-fit bounded alternatives: {', '.join(bounded)}")

    lines.extend(["", "Next actions:"])
    for action in payload.get("nextActions") or []:
        lines.append(f"- {action}")

    lines.extend(["", "Reminders:"])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_swarm(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if payload is None:
        payload = build_swarm()
    ensure_dirs()
    atomic_write_json(PAPER_BLOCKER_SWARM_FILE, payload)
    atomic_write_text(PAPER_BLOCKER_SWARM_TEXT_FILE, render_text(payload))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Inferno paper blocker swarm report.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "build", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        if PAPER_BLOCKER_SWARM_TEXT_FILE.exists():
            print(PAPER_BLOCKER_SWARM_TEXT_FILE.read_text(encoding="utf-8"), end="")
            return 0
        print("(no cached paper blocker swarm report)")
        return 1
    payload = save_swarm()
    print(render_text(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
