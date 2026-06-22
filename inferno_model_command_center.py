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
from inferno_reporting_summary import (
    build_freshness_panel,
    build_tos_visibility_summary,
    render_freshness_lines,
    render_tos_visibility_line,
)
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


COORDINATION_DIR = ROOT / "coordination"
PROMPTS_DIR = COORDINATION_DIR / "prompts"
MODEL_NOTES_FILE = COORDINATION_DIR / "model_notes.jsonl"
ACTIVE_MISSIONS_FILE = COORDINATION_DIR / "active_missions.json"

MODEL_COMMAND_CENTER_FILE = DATA_DIR / "inferno_model_command_center.json"
MODEL_COMMAND_CENTER_TEXT_FILE = REPORTS_DIR / "model_command_center_latest.txt"
WHILE_AWAY_PACKET_FILE = DATA_DIR / "inferno_while_away_packet.json"

DEPLOY_PREFLIGHT_FILE = DATA_DIR / "inferno_deploy_preflight.json"
OPS_MAINTENANCE_FILE = DATA_DIR / "inferno_ops_maintenance.json"
LIVE_POSITION_REVIEW_FILE = DATA_DIR / "inferno_live_position_review.json"
LIVE_BOOK_REVIEW_PACKET_FILE = DATA_DIR / "inferno_live_book_review_packet.json"
LIVE_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_live_account_sync.json"
SCHWAB_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_schwab_account_sync.json"
SCHWAB_PRICE_HISTORY_FILE = DATA_DIR / "inferno_schwab_price_history.json"
SCHWAB_TOS_METRICS_SYNC_FILE = DATA_DIR / "inferno_schwab_tos_metrics_sync.json"
CAPITAL_DEPLOYMENT_READINESS_FILE = DATA_DIR / "inferno_capital_deployment_readiness.json"
CAPITAL_SCENARIO_MATRIX_FILE = DATA_DIR / "inferno_capital_scenario_matrix.json"
ACCOUNT_OPTIMIZATION_FILE = DATA_DIR / "inferno_account_optimization.json"
RISK_GATE_AUDIT_FILE = DATA_DIR / "inferno_risk_gate_audit.json"
PAPER_TEST_DIRECTOR_FILE = DATA_DIR / "inferno_paper_test_director.json"
PAPER_BOTTLENECK_REDUCER_FILE = DATA_DIR / "inferno_paper_bottleneck_reducer.json"
FAST_PAPER_COHORT_FILE = DATA_DIR / "inferno_fast_paper_cohort.json"
PAPER_MTM_FILE = DATA_DIR / "inferno_paper_mark_to_market.json"
TRADE_MANAGEMENT_FILE = DATA_DIR / "inferno_trade_management.json"
SCENARIO_EVIDENCE_FILE = DATA_DIR / "inferno_scenario_evidence.json"
SCENARIO_BACKTEST_FILE = DATA_DIR / "inferno_scenario_backtest.json"
SCORE_CALIBRATION_FILE = DATA_DIR / "inferno_score_calibration.json"
EXPECTED_MOVE_LEDGER_FILE = DATA_DIR / "inferno_expected_move_ledger.json"
STRATEGY_ALTERNATIVE_SCORER_FILE = DATA_DIR / "inferno_strategy_alternative_scorer.json"
STRATEGY_ALTERNATIVE_PRICING_FILE = DATA_DIR / "inferno_strategy_alternative_pricing.json"
STRATEGY_SHADOW_COMPARISON_FILE = DATA_DIR / "inferno_strategy_shadow_comparison.json"
PAPER_EVIDENCE_LOOP_FILE = DATA_DIR / "inferno_paper_evidence_loop.json"
PERFORMANCE_ANALYTICS_FILE = DATA_DIR / "inferno_performance_analytics.json"
STRATEGY_LAB_FILE = DATA_DIR / "inferno_strategy_lab.json"
SHADOW_EVIDENCE_FILE = DATA_DIR / "inferno_shadow_evidence.json"
EDGE_RESEARCH_FILE = DATA_DIR / "inferno_edge_research.json"
CONVICTION_RESEARCH_FILE = DATA_DIR / "inferno_conviction_research.json"
SCHWAB_EDGE_SIGNALS_FILE = DATA_DIR / "inferno_schwab_edge_signals.json"
OUTCOME_ATTRIBUTION_FILE = DATA_DIR / "inferno_outcome_attribution.json"
RULE_EDGE_DECAY_FILE = DATA_DIR / "inferno_rule_edge_decay.json"
SLIPPAGE_ESTIMATOR_FILE = DATA_DIR / "inferno_slippage_estimator.json"
PORTFOLIO_CORRELATION_FILE = DATA_DIR / "inferno_portfolio_correlation.json"
DRAWDOWN_PROTOCOL_FILE = DATA_DIR / "inferno_drawdown_protocol.json"
CONSENSUS_MONITOR_FILE = DATA_DIR / "inferno_consensus_monitor.json"
PAPER_VELOCITY_FILE = DATA_DIR / "inferno_paper_velocity.json"
CAPITAL_SCALING_FILE = DATA_DIR / "inferno_capital_scaling.json"
MATH_VERIFY_FILE = DATA_DIR / "inferno_math_verify.json"
TOS_FORMULA_AUDIT_FILE = DATA_DIR / "inferno_tos_formula_audit.json"
TOS_CUSTOM_METRICS_FILE = DATA_DIR / "inferno_tos_custom_metrics.json"
TOS_METRIC_THEORY_AUDIT_FILE = DATA_DIR / "inferno_tos_metric_theory_audit.json"
MARKET_MASTERY_PLAN_FILE = DATA_DIR / "inferno_market_mastery_plan.json"


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
        "lane": "while-away",
        "question": "What should I read when I am away from the desk?",
        "artifact": "reports/while_away_latest.txt",
        "owner": "codex",
    },
    {
        "lane": "capital",
        "question": "Can new cash be sized?",
        "artifact": "reports/capital_deployment_readiness_latest.txt",
        "owner": "codex",
    },
    {
        "lane": "capital-scenarios",
        "question": "How does the desk behave across likely cash amounts?",
        "artifact": "reports/capital_scenario_matrix_latest.txt",
        "owner": "codex",
    },
    {
        "lane": "account-optimization",
        "question": "Which growth levers and risk constraints matter at the current NLV?",
        "artifact": "reports/account_optimization_latest.txt",
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
        "lane": "schwab-account",
        "question": "What does the Schwab account API say about cash and positions?",
        "artifact": "reports/schwab_account_sync_latest.txt",
        "owner": "codex",
    },
    {
        "lane": "paper",
        "question": "What paper evidence is next?",
        "artifact": "reports/paper_test_director_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "fast-paper",
        "question": "How many option simulations are cycling for rapid exploratory evidence?",
        "artifact": "reports/fast_paper_cohort_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "paper-mtm",
        "question": "What are open paper tickets worth right now?",
        "artifact": "reports/paper_mark_to_market_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "paper-trade-management",
        "question": "Which open paper tickets need action under the playbook?",
        "artifact": "reports/trade_management_latest.txt",
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
        "lane": "scenario-evidence",
        "question": "Which daily slate observations have closed as underlying-move evidence?",
        "artifact": "reports/scenario_evidence_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "score-calibration",
        "question": "Do readiness/scenario scores behave like useful ranks?",
        "artifact": "reports/score_calibration_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "expected-move",
        "question": "Did long-vol realised moves clear their debit-implied hurdle?",
        "artifact": "reports/expected_move_ledger_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "strategy-alternatives",
        "question": "Which non-call defined-risk structure beats pressured long vol?",
        "artifact": "reports/strategy_alternative_scorer_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "strategy-alternative-pricing",
        "question": "Did the preferred alternatives price cleanly and pass paper risk?",
        "artifact": "reports/strategy_alternative_pricing_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "strategy-shadow-comparison",
        "question": "Which passing alternatives should be watched against long-vol and put-credit without staging?",
        "artifact": "reports/strategy_shadow_comparison_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "math",
        "question": "Do the formulas still check out?",
        "artifact": "reports/math_verify_latest.txt",
        "owner": "codex",
    },
    {
        "lane": "tos-formulas",
        "question": "Do the TOS-style RVOL, trend, level, momentum, and strength mirrors match the tracker?",
        "artifact": "reports/tos_formula_audit_latest.txt",
        "owner": "codex",
    },
    {
        "lane": "tos-custom-metrics",
        "question": "Have the user-authored ThinkScript metrics and latest TOS values been captured?",
        "artifact": "reports/tos_custom_metrics_latest.txt",
        "owner": "operator+codex",
    },
    {
        "lane": "tos-metric-theory",
        "question": "Are the custom metrics actually useful evidence, or are they just confirming the thesis?",
        "artifact": "reports/tos_metric_theory_audit_latest.txt",
        "owner": "codex",
    },
    {
        "lane": "schwab-price-history",
        "question": "Can Schwab daily candles feed the OHLCV-derived TOS metrics?",
        "artifact": "reports/schwab_price_history_latest.txt",
        "owner": "codex",
    },
    {
        "lane": "schwab-tos-metrics-sync",
        "question": "Were the visible TOS custom metrics regenerated from Schwab price history?",
        "artifact": "reports/schwab_tos_metrics_sync_latest.txt",
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
        "lane": "schwab-edge",
        "question": "Which Schwab tickers are capitalize-now vs thin-data today?",
        "artifact": "reports/schwab_edge_signals_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "outcome-attribution",
        "question": "What did we actually learn from each closed outcome?",
        "artifact": "reports/outcome_attribution_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "rule-edge-decay",
        "question": "Which conviction-audit rules are still earning their place?",
        "artifact": "reports/rule_edge_decay_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "slippage-estimator",
        "question": "How much edge do we lose to the spread by strategy family?",
        "artifact": "reports/slippage_estimator_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "portfolio-correlation",
        "question": "Are our active tickets actually independent bets?",
        "artifact": "reports/portfolio_correlation_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "drawdown-protocol",
        "question": "What's the desk's current drawdown and recommended sizing regime?",
        "artifact": "reports/drawdown_protocol_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "consensus-monitor",
        "question": "Are we contrarian today, or in the crowded trade?",
        "artifact": "reports/consensus_monitor_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "paper-velocity",
        "question": "Are we closing paper outcomes fast enough to clear the 30-gate?",
        "artifact": "reports/paper_velocity_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "capital-scaling",
        "question": "Is the per-ticket cap correctly sized for current NLV, or do we need to ack a new formula state?",
        "artifact": "reports/capital_scaling_latest.txt",
        "owner": "shared",
    },
    {
        "lane": "market-mastery",
        "question": "Which strategy, sizing, exit, and discipline improvements should the desk do next?",
        "artifact": "reports/market_mastery_next_actions_latest.txt",
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


def has_display_value(value: Any) -> bool:
    """Return true for real zero values while rejecting absent display fields."""
    if value is None:
        return False
    if isinstance(value, str) and text(value) == "":
        return False
    return True


def first_display_value(*values: Any) -> Any:
    """Return the first non-empty value without treating zero as missing."""
    for value in values:
        if has_display_value(value):
            return value
    return None


def display_value(value: Any) -> Any:
    """Render missing values as '-' without hiding numeric zero."""
    return value if has_display_value(value) else "-"


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
            notes.append(normalize_note(payload))
    if limit is not None:
        return notes[-limit:]
    return notes


def normalize_note(note: dict[str, Any]) -> dict[str, Any]:
    """Normalize Codex and Claude note schemas for clean command-center display."""
    normalized = dict(note)
    normalized["createdAt"] = text(note.get("createdAt") or note.get("ts") or note.get("timestamp"))
    normalized["author"] = text(note.get("author") or note.get("model") or "unknown")
    title = text(note.get("title"))
    if not title:
        summary = text(note.get("summary"))
        kind = text(note.get("kind"))
        # Claude handoff notes often use "kind" plus a long summary instead of
        # the Codex title field; prefer the summary so the command memo stays
        # useful instead of showing generic labels like "Ship".
        if summary:
            first_sentence = summary.split(". ", 1)[0]
            title = first_sentence[:93] + "..." if len(first_sentence) > 96 else first_sentence
        else:
            title = kind.replace("-", " ").title()
    normalized["title"] = title or "Untitled note"
    return normalized


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
            f"optimization={metrics.get('accountOptimizationVerdict')}; "
            f"edge-adjusted options max loss=${metrics.get('edgeAdjustedLiveOptionsMaxLoss', 0):,.2f}; "
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
            f"fast-paper={metrics.get('fastPaperVerdict')}; "
            f"fast closed={metrics.get('fastPaperClosedLifetime', 0)}; "
            f"scenarios={metrics.get('paperScenarioCount', 0)}; "
            f"scenario evidence={metrics.get('scenarioClosedEvidenceCount', 0)}; "
            f"scenario observations={metrics.get('scenarioClosedObservationCount', 0)}; "
            f"calibration={metrics.get('scoreCalibrationVerdict')}; "
            f"expected move={metrics.get('expectedMoveVerdict')}; "
            f"alternatives={metrics.get('strategyAlternativeVerdict')}; "
            f"alt pricing={metrics.get('strategyAlternativePricingVerdict')}; "
            f"shadow compare={metrics.get('strategyShadowComparisonVerdict')}; "
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
    while_away_packet = load_json_file(WHILE_AWAY_PACKET_FILE) or {}
    live_sync = load_json_file(LIVE_ACCOUNT_SYNC_FILE) or {}
    schwab_account_sync = load_json_file(SCHWAB_ACCOUNT_SYNC_FILE) or {}
    capital_readiness = load_json_file(CAPITAL_DEPLOYMENT_READINESS_FILE) or {}
    account_optimization = load_json_file(ACCOUNT_OPTIMIZATION_FILE) or {}
    risk_gate_audit = load_json_file(RISK_GATE_AUDIT_FILE) or {}
    paper_director = load_json_file(PAPER_TEST_DIRECTOR_FILE) or {}
    paper_reducer = load_json_file(PAPER_BOTTLENECK_REDUCER_FILE) or {}
    fast_paper = load_json_file(FAST_PAPER_COHORT_FILE) or {}
    paper_mtm = load_json_file(PAPER_MTM_FILE) or {}
    trade_management = load_json_file(TRADE_MANAGEMENT_FILE) or {}
    scenario_evidence = load_json_file(SCENARIO_EVIDENCE_FILE) or {}
    scenario_backtest = load_json_file(SCENARIO_BACKTEST_FILE) or {}
    score_calibration = load_json_file(SCORE_CALIBRATION_FILE) or {}
    expected_move = load_json_file(EXPECTED_MOVE_LEDGER_FILE) or {}
    strategy_alternatives = load_json_file(STRATEGY_ALTERNATIVE_SCORER_FILE) or {}
    strategy_alt_pricing = load_json_file(STRATEGY_ALTERNATIVE_PRICING_FILE) or {}
    strategy_shadow_comparison = load_json_file(STRATEGY_SHADOW_COMPARISON_FILE) or {}
    paper_loop = load_json_file(PAPER_EVIDENCE_LOOP_FILE) or {}
    performance = load_json_file(PERFORMANCE_ANALYTICS_FILE) or {}
    strategy_lab = load_json_file(STRATEGY_LAB_FILE) or {}
    shadow = load_json_file(SHADOW_EVIDENCE_FILE) or {}
    edge = load_json_file(EDGE_RESEARCH_FILE) or {}
    conviction_research = load_json_file(CONVICTION_RESEARCH_FILE) or {}
    math_verify = load_json_file(MATH_VERIFY_FILE) or {}
    tos_formula_audit = load_json_file(TOS_FORMULA_AUDIT_FILE) or {}
    tos_custom_metrics = load_json_file(TOS_CUSTOM_METRICS_FILE) or {}
    tos_metric_theory = load_json_file(TOS_METRIC_THEORY_AUDIT_FILE) or {}
    schwab_price_history = load_json_file(SCHWAB_PRICE_HISTORY_FILE) or {}
    schwab_tos_metrics_sync = load_json_file(SCHWAB_TOS_METRICS_SYNC_FILE) or {}
    market_mastery = load_json_file(MARKET_MASTERY_PLAN_FILE) or {}

    missions = load_active_missions()
    notes = load_notes(limit=12)
    freshness_panel = build_freshness_panel()
    tos_visibility = build_tos_visibility_summary()

    live_counts = live_review.get("counts") or {}
    live_packet_counts = live_book_packet.get("counts") or {}
    paper_counts = paper_director.get("counts") or {}
    loop_counts = paper_loop.get("counts") or {}
    deployable_cash_arg = command_cash_arg((capital_readiness.get("guardrails") or {}).get("deployableCash"))

    next_actions: list[str] = []
    next_actions.extend((market_mastery.get("nextActions") or [])[:3])
    next_actions.extend((account_optimization.get("nextActions") or [])[:2])
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
        "schwabAccountSync": artifact_summary(SCHWAB_ACCOUNT_SYNC_FILE, keys=("stage", "verdict", "message", "generatedAt", "matchedSuffix", "brokerReadOnly", "orderEndpointsAllowed")),
        "livePositionReview": artifact_summary(LIVE_POSITION_REVIEW_FILE, keys=("verdict", "message", "generatedAt")),
        "liveBookReviewPacket": artifact_summary(LIVE_BOOK_REVIEW_PACKET_FILE, keys=("verdict", "generatedAt", "capitalReadinessVerdict", "manualDeploymentAllowed", "autoLiveAllowed")),
        "whileAwayPacket": artifact_summary(WHILE_AWAY_PACKET_FILE, keys=("stage", "verdict", "generatedAt", "researchOnly", "promotable")),
        "capitalDeploymentReadiness": artifact_summary(CAPITAL_DEPLOYMENT_READINESS_FILE, keys=("verdict", "message", "generatedAt", "deploymentDate", "manualDeploymentAllowed", "autoLiveAllowed")),
        "capitalScenarioMatrix": artifact_summary(CAPITAL_SCENARIO_MATRIX_FILE, keys=("stage", "verdict", "generatedAt", "deploymentDate", "scenarioCount")),
        "accountOptimization": artifact_summary(ACCOUNT_OPTIMIZATION_FILE, keys=("stage", "verdict", "generatedAt", "researchOnly", "promotable", "authorityChanged")),
        "riskGateAudit": artifact_summary(RISK_GATE_AUDIT_FILE, keys=("verdict", "message", "generatedAt", "liveTradingAllowed")),
        "paperTestDirector": artifact_summary(PAPER_TEST_DIRECTOR_FILE, keys=("verdict", "generatedAt", "authorityLevel")),
        "paperBottleneckReducer": artifact_summary(PAPER_BOTTLENECK_REDUCER_FILE, keys=("verdict", "generatedAt", "scenarioTarget")),
        "fastPaperCohort": artifact_summary(
            FAST_PAPER_COHORT_FILE,
            keys=("stage", "verdict", "generatedAt", "researchOnly", "promotable"),
        ),
        "paperMarkToMarket": artifact_summary(PAPER_MTM_FILE, keys=("stage", "verdict", "fetchStatus", "generatedAt", "researchOnly", "promotable", "openPositionCount")),
        "tradeManagement": artifact_summary(TRADE_MANAGEMENT_FILE, keys=("stage", "verdict", "generatedAt", "researchOnly", "promotable", "authorityChanged", "openPositionCount", "actionableCount")),
        "scenarioEvidence": artifact_summary(SCENARIO_EVIDENCE_FILE, keys=("stage", "generatedAt", "researchOnly", "promotable", "sourceScenarioCount")),
        "scenarioBacktest": artifact_summary(SCENARIO_BACKTEST_FILE, keys=("stage", "generatedAt", "researchOnly", "promotable", "scenarioCount")),
        "scoreCalibration": artifact_summary(SCORE_CALIBRATION_FILE, keys=("stage", "verdict", "generatedAt", "researchOnly", "promotable")),
        "expectedMoveLedger": artifact_summary(EXPECTED_MOVE_LEDGER_FILE, keys=("stage", "verdict", "generatedAt", "researchOnly", "promotable")),
        "strategyAlternativeScorer": artifact_summary(STRATEGY_ALTERNATIVE_SCORER_FILE, keys=("stage", "verdict", "generatedAt", "researchOnly", "promotable")),
        "strategyAlternativePricing": artifact_summary(STRATEGY_ALTERNATIVE_PRICING_FILE, keys=("stage", "verdict", "generatedAt", "researchOnly", "promotable")),
        "strategyShadowComparison": artifact_summary(STRATEGY_SHADOW_COMPARISON_FILE, keys=("stage", "verdict", "generatedAt", "researchOnly", "promotable")),
        "paperEvidenceLoop": artifact_summary(PAPER_EVIDENCE_LOOP_FILE, keys=("verdict", "generatedAt", "strategyLabVerdict")),
        "performanceAnalytics": artifact_summary(PERFORMANCE_ANALYTICS_FILE, keys=("verdict", "generatedAt", "message")),
        "strategyLab": strategy_lab_status(strategy_lab),
        "shadowEvidence": artifact_summary(SHADOW_EVIDENCE_FILE, keys=("verdict", "generatedAt", "message")),
        "edgeResearch": artifact_summary(EDGE_RESEARCH_FILE, keys=("verdict", "generatedAt", "message")),
        "convictionResearch": artifact_summary(CONVICTION_RESEARCH_FILE, keys=("stage", "generatedAt", "researchOnly", "promotable")),
        "schwabEdgeSignals": artifact_summary(SCHWAB_EDGE_SIGNALS_FILE, keys=("stage", "verdict", "generatedAt", "sourceStatus", "sourceConfigured", "researchOnly", "promotable")),
        "outcomeAttribution": artifact_summary(OUTCOME_ATTRIBUTION_FILE, keys=("stage", "verdict", "generatedAt", "researchOnly", "promotable")),
        "ruleEdgeDecay": artifact_summary(RULE_EDGE_DECAY_FILE, keys=("stage", "verdict", "generatedAt", "promotable")),
        "slippageEstimator": artifact_summary(SLIPPAGE_ESTIMATOR_FILE, keys=("stage", "verdict", "generatedAt", "researchOnly", "promotable")),
        "portfolioCorrelation": artifact_summary(PORTFOLIO_CORRELATION_FILE, keys=("stage", "verdict", "generatedAt", "researchOnly", "promotable")),
        "drawdownProtocol": artifact_summary(DRAWDOWN_PROTOCOL_FILE, keys=("stage", "verdict", "generatedAt", "researchOnly", "promotable")),
        "consensusMonitor": artifact_summary(CONSENSUS_MONITOR_FILE, keys=("stage", "verdict", "generatedAt", "consensusCount", "researchOnly", "promotable")),
        "paperVelocity": artifact_summary(PAPER_VELOCITY_FILE, keys=("stage", "verdict", "generatedAt", "totalTickets", "researchOnly", "promotable")),
        "capitalScaling": artifact_summary(CAPITAL_SCALING_FILE, keys=("stage", "verdict", "generatedAt", "researchOnly", "promotable")),
        "mathVerify": artifact_summary(MATH_VERIFY_FILE, keys=("verdict", "generatedAt", "totalViolations", "missingArtifacts")),
        "tosFormulaAudit": artifact_summary(TOS_FORMULA_AUDIT_FILE, keys=("stage", "verdict", "generatedAt", "formulaVersion", "checked", "flagCounts")),
        "tosCustomMetrics": artifact_summary(TOS_CUSTOM_METRICS_FILE, keys=("stage", "verdict", "generatedAt", "registryMetricCount", "missingFormulaMetrics")),
        "tosMetricTheoryAudit": artifact_summary(TOS_METRIC_THEORY_AUDIT_FILE, keys=("stage", "verdict", "generatedAt", "checked", "postureCounts")),
        "schwabPriceHistory": artifact_summary(SCHWAB_PRICE_HISTORY_FILE, keys=("stage", "status", "generatedAt", "configured", "symbolCount")),
        "schwabTosMetricsSync": artifact_summary(SCHWAB_TOS_METRICS_SYNC_FILE, keys=("stage", "sourceStatus", "generatedAt", "customMetricsVerdict", "metricValueCount")),
        "marketMasteryPlan": artifact_summary(
            MARKET_MASTERY_PLAN_FILE,
            keys=("stage", "verdict", "generatedAt", "researchOnly", "promotable"),
        ),
    }
    strategy_alt_pricing_ranked = sorted(
        [item for item in strategy_alt_pricing.get("items") or [] if isinstance(item, dict)],
        key=lambda item: (
            not bool(item.get("combinedPassed", (item.get("riskVerdict") or {}).get("passed"))),
            not bool(item.get("optimizerPassed")),
            not bool(item.get("fallbackVariant")),
            number(item.get("candidateStrategyRank"), 99),
            str(item.get("ticker") or ""),
        ),
    )
    headline_metrics = {
        "accountDataSource": live_sync.get("accountDataSource"),
        "accountNetLiquidatingValue": first_display_value(
            live_sync.get("netLiquidatingValue"), schwab_account_sync.get("netLiquidatingValue")
        ),
        "accountTotalCash": first_display_value(live_sync.get("totalCash"), schwab_account_sync.get("totalCash")),
        "accountOptimizationVerdict": account_optimization.get("verdict"),
        "targetMonthlyReturnAnnualizedPct": (
            account_optimization.get("targetStressTest") or {}
        ).get("compoundedAnnualReturnPct"),
        "referenceOptionsTicketPctOfNlv": (
            account_optimization.get("optionsAffordability") or {}
        ).get("referenceTicketPctOfNlv"),
        "edgeAdjustedLiveOptionsMaxLoss": number(
            (account_optimization.get("optionsAffordability") or {}).get(
                "edgeAdjustedLiveOptionsMaxLossDollars"
            )
        ),
        "accountTopPositionPct": (
            account_optimization.get("concentration") or {}
        ).get("topPositionPct"),
        "schwabAccountVerdict": schwab_account_sync.get("verdict"),
        "liveSupported": live_counts.get("supported", 0),
        "liveReview": live_counts.get("review", 0),
        "liveFragile": live_counts.get("fragile", 0),
        "liveBookHardBlockers": live_packet_counts.get("hardBlockers", 0),
        "liveBookWarnings": live_packet_counts.get("warnings", 0),
        "whileAwayVerdict": while_away_packet.get("verdict"),
        "paperStageable": paper_counts.get("stageableNow", 0),
        "paperAutoSelected": paper_counts.get("autoPaperSelected", 0),
        "paperApprovalOnly": paper_counts.get("approvalOnly", 0),
        "paperScenarioCount": (paper_reducer.get("counts") or {}).get("scenarios", 0),
        "fastPaperVerdict": fast_paper.get("verdict"),
        "fastPaperSelectedToday": (fast_paper.get("counts") or {}).get("selectedToday", 0),
        "fastPaperClosedToday": (fast_paper.get("counts") or {}).get("closedToday", 0),
        "fastPaperOpen": (fast_paper.get("counts") or {}).get("open", 0),
        "fastPaperClosedLifetime": (fast_paper.get("counts") or {}).get("closedLifetime", 0),
        "fastPaperPromotionEligible": False,
        "paperMtmFetchStatus": paper_mtm.get("fetchStatus"),
        "paperMtmOpenPositions": paper_mtm.get("openPositionCount"),
        "paperMtmMarkedTickets": len(paper_mtm.get("marksByTicketId") or {}),
        "tradeManagementVerdict": trade_management.get("verdict"),
        "tradeManagementOpenPositions": trade_management.get("openPositionCount"),
        "tradeManagementActionable": trade_management.get("actionableCount"),
        "tradeManagementVerdictCounts": trade_management.get("verdictCounts") or {},
        "paperScenarioTopFive": [
            item.get("ticker")
            for item in (paper_reducer.get("topFiveFocus") or [])
        ],
        "scenarioClosedEvidenceCount": scenario_backtest.get("closedEvidenceCount", 0),
        "scenarioClosedObservationCount": scenario_backtest.get("closedObservationCount", 0),
        "scenarioObservationLedgerCount": (scenario_evidence.get("counts") or {}).get("observations", 0),
        "scenarioBacktestVerdicts": (scenario_backtest.get("counts") or {}).get("verdictCounts") or {},
        "scenarioObservationVerdicts": (scenario_backtest.get("counts") or {}).get("observationVerdictCounts") or {},
        "scenarioBacktestTopFocus": [
            item.get("ticker")
            for item in (scenario_backtest.get("topFocus") or [])
        ],
        "scoreCalibrationVerdict": score_calibration.get("verdict"),
        "scoreCalibrationClosedObservations": (score_calibration.get("counts") or {}).get("closedScenarioObservations"),
        "scoreCalibrationScenarioScoreRows": (score_calibration.get("counts") or {}).get("scenarioScoreRows"),
        "expectedMoveVerdict": expected_move.get("verdict"),
        "expectedMoveClosedLongVol": (expected_move.get("counts") or {}).get("closedLongVolRecords"),
        "expectedMoveCurrentLongVol": (expected_move.get("counts") or {}).get("currentLongVolCandidates"),
        "expectedMoveBeatRate": (expected_move.get("overall") or {}).get("beatRate"),
        "expectedMoveHurdleCounts": expected_move.get("currentHurdleCounts") or {},
        "expectedMoveTopPressure": [
            {
                "ticker": item.get("ticker"),
                "hurdle": item.get("premiumHurdleLabel"),
                "atrMultiple": item.get("requiredMoveAtrMultiple"),
                "pressureScore": item.get("rankPressureScore"),
            }
            for item in (expected_move.get("currentPressureCandidates") or [])[:5]
        ],
        "strategyAlternativeVerdict": strategy_alternatives.get("verdict"),
        "strategyAlternativeRecommendations": (strategy_alternatives.get("counts") or {}).get("recommendations") or {},
        "strategyAlternativeVerdicts": (strategy_alternatives.get("counts") or {}).get("verdicts") or {},
        "strategyAlternativeTop": [
            {
                "ticker": item.get("ticker"),
                "recommend": (item.get("recommendation") or {}).get("strategy"),
                "verdict": (item.get("recommendation") or {}).get("verdict"),
            }
            for item in (strategy_alternatives.get("scorecards") or [])[:5]
        ],
        "strategyAlternativePricingVerdict": strategy_alt_pricing.get("verdict"),
        "strategyAlternativePricingCounts": strategy_alt_pricing.get("counts") or {},
        "strategyAlternativePricedTop": [
            {
                "ticker": item.get("ticker"),
                "strategy": ((item.get("strikePlan") or {}).get("strategy") or item.get("recommendedStrategy")),
                "status": item.get("status"),
                "combinedPassed": item.get("combinedPassed", (item.get("riskVerdict") or {}).get("passed")),
                "optimizerPassed": item.get("optimizerPassed"),
                "fallbackVariant": item.get("fallbackVariant"),
                "rank": item.get("candidateStrategyRank"),
                "ladderRows": item.get("putCreditLadderRows") or len(item.get("putCreditLadder") or []),
                "supportSafeRows": item.get("putCreditSupportSafeRows") or len(item.get("putCreditSupportSafeLadder") or []),
                "condorRows": item.get("ironCondorLadderRows") or len(item.get("ironCondorLadder") or []),
                "rangeSafeRows": item.get("ironCondorRangeSafeRows") or len(item.get("ironCondorRangeSafeLadder") or []),
            }
            for item in strategy_alt_pricing_ranked[:5]
        ],
        "strategyShadowComparisonVerdict": strategy_shadow_comparison.get("verdict"),
        "strategyShadowComparisonCounts": strategy_shadow_comparison.get("counts") or {},
        "strategyShadowComparisonTop": [
            {
                "ticker": item.get("ticker"),
                "strategy": ((item.get("bestPassingVariant") or {}).get("strategy")),
                "expiration": (((item.get("bestPassingVariant") or {}).get("plan") or {}).get("expiration")),
                "credit": (((item.get("bestPassingVariant") or {}).get("plan") or {}).get("estimatedCredit")),
                "maxLoss": (((item.get("bestPassingVariant") or {}).get("plan") or {}).get("estimatedMaxLoss")),
            }
            for item in (strategy_shadow_comparison.get("register") or [])[:5]
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
        "tosFormulaAuditVerdict": tos_formula_audit.get("verdict"),
        "tosFormulaAuditChecked": tos_formula_audit.get("checked"),
        "tosFormulaFlagCounts": tos_formula_audit.get("flagCounts") or {},
        "tosCustomMetricsVerdict": tos_custom_metrics.get("verdict"),
        "tosCustomMetricsSourceProvider": ((tos_custom_metrics.get("values") or {}).get("sourceProvider")),
        "tosCustomMetricValues": ((tos_custom_metrics.get("values") or {}).get("metricValueCount")),
        "tosCustomMetricTickers": ((tos_custom_metrics.get("values") or {}).get("tickerCount")),
        "tosCustomMetricMissingFormulas": tos_custom_metrics.get("missingFormulaMetrics") or [],
        "tosMetricTheoryVerdict": tos_metric_theory.get("verdict"),
        "tosMetricTheoryPostures": tos_metric_theory.get("postureCounts") or {},
        "tosMetricTheoryRedundancy": ((tos_metric_theory.get("redundancy") or {}).get("highCorrelationPairs") or [])[:5],
        "schwabPriceHistoryStatus": schwab_price_history.get("status"),
        "schwabPriceHistoryConfigured": schwab_price_history.get("configured"),
        "schwabPriceHistoryRows": len(schwab_price_history.get("rows") or []),
        "schwabTosMetricsSyncStatus": schwab_tos_metrics_sync.get("sourceStatus"),
        "schwabTosMetricsMetricValues": schwab_tos_metrics_sync.get("metricValueCount"),
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
        "freshnessPanel": freshness_panel,
        "tosVisibility": tos_visibility,
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
            "./run_inferno_paper_evidence_harvest.sh",
            "./run_inferno_fast_paper_cohort.sh",
            "./run_inferno_paper_mark_to_market.sh",
            "./run_inferno_trade_management.sh",
            "./run_inferno_scenario_evidence.sh",
            "./run_inferno_scenario_backtest.sh",
            "./run_inferno_score_calibration.sh",
            "./run_inferno_expected_move_ledger.sh",
            "./run_inferno_tos_formula_audit.sh --limit 20",
            "./run_inferno_tos_custom_metrics.sh --init-registry",
            "./run_inferno_schwab_tos_metrics_sync.sh --from-snapshot --limit 12",
            "./run_inferno_tos_metric_theory_audit.sh --limit 12",
            "./run_inferno_strategy_alternative_scorer.sh",
            "./run_inferno_strategy_alternative_pricing.sh --limit 4 --variants-per-ticker 2",
            "./run_inferno_strategy_shadow_comparison.sh",
            "./run_inferno_schwab_account_sync.sh",
            "./run_inferno_live_account_sync.sh",
            "./run_inferno_live_position_review.sh",
            "./run_inferno_live_book_review_packet.sh",
            "./run_inferno_while_away_packet.sh",
            "./run_inferno_usage_optimizer.sh",
            f"./run_inferno_action_pulse.sh --phase manual --deployable-cash {deployable_cash_arg} --fast --send --force-send",
            "./run_inferno_capital_scenario_matrix.sh --deployable-cash 500 3000 5000",
            "./run_inferno_account_optimization.sh",
            f"./run_inferno_capital_launch_check.sh --deployable-cash {deployable_cash_arg}",
            f"./run_inferno_capital_deployment_readiness.sh --deployable-cash {deployable_cash_arg}",
            f"./run_inferno_strike_cycle.sh --deployable-cash {deployable_cash_arg}",
            "./run_inferno_risk_gate_audit.sh",
            "./run_inferno_conviction_research.sh",
            "./run_inferno_market_mastery_plan.sh",
        ],
        "recommendedReads": [
            str(ROOT / "reports/usage_optimizer_latest.txt"),
            str(ROOT / "reports/model_command_center_latest.txt"),
            str(ROOT / "reports/while_away_latest.txt"),
            str(ROOT / "reports/central_command_latest.txt"),
            str(ROOT / "docs/PROJECT_STATUS.md"),
            str(ROOT / "docs/MODEL_COLLABORATION_BRIEF.md"),
            str(ROOT / "docs/RUNBOOK.md"),
            str(ROOT / "reports/deploy_preflight_latest.txt"),
            str(ROOT / "reports/action_pulse_latest.txt"),
            str(ROOT / "reports/capital_launch_check_latest.txt"),
            str(ROOT / "reports/capital_deployment_readiness_latest.txt"),
            str(ROOT / "reports/account_optimization_latest.txt"),
            str(ROOT / "reports/live_book_review_packet_latest.txt"),
            str(ROOT / "reports/risk_gate_audit_latest.txt"),
            str(ROOT / "reports/scenario_evidence_latest.txt"),
            str(ROOT / "reports/scenario_backtest_latest.txt"),
            str(ROOT / "reports/fast_paper_cohort_latest.txt"),
            str(ROOT / "reports/paper_mark_to_market_latest.txt"),
            str(ROOT / "reports/trade_management_latest.txt"),
            str(ROOT / "reports/score_calibration_latest.txt"),
            str(ROOT / "reports/expected_move_ledger_latest.txt"),
            str(ROOT / "reports/strategy_alternative_scorer_latest.txt"),
            str(ROOT / "reports/strategy_alternative_pricing_latest.txt"),
            str(ROOT / "reports/strategy_shadow_comparison_latest.txt"),
            str(ROOT / "reports/tos_formula_audit_latest.txt"),
            str(ROOT / "reports/tos_custom_metrics_latest.txt"),
            str(ROOT / "reports/tos_metric_theory_audit_latest.txt"),
            str(ROOT / "reports/schwab_price_history_latest.txt"),
            str(ROOT / "reports/schwab_tos_metrics_sync_latest.txt"),
            str(ROOT / "reports/schwab_account_sync_latest.txt"),
            str(ROOT / "reports/conviction_research_latest.txt"),
            str(ROOT / "reports/ops_maintenance_latest.txt"),
            str(ROOT / "reports/live_position_review_latest.txt"),
            str(ROOT / "reports/trade_conviction_audit_latest.txt"),
            str(ROOT / "reports/blowup_guardrails_latest.txt"),
            str(ROOT / "reports/market_mastery_next_actions_latest.txt"),
            str(ROOT / "docs/TRADING_DISCIPLINE_RESEARCH_2026-06-22.md"),
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

    lines.extend(["", "Freshness panel:"])
    lines.append(f"- TOS: {render_tos_visibility_line(payload.get('tosVisibility') or {})}")
    for item in render_freshness_lines(payload.get("freshnessPanel") or {}):
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "System status:",
            f"- Deploy preflight: {status_value(status.get('deployPreflight') or {})}",
            f"- Live account sync: {status_value(status.get('liveAccountSync') or {})}",
            f"- Schwab account sync: {status_value(status.get('schwabAccountSync') or {})}",
            f"- Live position review: {status_value(status.get('livePositionReview') or {})}",
            f"- Live book review packet: {status_value(status.get('liveBookReviewPacket') or {})}",
            f"- While away packet: {status_value(status.get('whileAwayPacket') or {})}",
            f"- Capital deployment readiness: {status_value(status.get('capitalDeploymentReadiness') or {})}",
            f"- Capital scenario matrix: {status_value(status.get('capitalScenarioMatrix') or {})}",
            f"- Risk gate audit: {status_value(status.get('riskGateAudit') or {})}",
            f"- Paper director: {status_value(status.get('paperTestDirector') or {})}",
            f"- Paper bottleneck reducer: {status_value(status.get('paperBottleneckReducer') or {})}",
            f"- Fast paper cohort: {status_value(status.get('fastPaperCohort') or {})}",
            f"- Paper mark-to-market: {status_value(status.get('paperMarkToMarket') or {})}",
            f"- Trade management: {status_value(status.get('tradeManagement') or {})}",
            f"- Scenario evidence: {status_value(status.get('scenarioEvidence') or {}, key='stage')}",
            f"- Scenario backtest: {status_value(status.get('scenarioBacktest') or {}, key='stage')}",
            f"- Score calibration: {status_value(status.get('scoreCalibration') or {})}",
            f"- Expected move ledger: {status_value(status.get('expectedMoveLedger') or {})}",
            f"- Strategy alternative scorer: {status_value(status.get('strategyAlternativeScorer') or {})}",
            f"- Strategy alternative pricing: {status_value(status.get('strategyAlternativePricing') or {})}",
            f"- Strategy shadow comparison: {status_value(status.get('strategyShadowComparison') or {})}",
            f"- Paper evidence loop: {status_value(status.get('paperEvidenceLoop') or {})}",
            f"- Math verify: {status_value(status.get('mathVerify') or {})}",
            f"- TOS formula audit: {status_value(status.get('tosFormulaAudit') or {})}",
            f"- TOS custom metrics: {status_value(status.get('tosCustomMetrics') or {})}",
            f"- Conviction research: {status_value(status.get('convictionResearch') or {}, key='stage')}",
            f"- Market mastery plan: {status_value(status.get('marketMasteryPlan') or {})}",
            "",
            "Headline metrics:",
            f"- Account source: {metrics.get('accountDataSource') or '-'}",
            f"- Account NLV: {display_value(metrics.get('accountNetLiquidatingValue'))}",
            f"- Account cash: {display_value(metrics.get('accountTotalCash'))}",
            f"- Live supported: {metrics.get('liveSupported', 0)}",
            f"- Live fragile: {metrics.get('liveFragile', 0)}",
            f"- Live hard blockers: {metrics.get('liveBookHardBlockers', 0)}",
            f"- Live review warnings: {metrics.get('liveBookWarnings', 0)}",
            f"- While away verdict: {metrics.get('whileAwayVerdict') or '-'}",
            f"- Paper stageable: {metrics.get('paperStageable', 0)}",
            f"- Paper auto-selected: {metrics.get('paperAutoSelected', 0)}",
            f"- Paper approval-only: {metrics.get('paperApprovalOnly', 0)}",
            f"- Paper scenarios: {metrics.get('paperScenarioCount', 0)}",
            f"- Fast paper: {metrics.get('fastPaperVerdict') or '-'} | "
            f"opened {metrics.get('fastPaperSelectedToday', 0)} | "
            f"closed {metrics.get('fastPaperClosedToday', 0)} | "
            f"open {metrics.get('fastPaperOpen', 0)} | "
            f"lifetime closed {metrics.get('fastPaperClosedLifetime', 0)} | "
            "promotion credit off",
            f"- Paper MTM: {metrics.get('paperMtmFetchStatus') or '-'} | "
            f"open {metrics.get('paperMtmOpenPositions')} | "
            f"marked {metrics.get('paperMtmMarkedTickets')}",
            f"- Trade management: {metrics.get('tradeManagementVerdict') or '-'} | "
            f"open {metrics.get('tradeManagementOpenPositions')} | "
            f"actionable {metrics.get('tradeManagementActionable')} | "
            f"counts {json.dumps(metrics.get('tradeManagementVerdictCounts') or {})}",
            f"- Paper top five: {', '.join(metrics.get('paperScenarioTopFive') or []) or 'none'}",
            f"- Scenario backtest evidence: {metrics.get('scenarioClosedEvidenceCount', 0)}",
            f"- Scenario observations closed: {metrics.get('scenarioClosedObservationCount', 0)}",
            f"- Scenario observations tracked: {metrics.get('scenarioObservationLedgerCount', 0)}",
            f"- Scenario backtest verdicts: {json.dumps(metrics.get('scenarioBacktestVerdicts') or {})}",
            f"- Scenario observation verdicts: {json.dumps(metrics.get('scenarioObservationVerdicts') or {})}",
            f"- Scenario backtest focus: {', '.join(metrics.get('scenarioBacktestTopFocus') or []) or 'none'}",
            f"- Score calibration: {metrics.get('scoreCalibrationVerdict')} | "
            f"closed observations {metrics.get('scoreCalibrationClosedObservations')} | "
            f"score rows {metrics.get('scoreCalibrationScenarioScoreRows')}",
            f"- Expected move ledger: {metrics.get('expectedMoveVerdict')} | "
            f"closed long-vol {metrics.get('expectedMoveClosedLongVol')} | "
            f"current long-vol {metrics.get('expectedMoveCurrentLongVol')} | "
            f"beat rate {metrics.get('expectedMoveBeatRate')}",
            f"- Expected move hurdle counts: {json.dumps(metrics.get('expectedMoveHurdleCounts') or {})}",
            f"- Expected move top pressure: {json.dumps(metrics.get('expectedMoveTopPressure') or [])}",
            f"- Strategy alternatives: {metrics.get('strategyAlternativeVerdict')} | "
            f"recommendations {json.dumps(metrics.get('strategyAlternativeRecommendations') or {})}",
            f"- Strategy alternative top: {json.dumps(metrics.get('strategyAlternativeTop') or [])}",
            f"- Strategy alternative pricing: {metrics.get('strategyAlternativePricingVerdict')} | "
            f"counts {json.dumps(metrics.get('strategyAlternativePricingCounts') or {})}",
            f"- Strategy alternative priced top: {json.dumps(metrics.get('strategyAlternativePricedTop') or [])}",
            f"- Strategy shadow comparison: {metrics.get('strategyShadowComparisonVerdict')} | "
            f"counts {json.dumps(metrics.get('strategyShadowComparisonCounts') or {})}",
            f"- Strategy shadow comparison top: {json.dumps(metrics.get('strategyShadowComparisonTop') or [])}",
            f"- Promotion gap: {metrics.get('paperRemainingForPromotion', 0)}",
            f"- Auto live allowed: {metrics.get('autoLiveAllowed')}",
            f"- Risk gate hard fails: {metrics.get('riskGateHardFails')}",
            f"- Math violations: {metrics.get('mathViolations')}",
            f"- TOS formula audit: {metrics.get('tosFormulaAuditVerdict')} | "
            f"checked {metrics.get('tosFormulaAuditChecked')} | "
            f"flags {json.dumps(metrics.get('tosFormulaFlagCounts') or {})}",
            f"- TOS custom metrics: {metrics.get('tosCustomMetricsVerdict')} | "
            f"values {metrics.get('tosCustomMetricValues')} | "
            f"tickers {metrics.get('tosCustomMetricTickers')} | "
            f"missing formulas {json.dumps(metrics.get('tosCustomMetricMissingFormulas') or [])}",
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
        "Freshness / attach status:",
        f"- TOS: {render_tos_visibility_line(payload.get('tosVisibility') or {})}",
    ])
    for item in render_freshness_lines(payload.get("freshnessPanel") or {})[:5]:
        lines.append(f"- {item}")
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
        f"- Trade management: {status_value(status.get('tradeManagement') or {})} | "
        f"actionable {metrics.get('tradeManagementActionable')}",
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
