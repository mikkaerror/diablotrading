from __future__ import annotations

"""Shared model command center for the Inferno desk.

This module creates a small repo-native collaboration layer so multiple models
can work through the same operating picture instead of passing context through
chat alone. It is intentionally simple:

1. aggregate the latest desk artifacts into one machine-readable brain file
2. render a human-readable command-center memo for fast handoffs
3. keep a lightweight note log for Codex / Claude / human operator updates
4. track active missions in one durable queue

It does not place trades, touch broker order entry, or change authority.
"""

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

from inferno_config import ROOT, TOS_ALLOWED_ACCOUNT_SUFFIXES, local_now
from inferno_io import append_text, atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


COORDINATION_DIR = ROOT / "coordination"
PROMPTS_DIR = COORDINATION_DIR / "prompts"
MODEL_NOTES_FILE = COORDINATION_DIR / "model_notes.jsonl"
ACTIVE_MISSIONS_FILE = COORDINATION_DIR / "active_missions.json"

MODEL_COMMAND_CENTER_FILE = DATA_DIR / "inferno_model_command_center.json"
MODEL_COMMAND_CENTER_TEXT_FILE = REPORTS_DIR / "model_command_center_latest.txt"

DEPLOY_PREFLIGHT_FILE = DATA_DIR / "inferno_deploy_preflight.json"
OPS_MAINTENANCE_FILE = DATA_DIR / "inferno_ops_maintenance.json"
LIVE_POSITION_REVIEW_FILE = DATA_DIR / "inferno_live_position_review.json"
LIVE_BOOK_REVIEW_PACKET_FILE = DATA_DIR / "inferno_live_book_review_packet.json"
LIVE_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_live_account_sync.json"
CAPITAL_DEPLOYMENT_READINESS_FILE = DATA_DIR / "inferno_capital_deployment_readiness.json"
RISK_GATE_AUDIT_FILE = DATA_DIR / "inferno_risk_gate_audit.json"
PAPER_TEST_DIRECTOR_FILE = DATA_DIR / "inferno_paper_test_director.json"
PAPER_BOTTLENECK_REDUCER_FILE = DATA_DIR / "inferno_paper_bottleneck_reducer.json"
SCENARIO_BACKTEST_FILE = DATA_DIR / "inferno_scenario_backtest.json"
PAPER_EVIDENCE_LOOP_FILE = DATA_DIR / "inferno_paper_evidence_loop.json"
PERFORMANCE_ANALYTICS_FILE = DATA_DIR / "inferno_performance_analytics.json"
STRATEGY_LAB_FILE = DATA_DIR / "inferno_strategy_lab.json"
SHADOW_EVIDENCE_FILE = DATA_DIR / "inferno_shadow_evidence.json"
EDGE_RESEARCH_FILE = DATA_DIR / "inferno_edge_research.json"
CONVICTION_RESEARCH_FILE = DATA_DIR / "inferno_conviction_research.json"
MATH_VERIFY_FILE = DATA_DIR / "inferno_math_verify.json"


REPORTING_MAP: tuple[dict[str, str], ...] = (
    {
        "lane": "handoff",
        "question": "What should a fresh model read first?",
        "artifact": "reports/usage_optimizer_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "health",
        "question": "Is the desk broken?",
        "artifact": "reports/doctor_latest.txt",
        "owner": "operator",
    },
    {
        "lane": "command",
        "question": "What matters right now?",
        "artifact": "reports/model_command_center_latest.txt",
        "owner": "codex",
    },
    {
        "lane": "capital",
        "question": "Can new cash be sized?",
        "artifact": "reports/capital_deployment_readiness_latest.txt",
        "owner": "codex",
    },
    {
        "lane": "risk",
        "question": "Which gates are blocking?",
        "artifact": "reports/risk_gate_audit_latest.txt",
        "owner": "codex",
    },
    {
        "lane": "live-book",
        "question": "What is in the approved read-only account?",
        "artifact": "reports/live_position_review_latest.txt",
        "owner": "codex",
    },
    {
        "lane": "paper",
        "question": "What paper evidence is next?",
        "artifact": "reports/paper_test_director_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "paper-scenarios",
        "question": "What 10+ paper/shadow scenarios should we track?",
        "artifact": "reports/paper_bottleneck_reducer_latest.csv",
        "owner": "shared",
    },
    {
        "lane": "scenario-backtest",
        "question": "What can the current scenario slate honestly teach us from closed evidence?",
        "artifact": "reports/scenario_backtest_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "math",
        "question": "Do the formulas still check out?",
        "artifact": "reports/math_verify_latest.txt",
        "owner": "codex",
    },
    {
        "lane": "conviction",
        "question": "What's the math case for and against each ready trade?",
        "artifact": "reports/trade_conviction_audit_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "blowup-guardrails",
        "question": "Which historical blow-up patterns is today's slate brushing up against?",
        "artifact": "reports/blowup_guardrails_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "conviction-research",
        "question": "Which giants, sleepers, and near-term winners deserve attention?",
        "artifact": "reports/conviction_research_latest.txt",
        "owner": "codex",
    },
    {
        "lane": "briefing",
        "question": "What did the morning desk say?",
        "artifact": "reports/morning_brief_latest.txt",
        "owner": "automation",
    },
)


def ensure_command_center_dirs() -> None:
    """Create the collaboration directories and queue files if missing."""
    ensure_dirs()
    COORDINATION_DIR.mkdir(exist_ok=True)
    PROMPTS_DIR.mkdir(exist_ok=True)
    if not ACTIVE_MISSIONS_FILE.exists():
        atomic_write_text(ACTIVE_MISSIONS_FILE, "[]\n")
    if not MODEL_NOTES_FILE.exists():
        atomic_write_text(MODEL_NOTES_FILE, "")


def text(value: Any) -> str:
    """Normalize loose values into compact display text."""
    return str(value or "").strip()


def number(value: Any, default: float = 0.0) -> float:
    """Parse numeric artifact values without trusting display formatting."""
    cleaned = text(value).replace("$", "").replace(",", "").replace("%", "")
    try:
        return float(cleaned)
    except ValueError:
        return default


def command_cash_arg(value: Any) -> str:
    """Render deployable cash for copy/paste-safe command snippets."""
    cash = number(value)
    if cash <= 0:
        return "<deployable-cash>"
    if cash.is_integer():
        return str(int(cash))
    return f"{cash:.2f}"


def load_active_missions() -> list[dict[str, Any]]:
    """Load the active mission queue safely."""
    data = load_json_file(ACTIVE_MISSIONS_FILE)
    return data if isinstance(data, list) else []


def save_active_missions(missions: list[dict[str, Any]]) -> None:
    """Persist the active mission queue."""
    ensure_command_center_dirs()
    atomic_write_json(ACTIVE_MISSIONS_FILE, missions)


def load_notes(limit: int | None = None) -> list[dict[str, Any]]:
    """Load the shared model note log from JSONL."""
    ensure_command_center_dirs()
    notes: list[dict[str, Any]] = []
    for raw_line in MODEL_NOTES_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            notes.append(payload)
    if limit is not None:
        return notes[-limit:]
    return notes


def append_note(
    *,
    author: str,
    title: str,
    body: str,
    priority: str = "normal",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Append one note to the shared collaboration log."""
    ensure_command_center_dirs()
    entry = {
        "id": f"note-{uuid.uuid4().hex[:10]}",
        "createdAt": local_now().isoformat(),
        "author": text(author).lower() or "unknown",
        "title": text(title) or "Untitled note",
        "body": text(body),
        "priority": text(priority).lower() or "normal",
        "tags": [text(tag) for tag in (tags or []) if text(tag)],
    }
    append_text(MODEL_NOTES_FILE, json.dumps(entry) + "\n")
    return entry


def add_mission(
    *,
    title: str,
    body: str,
    owner: str = "shared",
    status: str = "pending",
    priority: str = "normal",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Add a new active mission for the shared model queue."""
    missions = load_active_missions()
    now = local_now().isoformat()
    entry = {
        "id": f"mission-{uuid.uuid4().hex[:8]}",
        "createdAt": now,
        "updatedAt": now,
        "title": text(title) or "Untitled mission",
        "body": text(body),
        "owner": text(owner).lower() or "shared",
        "status": text(status).lower() or "pending",
        "priority": text(priority).lower() or "normal",
        "tags": [text(tag) for tag in (tags or []) if text(tag)],
    }
    missions.append(entry)
    save_active_missions(missions)
    return entry


def update_mission(
    mission_id: str,
    *,
    title: str | None = None,
    body: str | None = None,
    owner: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Update one mission in the active queue."""
    missions = load_active_missions()
    for mission in missions:
        if mission.get("id") != mission_id:
            continue
        if title is not None:
            mission["title"] = text(title)
        if body is not None:
            mission["body"] = text(body)
        if owner is not None:
            mission["owner"] = text(owner).lower()
        if status is not None:
            mission["status"] = text(status).lower()
        if priority is not None:
            mission["priority"] = text(priority).lower()
        if tags is not None:
            mission["tags"] = [text(tag) for tag in tags if text(tag)]
        mission["updatedAt"] = local_now().isoformat()
        save_active_missions(missions)
        return mission
    raise SystemExit(f"Unknown mission id: {mission_id}")


def artifact_summary(path: Path, *, keys: tuple[str, ...] = ("verdict", "message", "generatedAt")) -> dict[str, Any]:
    """Return a compact summary for one JSON artifact."""
    payload = load_json_file(path) or {}
    if not payload:
        return {"present": False, "path": str(path)}
    summary = {"present": True, "path": str(path)}
    for key in keys:
        summary[key] = payload.get(key)
    return summary


def status_value(summary: dict[str, Any], key: str = "verdict") -> str:
    """Extract a printable status value from an artifact summary."""
    if not summary.get("present"):
        return "missing"
    value = summary.get(key)
    if value is None and key != "ok":
        value = summary.get("ok")
    return text(value) or "unknown"


def approved_account_scope() -> str:
    """Describe the local live-account allowlist without hard-coding it in docs."""
    if TOS_ALLOWED_ACCOUNT_SUFFIXES:
        return "approved suffix " + ",".join(TOS_ALLOWED_ACCOUNT_SUFFIXES)
    return "the locally configured approved account suffix"


def strategy_lab_status(payload: dict[str, Any]) -> dict[str, Any]:
    """Summarize strategy-lab artifacts that store verdicts in nested shape."""
    if not payload:
        return {"present": False, "path": str(STRATEGY_LAB_FILE)}
    desk_verdict = payload.get("deskVerdict") or {}
    overall_verdict = ((payload.get("overall") or {}).get("verdict") or {})
    return {
        "present": True,
        "path": str(STRATEGY_LAB_FILE),
        "verdict": payload.get("verdict") or desk_verdict.get("level") or overall_verdict.get("level"),
        "generatedAt": payload.get("generatedAt"),
        "message": payload.get("message") or desk_verdict.get("message") or overall_verdict.get("message"),
    }


def build_executive_summary(
    *,
    status: dict[str, dict[str, Any]],
    metrics: dict[str, Any],
    next_actions: list[str],
) -> list[str]:
    """Compress the desk state into the four lines a PM needs first."""
    first_action = next_actions[0] if next_actions else "Review the canonical report map."
    return [
        (
            "Capital: "
            f"{status_value(status.get('capitalDeploymentReadiness') or {})}; "
            f"risk gates {status_value(status.get('riskGateAudit') or {})}; "
            f"auto-live allowed={metrics.get('autoLiveAllowed')}"
        ),
        (
            "Live book: "
            f"{status_value(status.get('liveAccountSync') or {})}; "
            f"fragile={metrics.get('liveFragile', 0)}; "
            f"hard blockers={metrics.get('liveBookHardBlockers', 0)}"
        ),
        (
            "Evidence: "
            f"paper={status_value(status.get('paperTestDirector') or {})}; "
            f"scenarios={metrics.get('paperScenarioCount', 0)}; "
            f"scenario evidence={metrics.get('scenarioClosedEvidenceCount', 0)}; "
            f"promotion gap={metrics.get('paperRemainingForPromotion', 0)}; "
            f"math={status_value(status.get('mathVerify') or {})}"
        ),
        f"Next move: {first_action}",
    ]


def build_command_center() -> dict[str, Any]:
    """Aggregate the latest desk state into one shared command-center artifact."""
    ensure_command_center_dirs()

    deploy = load_json_file(DEPLOY_PREFLIGHT_FILE) or {}
    ops = load_json_file(OPS_MAINTENANCE_FILE) or {}
    live_review = load_json_file(LIVE_POSITION_REVIEW_FILE) or {}
    live_book_packet = load_json_file(LIVE_BOOK_REVIEW_PACKET_FILE) or {}
    live_sync = load_json_file(LIVE_ACCOUNT_SYNC_FILE) or {}
    capital_readiness = load_json_file(CAPITAL_DEPLOYMENT_READINESS_FILE) or {}
    risk_gate_audit = load_json_file(RISK_GATE_AUDIT_FILE) or {}
    paper_director = load_json_file(PAPER_TEST_DIRECTOR_FILE) or {}
    paper_reducer = load_json_file(PAPER_BOTTLENECK_REDUCER_FILE) or {}
    scenario_backtest = load_json_file(SCENARIO_BACKTEST_FILE) or {}
    paper_loop = load_json_file(PAPER_EVIDENCE_LOOP_FILE) or {}
    performance = load_json_file(PERFORMANCE_ANALYTICS_FILE) or {}
    strategy_lab = load_json_file(STRATEGY_LAB_FILE) or {}
    shadow = load_json_file(SHADOW_EVIDENCE_FILE) or {}
    edge = load_json_file(EDGE_RESEARCH_FILE) or {}
    conviction_research = load_json_file(CONVICTION_RESEARCH_FILE) or {}
    math_verify = load_json_file(MATH_VERIFY_FILE) or {}

    missions = load_active_missions()
    notes = load_notes(limit=12)

    live_counts = live_review.get("counts") or {}
    live_packet_counts = live_book_packet.get("counts") or {}
    paper_counts = paper_director.get("counts") or {}
    loop_counts = paper_loop.get("counts") or {}
    deployable_cash_arg = command_cash_arg((capital_readiness.get("guardrails") or {}).get("deployableCash"))

    next_actions: list[str] = []
    next_actions.extend(live_book_packet.get("unlockChecklist") or [])
    next_actions.extend(live_review.get("nextActions") or [])
    next_actions.extend(paper_director.get("nextActions") or [])
    next_actions.extend(paper_loop.get("actions") or [])
    if not next_actions:
        next_actions.append("No explicit next actions were found; review the latest artifacts manually.")

    system_status = {
        "deployPreflight": artifact_summary(DEPLOY_PREFLIGHT_FILE, keys=("verdict", "message", "generatedAt", "coreReady", "cloudReady", "brokerDesktopReady")),
        "opsMaintenance": artifact_summary(OPS_MAINTENANCE_FILE, keys=("ok", "generatedAt")),
        "liveAccountSync": artifact_summary(LIVE_ACCOUNT_SYNC_FILE, keys=("verdict", "message", "generatedAt", "matchedSuffix")),
        "livePositionReview": artifact_summary(LIVE_POSITION_REVIEW_FILE, keys=("verdict", "message", "generatedAt")),
        "liveBookReviewPacket": artifact_summary(LIVE_BOOK_REVIEW_PACKET_FILE, keys=("verdict", "generatedAt", "capitalReadinessVerdict", "manualDeploymentAllowed", "autoLiveAllowed")),
        "capitalDeploymentReadiness": artifact_summary(CAPITAL_DEPLOYMENT_READINESS_FILE, keys=("verdict", "message", "generatedAt", "deploymentDate", "manualDeploymentAllowed", "autoLiveAllowed")),
        "riskGateAudit": artifact_summary(RISK_GATE_AUDIT_FILE, keys=("verdict", "message", "generatedAt", "liveTradingAllowed")),
        "paperTestDirector": artifact_summary(PAPER_TEST_DIRECTOR_FILE, keys=("verdict", "generatedAt", "authorityLevel")),
        "paperBottleneckReducer": artifact_summary(PAPER_BOTTLENECK_REDUCER_FILE, keys=("verdict", "generatedAt", "scenarioTarget")),
        "scenarioBacktest": artifact_summary(SCENARIO_BACKTEST_FILE, keys=("stage", "generatedAt", "researchOnly", "promotable", "scenarioCount")),
        "paperEvidenceLoop": artifact_summary(PAPER_EVIDENCE_LOOP_FILE, keys=("verdict", "generatedAt", "strategyLabVerdict")),
        "performanceAnalytics": artifact_summary(PERFORMANCE_ANALYTICS_FILE, keys=("verdict", "generatedAt", "message")),
        "strategyLab": strategy_lab_status(strategy_lab),
        "shadowEvidence": artifact_summary(SHADOW_EVIDENCE_FILE, keys=("verdict", "generatedAt", "message")),
        "edgeResearch": artifact_summary(EDGE_RESEARCH_FILE, keys=("verdict", "generatedAt", "message")),
        "convictionResearch": artifact_summary(CONVICTION_RESEARCH_FILE, keys=("stage", "generatedAt", "researchOnly", "promotable")),
        "mathVerify": artifact_summary(MATH_VERIFY_FILE, keys=("verdict", "generatedAt", "totalViolations", "missingArtifacts")),
    }
    headline_metrics = {
        "liveSupported": live_counts.get("supported", 0),
        "liveReview": live_counts.get("review", 0),
        "liveFragile": live_counts.get("fragile", 0),
        "liveBookHardBlockers": live_packet_counts.get("hardBlockers", 0),
        "liveBookWarnings": live_packet_counts.get("warnings", 0),
        "paperStageable": paper_counts.get("stageableNow", 0),
        "paperAutoSelected": paper_counts.get("autoPaperSelected", 0),
        "paperApprovalOnly": paper_counts.get("approvalOnly", 0),
        "paperScenarioCount": (paper_reducer.get("counts") or {}).get("scenarios", 0),
        "paperScenarioTopFive": [
            item.get("ticker")
            for item in (paper_reducer.get("topFiveFocus") or [])
        ],
        "scenarioClosedEvidenceCount": scenario_backtest.get("closedEvidenceCount", 0),
        "scenarioBacktestVerdicts": (scenario_backtest.get("counts") or {}).get("verdictCounts") or {},
        "scenarioBacktestTopFocus": [
            item.get("ticker")
            for item in (scenario_backtest.get("topFocus") or [])
        ],
        "paperRemainingForPromotion": loop_counts.get("remainingForPromotion", 0),
        "capitalDeploymentVerdict": capital_readiness.get("verdict"),
        "capitalDeploymentDate": capital_readiness.get("deploymentDate"),
        "autoLiveAllowed": capital_readiness.get("autoLiveAllowed"),
        "riskGateVerdict": risk_gate_audit.get("verdict"),
        "riskGateHardFails": (risk_gate_audit.get("summary") or {}).get("hardFails"),
        "riskGatePromotionFails": (risk_gate_audit.get("summary") or {}).get("promotionFails"),
        "riskGateWarnings": (risk_gate_audit.get("summary") or {}).get("warnings"),
        "shadowTracked": (shadow.get("counts") or {}).get("tracked", shadow.get("trackedCount")),
        "shadowClosed": (shadow.get("counts") or {}).get("closed", shadow.get("closedCount")),
        "edgeRanked": len(edge.get("ranked") or []),
        "convictionBehemoths": [
            item.get("ticker")
            for item in (conviction_research.get("behemoths") or [])[:5]
        ],
        "convictionSleepers": [
            item.get("ticker")
            for item in (conviction_research.get("sleepers") or [])[:5]
        ],
        "convictionNearTermWinners": [
            item.get("ticker")
            for item in (conviction_research.get("nearTermWinners") or [])[:5]
        ],
        "convictionBestBalanced": [
            item.get("ticker")
            for item in (conviction_research.get("bestBalanced") or [])[:5]
        ],
        "mathVerifyVerdict": math_verify.get("verdict"),
        "mathViolations": math_verify.get("totalViolations"),
        "mathMissingArtifacts": math_verify.get("missingArtifacts"),
    }

    payload = {
        "generatedAt": local_now().isoformat(),
        "mission": {
            "name": "Inferno Desk Shared Command Center",
            "goal": "Keep the earnings desk automated, testable, and safe while building toward broker-assisted execution without granting unapproved authority.",
        },
        "safetyRails": [
            "Never place a trade without explicit user confirmation.",
            f"Only {approved_account_scope()} is approved for read-only automation.",
            "Do not open a new thinkorswim instance or extra TOS window.",
            "Use the already-open TOS window only.",
            "Paper evidence remains the promotion gate.",
        ],
        "systemStatus": system_status,
        "headlineMetrics": headline_metrics,
        "executiveSummary": build_executive_summary(
            status=system_status,
            metrics=headline_metrics,
            next_actions=next_actions,
        ),
        "reportingMap": list(REPORTING_MAP),
        "recommendedCommands": [
            f'cd "{ROOT}"',
            "python3 inferno_doctor.py",
            "./run_inferno_dawn_cycle.sh",
            "./run_inferno_strike_cycle.sh",
            "./run_inferno_ops_maintenance.sh",
            "./run_inferno_scenario_backtest.sh",
            "./run_inferno_live_account_sync.sh",
            "./run_inferno_live_position_review.sh",
            "./run_inferno_live_book_review_packet.sh",
            "./run_inferno_usage_optimizer.sh",
            f"./run_inferno_action_pulse.sh --phase manual --deployable-cash {deployable_cash_arg} --send --force-send",
            f"./run_inferno_capital_launch_check.sh --deployable-cash {deployable_cash_arg}",
            f"./run_inferno_capital_deployment_readiness.sh --deployable-cash {deployable_cash_arg}",
            f"./run_inferno_strike_cycle.sh --deployable-cash {deployable_cash_arg}",
            "./run_inferno_risk_gate_audit.sh",
            "./run_inferno_conviction_research.sh",
        ],
        "recommendedReads": [
            str(ROOT / "reports/usage_optimizer_latest.txt"),
            str(ROOT / "reports/model_command_center_latest.txt"),
            str(ROOT / "reports/central_command_latest.txt"),
            str(ROOT / "docs/PROJECT_STATUS.md"),
            str(ROOT / "docs/MODEL_COLLABORATION_BRIEF.md"),
            str(ROOT / "docs/RUNBOOK.md"),
            str(ROOT / "reports/deploy_preflight_latest.txt"),
            str(ROOT / "reports/action_pulse_latest.txt"),
            str(ROOT / "reports/capital_launch_check_latest.txt"),
            str(ROOT / "reports/capital_deployment_readiness_latest.txt"),
            str(ROOT / "reports/live_book_review_packet_latest.txt"),
            str(ROOT / "reports/risk_gate_audit_latest.txt"),
            str(ROOT / "reports/scenario_backtest_latest.txt"),
            str(ROOT / "reports/conviction_research_latest.txt"),
            str(ROOT / "reports/ops_maintenance_latest.txt"),
            str(ROOT / "reports/live_position_review_latest.txt"),
            str(ROOT / "reports/trade_conviction_audit_latest.txt"),
            str(ROOT / "reports/blowup_guardrails_latest.txt"),
        ],
        "nextActions": next_actions[:12],
        "activeMissions": missions,
        "recentNotes": notes,
        "collaborationPrompt": (
            "Start with the usage optimizer packet, preserve the safety rails, claim or update a mission, "
            "append a note with what you changed, and rebuild central command plus usage optimizer."
        ),
    }
    save_command_center(payload)
    return payload


def render_command_center_text(payload: dict[str, Any]) -> str:
    """Render the shared command-center payload into a readable memo."""
    status = payload.get("systemStatus") or {}
    metrics = payload.get("headlineMetrics") or {}
    lines = [
        "Inferno Model Command Center",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Mission: {(payload.get('mission') or {}).get('goal')}",
        "",
        "Safety rails:",
    ]
    for rail in payload.get("safetyRails") or []:
        lines.append(f"- {rail}")

    lines.extend(["", "Executive summary:"])
    for item in payload.get("executiveSummary") or []:
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "System status:",
            f"- Deploy preflight: {status_value(status.get('deployPreflight') or {})}",
            f"- Live account sync: {status_value(status.get('liveAccountSync') or {})}",
            f"- Live position review: {status_value(status.get('livePositionReview') or {})}",
            f"- Live book review packet: {status_value(status.get('liveBookReviewPacket') or {})}",
            f"- Capital deployment readiness: {status_value(status.get('capitalDeploymentReadiness') or {})}",
            f"- Risk gate audit: {status_value(status.get('riskGateAudit') or {})}",
            f"- Paper director: {status_value(status.get('paperTestDirector') or {})}",
            f"- Paper bottleneck reducer: {status_value(status.get('paperBottleneckReducer') or {})}",
            f"- Scenario backtest: {status_value(status.get('scenarioBacktest') or {}, key='stage')}",
            f"- Paper evidence loop: {status_value(status.get('paperEvidenceLoop') or {})}",
            f"- Math verify: {status_value(status.get('mathVerify') or {})}",
            f"- Conviction research: {status_value(status.get('convictionResearch') or {}, key='stage')}",
            "",
            "Headline metrics:",
            f"- Live supported: {metrics.get('liveSupported', 0)}",
            f"- Live fragile: {metrics.get('liveFragile', 0)}",
            f"- Live hard blockers: {metrics.get('liveBookHardBlockers', 0)}",
            f"- Live review warnings: {metrics.get('liveBookWarnings', 0)}",
            f"- Paper stageable: {metrics.get('paperStageable', 0)}",
            f"- Paper auto-selected: {metrics.get('paperAutoSelected', 0)}",
            f"- Paper approval-only: {metrics.get('paperApprovalOnly', 0)}",
            f"- Paper scenarios: {metrics.get('paperScenarioCount', 0)}",
            f"- Paper top five: {', '.join(metrics.get('paperScenarioTopFive') or []) or 'none'}",
            f"- Scenario backtest evidence: {metrics.get('scenarioClosedEvidenceCount', 0)}",
            f"- Scenario backtest verdicts: {json.dumps(metrics.get('scenarioBacktestVerdicts') or {})}",
            f"- Scenario backtest focus: {', '.join(metrics.get('scenarioBacktestTopFocus') or []) or 'none'}",
            f"- Promotion gap: {metrics.get('paperRemainingForPromotion', 0)}",
            f"- Auto live allowed: {metrics.get('autoLiveAllowed')}",
            f"- Risk gate hard fails: {metrics.get('riskGateHardFails')}",
            f"- Math violations: {metrics.get('mathViolations')}",
            f"- Conviction giants: {', '.join(metrics.get('convictionBehemoths') or []) or 'none'}",
            f"- Conviction sleepers: {', '.join(metrics.get('convictionSleepers') or []) or 'none'}",
            f"- Conviction near-term: {', '.join(metrics.get('convictionNearTermWinners') or []) or 'none'}",
            f"- Conviction balanced: {', '.join(metrics.get('convictionBestBalanced') or []) or 'none'}",
            "",
            "Next actions:",
        ]
    )
    for action in payload.get("nextActions") or []:
        lines.append(f"- {action}")

    lines.extend(["", "Active missions:"])
    missions = payload.get("activeMissions") or []
    if not missions:
        lines.append("- none")
    for mission in missions[:10]:
        lines.append(
            f"- {mission.get('id')} | {mission.get('status')} | {mission.get('owner')} | {mission.get('title')}"
        )

    lines.extend(["", "Recent notes:"])
    notes = payload.get("recentNotes") or []
    if not notes:
        lines.append("- none")
    for note in notes[-8:]:
        lines.append(f"- {note.get('createdAt')} | {note.get('author')} | {note.get('title')}")

    lines.extend(["", "Canonical report map:"])
    for item in payload.get("reportingMap") or []:
        lines.append(
            f"- {item.get('lane')}: {item.get('question')} -> {item.get('artifact')}"
        )

    lines.extend(["", "Recommended commands:"])
    for command in payload.get("recommendedCommands") or []:
        lines.append(f"- {command}")

    return "\n".join(lines).rstrip() + "\n"


def save_command_center(payload: dict[str, Any]) -> None:
    """Persist the command-center JSON and text artifacts."""
    ensure_command_center_dirs()
    atomic_write_json(MODEL_COMMAND_CENTER_FILE, payload)
    atomic_write_text(MODEL_COMMAND_CENTER_TEXT_FILE, render_command_center_text(payload))


def parse_tags(raw: str) -> list[str]:
    """Parse a comma-delimited tag string."""
    return [text(chunk) for chunk in raw.split(",") if text(chunk)]


def onboard_digest(payload: dict[str, Any] | None = None) -> str:
    """Render the fast onboarding digest for a new model session.

    This is the closest analog to a Nate-Herk-style "onboarding skill": one
    command that prints the mission, safety rails, current verdict, claimed
    missions, top next actions, and a short read-list. The intent is to give a
    new model 30 seconds of context before it does anything.
    """
    payload = payload if payload is not None else build_command_center()
    safety_rails = payload.get("safetyRails") or []
    status = payload.get("systemStatus") or {}
    metrics = payload.get("headlineMetrics") or {}
    next_actions = (payload.get("nextActions") or [])[:3]
    missions = [
        mission for mission in (payload.get("activeMissions") or [])
        if str(mission.get("status") or "").lower() != "done"
    ][:5]
    recent_notes = (payload.get("recentNotes") or [])[-3:]

    lines = [
        "Inferno Onboarding Digest",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Mission: {(payload.get('mission') or {}).get('goal')}",
        "",
        "Non-negotiable safety rails:",
    ]
    for rail in safety_rails:
        lines.append(f"- {rail}")
    lines.extend([
        "",
        "Current verdict (one line each):",
        f"- Deploy preflight: {status_value(status.get('deployPreflight') or {})}",
        f"- Live account sync: {status_value(status.get('liveAccountSync') or {})} | "
        f"suffix {(status.get('liveAccountSync') or {}).get('matchedSuffix')}",
        f"- Live position review: {status_value(status.get('livePositionReview') or {})} | "
        f"fragile {metrics.get('liveFragile', 0)} | "
        f"hard blockers {metrics.get('liveBookHardBlockers', 0)}",
        f"- Capital deployment: {status_value(status.get('capitalDeploymentReadiness') or {})} | "
        f"date {metrics.get('capitalDeploymentDate')}",
        f"- Risk gates: {status_value(status.get('riskGateAudit') or {})} | "
        f"hard fails {metrics.get('riskGateHardFails')}",
        f"- Strategy lab: {status_value(status.get('strategyLab') or {})} | "
        f"remaining {metrics.get('paperRemainingForPromotion', 0)}",
        "",
        "Currently active missions:",
    ])
    if not missions:
        lines.append("- none claimed")
    for mission in missions:
        lines.append(
            f"- {mission.get('id')} | {mission.get('status')} | "
            f"owner={mission.get('owner')} | {mission.get('title')}"
        )
    lines.extend(["", "Top next actions:"])
    if not next_actions:
        lines.append("- none recorded")
    for action in next_actions:
        lines.append(f"- {action}")
    lines.extend(["", "Recent notes:"])
    if not recent_notes:
        lines.append("- none")
    for note in recent_notes:
        lines.append(
            f"- {note.get('createdAt')} | {note.get('author')} | {note.get('title')}"
        )
    lines.extend([
        "",
        "Read before doing anything:",
        "- reports/usage_optimizer_latest.txt",
        "- reports/model_command_center_latest.txt",
        "- reports/central_command_latest.txt",
        "- docs/PROJECT_STATUS.md",
        "- docs/MODEL_COLLABORATION_BRIEF.md",
        "- docs/RUNBOOK.md only when you need operating procedure detail",
        "",
        "Collaboration prompt:",
        f"  {payload.get('collaborationPrompt')}",
    ])
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser for the command center."""
    parser = argparse.ArgumentParser(description="Shared model command center for the Inferno desk.")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("build")
    subparsers.add_parser("status")
    subparsers.add_parser("onboard")

    note_parser = subparsers.add_parser("note")
    note_parser.add_argument("--author", required=True)
    note_parser.add_argument("--title", required=True)
    note_parser.add_argument("--body", required=True)
    note_parser.add_argument("--priority", default="normal")
    note_parser.add_argument("--tags", default="")

    mission_add = subparsers.add_parser("mission-add")
    mission_add.add_argument("--title", required=True)
    mission_add.add_argument("--body", required=True)
    mission_add.add_argument("--owner", default="shared")
    mission_add.add_argument("--status", default="pending")
    mission_add.add_argument("--priority", default="normal")
    mission_add.add_argument("--tags", default="")

    mission_update = subparsers.add_parser("mission-update")
    mission_update.add_argument("--id", required=True)
    mission_update.add_argument("--title")
    mission_update.add_argument("--body")
    mission_update.add_argument("--owner")
    mission_update.add_argument("--status")
    mission_update.add_argument("--priority")
    mission_update.add_argument("--tags")
    return parser


def main() -> int:
    """Run the command-center CLI."""
    parser = build_parser()
    args = parser.parse_args()
    command = args.command or "build"

    if command == "build":
        payload = build_command_center()
        print(render_command_center_text(payload))
        return 0

    if command == "status":
        if MODEL_COMMAND_CENTER_TEXT_FILE.exists():
            print(MODEL_COMMAND_CENTER_TEXT_FILE.read_text(encoding="utf-8"))
            return 0
        payload = build_command_center()
        print(render_command_center_text(payload))
        return 0

    if command == "onboard":
        payload = build_command_center()
        print(onboard_digest(payload))
        return 0

    if command == "note":
        note = append_note(
            author=args.author,
            title=args.title,
            body=args.body,
            priority=args.priority,
            tags=parse_tags(args.tags),
        )
        payload = build_command_center()
        print(json.dumps({"note": note, "commandCenterGeneratedAt": payload.get("generatedAt")}, indent=2))
        return 0

    if command == "mission-add":
        mission = add_mission(
            title=args.title,
            body=args.body,
            owner=args.owner,
            status=args.status,
            priority=args.priority,
            tags=parse_tags(args.tags),
        )
        payload = build_command_center()
        print(json.dumps({"mission": mission, "commandCenterGeneratedAt": payload.get("generatedAt")}, indent=2))
        return 0

    if command == "mission-update":
        mission = update_mission(
            args.id,
            title=args.title,
            body=args.body,
            owner=args.owner,
            status=args.status,
            priority=args.priority,
            tags=parse_tags(args.tags) if args.tags is not None else None,
        )
        payload = build_command_center()
        print(json.dumps({"mission": mission, "commandCenterGeneratedAt": payload.get("generatedAt")}, indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
