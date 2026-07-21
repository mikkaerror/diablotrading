from __future__ import annotations

"""Read-only contract validation for human-owned full-tracker role policy.

The role-review queue intentionally records no policy decisions.  This module
is the narrow handoff from that queue to a future operator-maintained policy
file.  It never writes the policy input, applies its decisions to the tracker,
or accepts target weights.  Its output is only an auditable coverage and
validation report for research planning.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_tracker_role_review import ROLE_REVIEW_OUTCOMES
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


TRACKER_REGISTRY_FILE = DATA_DIR / "inferno_tracker_registry.json"
OPERATOR_ROLE_POLICY_FILE = DATA_DIR / "operator_tracker_role_policy.json"
TRACKER_ROLE_POLICY_FILE = DATA_DIR / "inferno_tracker_role_policy.json"
TRACKER_ROLE_POLICY_TEXT_FILE = REPORTS_DIR / "tracker_role_policy_latest.txt"

TRACKER_ROLE_POLICY_STAGE = "full-tracker-operator-role-policy-contract-research-only"
POLICY_VERSION = 1
DCA_RESEARCH_OUTCOMES = (
    "include-in-DCA-research",
    "exclude-from-DCA-research",
)
REQUIRED_DOCUMENT_FIELDS = ("version", "operator", "updatedAt", "decisions")
REQUIRED_DECISION_FIELDS = (
    "ticker",
    "portfolioRole",
    "dcaResearchInclusion",
    "decisionAt",
    "decisionSource",
    "rationale",
)


def ticker(value: Any) -> str:
    """Normalize a symbol without changing tracker membership."""
    return str(value or "").strip().upper()


def text(value: Any, default: str = "") -> str:
    """Return a human-supplied field without substituting a policy value."""
    rendered = str(value or "").strip()
    return rendered or default


def issue(code: str, path: str, message: str) -> dict[str, str]:
    """Use structured validation output suitable for a human review queue."""
    return {"code": code, "path": path, "message": message}


def valid_timestamp(value: Any) -> bool:
    """Require auditable ISO timestamps without fabricating a date."""
    rendered = text(value)
    if not rendered:
        return False
    try:
        datetime.fromisoformat(rendered.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def collect_weight_field_issues(value: Any, *, path: str = "$") -> list[dict[str, str]]:
    """Reject target-weight-like fields everywhere in this deliberately weight-free contract."""
    problems: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if "weight" in str(key).lower():
                problems.append(
                    issue(
                        "target-weight-not-accepted",
                        child_path,
                        "Target weights belong in a separately approved human-owned policy and are not accepted here.",
                    )
                )
            problems.extend(collect_weight_field_issues(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            problems.extend(collect_weight_field_issues(child, path=f"{path}[{index}]"))
    return problems


def validate_policy_document(
    policy: Any,
    *,
    tracked_tickers: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Validate only operator input; do not infer or repair any decision."""
    problems = collect_weight_field_issues(policy)
    if not isinstance(policy, dict):
        return [], problems + [issue("document-must-be-object", "$", "Policy input must be a JSON object.")]

    for field in REQUIRED_DOCUMENT_FIELDS:
        if field not in policy:
            problems.append(issue("missing-document-field", f"$.{field}", f"Required field '{field}' is missing."))
    if policy.get("version") != POLICY_VERSION:
        problems.append(issue("unsupported-policy-version", "$.version", f"Version must be {POLICY_VERSION}."))
    if not text(policy.get("operator")):
        problems.append(issue("missing-operator", "$.operator", "A human operator identifier is required."))
    if not valid_timestamp(policy.get("updatedAt")):
        problems.append(issue("invalid-updated-at", "$.updatedAt", "updatedAt must be an ISO-8601 timestamp."))

    decisions = policy.get("decisions")
    if not isinstance(decisions, list):
        problems.append(issue("decisions-must-be-list", "$.decisions", "decisions must be a JSON list."))
        return [], problems

    accepted: list[dict[str, Any]] = []
    seen_tickers: set[str] = set()
    for index, entry in enumerate(decisions):
        entry_path = f"$.decisions[{index}]"
        entry_problems_before = len(problems)
        if not isinstance(entry, dict):
            problems.append(issue("decision-must-be-object", entry_path, "Each decision must be a JSON object."))
            continue
        for field in REQUIRED_DECISION_FIELDS:
            if field not in entry:
                problems.append(issue("missing-decision-field", f"{entry_path}.{field}", f"Required field '{field}' is missing."))
        symbol = ticker(entry.get("ticker"))
        if not symbol:
            problems.append(issue("missing-ticker", f"{entry_path}.ticker", "ticker must be a non-empty tracker symbol."))
        elif symbol not in tracked_tickers:
            problems.append(issue("ticker-not-in-tracker", f"{entry_path}.ticker", f"{symbol} is not in the full tracker."))
        elif symbol in seen_tickers:
            problems.append(issue("duplicate-ticker", f"{entry_path}.ticker", f"{symbol} appears more than once."))
        else:
            seen_tickers.add(symbol)
        if text(entry.get("portfolioRole")) not in ROLE_REVIEW_OUTCOMES:
            problems.append(
                issue(
                    "invalid-portfolio-role",
                    f"{entry_path}.portfolioRole",
                    "portfolioRole must be one of the documented operator role outcomes.",
                )
            )
        if text(entry.get("dcaResearchInclusion")) not in DCA_RESEARCH_OUTCOMES:
            problems.append(
                issue(
                    "invalid-dca-research-inclusion",
                    f"{entry_path}.dcaResearchInclusion",
                    "dcaResearchInclusion must explicitly include or exclude this name from DCA research.",
                )
            )
        if not valid_timestamp(entry.get("decisionAt")):
            problems.append(issue("invalid-decision-at", f"{entry_path}.decisionAt", "decisionAt must be an ISO-8601 timestamp."))
        if text(entry.get("decisionSource")) != "operator":
            problems.append(issue("invalid-decision-source", f"{entry_path}.decisionSource", "decisionSource must be 'operator'."))
        if not text(entry.get("rationale")):
            problems.append(issue("missing-rationale", f"{entry_path}.rationale", "A human-authored rationale is required."))
        if len(problems) == entry_problems_before:
            accepted.append({"ticker": symbol, **entry})
    # A malformed document is intentionally not partially accepted.  A human
    # must repair it first so no downstream layer can silently use a subset.
    return (accepted if not problems else []), problems


def load_operator_policy(path: Path = OPERATOR_ROLE_POLICY_FILE) -> tuple[Any | None, str, list[dict[str, str]]]:
    """Read an operator file if present, never create or modify it."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "not-provided", []
    except OSError as exc:
        return None, "unreadable", [issue("policy-file-unreadable", "file", str(exc))]
    try:
        return json.loads(raw), "provided", []
    except json.JSONDecodeError as exc:
        return None, "invalid-json", [issue("invalid-json", "file", f"{exc.msg} at line {exc.lineno}, column {exc.colno}.")]


def reference_summary(registry_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Carry source quality forward without guessing a missing reference."""
    missing: list[str] = []
    for entry in registry_entries:
        taxonomy = entry.get("taxonomy") if isinstance(entry.get("taxonomy"), dict) else {}
        if taxonomy.get("referenceStatus") != "reference-covered":
            missing.append(ticker(entry.get("ticker")))
    return {
        "referenceCoveredRows": len(registry_entries) - len(missing),
        "referenceMissingRows": len(missing),
        "missingReferenceTickers": sorted(symbol for symbol in missing if symbol),
    }


def build_tracker_role_policy_contract(
    *,
    registry: dict[str, Any] | None = None,
    policy: Any | None = None,
    policy_input_status: str | None = None,
    policy_input_issues: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Report human-policy coverage while preserving every tracker row and all unknowns."""
    registry = registry if registry is not None else (load_json_file(TRACKER_REGISTRY_FILE) or {})
    registry_entries = [
        entry
        for entry in registry.get("entries") or []
        if isinstance(entry, dict) and ticker(entry.get("ticker"))
    ]
    tracked_tickers = {ticker(entry.get("ticker")) for entry in registry_entries}
    input_status = policy_input_status or ("not-provided" if policy is None else "provided")
    input_issues = list(policy_input_issues or [])
    accepted: list[dict[str, Any]] = []
    problems = list(input_issues)
    if input_status == "provided":
        accepted, validation_issues = validate_policy_document(policy, tracked_tickers=tracked_tickers)
        problems.extend(validation_issues)

    accepted_tickers = {ticker(entry.get("ticker")) for entry in accepted}
    pending_tickers = sorted(tracked_tickers - accepted_tickers)
    references = reference_summary(registry_entries)
    input_rows = len(policy.get("decisions") or []) if isinstance(policy, dict) and isinstance(policy.get("decisions"), list) else 0
    invalid_rows = max(0, input_rows - len(accepted))
    fully_covered = len(accepted_tickers) == len(tracked_tickers)
    if input_status == "not-provided":
        verdict = "operator-policy-not-provided"
    elif problems:
        verdict = "operator-policy-invalid"
    elif not fully_covered:
        verdict = "operator-policy-incomplete"
    elif references["referenceMissingRows"]:
        verdict = "operator-policy-complete-reference-gap"
    else:
        verdict = "operator-policy-complete-awaiting-separate-weight-policy"

    ready_for_role_integration = bool(
        fully_covered and not problems and not references["referenceMissingRows"]
    )
    return {
        "generatedAt": local_now().isoformat(),
        "stage": TRACKER_ROLE_POLICY_STAGE,
        "verdict": verdict,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "purpose": "Read-only validation of a human-owned full-tracker role and DCA-research policy contract before any allocation research.",
        "authorityBoundary": {
            "policyInputReadOnly": True,
            "operatorPolicyChanged": False,
            "trackerMembershipChanged": False,
            "eligibilityChanged": False,
            "riskConstantsChanged": False,
            "targetWeightsAccepted": False,
            "targetWeightsProduced": False,
            "purchasesProduced": False,
            "brokerActionProduced": False,
        },
        "operatorPolicyInput": {
            "path": "data/operator_tracker_role_policy.json",
            "status": input_status,
            "readOnly": True,
            "template": "docs/OPERATOR_TRACKER_ROLE_POLICY_TEMPLATE.md",
            "acceptedRoles": list(ROLE_REVIEW_OUTCOMES),
            "acceptedDcaResearchOutcomes": list(DCA_RESEARCH_OUTCOMES),
            "targetWeightsAccepted": False,
        },
        "coverage": {
            "trackedRows": len(tracked_tickers),
            "inputDecisionRows": input_rows,
            "validDecisionRows": len(accepted_tickers),
            "invalidDecisionRows": invalid_rows,
            "pendingDecisionRows": len(pending_tickers),
            "pendingTickers": pending_tickers,
            "targetWeightDefinedRows": 0,
            **references,
        },
        "validationIssues": problems,
        "nextBuildGate": {
            "readyForRolePolicyIntegration": ready_for_role_integration,
            "readyForDcaWeightResearch": False,
            "requirements": [
                "A human operator must manually create data/operator_tracker_role_policy.json from the documentation template.",
                "The policy file must contain one valid role and DCA-research decision for every retained tracker name.",
                "Resolve missing reference taxonomy without guessing before any role-policy integration.",
                "Keep target-weight policy in a separate approved human-owned source; this contract rejects it.",
                "No allocation, purchase, eligibility, or broker action follows from a valid contract by itself.",
            ],
        },
        "citations": [
            "data/inferno_tracker_registry.json",
            "data/inferno_tracker_taxonomy.json",
            "data/operator_tracker_role_policy.json (optional human-owned input; read-only)",
            "docs/OPERATOR_TRACKER_ROLE_POLICY_TEMPLATE.md",
            "docs/FULL_TRACKER_DCA_OPERATING_PLAN.md",
        ],
    }


def tracker_role_policy_text(payload: dict[str, Any]) -> str:
    """Render a concise policy-input status, never a buy list or allocation proposal."""
    coverage = payload.get("coverage") or {}
    policy_input = payload.get("operatorPolicyInput") or {}
    lines = [
        "Inferno Full-Tracker Operator Role-Policy Contract (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Operator input: {policy_input.get('status')} | read-only={policy_input.get('readOnly')} | {policy_input.get('path')}",
        f"Decision coverage: {coverage.get('validDecisionRows', 0)}/{coverage.get('trackedRows', 0)} valid | {coverage.get('pendingDecisionRows', 0)} pending | {coverage.get('invalidDecisionRows', 0)} invalid",
        f"Reference gate: {coverage.get('referenceCoveredRows', 0)}/{coverage.get('trackedRows', 0)} covered | {coverage.get('referenceMissingRows', 0)} missing",
        f"Target weights accepted: {policy_input.get('targetWeightsAccepted')}",
        "",
        "Next pending tracker names (all names remain retained)",
    ]
    pending = coverage.get("pendingTickers") or []
    lines.append(f"- {', '.join(pending[:16]) or 'none'}" + (" …" if len(pending) > 16 else ""))
    problems = payload.get("validationIssues") or []
    if problems:
        lines.extend(["", "Validation issues"])
        for item in problems[:8]:
            lines.append(f"- {item.get('path')}: {item.get('message')}")
    lines.extend(["", "Boundary and next gate"])
    for requirement in (payload.get("nextBuildGate") or {}).get("requirements") or []:
        lines.append(f"- {requirement}")
    lines.extend(
        [
            "",
            "This validator never creates or edits operator decisions and does not assign weights, purchases, eligibility, or broker actions.",
            "Broker submission and live trading remain disabled.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def save_tracker_role_policy_contract(payload: dict[str, Any]) -> None:
    """Persist only the derived evidence report, not the operator-owned input file."""
    ensure_dirs()
    atomic_write_json(TRACKER_ROLE_POLICY_FILE, payload)
    atomic_write_text(TRACKER_ROLE_POLICY_TEXT_FILE, tracker_role_policy_text(payload))


def parse_args() -> argparse.Namespace:
    """Expose a tiny run/status surface without a policy-writing command."""
    parser = argparse.ArgumentParser(description="Validate a human-owned full-tracker role-policy contract read-only.")
    parser.add_argument("action", nargs="?", choices=("run", "status"), default="run")
    return parser.parse_args()


def main() -> int:
    """Build the derived validator report or display the latest saved report."""
    args = parse_args()
    if args.action == "status":
        payload = load_json_file(TRACKER_ROLE_POLICY_FILE) or build_tracker_role_policy_contract()
    else:
        policy, input_status, input_issues = load_operator_policy()
        payload = build_tracker_role_policy_contract(
            policy=policy,
            policy_input_status=input_status,
            policy_input_issues=input_issues,
        )
        save_tracker_role_policy_contract(payload)
    print(tracker_role_policy_text(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
