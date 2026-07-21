from __future__ import annotations

"""Research-only full-tracker registry for portfolio-construction work.

The tracker is the operator-maintained research universe.  This module makes
that full universe inspectable as a portfolio-construction input without
silently turning a research rank into a buy list.  It joins four distinct
facts, which must never be conflated:

* tracker membership and existing eligibility labels;
* conviction research and its evidence grade;
* existing category labels and their broad economic exposure;
* read-only broker holdings.

The result deliberately reports missing taxonomy instead of inventing it.
It never changes tracker membership, risk constants, capital sleeves, paper
tickets, approvals, broker authority, or broker positions.
"""

import argparse
from collections import Counter
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


TRACKER_SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
CONVICTION_RESEARCH_FILE = DATA_DIR / "inferno_conviction_research.json"
LIVE_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_live_account_sync.json"
SCHWAB_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_schwab_account_sync.json"
TRACKER_TAXONOMY_FILE = DATA_DIR / "inferno_tracker_taxonomy.json"
TRACKER_REGISTRY_FILE = DATA_DIR / "inferno_tracker_registry.json"
TRACKER_REGISTRY_TEXT_FILE = REPORTS_DIR / "tracker_registry_latest.txt"

TRACKER_REGISTRY_STAGE = "full-tracker-registry-research-only"

# These are broad economic exposures derived only from category labels already
# emitted by conviction research.  They are not GICS classifications and do
# not add a ticker to, or remove one from, the operator's universe.
ECONOMIC_EXPOSURE_BY_CATEGORY = {
    "AI/Data Center Giant": "AI platform and data-center demand",
    "AI/Compute Picks": "AI compute and semiconductors",
    "Semiconductor Supply Chain": "semiconductor equipment and supply chain",
    "Cloud/Data Rails": "cloud software and data infrastructure",
    "Data Center Power/Cooling": "digital infrastructure power and cooling",
    "AI Server OEM": "servers and enterprise hardware",
    "AI Networking Silicon": "networking and connectivity semiconductors",
    "Optical/Data Center Materials": "optical networking and components",
    "Semi Test Equipment": "semiconductor test equipment",
    "Data Center Operator": "data-center operations",
}


def ticker(value: Any) -> str:
    """Normalize a ticker without making a judgement about eligibility."""
    return str(value or "").strip().upper()


def number(value: Any, default: float = 0.0) -> float:
    """Safely coerce a loose numeric value for display-only broker fields."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def snapshot_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Return usable tracker rows from the source snapshot."""
    rows = snapshot.get("rows") if isinstance(snapshot, dict) else []
    return [row for row in rows or [] if isinstance(row, dict) and ticker(row.get("ticker"))]


def indexed_rows(rows: list[dict[str, Any]], key: str = "ticker") -> dict[str, dict[str, Any]]:
    """Index row-like payloads by ticker, retaining the first source record."""
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = ticker(row.get(key))
        if symbol and symbol not in result:
            result[symbol] = row
    return result


def existing_eligible_tickers(snapshot: dict[str, Any]) -> set[str]:
    """Mirror existing tracker eligibility; never create a new eligibility label."""
    values = snapshot.get("eligibleTickers") if isinstance(snapshot, dict) else []
    return {ticker(value) for value in values or [] if ticker(value)}


def account_positions(account: dict[str, Any]) -> list[dict[str, Any]]:
    """Read normalized read-only positions from either account artifact shape."""
    if not isinstance(account, dict):
        return []
    candidates = account.get("positions") or account.get("holdings") or []
    return [position for position in candidates if isinstance(position, dict) and ticker(position.get("symbol") or position.get("ticker"))]


def taxonomy_fields(
    conviction_row: dict[str, Any] | None,
    reference_row: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep thematic research distinct from reference data and portfolio policy."""
    category = str((conviction_row or {}).get("category") or "").strip()
    theme_exposure = ECONOMIC_EXPOSURE_BY_CATEGORY.get(category)
    theme_classified = bool(theme_exposure)
    reference_row = reference_row or {}
    reference_covered = reference_row.get("referenceStatus") == "reference-covered"
    reference_exposure = str(reference_row.get("economicExposure") or "").strip()
    return {
        "category": category if theme_classified else "Unclassified",
        "themeEconomicExposure": theme_exposure or "Unclassified",
        "themeTaxonomyStatus": "mapped-from-existing-research" if theme_classified else "unclassified-research-theme",
        "sector": str(reference_row.get("sector") or "Unknown"),
        "industry": str(reference_row.get("industry") or "Unknown"),
        "economicExposure": reference_exposure if reference_covered and reference_exposure else (theme_exposure or "Unclassified"),
        "taxonomyStatus": "reference-backed" if reference_covered else "reference-missing",
        "taxonomySource": str(reference_row.get("referenceSource") or "no-reference-taxonomy-yet"),
        "referenceStatus": str(reference_row.get("referenceStatus") or "reference-missing"),
        "referenceFresh": bool(reference_row.get("referenceFresh")),
        "referenceAsOf": reference_row.get("referenceAsOf"),
        "portfolioRole": str(reference_row.get("portfolioRole") or "not-defined-by-reference-data"),
        "portfolioRoleStatus": str(reference_row.get("portfolioRoleStatus") or "requires-operator-policy"),
    }


def entry_for(
    row: dict[str, Any],
    conviction_row: dict[str, Any] | None,
    holding: dict[str, Any] | None,
    eligible: set[str],
    research_rank: int | None,
    reference_row: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build one full-tracker record without generating a funding recommendation."""
    symbol = ticker(row.get("ticker"))
    market_context = row.get("marketContext") if isinstance(row.get("marketContext"), dict) else {}
    classification = taxonomy_fields(conviction_row, reference_row)
    evidence_grade = str((conviction_row or {}).get("evidenceGrade") or "unknown")
    source_status = str(market_context.get("sourceStatus") or "unknown")
    long_term_research_qualified = (
        number((conviction_row or {}).get("longTermConvictionScore")) >= 66.0
        and number((conviction_row or {}).get("support")) > 0.0
    )
    return {
        "ticker": symbol,
        "trackerMembership": "operator-maintained",
        "existingEligibility": "existing-eligible" if symbol in eligible else "existing-tracked-not-eligible",
        "trackerData": {
            "status": row.get("status"),
            "priceAsOf": row.get("priceAsOf"),
            "priceSource": row.get("priceSource"),
            "sourceStatus": source_status,
        },
        "research": {
            "rank": research_rank,
            "convictionAdjustedScore": (conviction_row or {}).get("convictionAdjustedScore"),
            "longTermConvictionScore": (conviction_row or {}).get("longTermConvictionScore"),
            "researchAction": (conviction_row or {}).get("researchAction") or "not-scored",
            "evidenceGrade": evidence_grade,
            "longTermResearchQualified": long_term_research_qualified,
        },
        "taxonomy": classification,
        "holding": {
            "currentlyHeld": bool(holding),
            "quantity": (holding or {}).get("qty"),
            "marketValue": (holding or {}).get("markValue"),
            "weightPct": (holding or {}).get("weightPct"),
            "operatorLongTermHold": bool((holding or {}).get("operatorLongTermHold")),
        },
        "dcaStatus": "research-input-only",
    }


def coverage_summary(entries: list[dict[str, Any]], positions: list[dict[str, Any]]) -> dict[str, Any]:
    """State exactly what is ready for portfolio construction and what is not."""
    taxonomy_counts = Counter(item["taxonomy"]["taxonomyStatus"] for item in entries)
    theme_taxonomy_counts = Counter(item["taxonomy"]["themeTaxonomyStatus"] for item in entries)
    category_counts = Counter(item["taxonomy"]["category"] for item in entries)
    sector_counts = Counter(item["taxonomy"]["sector"] for item in entries if item["taxonomy"]["referenceStatus"] == "reference-covered")
    exposure_counts = Counter(item["taxonomy"]["economicExposure"] for item in entries if item["taxonomy"]["referenceStatus"] == "reference-covered")
    role_counts = Counter(item["taxonomy"]["portfolioRoleStatus"] for item in entries)
    grade_counts = Counter(item["research"]["evidenceGrade"] for item in entries)
    action_counts = Counter(item["research"]["researchAction"] for item in entries)
    tracked = {item["ticker"] for item in entries}
    held = {ticker(position.get("symbol") or position.get("ticker")) for position in positions}
    matched_holdings = sorted(symbol for symbol in held if symbol in tracked)
    untracked_holdings = sorted(symbol for symbol in held if symbol and symbol not in tracked)
    reference_covered = taxonomy_counts.get("reference-backed", 0)
    reference_missing = taxonomy_counts.get("reference-missing", 0)
    stale_reference = sum(
        1
        for item in entries
        if item["taxonomy"]["referenceStatus"] == "reference-covered" and not item["taxonomy"]["referenceFresh"]
    )
    return {
        "trackedRows": len(entries),
        "convictionCoverage": sum(1 for item in entries if item["research"]["rank"] is not None),
        "referenceCoverage": {
            "referenceCoveredRows": reference_covered,
            "referenceMissingRows": reference_missing,
            "staleReferenceRows": stale_reference,
            "complete": reference_covered == len(entries) and bool(entries),
            "bySector": dict(sorted(sector_counts.items())),
            "byEconomicExposure": dict(sorted(exposure_counts.items())),
        },
        "taxonomyCoverage": {
            "mappedRows": theme_taxonomy_counts.get("mapped-from-existing-research", 0),
            "needsOperatorTaxonomy": category_counts.get("Unclassified", 0),
            "complete": category_counts.get("Unclassified", 0) == 0 and bool(entries),
            "byCategory": dict(sorted(category_counts.items())),
        },
        "portfolioRolePolicyCoverage": {
            "definedRows": sum(1 for item in entries if item["taxonomy"]["portfolioRoleStatus"] == "operator-policy-defined"),
            "requiresOperatorPolicy": role_counts.get("requires-operator-policy", 0),
            "complete": role_counts.get("requires-operator-policy", 0) == 0 and bool(entries),
        },
        "researchCoverage": {
            "byEvidenceGrade": dict(sorted(grade_counts.items())),
            "byResearchAction": dict(sorted(action_counts.items())),
            "longTermResearchQualified": sum(
                1 for item in entries if item["research"]["longTermResearchQualified"]
            ),
        },
        "holdingsCoverage": {
            "brokerPositions": len(held),
            "matchedToTracker": len(matched_holdings),
            "heldNotInTracker": untracked_holdings,
        },
    }


def build_tracker_registry(
    *,
    snapshot: dict[str, Any] | None = None,
    conviction: dict[str, Any] | None = None,
    account: dict[str, Any] | None = None,
    taxonomy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Join tracker, research, reference taxonomy, and broker holdings safely."""
    snapshot = snapshot if snapshot is not None else (load_json_file(TRACKER_SNAPSHOT_FILE) or {})
    conviction = conviction if conviction is not None else (load_json_file(CONVICTION_RESEARCH_FILE) or {})
    account = account if account is not None else (load_json_file(LIVE_ACCOUNT_SYNC_FILE) or load_json_file(SCHWAB_ACCOUNT_SYNC_FILE) or {})
    taxonomy = taxonomy if taxonomy is not None else (load_json_file(TRACKER_TAXONOMY_FILE) or {})

    rows = snapshot_rows(snapshot)
    counts = Counter(ticker(row.get("ticker")) for row in rows)
    duplicate_tickers = sorted(symbol for symbol, count in counts.items() if symbol and count > 1)
    conviction_rows = [row for row in (conviction.get("ranked") or []) if isinstance(row, dict)]
    conviction_by_ticker = indexed_rows(conviction_rows)
    research_rank_by_ticker = {
        ticker(row.get("ticker")): index
        for index, row in enumerate(conviction_rows, start=1)
        if ticker(row.get("ticker"))
    }
    positions = account_positions(account)
    holdings_by_ticker = indexed_rows(positions, key="symbol")
    eligible = existing_eligible_tickers(snapshot)
    taxonomy_by_ticker = indexed_rows(
        [row for row in (taxonomy.get("entries") or []) if isinstance(row, dict)]
    )

    entries = [
        entry_for(
            row,
            conviction_by_ticker.get(ticker(row.get("ticker"))),
            holdings_by_ticker.get(ticker(row.get("ticker"))),
            eligible,
            research_rank_by_ticker.get(ticker(row.get("ticker"))),
            taxonomy_by_ticker.get(ticker(row.get("ticker"))),
        )
        for row in rows
    ]
    entries.sort(key=lambda item: (
        item["research"]["rank"] is None,
        item["research"]["rank"] if item["research"]["rank"] is not None else 10**9,
        item["ticker"],
    ))
    coverage = coverage_summary(entries, positions)
    reference_coverage = coverage.get("referenceCoverage") or {}
    reference_complete = bool(reference_coverage.get("complete"))
    role_coverage = coverage.get("portfolioRolePolicyCoverage") or {}
    verdict = "reference-covered-role-policy-pending" if reference_complete else "reference-coverage-incomplete"
    blockers = []
    if duplicate_tickers:
        blockers.append(f"duplicate tracker symbols: {', '.join(duplicate_tickers)}")
    missing_reference = int(reference_coverage.get("referenceMissingRows") or 0)
    stale_reference = int(reference_coverage.get("staleReferenceRows") or 0)
    if missing_reference:
        blockers.append(f"{missing_reference} tracked name(s) lack reference sector/industry coverage")
    if stale_reference:
        blockers.append(f"{stale_reference} tracked name(s) have stale reference sector/industry coverage")
    missing_role_policy = int(role_coverage.get("requiresOperatorPolicy") or 0)
    if missing_role_policy:
        blockers.append(f"{missing_role_policy} tracked name(s) require an operator-approved portfolio-role policy before diversified DCA research")
    if coverage.get("convictionCoverage") != len(entries):
        blockers.append("conviction coverage is incomplete; refresh research before using this registry")

    return {
        "generatedAt": local_now().isoformat(),
        "stage": TRACKER_REGISTRY_STAGE,
        "verdict": verdict,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "purpose": "Full-tracker taxonomy and holdings-coverage audit before any DCA construction research.",
        "authorityBoundary": {
            "trackerMembershipChanged": False,
            "eligibilityChanged": False,
            "riskConstantsChanged": False,
            "targetWeightsProduced": False,
            "brokerActionProduced": False,
        },
        "inputFreshness": {
            "trackerGeneratedAt": snapshot.get("generatedAt"),
            "convictionGeneratedAt": conviction.get("generatedAt"),
            "accountGeneratedAt": account.get("generatedAt"),
            "referenceTaxonomyGeneratedAt": taxonomy.get("generatedAt"),
        },
        "coverage": coverage,
        "blockers": blockers,
        "nextBuildGate": {
            "readyForDiversifiedDcaConstruction": False,
            "requirements": [
                "Keep all tracker rows retained and conviction-covered.",
                "Resolve any missing or stale reference sector-and-industry record without guessing.",
                "Define operator-approved diversification and deposit allocation policy separately from research ranks.",
                "Keep portfolio roles, target weights, and purchases outside this coverage artifact.",
            ],
        },
        "entries": entries,
        "citations": [
            "data/latest_snapshot.json",
            "data/inferno_conviction_research.json",
            "data/inferno_live_account_sync.json",
            "data/inferno_tracker_taxonomy.json",
            "docs/FULL_TRACKER_DCA_OPERATING_PLAN.md",
        ],
    }


def tracker_registry_text(payload: dict[str, Any]) -> str:
    """Render a concise operational report without presenting an allocation."""
    coverage = payload.get("coverage") or {}
    reference = coverage.get("referenceCoverage") or {}
    taxonomy = coverage.get("taxonomyCoverage") or {}
    roles = coverage.get("portfolioRolePolicyCoverage") or {}
    research = coverage.get("researchCoverage") or {}
    holdings = coverage.get("holdingsCoverage") or {}
    lines = [
        "Inferno Full-Tracker Registry (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Tracker coverage: {coverage.get('trackedRows', 0)} rows | conviction matched {coverage.get('convictionCoverage', 0)}",
        f"Reference taxonomy: {reference.get('referenceCoveredRows', 0)} covered | {reference.get('referenceMissingRows', 0)} missing | {reference.get('staleReferenceRows', 0)} stale",
        f"Research themes: {taxonomy.get('mappedRows', 0)} mapped | {taxonomy.get('needsOperatorTaxonomy', 0)} unclassified",
        f"Portfolio roles: {roles.get('definedRows', 0)} defined | {roles.get('requiresOperatorPolicy', 0)} require operator policy",
        f"Research: {research.get('longTermResearchQualified', 0)} long-term research-qualified | evidence {research.get('byEvidenceGrade', {})}",
        f"Holdings join: {holdings.get('matchedToTracker', 0)}/{holdings.get('brokerPositions', 0)} broker positions match the tracker",
        "",
        "Reference economic-exposure coverage",
    ]
    for exposure, count in (reference.get("byEconomicExposure") or {}).items():
        lines.append(f"- {exposure}: {count}")
    lines.extend(["", "DCA construction gate"])
    gate = payload.get("nextBuildGate") or {}
    lines.append(f"- Ready for diversified DCA construction: {bool(gate.get('readyForDiversifiedDcaConstruction'))}")
    for requirement in gate.get("requirements") or []:
        lines.append(f"- {requirement}")
    lines.extend(["", "Blockers"])
    lines.extend(f"- {item}" for item in payload.get("blockers") or ["none"])
    lines.extend(
        [
            "",
            "This is a coverage and source-reconciliation artifact, not a target-weight model, buy list,",
            "order instruction, or eligibility change. Broker submission and live trading remain disabled.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def save_tracker_registry(payload: dict[str, Any]) -> None:
    """Persist the machine and human views of the registry."""
    ensure_dirs()
    atomic_write_json(TRACKER_REGISTRY_FILE, payload)
    atomic_write_text(TRACKER_REGISTRY_TEXT_FILE, tracker_registry_text(payload))


def parse_args() -> argparse.Namespace:
    """Parse the small research-only CLI surface."""
    parser = argparse.ArgumentParser(description="Build the full-tracker portfolio-construction registry.")
    parser.add_argument("action", nargs="?", choices=("run", "status"), default="run")
    return parser.parse_args()


def main() -> int:
    """Run or rebuild the registry."""
    args = parse_args()
    if args.action == "status":
        payload = load_json_file(TRACKER_REGISTRY_FILE) or build_tracker_registry()
    else:
        payload = build_tracker_registry()
        save_tracker_registry(payload)
    print(tracker_registry_text(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
