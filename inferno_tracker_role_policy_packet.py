from __future__ import annotations

"""Create a blank, source-contextual full-tracker role-policy worksheet.

The existing role-review queue identifies all retained tracker names and the
read-only policy contract validates a human-created policy file.  Neither is
an editable per-row handoff.  This module fills that narrow gap with a derived
packet that deliberately contains *blank* operator fields for every tracker
name.  It never reads, writes, or imports ``operator_tracker_role_policy``;
the operator must copy completed choices into that separately owned input by
hand before the contract can validate it.
"""

import argparse
import csv
import io
from pathlib import Path
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_tracker_role_policy import DCA_RESEARCH_OUTCOMES, REQUIRED_DECISION_FIELDS
from inferno_tracker_role_review import ROLE_REVIEW_OUTCOMES, build_tracker_role_review
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


TRACKER_REGISTRY_FILE = DATA_DIR / "inferno_tracker_registry.json"
TRACKER_ROLE_POLICY_PACKET_FILE = DATA_DIR / "inferno_tracker_role_policy_packet.json"
TRACKER_ROLE_POLICY_PACKET_TEXT_FILE = REPORTS_DIR / "tracker_role_policy_packet_latest.txt"
TRACKER_ROLE_POLICY_PACKET_CSV_FILE = REPORTS_DIR / "tracker_role_policy_packet_latest.csv"

TRACKER_ROLE_POLICY_PACKET_STAGE = "full-tracker-blank-role-policy-packet-research-only"
PACKET_VERSION = 1
OPERATOR_ENTRY_FIELDS = (
    "portfolioRole",
    "dcaResearchInclusion",
    "decisionAt",
    "decisionSource",
    "rationale",
)
CSV_FIELDS = (
    "ticker",
    "company_name",
    "review_priority",
    "reference_status",
    "reference_fresh",
    "sector",
    "industry",
    "economic_exposure",
    "reference_source",
    "currently_held",
    "operator_declared_long_term_hold",
    "existing_eligibility",
    "research_rank",
    "long_term_research_qualified",
    "evidence_grade",
    "theme_category",
    "portfolio_role",
    "dca_research_inclusion",
    "decision_at",
    "decision_source",
    "rationale",
)


def text(value: Any, default: str = "") -> str:
    """Render source context without fabricating an operator decision."""
    rendered = str(value or "").strip()
    return rendered or default


def blank_operator_entry(symbol: str) -> dict[str, str]:
    """Return the contract-shaped fields with every operator choice blank."""
    return {"ticker": symbol, **{field: "" for field in OPERATOR_ENTRY_FIELDS}}


def packet_row(review_row: dict[str, Any]) -> dict[str, Any]:
    """Keep review evidence separate from deliberately blank operator entry fields."""
    reference = review_row.get("reference") if isinstance(review_row.get("reference"), dict) else {}
    existing = review_row.get("existingContext") if isinstance(review_row.get("existingContext"), dict) else {}
    research = review_row.get("researchContext") if isinstance(review_row.get("researchContext"), dict) else {}
    symbol = text(review_row.get("ticker")).upper()
    return {
        "ticker": symbol,
        "companyName": text(review_row.get("companyName"), symbol),
        "reviewPriority": text(review_row.get("reviewPriority"), "standard-role-review"),
        "reference": {
            "status": text(reference.get("status"), "reference-missing"),
            "fresh": bool(reference.get("fresh")),
            "sector": text(reference.get("sector"), "Unknown"),
            "industry": text(reference.get("industry"), "Unknown"),
            "economicExposure": text(reference.get("economicExposure"), "Unclassified"),
            "source": text(reference.get("source"), "no-reference-taxonomy-yet"),
        },
        "existingContext": {
            "currentlyHeld": bool(existing.get("currentlyHeld")),
            "operatorDeclaredLongTermHold": bool(existing.get("operatorDeclaredLongTermHold")),
            "existingEligibility": text(existing.get("existingEligibility"), "unknown"),
        },
        "researchContext": {
            "rank": research.get("rank"),
            "longTermResearchQualified": bool(research.get("longTermResearchQualified")),
            "evidenceGrade": text(research.get("evidenceGrade"), "unknown"),
            "themeCategory": text(research.get("themeCategory"), "Unclassified"),
        },
        "operatorEntry": blank_operator_entry(symbol),
    }


def blank_policy_skeleton(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Provide a manually copyable document shape, not an import or policy mutation."""
    return {
        "version": PACKET_VERSION,
        "operator": "",
        "updatedAt": "",
        "decisions": [dict(row["operatorEntry"]) for row in rows],
    }


def build_tracker_role_policy_packet(*, registry: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a complete blank worksheet from the read-only full-tracker queue."""
    registry = registry if registry is not None else (load_json_file(TRACKER_REGISTRY_FILE) or {})
    review = build_tracker_role_review(registry=registry)
    rows = [packet_row(row) for row in review.get("reviewQueue") or [] if isinstance(row, dict)]
    rows = [row for row in rows if row["ticker"]]
    blank_rows = [row for row in rows if all(not row["operatorEntry"][field] for field in OPERATOR_ENTRY_FIELDS)]
    references = review.get("coverage") if isinstance(review.get("coverage"), dict) else {}

    return {
        "generatedAt": local_now().isoformat(),
        "stage": TRACKER_ROLE_POLICY_PACKET_STAGE,
        "verdict": "blank-operator-entry-packet-ready",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "purpose": "Blank full-tracker operator role and DCA-research worksheet with read-only source context; not a policy input or import mechanism.",
        "authorityBoundary": {
            "operatorPolicyChanged": False,
            "operatorDecisionsProduced": False,
            "operatorDecisionsImported": False,
            "trackerMembershipChanged": False,
            "eligibilityChanged": False,
            "riskConstantsChanged": False,
            "targetWeightsAccepted": False,
            "targetWeightsProduced": False,
            "purchasesProduced": False,
            "brokerActionProduced": False,
        },
        "operatorHandoff": {
            "packetCanBeImported": False,
            "operatorPolicyInputPath": "data/operator_tracker_role_policy.json",
            "completionMethod": "A human must manually copy a completed policy document into the separate operator-owned input path.",
            "acceptedRoles": list(ROLE_REVIEW_OUTCOMES),
            "acceptedDcaResearchOutcomes": list(DCA_RESEARCH_OUTCOMES),
            "requiredDecisionFields": list(REQUIRED_DECISION_FIELDS),
            "weightFieldsIncluded": False,
        },
        "coverage": {
            "trackedRows": len(rows),
            "blankOperatorEntryRows": len(blank_rows),
            "operatorDecisionRows": 0,
            "referenceCoveredRows": references.get("referenceCoveredRows", 0),
            "referenceMissingRows": references.get("referenceMissingRows", 0),
            "targetWeightDefinedRows": 0,
        },
        "blankPolicySkeleton": blank_policy_skeleton(rows),
        "rows": rows,
        "nextBuildGate": {
            "readyForRolePolicyIntegration": False,
            "readyForDcaWeightResearch": False,
            "requirements": [
                "A human operator must fill every blank entry manually; this packet does not create or import decisions.",
                "Copy only a completed, human-owned document to data/operator_tracker_role_policy.json, then run ./inferno tracker-role-policy for read-only validation.",
                "Keep target-weight policy in a separately approved human-owned source; this packet has no weight-entry field.",
                "No allocation, purchase, eligibility, ticket, or broker action follows from this packet.",
            ],
        },
        "citations": [
            "data/inferno_tracker_registry.json",
            "data/inferno_tracker_role_review.json",
            "data/inferno_tracker_taxonomy.json",
            "docs/OPERATOR_TRACKER_ROLE_POLICY_TEMPLATE.md",
            "docs/FULL_TRACKER_DCA_OPERATING_PLAN.md",
        ],
    }


def packet_csv(payload: dict[str, Any]) -> str:
    """Render the blank worksheet in a spreadsheet-friendly, non-importable form."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in payload.get("rows") or []:
        if not isinstance(row, dict):
            continue
        reference = row.get("reference") or {}
        existing = row.get("existingContext") or {}
        research = row.get("researchContext") or {}
        entry = row.get("operatorEntry") or {}
        writer.writerow(
            {
                "ticker": row.get("ticker", ""),
                "company_name": row.get("companyName", ""),
                "review_priority": row.get("reviewPriority", ""),
                "reference_status": reference.get("status", ""),
                "reference_fresh": reference.get("fresh", ""),
                "sector": reference.get("sector", ""),
                "industry": reference.get("industry", ""),
                "economic_exposure": reference.get("economicExposure", ""),
                "reference_source": reference.get("source", ""),
                "currently_held": existing.get("currentlyHeld", ""),
                "operator_declared_long_term_hold": existing.get("operatorDeclaredLongTermHold", ""),
                "existing_eligibility": existing.get("existingEligibility", ""),
                "research_rank": research.get("rank", ""),
                "long_term_research_qualified": research.get("longTermResearchQualified", ""),
                "evidence_grade": research.get("evidenceGrade", ""),
                "theme_category": research.get("themeCategory", ""),
                "portfolio_role": entry.get("portfolioRole", ""),
                "dca_research_inclusion": entry.get("dcaResearchInclusion", ""),
                "decision_at": entry.get("decisionAt", ""),
                "decision_source": entry.get("decisionSource", ""),
                "rationale": entry.get("rationale", ""),
            }
        )
    return output.getvalue()


def tracker_role_policy_packet_text(payload: dict[str, Any]) -> str:
    """Explain the worksheet boundary without presenting any allocation guidance."""
    coverage = payload.get("coverage") or {}
    handoff = payload.get("operatorHandoff") or {}
    lines = [
        "Inferno Full-Tracker Blank Role-Policy Packet (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Worksheet rows: {coverage.get('trackedRows', 0)} retained | {coverage.get('blankOperatorEntryRows', 0)} blank operator entries | {coverage.get('operatorDecisionRows', 0)} decisions produced",
        f"Reference context: {coverage.get('referenceCoveredRows', 0)}/{coverage.get('trackedRows', 0)} covered | {coverage.get('referenceMissingRows', 0)} missing",
        f"Automatic import: {handoff.get('packetCanBeImported')} | target-weight fields included: {handoff.get('weightFieldsIncluded')}",
        "",
        "Files",
        "- JSON packet: data/inferno_tracker_role_policy_packet.json",
        "- Blank CSV worksheet: reports/tracker_role_policy_packet_latest.csv",
        "",
        "Operator handoff",
        "- Fill the blank role, DCA-research inclusion, date, source, and rationale cells manually; source context is read-only research evidence.",
        "- This packet is not policy input and Inferno has no automatic import path. A human may manually prepare the separately owned policy file, then run ./inferno tracker-role-policy for validation.",
        "- Do not add target weights here; allocation policy is a separate approved authority source.",
        "",
        "Boundary and next gate",
    ]
    for requirement in (payload.get("nextBuildGate") or {}).get("requirements") or []:
        lines.append(f"- {requirement}")
    lines.extend(
        [
            "",
            "This packet retains all tracker names but creates, infers, imports, and changes no operator decision.",
            "It does not change tracker membership, eligibility, policy, tickets, broker state, authority, purchases, or live trading.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def save_tracker_role_policy_packet(payload: dict[str, Any]) -> None:
    """Persist only derived research artifacts, never a human policy input."""
    ensure_dirs()
    atomic_write_json(TRACKER_ROLE_POLICY_PACKET_FILE, payload)
    atomic_write_text(TRACKER_ROLE_POLICY_PACKET_TEXT_FILE, tracker_role_policy_packet_text(payload))
    atomic_write_text(TRACKER_ROLE_POLICY_PACKET_CSV_FILE, packet_csv(payload))


def parse_args() -> argparse.Namespace:
    """Expose run/status only; no input, import, or policy-mutation command exists."""
    parser = argparse.ArgumentParser(description="Build a blank full-tracker operator role-policy worksheet packet.")
    parser.add_argument("action", nargs="?", choices=("run", "status"), default="run")
    return parser.parse_args()


def main() -> int:
    """Build a derived blank packet or display its latest report."""
    args = parse_args()
    if args.action == "status":
        payload = load_json_file(TRACKER_ROLE_POLICY_PACKET_FILE) or build_tracker_role_policy_packet()
    else:
        payload = build_tracker_role_policy_packet()
        save_tracker_role_policy_packet(payload)
    print(tracker_role_policy_packet_text(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
