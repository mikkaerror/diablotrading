from __future__ import annotations

"""Automation authority controller for the Inferno desk.

This is the control tower between "the dashboard found something" and "the
system is allowed to do something about it." It aggregates freshness, paper
evidence, exposure concentration, broker-preview state, and live-trading flags
into one explicit permission manifest. Future broker adapters should treat this
file as a hard gate, not a suggestion.
"""

import argparse
import json
import os
from datetime import datetime
from typing import Any

from inferno_config import BROKER_ADAPTER_MODE, ROOT, local_now, local_today
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file, smtp_configured


AUTHORITY_MANIFEST_FILE = DATA_DIR / "inferno_authority_manifest.json"
AUTHORITY_MANIFEST_TEXT_FILE = REPORTS_DIR / "authority_manifest_latest.txt"
SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
EXECUTION_QUEUE_FILE = DATA_DIR / "inferno_execution_queue.json"
PAPER_EXECUTION_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
PERFORMANCE_ANALYTICS_FILE = DATA_DIR / "inferno_performance_analytics.json"
STRATEGY_LAB_FILE = DATA_DIR / "inferno_strategy_lab.json"
EXPOSURE_ANALYTICS_FILE = DATA_DIR / "inferno_exposure_analytics.json"
BROKER_PREVIEW_FILE = DATA_DIR / "inferno_broker_preview.json"
SMTP_ENV_FILE = ROOT / ".env.smtp"

AUTHORITY_RANKS = {
    "halted": 0,
    "recommendations-only": 1,
    "paper-evidence-only": 2,
    "broker-preview-only": 3,
    "live-review-required": 4,
}
SAFE_BROKER_MODES = {"OFF", "READ_ONLY", "PREVIEW_ONLY", "PAPER"}
MIN_SCORED_TICKETS_FOR_BROKER_PREVIEW_AUTHORITY = 30


def is_today(value: Any) -> bool:
    """Return whether an ISO timestamp belongs to the local trading day."""
    return str(value or "").startswith(local_today())


def load_env_file() -> None:
    """Load local environment settings used by standalone report scripts."""
    if not SMTP_ENV_FILE.exists():
        return
    for raw_line in SMTP_ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key] = value


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO timestamp for manifest age reporting."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def age_minutes(value: Any) -> float | None:
    """Return artifact age in minutes for operator visibility."""
    parsed = parse_timestamp(value)
    if not parsed:
        return None
    return round(max(0.0, (local_now() - parsed).total_seconds() / 60), 2)


def artifact_status(name: str, payload: dict[str, Any], timestamp_key: str = "generatedAt") -> dict[str, Any]:
    """Build a consistent freshness status block for one artifact."""
    timestamp = payload.get(timestamp_key)
    return {
        "name": name,
        "present": bool(payload),
        "timestamp": timestamp,
        "freshToday": is_today(timestamp),
        "ageMinutes": age_minutes(timestamp),
    }


def closed_scored_count(performance: dict[str, Any]) -> int:
    """Return how many closed paper tickets have usable scored outcomes."""
    return int(((performance.get("closedMetrics") or {}).get("scoredCount")) or 0)


def performance_promoted(performance: dict[str, Any]) -> bool:
    """Return whether any strategy has earned the next promotion review."""
    return any(strategy.get("eligibleForPromotion") for strategy in performance.get("strategies", []))


def strategy_lab_promoted(strategy_lab: dict[str, Any]) -> bool:
    """Return whether the conservative strategy lab found promotable evidence."""
    verdict = strategy_lab.get("deskVerdict") or {}
    return bool(verdict.get("promotable") or strategy_lab.get("promotionCandidates"))


def exposure_clear(exposure: dict[str, Any]) -> bool:
    """Return whether portfolio/context exposure is clean enough to escalate."""
    verdict = exposure.get("verdict") or {}
    return verdict.get("level") == "clear"


def market_high_risk(exposure: dict[str, Any]) -> bool:
    """Return whether the broad-market regime is too hot for authority upgrades."""
    regime = exposure.get("marketRegime") or {}
    return regime.get("riskLevel") == "high"


def broker_preview_clean(preview: dict[str, Any]) -> bool:
    """Return whether preview artifacts contain clean preview-only orders."""
    return (
        bool(preview)
        and preview.get("previewOnly") is True
        and preview.get("liveTradingAllowed") is False
        and not preview.get("blockedReason")
        and int(preview.get("count") or 0) > 0
    )


def live_flag_detected(*payloads: dict[str, Any]) -> bool:
    """Detect any unexpected live-trading flag in nested artifacts."""
    stack: list[Any] = list(payloads)
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if item.get("liveTradingAllowed") is True:
                return True
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return False


def decide_authority(
    snapshot: dict[str, Any],
    execution_queue: dict[str, Any],
    ledger: dict[str, Any],
    performance: dict[str, Any],
    strategy_lab: dict[str, Any],
    exposure: dict[str, Any],
    broker_preview: dict[str, Any],
) -> dict[str, Any]:
    """Decide today's maximum automation authority."""
    blockers: list[str] = []
    warnings: list[str] = []
    allowed_actions = {"send_morning_brief"}
    blocked_actions: dict[str, list[str]] = {
        "submit_live_order": ["live broker submission is disabled by policy"],
        "increase_position_size": ["size increases require promotion review and manual approval"],
    }

    if not snapshot.get("rows"):
        blockers.append("latest snapshot is missing rows")
    if not is_today(snapshot.get("generatedAt")):
        blockers.append("latest snapshot is stale")
    if not is_today(execution_queue.get("generatedAt")):
        blockers.append("execution queue is stale")
    if not is_today(performance.get("generatedAt")):
        blockers.append("performance analytics are stale")
    if not is_today(strategy_lab.get("generatedAt")):
        blockers.append("strategy lab is stale")
    if not is_today(exposure.get("generatedAt")):
        blockers.append("exposure analytics are stale")
    if live_flag_detected(ledger, broker_preview):
        blockers.append("unexpected liveTradingAllowed flag detected")
    if BROKER_ADAPTER_MODE not in SAFE_BROKER_MODES:
        blockers.append(f"broker adapter mode {BROKER_ADAPTER_MODE} is not in safe preview modes")

    if not smtp_configured():
        warnings.append("SMTP is not configured, so morning delivery is not automated")
    if market_high_risk(exposure):
        warnings.append(f"market regime high risk: {(exposure.get('marketRegime') or {}).get('regime')}")
    if not exposure_clear(exposure):
        warnings.append(f"exposure review required: {(exposure.get('verdict') or {}).get('message')}")
    if closed_scored_count(performance) < MIN_SCORED_TICKETS_FOR_BROKER_PREVIEW_AUTHORITY:
        warnings.append(
            f"only {closed_scored_count(performance)} scored paper tickets; "
            f"need {MIN_SCORED_TICKETS_FOR_BROKER_PREVIEW_AUTHORITY} before promotion"
        )
    if not strategy_lab_promoted(strategy_lab):
        lab_verdict = strategy_lab.get("deskVerdict") or {}
        warnings.append(f"strategy lab not promoted: {lab_verdict.get('level')}")
    if not broker_preview_clean(broker_preview):
        warnings.append("no clean broker-preview orders are available")

    if blockers:
        level = "halted"
    else:
        allowed_actions.update(
            {
                "refresh_tracker",
                "score_dashboard",
                "build_execution_queue",
                "build_strike_plan",
                "record_paper_ledger",
                "review_paper_outcomes",
                "build_performance_analytics",
                "build_exposure_analytics",
                "build_broker_preview_artifact",
            }
        )
        # Broker preview authority requires evidence, clean exposure, and actual
        # previewable paper orders. Until then, preview generation remains a
        # report-building action, not a permission to route anything.
        if (
            performance_promoted(performance)
            and strategy_lab_promoted(strategy_lab)
            and exposure_clear(exposure)
            and broker_preview_clean(broker_preview)
        ):
            level = "broker-preview-only"
            blocked_actions["submit_live_order"].append("broker preview only, no live submit authority")
        else:
            level = "paper-evidence-only"
            blocked_actions["broker_order_preview_escalation"] = [
                "needs promoted performance evidence, promoted strategy lab, clear exposure, and clean preview orders"
            ]

    if level == "halted":
        allowed_actions = {"inspect_reports"}

    return {
        "authorityLevel": level,
        "authorityRank": AUTHORITY_RANKS[level],
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "brokerAdapterMode": BROKER_ADAPTER_MODE,
        "allowedActions": sorted(allowed_actions),
        "blockedActions": blocked_actions,
        "blockers": blockers,
        "warnings": warnings,
        "nextMilestones": next_milestones(performance, strategy_lab, exposure, broker_preview),
    }


def next_milestones(
    performance: dict[str, Any],
    strategy_lab: dict[str, Any],
    exposure: dict[str, Any],
    broker_preview: dict[str, Any],
) -> list[str]:
    """List the next practical upgrades before broker authority can increase."""
    milestones: list[str] = []
    scored = closed_scored_count(performance)
    if scored < MIN_SCORED_TICKETS_FOR_BROKER_PREVIEW_AUTHORITY:
        milestones.append(
            f"collect {MIN_SCORED_TICKETS_FOR_BROKER_PREVIEW_AUTHORITY - scored} more scored paper outcomes"
        )
    if not exposure_clear(exposure):
        milestones.append("reduce sector/setup concentration or explicitly down-rank crowded slates")
    if not broker_preview_clean(broker_preview):
        milestones.append("produce at least one clean paper-staged ticket for broker-preview payload testing")
    if not performance_promoted(performance):
        milestones.append("earn strategy promotion through positive expectancy and profit factor")
    if not strategy_lab_promoted(strategy_lab):
        milestones.append("pass conservative strategy-lab gates: positive lower-bound edge and controlled drawdown")
    milestones.append("keep live submit authority disabled until broker sandbox tests pass")
    return milestones


def build_authority_manifest() -> dict[str, Any]:
    """Build the full daily authority manifest from current desk artifacts."""
    load_env_file()
    snapshot = load_json_file(SNAPSHOT_FILE) or {}
    execution_queue = load_json_file(EXECUTION_QUEUE_FILE) or {}
    ledger = load_json_file(PAPER_EXECUTION_LEDGER_FILE) or {}
    performance = load_json_file(PERFORMANCE_ANALYTICS_FILE) or {}
    strategy_lab = load_json_file(STRATEGY_LAB_FILE) or {}
    exposure = load_json_file(EXPOSURE_ANALYTICS_FILE) or {}
    broker_preview = load_json_file(BROKER_PREVIEW_FILE) or {}
    decision = decide_authority(snapshot, execution_queue, ledger, performance, strategy_lab, exposure, broker_preview)
    return {
        "generatedAt": local_now().isoformat(),
        "stage": "automation-authority-control",
        "decision": decision,
        "artifacts": {
            "snapshot": artifact_status("snapshot", snapshot),
            "executionQueue": artifact_status("executionQueue", execution_queue),
            "paperLedger": artifact_status("paperLedger", ledger, timestamp_key="updatedAt"),
            "performanceAnalytics": artifact_status("performanceAnalytics", performance),
            "strategyLab": artifact_status("strategyLab", strategy_lab),
            "exposureAnalytics": artifact_status("exposureAnalytics", exposure),
            "brokerPreview": artifact_status("brokerPreview", broker_preview),
        },
        "evidence": {
            "scoredPaperTickets": closed_scored_count(performance),
            "performanceVerdict": performance.get("deskVerdict"),
            "strategyLabVerdict": strategy_lab.get("deskVerdict"),
            "strategyPromotionCandidates": strategy_lab.get("promotionCandidates", []),
            "exposureVerdict": exposure.get("verdict"),
            "marketRegime": exposure.get("marketRegime"),
            "brokerPreviewCount": broker_preview.get("count", 0),
        },
    }


def authority_text(manifest: dict[str, Any]) -> str:
    """Render the authority manifest as a readable operator memo."""
    decision = manifest.get("decision") or {}
    evidence = manifest.get("evidence") or {}
    lines = [
        "Inferno Automation Authority Manifest",
        "",
        f"Generated: {manifest.get('generatedAt')}",
        f"Authority: {decision.get('authorityLevel')} (rank {decision.get('authorityRank')})",
        f"Broker mode: {decision.get('brokerAdapterMode')}",
        f"Live trading allowed: {decision.get('liveTradingAllowed')}",
        f"Broker submit allowed: {decision.get('brokerSubmitAllowed')}",
        "",
        "Allowed actions:",
    ]
    for action in decision.get("allowedActions", []):
        lines.append(f"- {action}")

    lines.extend(["", "Blockers:"])
    blockers = decision.get("blockers") or []
    if not blockers:
        lines.append("- none")
    for blocker in blockers:
        lines.append(f"- {blocker}")

    lines.extend(["", "Warnings:"])
    warnings = decision.get("warnings") or []
    if not warnings:
        lines.append("- none")
    for warning in warnings:
        lines.append(f"- {warning}")

    lines.extend(["", "Next milestones:"])
    for milestone in decision.get("nextMilestones", []):
        lines.append(f"- {milestone}")

    lines.extend(
        [
            "",
            "Evidence:",
            f"- scored paper tickets: {evidence.get('scoredPaperTickets')}",
            f"- performance verdict: {(evidence.get('performanceVerdict') or {}).get('level')}",
            f"- strategy lab verdict: {(evidence.get('strategyLabVerdict') or {}).get('level')}",
            f"- strategy candidates: {', '.join(evidence.get('strategyPromotionCandidates') or []) or 'none'}",
            f"- exposure verdict: {(evidence.get('exposureVerdict') or {}).get('level')}",
            f"- market regime: {(evidence.get('marketRegime') or {}).get('regime')}",
            f"- broker preview orders: {evidence.get('brokerPreviewCount')}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def save_authority_manifest(manifest: dict[str, Any]) -> None:
    """Persist the authority manifest JSON and text memo."""
    ensure_dirs()
    AUTHORITY_MANIFEST_FILE.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    AUTHORITY_MANIFEST_TEXT_FILE.write_text(authority_text(manifest), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Inferno automation authority manifest.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and AUTHORITY_MANIFEST_TEXT_FILE.exists():
        print(AUTHORITY_MANIFEST_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    manifest = build_authority_manifest()
    save_authority_manifest(manifest)
    print(authority_text(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
