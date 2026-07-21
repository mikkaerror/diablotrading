from __future__ import annotations

"""Operator-owned role and diversification review queue for the full tracker.

Reference taxonomy tells us what a company broadly does; it cannot decide its
place in a portfolio.  This module creates the explicit review surface needed
before any diversified-DCA research can be built.  It preserves existing
operator hold declarations as context, but never converts them into an
addition approval, role, target weight, eligibility label, or purchase.
"""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


TRACKER_REGISTRY_FILE = DATA_DIR / "inferno_tracker_registry.json"
OPERATOR_LONG_TERM_HOLDS_FILE = DATA_DIR / "operator_long_term_holds.json"
TRACKER_ROLE_REVIEW_FILE = DATA_DIR / "inferno_tracker_role_review.json"
TRACKER_ROLE_REVIEW_TEXT_FILE = REPORTS_DIR / "tracker_role_review_latest.txt"

TRACKER_ROLE_REVIEW_STAGE = "full-tracker-role-review-research-only"
ROLE_REVIEW_OUTCOMES = (
    "core compounder",
    "cyclical",
    "thematic satellite",
    "speculative/research-only",
    "exclude-from-DCA-research",
)


def ticker(value: Any) -> str:
    """Normalize a symbol without deciding whether it belongs in the tracker."""
    return str(value or "").strip().upper()


def text(value: Any, default: str = "") -> str:
    """Render loose source fields without substituting a guessed value."""
    rendered = str(value or "").strip()
    return rendered or default


def number(value: Any, default: float = 0.0) -> float:
    """Safely read display-only research scores from the registry."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_operator_long_term_holds(path: Path = OPERATOR_LONG_TERM_HOLDS_FILE) -> set[str]:
    """Read operator declarations as context only; never edit their membership."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return set()
    values = payload.get("symbols") if isinstance(payload, dict) else payload
    return {ticker(value) for value in values or [] if ticker(value)} if isinstance(values, list) else set()


def review_priority(entry: dict[str, Any], *, operator_long_term_holds: set[str]) -> str:
    """Order review work without creating a funding or sizing recommendation."""
    taxonomy = entry.get("taxonomy") if isinstance(entry.get("taxonomy"), dict) else {}
    holding = entry.get("holding") if isinstance(entry.get("holding"), dict) else {}
    research = entry.get("research") if isinstance(entry.get("research"), dict) else {}
    symbol = ticker(entry.get("ticker"))
    if taxonomy.get("referenceStatus") != "reference-covered":
        return "data-quality-repair"
    if bool(holding.get("currentlyHeld")) or symbol in operator_long_term_holds:
        return "existing-hold-review"
    if bool(research.get("longTermResearchQualified")):
        return "research-evidence-review"
    return "standard-role-review"


def review_questions(entry: dict[str, Any], *, operator_long_term_holds: set[str]) -> list[str]:
    """State the minimum human decisions required, without answering them."""
    taxonomy = entry.get("taxonomy") if isinstance(entry.get("taxonomy"), dict) else {}
    holding = entry.get("holding") if isinstance(entry.get("holding"), dict) else {}
    symbol = ticker(entry.get("ticker"))
    questions: list[str] = []
    if taxonomy.get("referenceStatus") != "reference-covered":
        questions.append("Resolve verified sector and industry reference data before assigning a portfolio role.")
    if bool(holding.get("currentlyHeld")) or symbol in operator_long_term_holds:
        questions.append("Confirm existing-hold intent separately from any future DCA-addition eligibility.")
    questions.extend(
        [
            "Record an operator-approved portfolio role and source rationale.",
            "Record whether this name belongs in diversified DCA research; this does not change tracker eligibility.",
            "Set any target weight only in a separately approved policy, never in this review queue.",
        ]
    )
    return questions


def review_entry(entry: dict[str, Any], *, operator_long_term_holds: set[str]) -> dict[str, Any]:
    """Build an auditable no-decision review row from the full registry."""
    taxonomy = entry.get("taxonomy") if isinstance(entry.get("taxonomy"), dict) else {}
    holding = entry.get("holding") if isinstance(entry.get("holding"), dict) else {}
    research = entry.get("research") if isinstance(entry.get("research"), dict) else {}
    symbol = ticker(entry.get("ticker"))
    declared_hold = symbol in operator_long_term_holds
    return {
        "ticker": symbol,
        "companyName": text(taxonomy.get("companyName"), symbol),
        "reviewPriority": review_priority(entry, operator_long_term_holds=operator_long_term_holds),
        "reference": {
            "status": text(taxonomy.get("referenceStatus"), "reference-missing"),
            "fresh": bool(taxonomy.get("referenceFresh")),
            "sector": text(taxonomy.get("sector"), "Unknown"),
            "industry": text(taxonomy.get("industry"), "Unknown"),
            "economicExposure": text(taxonomy.get("economicExposure"), "Unclassified"),
            "source": text(taxonomy.get("taxonomySource"), "no-reference-taxonomy-yet"),
        },
        "existingContext": {
            "currentlyHeld": bool(holding.get("currentlyHeld")),
            "operatorDeclaredLongTermHold": declared_hold,
            "existingEligibility": text(entry.get("existingEligibility"), "unknown"),
        },
        "researchContext": {
            "rank": research.get("rank"),
            "longTermResearchQualified": bool(research.get("longTermResearchQualified")),
            "longTermConvictionScore": number(research.get("longTermConvictionScore")),
            "evidenceGrade": text(research.get("evidenceGrade"), "unknown"),
            "themeCategory": text(taxonomy.get("category"), "Unclassified"),
        },
        "operatorDecision": {
            "portfolioRole": "not-recorded",
            "dcaResearchInclusion": "not-recorded",
            "targetWeight": "not-defined",
            "decisionSource": "operator-required",
            "allowedRoleOutcomes": list(ROLE_REVIEW_OUTCOMES),
        },
        "reviewQuestions": review_questions(entry, operator_long_term_holds=operator_long_term_holds),
    }


def review_sort_key(entry: dict[str, Any]) -> tuple[int, int, str]:
    """Keep manual review deterministic and clearly separate from a buy ranking."""
    priority = {
        "data-quality-repair": 0,
        "existing-hold-review": 1,
        "research-evidence-review": 2,
        "standard-role-review": 3,
    }
    rank = entry.get("researchContext", {}).get("rank")
    return priority.get(entry.get("reviewPriority"), 9), int(rank) if isinstance(rank, int) else 10**9, entry["ticker"]


def build_tracker_role_review(
    *,
    registry: dict[str, Any] | None = None,
    operator_long_term_holds: set[str] | None = None,
) -> dict[str, Any]:
    """Build the full review queue while keeping every policy decision human-owned."""
    registry = registry if registry is not None else (load_json_file(TRACKER_REGISTRY_FILE) or {})
    operator_long_term_holds = (
        operator_long_term_holds if operator_long_term_holds is not None else load_operator_long_term_holds()
    )
    registry_entries = [entry for entry in registry.get("entries") or [] if isinstance(entry, dict) and ticker(entry.get("ticker"))]
    entries = [review_entry(entry, operator_long_term_holds=operator_long_term_holds) for entry in registry_entries]
    entries.sort(key=review_sort_key)

    priority_counts = Counter(entry["reviewPriority"] for entry in entries)
    exposure_counts = Counter(
        entry["reference"]["economicExposure"]
        for entry in entries
        if entry["reference"]["status"] == "reference-covered"
    )
    held = [entry for entry in entries if entry["existingContext"]["currentlyHeld"]]
    declared = [entry for entry in entries if entry["existingContext"]["operatorDeclaredLongTermHold"]]
    reference_missing = [entry for entry in entries if entry["reference"]["status"] != "reference-covered"]
    reference_stale = [entry for entry in entries if entry["reference"]["status"] == "reference-covered" and not entry["reference"]["fresh"]]
    research_qualified = [entry for entry in entries if entry["researchContext"]["longTermResearchQualified"]]
    holdings_unmatched = [entry for entry in held if entry["ticker"] not in {ticker(row.get("ticker")) for row in registry_entries}]

    return {
        "generatedAt": local_now().isoformat(),
        "stage": TRACKER_ROLE_REVIEW_STAGE,
        "verdict": "operator-role-review-required",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "purpose": "Operator-owned full-tracker portfolio-role and diversification review queue before DCA construction research.",
        "authorityBoundary": {
            "trackerMembershipChanged": False,
            "eligibilityChanged": False,
            "riskConstantsChanged": False,
            "operatorPolicyChanged": False,
            "portfolioRolesProduced": False,
            "dcaResearchInclusionProduced": False,
            "targetWeightsProduced": False,
            "brokerActionProduced": False,
        },
        "coverage": {
            "trackedRows": len(entries),
            "referenceCoveredRows": len(entries) - len(reference_missing),
            "referenceMissingRows": len(reference_missing),
            "staleReferenceRows": len(reference_stale),
            "currentlyHeldRows": len(held),
            "operatorDeclaredLongTermHoldRows": len(declared),
            "longTermResearchQualifiedRows": len(research_qualified),
            "portfolioRoleDefinedRows": 0,
            "dcaResearchInclusionDefinedRows": 0,
            "targetWeightDefinedRows": 0,
            "rowsRequiringOperatorRoleDecision": len(entries),
            "holdingsUnmatchedToTracker": [entry["ticker"] for entry in holdings_unmatched],
            "byReviewPriority": dict(sorted(priority_counts.items())),
            "byEconomicExposure": dict(sorted(exposure_counts.items())),
        },
        "existingOperatorDeclarations": {
            "longTermHoldSymbols": sorted(entry["ticker"] for entry in declared),
            "meaning": "Existing-hold context only; it does not approve additions, roles, DCA inclusion, or target weights.",
        },
        "reviewQueue": entries,
        "nextBuildGate": {
            "readyForDcaWeightResearch": False,
            "requirements": [
                "Resolve missing or stale source reference data without guessing.",
                "Record an operator-approved portfolio role for each name considered in diversified DCA research.",
                "Record DCA-research inclusion separately from existing tracker eligibility and existing holdings.",
                "Approve any target-weight policy in a separate human-owned source before generating allocation research.",
            ],
        },
        "citations": [
            "data/inferno_tracker_registry.json",
            "data/inferno_tracker_taxonomy.json",
            "data/operator_long_term_holds.json",
            "docs/FULL_TRACKER_DCA_OPERATING_PLAN.md",
            "docs/CAPITAL_FLOW_POLICY.md",
        ],
    }


def tracker_role_review_text(payload: dict[str, Any]) -> str:
    """Render the decision queue without presenting any allocation instruction."""
    coverage = payload.get("coverage") or {}
    declarations = payload.get("existingOperatorDeclarations") or {}
    lines = [
        "Inferno Full-Tracker Role Review (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Tracker: {coverage.get('trackedRows', 0)} rows | reference {coverage.get('referenceCoveredRows', 0)} covered | {coverage.get('referenceMissingRows', 0)} missing | {coverage.get('staleReferenceRows', 0)} stale",
        f"Operator decisions: {coverage.get('portfolioRoleDefinedRows', 0)} roles | {coverage.get('dcaResearchInclusionDefinedRows', 0)} DCA-inclusion decisions | {coverage.get('targetWeightDefinedRows', 0)} target weights",
        f"Existing context: {coverage.get('currentlyHeldRows', 0)} holdings | {coverage.get('operatorDeclaredLongTermHoldRows', 0)} declared long-term holds | {coverage.get('longTermResearchQualifiedRows', 0)} research-qualified",
        f"Declared long-term holds: {', '.join(declarations.get('longTermHoldSymbols') or []) or 'none'}",
        "",
        "Review work by priority",
    ]
    for label, count in (coverage.get("byReviewPriority") or {}).items():
        lines.append(f"- {label}: {count}")
    lines.extend(["", "First review items (not a ranking or buy list)"])
    for entry in (payload.get("reviewQueue") or [])[:12]:
        reference = entry.get("reference") or {}
        context = entry.get("existingContext") or {}
        lines.append(
            f"- {entry.get('ticker')} | {entry.get('reviewPriority')} | {reference.get('economicExposure')} | "
            f"held={context.get('currentlyHeld')} | declared-hold={context.get('operatorDeclaredLongTermHold')}"
        )
    lines.extend(["", "DCA weights gate"])
    for requirement in (payload.get("nextBuildGate") or {}).get("requirements") or []:
        lines.append(f"- {requirement}")
    lines.extend(
        [
            "",
            "This queue does not assign portfolio roles, DCA inclusion, target weights, purchases, or eligibility.",
            "Existing long-term-hold declarations are context only. Broker submission and live trading remain disabled.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def save_tracker_role_review(payload: dict[str, Any]) -> None:
    """Persist the derived review artifact without touching any operator policy source."""
    ensure_dirs()
    atomic_write_json(TRACKER_ROLE_REVIEW_FILE, payload)
    atomic_write_text(TRACKER_ROLE_REVIEW_TEXT_FILE, tracker_role_review_text(payload))


def parse_args() -> argparse.Namespace:
    """Expose a small run/status surface for the operator control plane."""
    parser = argparse.ArgumentParser(description="Build the full-tracker operator role review queue.")
    parser.add_argument("action", nargs="?", choices=("run", "status"), default="run")
    return parser.parse_args()


def main() -> int:
    """Build or display the research-only role review queue."""
    args = parse_args()
    if args.action == "status":
        payload = load_json_file(TRACKER_ROLE_REVIEW_FILE) or build_tracker_role_review()
    else:
        payload = build_tracker_role_review()
        save_tracker_role_review(payload)
    print(tracker_role_review_text(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
