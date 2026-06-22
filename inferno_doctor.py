from __future__ import annotations

import json
import os
import re
import smtplib
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from inferno_config import (
    DESKTOP_AUTOMATION_LABEL,
    DOWNLOADS_WATCH_LABEL,
    LABEL,
    ROOT,
    TOS_EXPORT_AUTOMATION_ENABLED,
    UPDATER_LABEL,
    UPDATER_SCRIPTS,
    WATCHDOG_LABEL,
    backtest_python,
    default_backtest_root,
    local_now,
    local_today,
    SERVICE_HOUR,
    WAKE_HOUR,
    WAKE_MINUTE,
)
from inferno_io import atomic_write_json, atomic_write_text
from inferno_reporting_summary import build_tos_visibility_summary, render_tos_visibility_line
from inferno_schwab_oauth import load_config as load_schwab_oauth_config
from inferno_schwab_oauth import token_status as load_schwab_oauth_status
from server import (
    DATA_DIR,
    EXECUTION_QUEUE_FILE,
    LOG_FILE,
    OPS_STATUS_FILE,
    REPORTS_DIR,
    SNAPSHOT_FILE,
    WATCHDOG_STATUS_FILE,
    ensure_dirs,
    load_json_file,
    smtp_configured,
    smtp_settings,
)


SMTP_ENV_FILE = ROOT / ".env.smtp"
STRIKE_PLAN_FILE = ROOT / "data" / "inferno_strike_plan.json"
PAPER_EXECUTION_LEDGER_FILE = ROOT / "data" / "inferno_paper_execution_ledger.json"
SHADOW_EVIDENCE_FILE = ROOT / "data" / "inferno_shadow_evidence.json"
PERFORMANCE_ANALYTICS_FILE = ROOT / "data" / "inferno_performance_analytics.json"
STRATEGY_LAB_FILE = ROOT / "data" / "inferno_strategy_lab.json"
EXPOSURE_ANALYTICS_FILE = ROOT / "data" / "inferno_exposure_analytics.json"
EDGE_RESEARCH_FILE = ROOT / "data" / "inferno_edge_research.json"
CONVICTION_RESEARCH_FILE = ROOT / "data" / "inferno_conviction_research.json"
SCHWAB_ACCOUNT_SYNC_FILE = ROOT / "data" / "inferno_schwab_account_sync.json"
SCHWAB_EDGE_SIGNALS_FILE = ROOT / "data" / "inferno_schwab_edge_signals.json"
OUTCOME_ATTRIBUTION_FILE = ROOT / "data" / "inferno_outcome_attribution.json"
RULE_EDGE_DECAY_FILE = ROOT / "data" / "inferno_rule_edge_decay.json"
SLIPPAGE_ESTIMATOR_FILE = ROOT / "data" / "inferno_slippage_estimator.json"
SCORE_CALIBRATION_FILE = ROOT / "data" / "inferno_score_calibration.json"
EXPECTED_MOVE_LEDGER_FILE = ROOT / "data" / "inferno_expected_move_ledger.json"
STRATEGY_ALTERNATIVE_SCORER_FILE = ROOT / "data" / "inferno_strategy_alternative_scorer.json"
STRATEGY_ALTERNATIVE_PRICING_FILE = ROOT / "data" / "inferno_strategy_alternative_pricing.json"
STRATEGY_SHADOW_COMPARISON_FILE = ROOT / "data" / "inferno_strategy_shadow_comparison.json"
PORTFOLIO_CORRELATION_FILE = ROOT / "data" / "inferno_portfolio_correlation.json"
DRAWDOWN_PROTOCOL_FILE = ROOT / "data" / "inferno_drawdown_protocol.json"
CONSENSUS_MONITOR_FILE = ROOT / "data" / "inferno_consensus_monitor.json"
PAPER_VELOCITY_FILE = ROOT / "data" / "inferno_paper_velocity.json"
FAST_PAPER_COHORT_FILE = ROOT / "data" / "inferno_fast_paper_cohort.json"
CAPITAL_SCALING_FILE = ROOT / "data" / "inferno_capital_scaling.json"
PAPER_MTM_FILE = ROOT / "data" / "inferno_paper_mark_to_market.json"
TRADE_MANAGEMENT_FILE = ROOT / "data" / "inferno_trade_management.json"
EXPECTANCY_LEDGER_FILE = ROOT / "data" / "inferno_expectancy_ledger.json"
DTE_POLICY_ANALYSIS_FILE = ROOT / "data" / "inferno_dte_policy_analysis.json"
TRADING_BEHAVIOR_AUDIT_FILE = ROOT / "data" / "inferno_trading_behavior_audit.json"
PROCESS_COMPLIANCE_FILE = ROOT / "data" / "inferno_process_compliance.json"
PORTFOLIO_HEAT_FILE = ROOT / "data" / "inferno_portfolio_heat.json"
WHEEL_SHADOW_FILE = ROOT / "data" / "inferno_wheel_shadow.json"
BLOWUP_GUARDRAILS_FILE = ROOT / "data" / "inferno_blowup_guardrails.json"
AUTHORITY_MANIFEST_FILE = ROOT / "data" / "inferno_authority_manifest.json"
DOWNLOADS_MANAGER_FILE = ROOT / "data" / "inferno_downloads_manager.json"
DOWNLOADS_WATCH_FILE = ROOT / "data" / "inferno_downloads_watch.json"
TOS_EXPORT_BRIDGE_FILE = ROOT / "data" / "inferno_tos_export_bridge.json"
TOS_EXPORT_VERIFIER_FILE = ROOT / "data" / "inferno_tos_export_verifier.json"
TOS_EXPORT_STABILITY_FILE = ROOT / "data" / "inferno_tos_export_stability.json"
TOS_SESSION_PROBE_FILE = ROOT / "data" / "inferno_tos_session_probe.json"
TOS_SANDBOX_FILE = ROOT / "data" / "inferno_tos_sandbox_session.json"
TOS_FILL_INGEST_FILE = ROOT / "data" / "inferno_tos_fill_ingest.json"
DESKTOP_AUTOMATION_FILE = ROOT / "data" / "inferno_desktop_automation.json"
CLOUD_CONTROL_PLANE_FILE = ROOT / "data" / "inferno_cloud_control_plane.json"
CLOUD_STATE_FILE = ROOT / "data" / "inferno_cloud_state.json"
CLOUD_EXECUTION_AUDIT_FILE = ROOT / "data" / "inferno_cloud_execution_audit.json"
MARKET_CONTEXT_AUDIT_FILE = ROOT / "data" / "inferno_market_context_audit.json"
TICKER_UNIVERSE_AUDIT_FILE = ROOT / "data" / "inferno_ticker_universe_audit.json"
DATA_READINESS_AUDIT_FILE = ROOT / "data" / "inferno_data_readiness_audit.json"
PAPER_TEST_DIRECTOR_FILE = ROOT / "data" / "inferno_paper_test_director.json"
PAPER_BOTTLENECK_REDUCER_FILE = ROOT / "data" / "inferno_paper_bottleneck_reducer.json"
PAPER_EVIDENCE_LOOP_FILE = ROOT / "data" / "inferno_paper_evidence_loop.json"
PAPER_EXIT_AUDIT_FILE = ROOT / "data" / "inferno_paper_exit_audit.json"
LIVE_ACCOUNT_SYNC_FILE = ROOT / "data" / "inferno_live_account_sync.json"
LIVE_POSITION_REVIEW_FILE = ROOT / "data" / "inferno_live_position_review.json"
MODEL_COMMAND_CENTER_FILE = ROOT / "data" / "inferno_model_command_center.json"
SECRET_HYGIENE_FILE = ROOT / "data" / "inferno_secret_hygiene.json"
RESEARCH_CYCLE_FILE = ROOT / "data" / "inferno_research_cycle.json"
ACTION_PULSE_FILE = ROOT / "data" / "inferno_action_pulse.json"
ACTION_PULSE_LABEL = "io.diablotrading.inferno-action-pulse"
DOCTOR_ARTIFACT_FILE = DATA_DIR / "inferno_doctor.json"
DOCTOR_TEXT_FILE = REPORTS_DIR / "doctor_latest.txt"
SCHWAB_REFRESH_RESTART_ADVISORY_DAYS = 5.0


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key] = value

def run_command(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False)


def launch_agent_loaded(label: str) -> bool:
    domain = f"gui/{os.getuid()}/{label}"
    return run_command("launchctl", "print", domain).returncode == 0


def launch_agent_status(label: str) -> tuple[bool, str]:
    """Return launchd load health plus the last exit code when available."""
    domain = f"gui/{os.getuid()}/{label}"
    result = run_command("launchctl", "print", domain)
    if result.returncode != 0:
        return False, "not loaded"

    runs_match = re.search(r"\bruns = ([^\n]+)", result.stdout)
    exit_match = re.search(r"\blast exit code = ([^\n]+)", result.stdout)
    detail_parts = ["loaded"]
    if runs_match:
        detail_parts.append(f"runs={runs_match.group(1).strip()}")
    if exit_match:
        last_exit = exit_match.group(1).strip()
        detail_parts.append(f"last exit code={last_exit}")
        if not last_exit.startswith("0") and "never exited" not in last_exit:
            return False, " | ".join(detail_parts)
    return True, " | ".join(detail_parts)


def pmset_sched_text() -> str:
    return run_command("pmset", "-g", "sched").stdout


def pmset_custom_text() -> str:
    return run_command("pmset", "-g", "custom").stdout


def summarize_status(name: str, ok: bool, detail: str) -> str:
    marker = "PASS" if ok else "WARN"
    return f"[{marker}] {name}: {detail}"


def smtp_login_ok() -> tuple[bool, str]:
    settings = smtp_settings()
    if not settings["username"]:
        return True, "no authenticated SMTP user configured"
    try:
        if settings["use_ssl"]:
            with smtplib.SMTP_SSL(settings["host"], settings["port"], timeout=20) as server:
                server.login(settings["username"], settings["password"])
        else:
            with smtplib.SMTP(settings["host"], settings["port"], timeout=20) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(settings["username"], settings["password"])
        return True, "SMTP credentials accepted"
    except Exception as exc:  # noqa: BLE001
        return False, f"SMTP login failed: {exc}"


def latest_emailed_run_for_day(day: str) -> dict | None:
    if not LOG_FILE.exists():
        return None

    latest: dict | None = None
    for raw_line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        generated_at = str(payload.get("generatedAt", ""))
        if not generated_at.startswith(day):
            continue
        if not payload.get("ok", True) or not payload.get("emailSent"):
            continue
        latest = payload
    return latest


def cycle_reference_day(now: datetime | None = None, *, service_hour: int = SERVICE_HOUR) -> str:
    """Return the trading-cycle day used for morning artifact freshness.

    Before the morning service window completes, yesterday's artifacts are still
    the active operating baseline. This prevents the doctor from panicking just
    because the calendar flipped at midnight.
    """
    current = now or local_now()
    if current.hour < service_hour:
        return (current.date() - timedelta(days=1)).isoformat()
    return current.date().isoformat()


def cycle_days(now: datetime | None = None, *, service_hour: int = SERVICE_HOUR) -> tuple[str, ...]:
    """Return ISO day labels that belong to the current operating cycle."""
    current = now or local_now()
    today = current.date().isoformat()
    if current.hour < service_hour:
        return ((current.date() - timedelta(days=1)).isoformat(), today)
    return (today,)


def in_current_service_cycle(
    timestamp: str,
    *,
    now: datetime | None = None,
    service_hour: int = SERVICE_HOUR,
    max_age_hours: int = 36,
    future_grace_seconds: int = 300,
) -> bool:
    """Return True when a timestamp belongs to the active operating cycle."""
    stamp = str(timestamp or "").strip()
    if not stamp:
        return False
    current = now or local_now()
    if any(stamp.startswith(day) for day in cycle_days(current, service_hour=service_hour)):
        try:
            generated = datetime.fromisoformat(stamp)
        except ValueError:
            return True
        age_seconds = (current - generated).total_seconds()
        return -future_grace_seconds <= age_seconds <= max_age_hours * 3600
    return False


def latest_emailed_run_for_cycle(
    days: tuple[str, ...],
    *,
    now: datetime | None = None,
    service_hour: int = SERVICE_HOUR,
) -> dict | None:
    """Return the latest successful emailed run from the active service cycle."""
    if not LOG_FILE.exists():
        return None

    current = now or local_now()
    latest_payload: dict | None = None
    latest_generated: datetime | None = None
    for raw_line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        generated_at = str(payload.get("generatedAt", ""))
        if not any(generated_at.startswith(day) for day in days):
            continue
        if not in_current_service_cycle(
            generated_at,
            now=current,
            service_hour=service_hour,
        ):
            continue
        if not payload.get("ok", True) or not payload.get("emailSent"):
            continue
        try:
            generated = datetime.fromisoformat(generated_at)
        except ValueError:
            generated = None
        if latest_generated is None or (generated and generated > latest_generated):
            latest_payload = payload
            latest_generated = generated
    return latest_payload


def recent_or_today(timestamp: str, *, max_age_hours: int = 36, future_grace_seconds: int = 300) -> bool:
    """Return True when a timestamp is from today or still fresh enough to trust.

    Some control-plane reports are operator-readiness artifacts, not daily market
    outputs. Treating them as expired at midnight creates false warnings even
    when the underlying system is healthy.
    """
    stamp = str(timestamp or "").strip()
    if not stamp:
        return False
    if stamp.startswith(local_today()):
        return True
    try:
        generated = datetime.fromisoformat(stamp)
    except ValueError:
        return False
    age_seconds = (local_now() - generated).total_seconds()
    return -future_grace_seconds <= age_seconds <= max_age_hours * 3600


def block_reason_top_bucket_status(performance: dict) -> tuple[bool, str]:
    """Return (ok, detail) for the top block-reason bucket line.

    Always reports ``ok=True`` because this is informational. A heavy bucket
    (for example, ``approval-missing``) is a *signal* — not a desk failure —
    and should not bump the warnings count of the doctor run.
    """
    categories = performance.get("blockReasonCategories") or {}
    if not categories:
        return True, "no block reasons logged"
    top_label, top_payload = next(iter(categories.items()))
    return True, f"{top_label} x{int(top_payload.get('count') or 0)}"


def concentration_governor_status(strike_plan: dict) -> tuple[bool, str]:
    """Return (ok, detail) for the setup-concentration governor line.

    Always informational. The governor only demotes; demotions are evidence
    that the cap is working as designed, not an alarm.
    """
    if not strike_plan:
        return True, "no strike plan yet"
    governor = strike_plan.get("concentrationGovernor") or {}
    demoted = int(strike_plan.get("concentrationDemotedCount") or 0)
    primary = int(strike_plan.get("primaryCount") or 0)
    limit = governor.get("limit")
    if limit is None:
        return True, f"primary {primary} | demoted {demoted}"
    return True, f"limit {limit} | primary {primary} | demoted {demoted}"


def live_position_review_status(review: dict) -> tuple[bool, str]:
    """Evaluate the live-position review artifact without overreacting.

    A `review` verdict is still a healthy operating state for this lane. It
    means the read-only book review succeeded and surfaced at least one holding
    that deserves a human look before layering more exposure.
    """
    if not review:
        return False, "missing"

    generated = str(review.get("generatedAt", ""))
    verdict = str(review.get("verdict") or "")
    counts = review.get("counts") or {}
    fresh = recent_or_today(generated)
    ok = fresh and bool(review.get("ok")) and verdict in {"healthy", "review"}
    detail = (
        f"{verdict} | supported={counts.get('supported', 0)} | "
        f"review={counts.get('review', 0)} | "
        f"fragile={counts.get('fragile', 0)}"
        if fresh
        else json.dumps(
            {
                "generatedAt": review.get("generatedAt"),
                "verdict": verdict,
            }
        )
    )
    return ok, detail


def model_command_center_status(payload: dict) -> tuple[bool, str]:
    """Evaluate the shared model command center as core desk infrastructure.

    The command center is healthy when it is fresh, marked ready, and still
    carries the expected collaboration scaffolding like mission and note counts.
    """
    if not payload:
        return False, "missing"

    generated = str(payload.get("generatedAt", ""))
    status = str(payload.get("status") or "ready")
    headline_metrics = payload.get("headlineMetrics") or {}
    mission_count = len(payload.get("activeMissions") or []) if "activeMissions" in payload else int(payload.get("missionCount") or 0)
    note_count = len(payload.get("recentNotes") or []) if "recentNotes" in payload else int(payload.get("noteCount") or 0)
    fresh = recent_or_today(generated)
    ok = fresh and status in {"ready", "healthy"}
    detail = (
        f"{status} | missions={mission_count} | notes={note_count} | live-fragile={headline_metrics.get('liveFragile', 0)}"
        if fresh
        else json.dumps(
            {
                "generatedAt": generated,
                "status": status,
            }
        )
    )
    return ok, detail


def secret_hygiene_status(report: dict) -> tuple[bool, str]:
    """Evaluate repo secret hygiene without letting stale artifacts hide risk."""
    if not report:
        return False, "missing"

    generated = str(report.get("generatedAt", ""))
    verdict = str(report.get("verdict") or "")
    fresh = recent_or_today(generated, max_age_hours=72)
    ok = fresh and verdict == "healthy"
    detail = (
        f"{verdict} | tracked={report.get('trackedSensitiveCount', 0)} | "
        f"missing-ignore={len(report.get('missingGitignorePatterns') or [])}"
        if fresh
        else json.dumps({"generatedAt": generated, "verdict": verdict})
    )
    return ok, detail


def research_cycle_status(report: dict) -> tuple[bool, str]:
    """Evaluate the consolidated research/backtest lane as one desk artifact."""
    if not report:
        return False, "missing"

    generated = str(report.get("generatedAt", ""))
    verdict = str(report.get("verdict") or "")
    shadow = report.get("shadow") or {}
    strategy = report.get("strategyLab") or {}
    scenario_backtest = report.get("scenarioBacktest") or {}
    fresh = recent_or_today(generated, max_age_hours=72)
    ok = fresh and verdict == "research-refreshed"
    scenario_count = scenario_backtest.get("scenarioCount", 0)
    scenario_evidence_count = scenario_backtest.get("closedEvidenceCount", 0)
    scenario_observation_count = scenario_backtest.get("closedObservationCount", 0)
    detail = (
        f"{verdict} | shadow tracked={shadow.get('trackedCount', 0)} | "
        f"closed={shadow.get('closedCount', 0)} | "
        f"strategy={strategy.get('verdict') or '-'} ({strategy.get('scoredCount', 0)} scored) | "
        f"scenarios={scenario_count} | scenario evidence={scenario_evidence_count} | "
        f"scenario observations={scenario_observation_count}"
        if fresh
        else json.dumps({"generatedAt": generated, "verdict": verdict})
    )
    return ok, detail


def action_pulse_status(report: dict) -> tuple[bool, str]:
    """Evaluate the twice-daily action pulse as delivery infrastructure."""
    if not report:
        return False, "missing"

    generated = str(report.get("generatedAt", ""))
    verdict = str(report.get("verdict") or "")
    phase = str(report.get("phaseLabel") or report.get("phase") or "unknown")
    delivery = report.get("delivery") or {}
    fresh = recent_or_today(generated, max_age_hours=36)
    sent_or_not_requested = str(delivery.get("status") or "not-requested") in {
        "sent",
        "already-sent",
        "not-requested",
    }
    ok = fresh and sent_or_not_requested
    detail = (
        f"{phase} | verdict={verdict} | delivery={delivery.get('status') or 'not-requested'}"
        if fresh
        else json.dumps({"generatedAt": generated, "verdict": verdict})
    )
    return ok, detail


def blowup_guardrails_status(report: dict) -> tuple[bool, str]:
    """Evaluate the blow-up guardrails artifact without granting authority.

    Healthy means: the artifact is fresh, research-only flags are pinned, and
    verdict is one of the recognized values. A "blocked" or "advisory-warn"
    verdict is informational — the doctor reports it but does not treat it
    as a desk failure because the guardrails are visibility-only and the
    operator briefing's own caps are the enforcement layer.
    """
    if not report:
        return False, "missing"

    generated = str(report.get("generatedAt", ""))
    fresh = recent_or_today(generated, max_age_hours=36)
    research_only = bool(report.get("researchOnly")) and not bool(report.get("promotable"))
    verdict = str(report.get("verdict") or "")
    known_verdicts = {"clear", "advisory-warn", "blocked"}
    ok = fresh and research_only and verdict in known_verdicts
    slate_size = report.get("slateSize")
    detail = (
        f"{verdict} | slate={slate_size} | research-only={research_only}"
        if fresh
        else json.dumps(
            {
                "generatedAt": generated,
                "verdict": verdict,
                "researchOnly": report.get("researchOnly"),
                "promotable": report.get("promotable"),
            }
        )
    )
    return ok, detail


def conviction_research_status(report: dict) -> tuple[bool, str]:
    """Evaluate the research-only conviction map without granting authority."""
    if not report:
        return False, "missing"

    generated = str(report.get("generatedAt", ""))
    fresh = recent_or_today(generated, max_age_hours=36)
    research_only = bool(report.get("researchOnly")) and not bool(report.get("promotable"))
    scored_rows = report.get("scoredRows")
    ok = fresh and research_only and scored_rows is not None
    behemoths = ", ".join(
        str(item.get("ticker") or "")
        for item in (report.get("behemoths") or [])[:3]
        if item.get("ticker")
    )
    sleepers = ", ".join(
        str(item.get("ticker") or "")
        for item in (report.get("sleepers") or [])[:3]
        if item.get("ticker")
    )
    detail = (
        f"{scored_rows} scored | giants={behemoths or 'none'} | "
        f"sleepers={sleepers or 'none'} | research-only={research_only}"
        if fresh
        else json.dumps(
            {
                "generatedAt": generated,
                "scoredRows": scored_rows,
                "researchOnly": report.get("researchOnly"),
                "promotable": report.get("promotable"),
            }
        )
    )
    return ok, detail


def _research_module_status(report: dict, ok_verdicts: set[str], label_keys: tuple[str, ...] = ("verdict",)) -> tuple[bool, str]:
    """Shared freshness + research-only check for Phase A research modules.

    Returns (ok, detail). Stale (>36h), promotable=True, or unknown verdict
    each fail; otherwise pass with a one-line detail.
    """
    if not report:
        return False, "missing"
    generated = str(report.get("generatedAt", ""))
    fresh = recent_or_today(generated, max_age_hours=36)
    research_only = not bool(report.get("promotable"))
    verdict = str(report.get("verdict") or "unknown")
    ok = fresh and research_only and verdict in ok_verdicts
    counts = report.get("counts") or {}
    detail = (
        f"{verdict} | counts={counts} | research-only={research_only}"
        if fresh
        else json.dumps(
            {
                "generatedAt": generated,
                "verdict": verdict,
                "promotable": report.get("promotable"),
            }
        )
    )
    return ok, detail


def outcome_attribution_status(report: dict) -> tuple[bool, str]:
    return _research_module_status(
        report,
        ok_verdicts={"attribution-ready", "awaiting-closed-outcomes"},
    )


def rule_edge_decay_status(report: dict) -> tuple[bool, str]:
    return _research_module_status(
        report,
        ok_verdicts={
            "awaiting-closed-outcomes",
            "retire-candidates-present",
            "healthy",
        },
    )


def slippage_estimator_status(report: dict) -> tuple[bool, str]:
    return _research_module_status(
        report,
        ok_verdicts={"no-usable-tickets", "thin-anchors", "anchors-ready"},
    )


def expectancy_ledger_status(report: dict) -> tuple[bool, str]:
    return _research_module_status(
        report,
        ok_verdicts={"evidence-building", "awaiting-closed-outcomes"},
    )


def dte_policy_analysis_status(report: dict) -> tuple[bool, str]:
    return _research_module_status(
        report,
        ok_verdicts={"cohorts-ready", "awaiting-closed-outcomes"},
    )


def trading_behavior_audit_status(report: dict) -> tuple[bool, str]:
    return _research_module_status(
        report,
        ok_verdicts={
            "behavior-baseline-ready",
            "activity-watch",
            "disposition-watch",
            "awaiting-closed-outcomes",
        },
    )


def process_compliance_status(report: dict) -> tuple[bool, str]:
    return _research_module_status(
        report,
        ok_verdicts={"clear", "stop-new-paper-entries"},
    )


def portfolio_heat_status(report: dict) -> tuple[bool, str]:
    return _research_module_status(
        report,
        ok_verdicts={"normal", "theme-watch", "high-theme-heat"},
    )


def wheel_shadow_status(report: dict) -> tuple[bool, str]:
    return _research_module_status(
        report,
        ok_verdicts={
            "shadow-candidates-found",
            "no-capital-realistic-wheel",
            "stale-options-data",
        },
    )


def score_calibration_status(report: dict) -> tuple[bool, str]:
    return _research_module_status(
        report,
        ok_verdicts={"insufficient-data", "calibration-building", "calibration-watch"},
    )


def expected_move_ledger_status(report: dict) -> tuple[bool, str]:
    return _research_module_status(
        report,
        ok_verdicts={
            "insufficient-data",
            "move-edge-positive",
            "move-edge-negative",
            "move-edge-watch",
        },
    )


def strategy_alternative_scorer_status(report: dict) -> tuple[bool, str]:
    return _research_module_status(
        report,
        ok_verdicts={
            "no-pressure-candidates",
            "alternatives-preferred",
            "alternatives-watch",
            "stand-aside-biased",
        },
    )


def strategy_alternative_pricing_status(report: dict) -> tuple[bool, str]:
    return _research_module_status(
        report,
        ok_verdicts={
            "no-priceable-candidates",
            "priced-risk-pass",
            "priced-risk-blocked",
        },
    )


def strategy_shadow_comparison_status(report: dict) -> tuple[bool, str]:
    return _research_module_status(
        report,
        ok_verdicts={
            "shadow-comparison-ready",
            "no-passing-alternatives",
        },
    )


def portfolio_correlation_status(report: dict) -> tuple[bool, str]:
    return _research_module_status(
        report,
        ok_verdicts={
            "awaiting-outcomes",
            "diversified",
            "concentrated-by-drift",
            "concentrated-by-intent",
            "concentration-watch",
            "thin-diversification",
        },
    )


def drawdown_protocol_status(report: dict) -> tuple[bool, str]:
    return _research_module_status(
        report,
        ok_verdicts={
            "awaiting-closed-outcomes",
            "normal-sizing",
            "first-cut-advised",
            "deep-cut-advised",
            "no-new-positions-advised",
            "full-stop-advised",
        },
    )


def consensus_monitor_status(report: dict) -> tuple[bool, str]:
    return _research_module_status(
        report,
        ok_verdicts={
            "awaiting-data",
            "uncrowded",
            "normal",
            "crowded-watch",
            "consensus-extreme",
        },
    )


def paper_velocity_status(report: dict) -> tuple[bool, str]:
    """Evaluate the paper-velocity tracker freshness and verdict.

    Every published verdict is a valid research outcome; the doctor only
    checks that the artifact is present and freshly computed.
    """
    return _research_module_status(
        report,
        ok_verdicts={
            "stalled",
            "slow",
            "on-track",
            "promotion-ready",
        },
    )


def fast_paper_cohort_status(report: dict) -> tuple[bool, str]:
    """Evaluate the isolated accelerated simulation cohort."""
    if not report:
        return False, "missing"
    generated = str(report.get("generatedAt") or "")
    fresh = recent_or_today(generated, max_age_hours=36)
    verdict = str(report.get("verdict") or "unknown")
    research_only = bool(report.get("researchOnly"))
    non_promotable = not bool(report.get("promotable"))
    valid_verdicts = {
        "cycled-and-seeded",
        "seeded",
        "market-closed",
        "awaiting-next-session",
        "daily-risk-cap-limited",
        "no-priceable-candidates",
    }
    counts = report.get("counts") or {}
    ok = fresh and research_only and non_promotable and verdict in valid_verdicts
    detail = (
        f"{verdict} | opened={counts.get('selectedToday', 0)} | "
        f"closed={counts.get('closedToday', 0)} | open={counts.get('open', 0)} | "
        "promotion-credit=off"
    )
    return ok, detail


def paper_mark_to_market_status(report: dict) -> tuple[bool, str]:
    """Evaluate the paper mark-to-market freshness and fetch status.

    Every published fetchStatus is a valid research outcome (including
    'disabled' or 'not-configured', which mean Schwab options is gated off
    in this environment). The doctor checks the artifact is present and
    freshly computed; the auditor downstream decides what to do with the
    fetchStatus.
    """
    if not report:
        return False, "missing"
    generated = str(report.get("generatedAt", ""))
    fresh = recent_or_today(generated, max_age_hours=36)
    research_only = not bool(report.get("promotable"))
    verdict = str(report.get("fetchStatus") or report.get("verdict") or "unknown")
    ok_verdicts = {
        "ok",
        "fixture",
        "disabled",
        "not-configured",
        "no-open-positions",
        "partial-error",
        "error",
    }
    ok = fresh and research_only and verdict in ok_verdicts
    if fresh:
        detail = (
            f"{verdict} | open={report.get('openPositionCount')} | "
            f"marked={len(report.get('marksByTicketId') or {})} | "
            f"research-only={research_only}"
        )
    else:
        detail = json.dumps(
            {
                "generatedAt": generated,
                "verdict": verdict,
                "promotable": report.get("promotable"),
            }
        )
    return ok, detail


def trade_management_status(report: dict) -> tuple[bool, str]:
    """Evaluate the paper trade-management auditor freshness and safety flags.

    ``actions-recommended`` is a healthy research outcome: it means the
    operator has a morning decision card, not that the desk took action.
    """
    if not report:
        return False, "missing"
    generated = str(report.get("generatedAt", ""))
    fresh = recent_or_today(generated, max_age_hours=36)
    verdict = str(report.get("verdict") or "unknown")
    research_only = (
        bool(report.get("researchOnly"))
        and not bool(report.get("promotable"))
        and not bool(report.get("authorityChanged"))
        and not bool(report.get("liveTradingAllowed"))
        and not bool(report.get("brokerSubmitAllowed"))
    )
    ok = fresh and research_only and verdict in {
        "no-open-positions",
        "all-hold",
        "awaiting-data",
        "actions-recommended",
    }
    detail = (
        f"{verdict} | open={report.get('openPositionCount')} | "
        f"actionable={report.get('actionableCount')} | research-only={research_only}"
        if fresh
        else json.dumps(
            {
                "generatedAt": generated,
                "verdict": verdict,
                "researchOnly": report.get("researchOnly"),
                "promotable": report.get("promotable"),
            }
        )
    )
    return ok, detail


def capital_scaling_status(report: dict) -> tuple[bool, str]:
    """Evaluate the capital-scaling recommender freshness and verdict.

    Every published verdict is a valid research outcome; the doctor only
    checks that the artifact is present and freshly computed. The verdict
    itself (``aligned`` / ``config-cap-too-high`` / etc.) is informational
    — the operator decides whether to ack the formula.
    """
    return _research_module_status(
        report,
        ok_verdicts={
            "aligned",
            "config-cap-too-high",
            "config-cap-too-low",
            "ack-required",
            "nlv-stale",
            "nlv-missing",
            "config-cap-missing",
            "build-failed",
        },
    )


def schwab_edge_signals_status(report: dict) -> tuple[bool, str]:
    """Evaluate the Schwab edge-signals bridge freshness and verdict.

    A missing report or an unconfigured Schwab lane is a warning, not a hard
    failure: the desk runs fine without Schwab. Stale reports (>36h) are a
    warning so the operator notices when the bridge stops refreshing.
    """
    if not report:
        return False, "missing"
    generated = str(report.get("generatedAt", ""))
    fresh = recent_or_today(generated, max_age_hours=36)
    research_only = bool(report.get("researchOnly")) and not bool(report.get("promotable"))
    verdict = str(report.get("verdict") or "unknown")
    source_status = str(report.get("sourceStatus") or "unknown")
    summary = report.get("summary") or {}
    lane_counts = summary.get("laneCounts") or {}
    actionable = int(lane_counts.get("tradable-research") or 0) + int(
        lane_counts.get("calibration-watch") or 0
    )
    ok = fresh and research_only and verdict in {
        "edge-actionable",
        "watch-only",
        "thin-data-only",
        "schwab-not-configured",
        "no-rows",
        "no-source",
    }
    detail = (
        f"{verdict} | source={source_status} | actionable={actionable} | "
        f"research-only={research_only}"
        if fresh
        else json.dumps(
            {
                "generatedAt": generated,
                "verdict": verdict,
                "sourceStatus": source_status,
                "researchOnly": report.get("researchOnly"),
                "promotable": report.get("promotable"),
            }
        )
    )
    return ok, detail


def schwab_account_sync_status(report: dict) -> tuple[bool, str]:
    """Evaluate the read-only Schwab account sync freshness and safety flags."""
    if not report:
        return False, "missing"
    generated = str(report.get("generatedAt", ""))
    fresh = recent_or_today(generated, max_age_hours=36)
    verdict = str(report.get("verdict") or "")
    counts = report.get("counts") or {}
    safe = (
        bool(report.get("brokerReadOnly"))
        and not bool(report.get("orderEndpointsAllowed"))
        and not bool(report.get("brokerSubmitAllowed"))
        and not bool(report.get("liveTradingAllowed"))
    )
    ok = fresh and safe and bool(report.get("ok")) and verdict in {"healthy"}
    detail = (
        f"{verdict} | positions={counts.get('positions', 0)} | "
        f"approved={counts.get('approvedAccounts', 0)}/{counts.get('accounts', 0)} | "
        f"suffix={report.get('matchedSuffix') or '-'} | read-only={safe}"
        if fresh
        else json.dumps(
            {
                "generatedAt": generated,
                "verdict": verdict,
                "readOnly": report.get("brokerReadOnly"),
                "ordersAllowed": report.get("orderEndpointsAllowed"),
            }
        )
    )
    return ok, detail


def schwab_oauth_status(status: dict) -> tuple[bool, str]:
    """Evaluate local OAuth continuity without printing secret material."""
    configured = bool(status.get("clientIdConfigured")) and bool(
        status.get("clientSecretConfigured")
    )
    if not configured:
        return True, "not configured"
    if status.get("reauthorizationRequired"):
        return False, "reauthorization required; run inferno_schwab_oauth.py restart"
    if not status.get("accessTokenPresent") or not status.get("refreshTokenPresent"):
        return False, "access or refresh token missing"

    age_seconds = status.get("refreshTokenAgeSeconds")
    age_days = float(age_seconds) / 86_400 if age_seconds is not None else None
    if age_days is not None and age_days >= SCHWAB_REFRESH_RESTART_ADVISORY_DAYS:
        return (
            False,
            f"restart advisory | consent grant age={age_days:.1f}d | "
            "renew before the next trading session",
        )

    age_detail = f"{age_days:.1f}d" if age_days is not None else "unknown"
    return (
        True,
        f"ready | consent grant age={age_detail} | "
        f"access refresh needed={bool(status.get('accessTokenNeedsRefresh'))}",
    )


def paper_test_director_status(director: dict, reducer: dict, now: datetime) -> tuple[bool, str]:
    """Evaluate paper-test readiness with a shadow-evidence fallback.

    A `no-viable-paper-tests` director verdict is a real warning when nothing
    else can advance. It is *not* a desk failure when the bottleneck reducer has
    already produced a fresh shadow-only scenario slate, because the research
    loop can keep collecting evidence without broker staging or live authority.
    """
    if not director:
        return False, "missing"

    director_fresh = in_current_service_cycle(str(director.get("generatedAt", "")), now=now)
    verdict = str(director.get("verdict") or "")
    counts = director.get("counts") or {}
    reducer_fresh = in_current_service_cycle(str(reducer.get("generatedAt", "")), now=now)
    reducer_counts = reducer.get("counts") or {}
    shadow_fallback_ready = (
        reducer_fresh
        and reducer.get("verdict") == "scenario-slate-ready"
        and int(reducer_counts.get("scenarios") or 0) > 0
        and int(reducer_counts.get("shadowOnly") or 0) > 0
    )
    ok_verdicts = {"ready-to-paper-stage", "auto-paper-selected", "approval-bottleneck", "research-watch"}
    ok = director_fresh and (verdict in ok_verdicts or (verdict == "no-viable-paper-tests" and shadow_fallback_ready))
    detail = (
        f"{verdict} | stageable={counts.get('stageableNow', 0)} | "
        f"auto-paper={counts.get('autoPaperSelected', 0)} | "
        f"approval-only={counts.get('approvalOnly', 0)} | "
        f"hard-blocked={counts.get('hardBlocked', 0)}"
        if director_fresh
        else json.dumps(
            {
                "generatedAt": director.get("generatedAt"),
                "verdict": verdict,
            }
        )
    )
    if director_fresh and shadow_fallback_ready:
        detail += f" | shadow-fallback=ready ({reducer_counts.get('shadowOnly', 0)})"
    return ok, detail


def main() -> int:
    load_env_file(SMTP_ENV_FILE)

    now = local_now()
    today = local_today()
    cycle_day = cycle_reference_day(now)
    active_cycle_days = cycle_days(now)
    lines: list[str] = ["Inferno Doctor", f"Checked at: {datetime.now().astimezone().isoformat()}", ""]
    warnings = 0

    smtp_ok = smtp_configured()
    lines.append(summarize_status("SMTP", smtp_ok, "configured" if smtp_ok else "not configured"))
    if not smtp_ok:
        warnings += 1
    else:
        smtp_auth_ok, smtp_auth_detail = smtp_login_ok()
        lines.append(summarize_status("SMTP login", smtp_auth_ok, smtp_auth_detail))
        if not smtp_auth_ok:
            warnings += 1

    bt_root = default_backtest_root()
    bt_root_ok = bt_root.exists()
    lines.append(summarize_status("Backtest root", bt_root_ok, str(bt_root) if bt_root_ok else f"missing: {bt_root}"))
    if not bt_root_ok:
        warnings += 1

    bt_python = backtest_python()
    bt_python_ok = bt_python.exists()
    lines.append(summarize_status("Backtest Python", bt_python_ok, str(bt_python) if bt_python_ok else f"missing: {bt_python}"))
    if not bt_python_ok:
        warnings += 1

    missing_scripts = [script for script in UPDATER_SCRIPTS if not (bt_root / script).exists()]
    scripts_ok = not missing_scripts
    script_detail = UPDATER_LABEL if scripts_ok else f"missing: {', '.join(missing_scripts)}"
    lines.append(summarize_status("Updater scripts", scripts_ok, script_detail))
    if not scripts_ok:
        warnings += 1

    dawn_ok, dawn_detail = launch_agent_status(LABEL)
    lines.append(summarize_status("Dawn agent", dawn_ok, dawn_detail))
    if not dawn_ok:
        warnings += 1

    watchdog_ok, watchdog_detail = launch_agent_status(WATCHDOG_LABEL)
    lines.append(summarize_status("Watchdog agent", watchdog_ok, watchdog_detail))
    if not watchdog_ok:
        warnings += 1

    downloads_watch_ok, downloads_watch_detail = launch_agent_status(DOWNLOADS_WATCH_LABEL)
    desktop_automation_ok, desktop_automation_detail = launch_agent_status(DESKTOP_AUTOMATION_LABEL)
    local_automation_loaded = downloads_watch_ok or desktop_automation_ok
    local_automation_detail_parts = []
    if downloads_watch_ok:
        local_automation_detail_parts.append(f"downloads-watch ({downloads_watch_detail})")
    if desktop_automation_ok:
        local_automation_detail_parts.append(f"desktop-coordinator ({desktop_automation_detail})")
    lines.append(
        summarize_status(
            "Local automation agent",
            local_automation_loaded,
            "loaded: " + ", ".join(local_automation_detail_parts)
            if local_automation_loaded
            else "not loaded",
        )
    )
    if not local_automation_loaded:
        warnings += 1

    action_pulse_ok, action_pulse_detail = launch_agent_status(ACTION_PULSE_LABEL)
    lines.append(
        summarize_status(
            "Action pulse agent",
            action_pulse_ok,
            f"07:05 and 13:30 | {action_pulse_detail}" if action_pulse_ok else action_pulse_detail,
        )
    )
    if not action_pulse_ok:
        warnings += 1

    sched_text = pmset_sched_text()
    wake_label = f"{WAKE_HOUR:02d}:{WAKE_MINUTE:02d}"
    wake_phrase = f"wakepoweron at {WAKE_HOUR if WAKE_HOUR % 12 else 12}:{WAKE_MINUTE:02d}AM"
    wake_ok = wake_phrase in sched_text
    lines.append(summarize_status("Wake schedule", wake_ok, f"{wake_label} wake is scheduled" if wake_ok else f"{wake_label} wake not found"))
    if not wake_ok:
        warnings += 1

    custom_text = pmset_custom_text()
    ac_sleep_ok = "AC Power:" in custom_text and "sleep                15" in custom_text
    lines.append(summarize_status("AC sleep", ac_sleep_ok, "AC sleep is 15 minutes" if ac_sleep_ok else "AC sleep is not 15 minutes"))
    if not ac_sleep_ok:
        warnings += 1

    ops_status = load_json_file(OPS_STATUS_FILE) or {}
    emailed_status = latest_emailed_run_for_cycle(active_cycle_days, now=now)
    ops_reference = emailed_status or ops_status
    ops_today = in_current_service_cycle(str(ops_reference.get("generatedAt", "")), now=now)
    ops_email = bool(ops_reference.get("emailSent"))
    ops_ok = ops_today and ops_email and bool(ops_reference.get("ok", True))
    ops_detail = f"fresh run and email recorded for cycle {cycle_day}" if ops_ok else json.dumps(
        {
            "generatedAt": ops_reference.get("generatedAt"),
            "ok": ops_reference.get("ok", True),
            "emailSent": ops_reference.get("emailSent"),
        }
    )
    lines.append(summarize_status("Morning run", ops_ok, ops_detail))
    if not ops_ok:
        warnings += 1
    else:
        top_tickers = ops_reference.get("topTickers") or ops_reference.get("eligibleTickers", [])
        lines.append(f"Top tickers: {', '.join(top_tickers[:5]) or 'none'}")

    snapshot = load_json_file(SNAPSHOT_FILE) or {}
    snapshot_rows = snapshot.get("rows", [])
    negative_earnings_rows = [
        row for row in snapshot_rows
        if isinstance(row, dict) and int(row.get("daysUntilEarnings") or 0) < 0
    ]
    earnings_dates_ok = bool(snapshot_rows) and not negative_earnings_rows
    earnings_dates_detail = (
        f"{len(snapshot_rows)} snapshot rows checked; no negative earnings windows"
        if earnings_dates_ok
        else f"negative rows: {', '.join(row.get('ticker', 'UNKNOWN') for row in negative_earnings_rows[:8]) or 'snapshot missing'}"
    )
    lines.append(summarize_status("Earnings windows", earnings_dates_ok, earnings_dates_detail))
    if not earnings_dates_ok:
        warnings += 1

    market_context_audit = load_json_file(MARKET_CONTEXT_AUDIT_FILE) or {}
    market_context_today = in_current_service_cycle(str(market_context_audit.get("generatedAt", "")), now=now)
    populated_rows = int(market_context_audit.get("populatedRows") or 0)
    total_rows = int(market_context_audit.get("totalRows") or 0)
    market_context_ok = market_context_today and total_rows > 0 and populated_rows == total_rows
    market_context_detail = (
        f"{populated_rows}/{total_rows} rows confirmed | avg RVOL {market_context_audit.get('averageRvol')}"
        if market_context_ok
        else json.dumps(
            {
                "generatedAt": market_context_audit.get("generatedAt"),
                "populatedRows": populated_rows,
                "totalRows": total_rows,
                "missingTickers": (market_context_audit.get("missingTickers") or [])[:5],
            }
        )
    )
    lines.append(summarize_status("Market context audit", market_context_ok, market_context_detail))
    if not market_context_ok:
        warnings += 1

    ticker_universe_audit = load_json_file(TICKER_UNIVERSE_AUDIT_FILE) or {}
    ticker_universe_today = in_current_service_cycle(str(ticker_universe_audit.get("generatedAt", "")), now=now)
    ticker_universe_verdict = str(ticker_universe_audit.get("verdict") or "")
    ticker_universe_counts = ticker_universe_audit.get("counts") or {}
    ticker_universe_ok = ticker_universe_today and ticker_universe_verdict in {"healthy", "healthy-with-advisories"}
    ticker_universe_detail = (
        f"{ticker_universe_verdict} | critical={ticker_universe_counts.get('criticalIssueCount', 0)} | "
        f"advisory={ticker_universe_counts.get('advisoryIssueCount', 0)} | "
        f"hydration={len(ticker_universe_audit.get('hydrationNeededTickers') or [])}"
        if ticker_universe_today
        else json.dumps(
            {
                "generatedAt": ticker_universe_audit.get("generatedAt"),
                "verdict": ticker_universe_verdict,
            }
        )
    )
    lines.append(summarize_status("Ticker universe audit", ticker_universe_ok, ticker_universe_detail))
    if ticker_universe_audit and not ticker_universe_ok:
        warnings += 1

    data_readiness = load_json_file(DATA_READINESS_AUDIT_FILE) or {}
    data_readiness_today = in_current_service_cycle(str(data_readiness.get("generatedAt", "")), now=now)
    data_readiness_summary = data_readiness.get("summary") or {}
    data_readiness_verdict = str(data_readiness.get("verdict") or "")
    data_readiness_ok = data_readiness_today and data_readiness_verdict == "ready-for-next-week-prep" and bool(
        data_readiness.get("dailyPrepReady")
    )
    data_readiness_detail = (
        f"{data_readiness_verdict} | daily-safe {data_readiness_summary.get('dailySafeHealthy', 0)}/{data_readiness_summary.get('dailySafeTotal', 0)} | manual broker confirmation still required"
        if data_readiness_ok
        else json.dumps(
            {
                "generatedAt": data_readiness.get("generatedAt"),
                "verdict": data_readiness_verdict,
                "dailyPrepReady": data_readiness.get("dailyPrepReady"),
            }
        )
    )
    lines.append(summarize_status("Data readiness audit", data_readiness_ok, data_readiness_detail))
    if not data_readiness_ok:
        warnings += 1

    watchdog_status = load_json_file(WATCHDOG_STATUS_FILE) or {}
    watchdog_today = in_current_service_cycle(str(watchdog_status.get("checkedAt", "")), now=now)
    watchdog_ok = watchdog_today and bool(watchdog_status.get("ok"))
    watchdog_detail = "watchdog checked in cleanly today" if watchdog_ok else json.dumps(
        {
            "checkedAt": watchdog_status.get("checkedAt"),
            "ok": watchdog_status.get("ok"),
            "reasons": watchdog_status.get("reasons"),
        }
    )
    lines.append(summarize_status("Watchdog status", watchdog_ok, watchdog_detail))
    if not watchdog_ok:
        warnings += 1

    execution_queue = load_json_file(EXECUTION_QUEUE_FILE) or {}
    execution_today = in_current_service_cycle(str(execution_queue.get("generatedAt", "")), now=now)
    execution_ok = execution_today and execution_queue.get("count") is not None
    execution_detail = (
        f"{execution_queue.get('activeReadyCount', 0)} ready / {execution_queue.get('count', 0)} staged"
        if execution_ok
        else json.dumps(
            {
                "generatedAt": execution_queue.get("generatedAt"),
                "count": execution_queue.get("count"),
            }
        )
    )
    lines.append(summarize_status("Execution desk", execution_ok, execution_detail))
    if not execution_ok:
        warnings += 1

    cloud_execution = load_json_file(CLOUD_EXECUTION_AUDIT_FILE) or {}
    cloud_execution_today = in_current_service_cycle(str(cloud_execution.get("generatedAt", "")), now=now)
    cloud_execution_verdict = str(cloud_execution.get("verdict") or "")
    strike_cloud_proof = False
    for job in cloud_execution.get("jobs") or []:
        if job.get("key") == "strikes":
            execution = job.get("execution") or {}
            strike_cloud_proof = (
                cloud_execution_today
                and cloud_execution_verdict == "healthy"
                and bool(execution.get("completed"))
                and bool(job.get("successLogFound"))
            )
            break

    strike_window_started = now.weekday() != 5 and (now.hour, now.minute) >= (7, 45)
    strike_plan = load_json_file(STRIKE_PLAN_FILE) or {}
    paper_ledger = load_json_file(PAPER_EXECUTION_LEDGER_FILE) or {}
    if strike_window_started:
        strike_plan_today = in_current_service_cycle(str(strike_plan.get("generatedAt", "")), now=now)
        paper_ledger_today = in_current_service_cycle(str(paper_ledger.get("updatedAt", "")), now=now)
        strike_ok = (strike_plan_today and paper_ledger_today) or strike_cloud_proof
        strike_detail = (
            f"{paper_ledger.get('count', 0)} paper tickets recorded"
            if strike_ok
            else json.dumps(
                {
                    "strikePlanGeneratedAt": strike_plan.get("generatedAt"),
                    "paperLedgerUpdatedAt": paper_ledger.get("updatedAt"),
                }
            )
        )
        lines.append(summarize_status("Strike ledger", strike_ok, strike_detail))
        if not strike_ok:
            warnings += 1
        # Informational: setup-concentration governor visibility. Demotions
        # mean the cap fired as designed, not a problem.
        gov_ok, gov_detail = concentration_governor_status(strike_plan)
        lines.append(summarize_status("Setup concentration governor", gov_ok, gov_detail))
    else:
        lines.append(summarize_status("Strike ledger", True, "post-open strike window has not started yet"))

    performance = load_json_file(PERFORMANCE_ANALYTICS_FILE) or {}
    performance_today = in_current_service_cycle(str(performance.get("generatedAt", "")), now=now)
    performance_ok = performance_today and performance.get("count") is not None
    performance_detail = (
        f"{performance.get('count', 0)} tickets analyzed; verdict {(performance.get('deskVerdict') or {}).get('level')}"
        if performance_ok
        else json.dumps(
            {
                "generatedAt": performance.get("generatedAt"),
                "count": performance.get("count"),
            }
        )
    )
    lines.append(summarize_status("Performance analytics", performance_ok, performance_detail))
    if not performance_ok:
        warnings += 1

    # Informational: surface the dominant block-reason bucket so the funnel
    # killer is visible at a glance. Never bumps warnings.
    block_bucket_ok, block_bucket_detail = block_reason_top_bucket_status(performance)
    lines.append(summarize_status("Top block-reason bucket", block_bucket_ok, block_bucket_detail))

    strategy_lab = load_json_file(STRATEGY_LAB_FILE) or {}
    strategy_lab_today = in_current_service_cycle(str(strategy_lab.get("generatedAt", "")), now=now)
    strategy_lab_ok = strategy_lab_today and (strategy_lab.get("deskVerdict") or {}).get("level") is not None
    strategy_lab_detail = (
        f"{(strategy_lab.get('deskVerdict') or {}).get('level')} | "
        f"{(strategy_lab.get('overall') or {}).get('scoredCount', 0)} scored"
        if strategy_lab_ok
        else json.dumps(
            {
                "generatedAt": strategy_lab.get("generatedAt"),
                "deskVerdict": (strategy_lab.get("deskVerdict") or {}).get("level"),
            }
        )
    )
    lines.append(summarize_status("Strategy lab", strategy_lab_ok, strategy_lab_detail))
    if not strategy_lab_ok:
        warnings += 1

    shadow = load_json_file(SHADOW_EVIDENCE_FILE) or {}
    if strike_window_started:
        shadow_today = in_current_service_cycle(str(shadow.get("updatedAt", "")), now=now)
        shadow_ok = shadow_today and shadow.get("count") is not None
        overall = shadow.get("overall") or {}
        shadow_detail = (
            f"{overall.get('trackedCount', shadow.get('count', 0))} tracked | "
            f"{overall.get('closedCount', 0)} closed | research-only"
            if shadow_ok
            else json.dumps(
                {
                    "updatedAt": shadow.get("updatedAt"),
                    "count": shadow.get("count"),
                }
            )
        )
        lines.append(summarize_status("Shadow evidence", shadow_ok, shadow_detail))
        if not shadow_ok:
            warnings += 1
    else:
        lines.append(summarize_status("Shadow evidence", True, "post-open strike window has not started yet"))

    exposure = load_json_file(EXPOSURE_ANALYTICS_FILE) or {}
    exposure_today = in_current_service_cycle(str(exposure.get("generatedAt", "")), now=now)
    exposure_ok = exposure_today and exposure.get("tickerCount") is not None
    exposure_detail = (
        f"{exposure.get('tickerCount', 0)} tickers analyzed; verdict {(exposure.get('verdict') or {}).get('level')}"
        if exposure_ok
        else json.dumps(
            {
                "generatedAt": exposure.get("generatedAt"),
                "tickerCount": exposure.get("tickerCount"),
            }
        )
    )
    lines.append(summarize_status("Exposure analytics", exposure_ok, exposure_detail))
    if not exposure_ok:
        warnings += 1

    edge = load_json_file(EDGE_RESEARCH_FILE) or {}
    edge_today = in_current_service_cycle(str(edge.get("generatedAt", "")), now=now)
    edge_ok = edge_today and edge.get("scoredRows") is not None
    edge_detail = (
        f"{edge.get('scoredRows', 0)} shovel candidates scored"
        if edge_ok
        else json.dumps(
            {
                "generatedAt": edge.get("generatedAt"),
                "scoredRows": edge.get("scoredRows"),
            }
        )
    )
    lines.append(summarize_status("Edge research", edge_ok, edge_detail))
    if not edge_ok:
        warnings += 1

    conviction_research = load_json_file(CONVICTION_RESEARCH_FILE) or {}
    conviction_ok, conviction_detail = conviction_research_status(conviction_research)
    lines.append(summarize_status("Conviction research", conviction_ok, conviction_detail))
    if not conviction_ok:
        warnings += 1

    schwab_edge = load_json_file(SCHWAB_EDGE_SIGNALS_FILE) or {}
    schwab_edge_ok, schwab_edge_detail = schwab_edge_signals_status(schwab_edge)
    lines.append(summarize_status("Schwab edge signals", schwab_edge_ok, schwab_edge_detail))
    if not schwab_edge_ok:
        warnings += 1

    try:
        schwab_oauth = load_schwab_oauth_status(load_schwab_oauth_config())
    except Exception as exc:  # noqa: BLE001 - doctor should render the failure.
        schwab_oauth = {
            "clientIdConfigured": True,
            "clientSecretConfigured": True,
            "lastRefreshError": str(exc),
        }
    schwab_oauth_ok, schwab_oauth_detail = schwab_oauth_status(schwab_oauth)
    lines.append(summarize_status("Schwab OAuth", schwab_oauth_ok, schwab_oauth_detail))
    if not schwab_oauth_ok:
        warnings += 1

    schwab_account = load_json_file(SCHWAB_ACCOUNT_SYNC_FILE) or {}
    schwab_account_ok, schwab_account_detail = schwab_account_sync_status(schwab_account)
    lines.append(summarize_status("Schwab account sync", schwab_account_ok, schwab_account_detail))
    if schwab_account and not schwab_account_ok:
        warnings += 1

    attribution = load_json_file(OUTCOME_ATTRIBUTION_FILE) or {}
    attribution_ok, attribution_detail = outcome_attribution_status(attribution)
    lines.append(summarize_status("Outcome attribution", attribution_ok, attribution_detail))
    if not attribution_ok:
        warnings += 1

    rule_decay = load_json_file(RULE_EDGE_DECAY_FILE) or {}
    rule_decay_ok, rule_decay_detail = rule_edge_decay_status(rule_decay)
    lines.append(summarize_status("Rule edge decay", rule_decay_ok, rule_decay_detail))
    if not rule_decay_ok:
        warnings += 1

    slippage = load_json_file(SLIPPAGE_ESTIMATOR_FILE) or {}
    slippage_ok, slippage_detail = slippage_estimator_status(slippage)
    lines.append(summarize_status("Slippage estimator", slippage_ok, slippage_detail))
    if not slippage_ok:
        warnings += 1

    score_calibration = load_json_file(SCORE_CALIBRATION_FILE) or {}
    score_calibration_ok, score_calibration_detail = score_calibration_status(score_calibration)
    lines.append(summarize_status("Score calibration", score_calibration_ok, score_calibration_detail))
    if not score_calibration_ok:
        warnings += 1

    expected_move = load_json_file(EXPECTED_MOVE_LEDGER_FILE) or {}
    expected_move_ok, expected_move_detail = expected_move_ledger_status(expected_move)
    lines.append(summarize_status("Expected move ledger", expected_move_ok, expected_move_detail))
    if not expected_move_ok:
        warnings += 1

    strategy_alternatives = load_json_file(STRATEGY_ALTERNATIVE_SCORER_FILE) or {}
    strategy_alternatives_ok, strategy_alternatives_detail = strategy_alternative_scorer_status(strategy_alternatives)
    lines.append(summarize_status("Strategy alternative scorer", strategy_alternatives_ok, strategy_alternatives_detail))
    if not strategy_alternatives_ok:
        warnings += 1

    strategy_alt_pricing = load_json_file(STRATEGY_ALTERNATIVE_PRICING_FILE) or {}
    strategy_alt_pricing_ok, strategy_alt_pricing_detail = strategy_alternative_pricing_status(strategy_alt_pricing)
    lines.append(summarize_status("Strategy alternative pricing", strategy_alt_pricing_ok, strategy_alt_pricing_detail))
    if not strategy_alt_pricing_ok:
        warnings += 1

    strategy_shadow_comparison = load_json_file(STRATEGY_SHADOW_COMPARISON_FILE) or {}
    strategy_shadow_ok, strategy_shadow_detail = strategy_shadow_comparison_status(strategy_shadow_comparison)
    lines.append(summarize_status("Strategy shadow comparison", strategy_shadow_ok, strategy_shadow_detail))
    if not strategy_shadow_ok:
        warnings += 1

    portfolio_corr = load_json_file(PORTFOLIO_CORRELATION_FILE) or {}
    portfolio_corr_ok, portfolio_corr_detail = portfolio_correlation_status(portfolio_corr)
    lines.append(summarize_status("Portfolio correlation", portfolio_corr_ok, portfolio_corr_detail))
    if not portfolio_corr_ok:
        warnings += 1

    drawdown = load_json_file(DRAWDOWN_PROTOCOL_FILE) or {}
    drawdown_ok, drawdown_detail = drawdown_protocol_status(drawdown)
    lines.append(summarize_status("Drawdown protocol", drawdown_ok, drawdown_detail))
    if not drawdown_ok:
        warnings += 1

    consensus = load_json_file(CONSENSUS_MONITOR_FILE) or {}
    consensus_ok, consensus_detail = consensus_monitor_status(consensus)
    lines.append(summarize_status("Consensus monitor", consensus_ok, consensus_detail))
    if not consensus_ok:
        warnings += 1

    paper_velocity = load_json_file(PAPER_VELOCITY_FILE) or {}
    paper_velocity_ok, paper_velocity_detail = paper_velocity_status(paper_velocity)
    lines.append(summarize_status("Paper velocity", paper_velocity_ok, paper_velocity_detail))
    if not paper_velocity_ok:
        warnings += 1

    fast_paper = load_json_file(FAST_PAPER_COHORT_FILE) or {}
    fast_paper_ok, fast_paper_detail = fast_paper_cohort_status(fast_paper)
    lines.append(summarize_status("Fast paper cohort", fast_paper_ok, fast_paper_detail))
    if not fast_paper_ok:
        warnings += 1

    paper_mtm = load_json_file(PAPER_MTM_FILE) or {}
    paper_mtm_ok, paper_mtm_detail = paper_mark_to_market_status(paper_mtm)
    lines.append(summarize_status("Paper mark-to-market", paper_mtm_ok, paper_mtm_detail))
    if not paper_mtm_ok:
        warnings += 1

    trade_management = load_json_file(TRADE_MANAGEMENT_FILE) or {}
    trade_management_ok, trade_management_detail = trade_management_status(trade_management)
    lines.append(summarize_status("Trade management", trade_management_ok, trade_management_detail))
    if not trade_management_ok:
        warnings += 1

    expectancy_ledger = load_json_file(EXPECTANCY_LEDGER_FILE) or {}
    expectancy_ok, expectancy_detail = expectancy_ledger_status(expectancy_ledger)
    lines.append(summarize_status("Net-R expectancy", expectancy_ok, expectancy_detail))
    if not expectancy_ok:
        warnings += 1

    dte_policy = load_json_file(DTE_POLICY_ANALYSIS_FILE) or {}
    dte_policy_ok, dte_policy_detail = dte_policy_analysis_status(dte_policy)
    lines.append(summarize_status("DTE policy analysis", dte_policy_ok, dte_policy_detail))
    if not dte_policy_ok:
        warnings += 1

    behavior_audit = load_json_file(TRADING_BEHAVIOR_AUDIT_FILE) or {}
    behavior_ok, behavior_detail = trading_behavior_audit_status(behavior_audit)
    lines.append(summarize_status("Trading behavior audit", behavior_ok, behavior_detail))
    if not behavior_ok:
        warnings += 1

    process_compliance = load_json_file(PROCESS_COMPLIANCE_FILE) or {}
    process_ok, process_detail = process_compliance_status(process_compliance)
    lines.append(summarize_status("Process compliance", process_ok, process_detail))
    if not process_ok:
        warnings += 1

    portfolio_heat = load_json_file(PORTFOLIO_HEAT_FILE) or {}
    portfolio_heat_ok, portfolio_heat_detail = portfolio_heat_status(portfolio_heat)
    lines.append(summarize_status("Portfolio heat", portfolio_heat_ok, portfolio_heat_detail))
    if not portfolio_heat_ok:
        warnings += 1

    wheel_shadow = load_json_file(WHEEL_SHADOW_FILE) or {}
    wheel_ok, wheel_detail = wheel_shadow_status(wheel_shadow)
    lines.append(summarize_status("Wheel shadow", wheel_ok, wheel_detail))
    if not wheel_ok:
        warnings += 1

    capital_scaling = load_json_file(CAPITAL_SCALING_FILE) or {}
    capital_scaling_ok, capital_scaling_detail = capital_scaling_status(capital_scaling)
    lines.append(summarize_status("Capital scaling", capital_scaling_ok, capital_scaling_detail))
    if not capital_scaling_ok:
        warnings += 1

    blowup_guardrails = load_json_file(BLOWUP_GUARDRAILS_FILE) or {}
    blowup_ok, blowup_detail = blowup_guardrails_status(blowup_guardrails)
    lines.append(summarize_status("Blow-up guardrails", blowup_ok, blowup_detail))
    if not blowup_ok:
        warnings += 1

    authority = load_json_file(AUTHORITY_MANIFEST_FILE) or {}
    authority_today = in_current_service_cycle(str(authority.get("generatedAt", "")), now=now)
    authority_ok = authority_today and (authority.get("decision") or {}).get("authorityLevel") is not None
    decision = authority.get("decision") or {}
    authority_detail = (
        f"{decision.get('authorityLevel')} | broker submit {decision.get('brokerSubmitAllowed')}"
        if authority_ok
        else json.dumps(
            {
                "generatedAt": authority.get("generatedAt"),
                "authorityLevel": decision.get("authorityLevel"),
            }
        )
    )
    lines.append(summarize_status("Authority manifest", authority_ok, authority_detail))
    if not authority_ok:
        warnings += 1

    downloads_manager = load_json_file(DOWNLOADS_MANAGER_FILE) or {}
    downloads_today = in_current_service_cycle(str(downloads_manager.get("generatedAt", "")), now=now)
    downloads_ok = downloads_today and downloads_manager.get("importedFiles") is not None
    downloads_detail = (
        f"{downloads_manager.get('importedFiles', 0)} files | {downloads_manager.get('importedRows', 0)} rows"
        if downloads_ok
        else json.dumps(
            {
                "generatedAt": downloads_manager.get("generatedAt"),
                "importedFiles": downloads_manager.get("importedFiles"),
            }
        )
    )
    lines.append(summarize_status("Downloads manager", downloads_ok, downloads_detail))
    if not downloads_ok:
        warnings += 1

    downloads_watch = load_json_file(DOWNLOADS_WATCH_FILE) or {}
    downloads_watch_today = in_current_service_cycle(str(downloads_watch.get("generatedAt", "")), now=now)
    downloads_watch_skipped = bool(downloads_watch.get("skipped", False))
    skip_reason = str(downloads_watch.get("skipReason") or "")
    downloads_watch_ok = downloads_watch_today and (
        not downloads_watch_skipped or "outside" in skip_reason
    )
    if downloads_watch_today and downloads_watch_skipped:
        downloads_watch_detail = f"idle safely | {skip_reason or 'watch window closed'}"
    elif downloads_watch_today:
        downloads_watch_detail = (
            f"{(downloads_watch.get('downloadsManager') or {}).get('importedFiles', 0)} files | "
            f"{(downloads_watch.get('downloadsManager') or {}).get('importedRows', 0)} rows | "
            f"export-first {downloads_watch.get('exportFirst', False)}"
        )
    else:
        downloads_watch_detail = json.dumps(
            {
                "generatedAt": downloads_watch.get("generatedAt"),
                "skipped": downloads_watch.get("skipped"),
            }
        )
    lines.append(summarize_status("Downloads watch run", downloads_watch_ok, downloads_watch_detail))
    if not downloads_watch_ok:
        warnings += 1

    desktop_automation = load_json_file(DESKTOP_AUTOMATION_FILE) or {}
    tos_visibility = build_tos_visibility_summary()
    desktop_today = in_current_service_cycle(str(desktop_automation.get("generatedAt", "")), now=now)
    desktop_verdict = str(desktop_automation.get("verdict") or "")
    desktop_message = str(
        desktop_automation.get("message")
        or desktop_automation.get("blockReason")
        or ""
    )
    desktop_tos_closed_low_power = (
        desktop_today
        and desktop_verdict == "blocked"
        and not TOS_EXPORT_AUTOMATION_ENABLED
        and "thinkorswim is not running" in desktop_message.lower()
    )
    desktop_ok = (
        not desktop_automation
        or desktop_tos_closed_low_power
        or (
            desktop_today
            and desktop_verdict in {"ready", "review", "scheduled-idle"}
        )
    )
    if not desktop_automation:
        desktop_detail = "not run yet"
    elif desktop_tos_closed_low_power:
        desktop_detail = f"attach-only safe | {render_tos_visibility_line(tos_visibility)}"
    elif desktop_today:
        desktop_detail = (
            f"{desktop_verdict} | {desktop_automation.get('message')}"
        )
    else:
        desktop_detail = json.dumps(
            {
                "generatedAt": desktop_automation.get("generatedAt"),
                "verdict": desktop_verdict,
            }
        )
    # The desktop coordinator is advisory unless it explicitly ran and blocked.
    lines.append(summarize_status("Desktop automation", desktop_ok, desktop_detail))
    if desktop_automation and not desktop_ok:
        warnings += 1

    export_stability = load_json_file(TOS_EXPORT_STABILITY_FILE) or {}
    if export_stability:
        stability_verdict = export_stability.get("verdict") or "unknown"
        stability_dominant = export_stability.get("dominantFailMode") or "n/a"
        stability_today = in_current_service_cycle(str(export_stability.get("generatedAt", "")), now=now)
        stability_attach_only_safe = (
            stability_today
            and not TOS_EXPORT_AUTOMATION_ENABLED
            and stability_verdict == "blocked"
            and stability_dominant in {"account-not-authorized", "panel-unsafe", "window-missing"}
        )
        stability_ok = stability_today and stability_verdict in {
            "stable-ready",
            "transient-recovered",
            "inactive-safe",
        } or stability_attach_only_safe
        if stability_attach_only_safe:
            stability_detail = (
                f"attach-only safe | dominant {stability_dominant} | "
                "export remains blocked until the approved account/window is visible"
            )
        else:
            stability_detail = f"{stability_verdict} | dominant {stability_dominant}"
        lines.append(summarize_status("TOS export stability", stability_ok, stability_detail))
        if not stability_ok:
            warnings += 1

    export_verifier = load_json_file(TOS_EXPORT_VERIFIER_FILE) or {}
    export_shortcut = (
        export_verifier.get("shortcut")
        or os.environ.get("TOS_EXPORT_SHORTCUT")
        or "command+shift+e"
    )
    export_verdict = export_verifier.get("verdict") or ("inactive-safe" if not TOS_EXPORT_AUTOMATION_ENABLED else "unknown")
    export_ok = export_verdict in {"ready", "ready-live-readonly", "inactive-safe", "manual-check"}
    export_detail = (
        f"{export_verdict} | shortcut {export_shortcut} | app running {export_verifier.get('appRunning')}"
        if export_verifier
        else f"{'inactive-safe' if not TOS_EXPORT_AUTOMATION_ENABLED else 'unknown'} | shortcut {export_shortcut}"
    )
    current_panel = ((export_verifier.get("sessionProbe") or {}).get("currentPanel") if export_verifier else None)
    current_panel_safety = ((export_verifier.get("sessionProbe") or {}).get("currentPanelSafety") if export_verifier else None)
    if current_panel:
        export_detail += f" | panel {current_panel} ({current_panel_safety})"
    lines.append(summarize_status("TOS export verifier", export_ok, export_detail))
    if not export_ok:
        warnings += 1

    session_probe = load_json_file(TOS_SESSION_PROBE_FILE) or {}
    session_probe_today = in_current_service_cycle(str(session_probe.get("generatedAt", "")), now=now)
    session_probe_ok = session_probe_today and bool(session_probe.get("ok"))
    session_probe_detail = (
        session_probe.get("summary")
        or session_probe.get("message")
        or json.dumps({"generatedAt": session_probe.get("generatedAt"), "ok": session_probe.get("ok")})
    )
    lines.append(summarize_status("TOS session probe", session_probe_ok, session_probe_detail))
    if not session_probe_ok:
        warnings += 1

    export_bridge = load_json_file(TOS_EXPORT_BRIDGE_FILE) or {}
    export_status = export_bridge.get("status") or ("enabled" if TOS_EXPORT_AUTOMATION_ENABLED else "disabled")
    # A disabled export bridge is a deliberate safe mode, not an unhealthy desk state.
    lines.append(summarize_status("TOS export bridge", True, f"{export_status} | shortcut {export_shortcut}"))

    sandbox = load_json_file(TOS_SANDBOX_FILE) or {}
    sandbox_today = in_current_service_cycle(str(sandbox.get("generatedAt", "")), now=now)
    sandbox_ok = sandbox_today and sandbox.get("sandboxReady") is not None
    sandbox_detail = (
        f"ready={sandbox.get('sandboxReady')} | stageable={sandbox.get('stageableCount', 0)}"
        if sandbox_ok
        else json.dumps(
            {
                "generatedAt": sandbox.get("generatedAt"),
                "sandboxReady": sandbox.get("sandboxReady"),
                "stageableCount": sandbox.get("stageableCount"),
            }
        )
    )
    lines.append(summarize_status("paperMoney sandbox", sandbox_ok, sandbox_detail))
    if not sandbox_ok:
        warnings += 1

    paper_reducer = load_json_file(PAPER_BOTTLENECK_REDUCER_FILE) or {}
    paper_reducer_today = in_current_service_cycle(str(paper_reducer.get("generatedAt", "")), now=now)
    paper_reducer_counts = paper_reducer.get("counts") or {}

    paper_test_director = load_json_file(PAPER_TEST_DIRECTOR_FILE) or {}
    paper_director_ok, paper_director_detail = paper_test_director_status(paper_test_director, paper_reducer, now)
    lines.append(summarize_status("Paper test director", paper_director_ok, paper_director_detail))
    if paper_test_director and not paper_director_ok:
        warnings += 1

    paper_reducer_ok = paper_reducer_today and paper_reducer.get("verdict") in {
        "scenario-slate-ready",
        "scenario-slate-thin",
    }
    paper_reducer_detail = (
        f"{paper_reducer.get('verdict')} | scenarios={paper_reducer_counts.get('scenarios', 0)} | "
        f"paper={paper_reducer_counts.get('executablePaper', 0)} | "
        f"shadow={paper_reducer_counts.get('shadowOnly', 0)}"
        if paper_reducer_today
        else json.dumps(
            {
                "generatedAt": paper_reducer.get("generatedAt"),
                "verdict": paper_reducer.get("verdict"),
            }
        )
    )
    lines.append(summarize_status("Paper bottleneck reducer", paper_reducer_ok, paper_reducer_detail))
    if paper_reducer and not paper_reducer_ok:
        warnings += 1

    paper_evidence_loop = load_json_file(PAPER_EVIDENCE_LOOP_FILE) or {}
    paper_loop_today = in_current_service_cycle(str(paper_evidence_loop.get("generatedAt", "")), now=now)
    paper_loop_verdict = str(paper_evidence_loop.get("verdict") or "")
    paper_loop_ok = paper_loop_today and paper_loop_verdict in {
        "ready-to-stage",
        "approval-bottleneck",
        "collect-paper-outcomes",
        "evidence-building",
    }
    paper_loop_counts = paper_evidence_loop.get("counts") or {}
    paper_loop_detail = (
        f"{paper_loop_verdict} | planned-fill={paper_loop_counts.get('plannedFillRows', 0)} | "
        f"open-fill={paper_loop_counts.get('openFillRows', 0)} | "
        f"remaining={paper_loop_counts.get('remainingForPromotion', 0)}"
        if paper_loop_today
        else json.dumps(
            {
                "generatedAt": paper_evidence_loop.get("generatedAt"),
                "verdict": paper_loop_verdict,
            }
        )
    )
    lines.append(summarize_status("Paper evidence loop", paper_loop_ok, paper_loop_detail))
    if paper_evidence_loop and not paper_loop_ok:
        warnings += 1

    paper_exit_audit = load_json_file(PAPER_EXIT_AUDIT_FILE) or {}
    paper_exit_today = in_current_service_cycle(str(paper_exit_audit.get("generatedAt", "")), now=now)
    paper_exit_verdict = str(paper_exit_audit.get("verdict") or "")
    paper_exit_ok = paper_exit_today and paper_exit_verdict in {
        "clean",
        "review-open-exits",
        "close-today",
        "reconcile-open-rows",
    }
    paper_exit_counts = paper_exit_audit.get("counts") or {}
    paper_exit_detail = (
        f"{paper_exit_verdict} | open={paper_exit_counts.get('openLedgerTickets', 0)} | "
        f"close-now={paper_exit_counts.get('closeNow', 0)} | "
        f"review={paper_exit_counts.get('reviewToday', 0)} | "
        f"reconcile={paper_exit_counts.get('orphanOpenFillRows', 0)}"
        if paper_exit_today
        else json.dumps(
            {
                "generatedAt": paper_exit_audit.get("generatedAt"),
                "verdict": paper_exit_verdict,
            }
        )
    )
    lines.append(summarize_status("Paper exit audit", paper_exit_ok, paper_exit_detail))
    if paper_exit_audit and not paper_exit_ok:
        warnings += 1

    live_account_sync = load_json_file(LIVE_ACCOUNT_SYNC_FILE) or {}
    live_sync_generated = str(live_account_sync.get("generatedAt", ""))
    live_sync_ok = (
        recent_or_today(live_sync_generated)
        and bool(live_account_sync.get("ok"))
        and str(live_account_sync.get("verdict")) in {"healthy", "attention"}
    )
    live_sync_counts = live_account_sync.get("counts") or {}
    live_sync_detail = (
        f"{live_account_sync.get('verdict')} | positions={live_sync_counts.get('positions', 0)} | "
        f"matched={live_sync_counts.get('matchedPositions', 0)} | "
        f"suffix={live_account_sync.get('matchedSuffix') or '-'} | "
        f"source={live_account_sync.get('accountDataSource') or '-'}"
        if live_account_sync
        else "missing"
    )
    lines.append(summarize_status("Live account sync", live_sync_ok, live_sync_detail))
    if not live_sync_ok:
        warnings += 1

    live_position_review = load_json_file(LIVE_POSITION_REVIEW_FILE) or {}
    live_review_ok, live_review_detail = live_position_review_status(live_position_review)
    lines.append(summarize_status("Live position review", live_review_ok, live_review_detail))
    if not live_review_ok:
        warnings += 1

    model_command_center = load_json_file(MODEL_COMMAND_CENTER_FILE) or {}
    command_center_ok, command_center_detail = model_command_center_status(model_command_center)
    lines.append(summarize_status("Model command center", command_center_ok, command_center_detail))
    if not command_center_ok:
        warnings += 1

    action_pulse = load_json_file(ACTION_PULSE_FILE) or {}
    action_pulse_ok, action_pulse_detail = action_pulse_status(action_pulse)
    lines.append(summarize_status("Action pulse", action_pulse_ok, action_pulse_detail))
    if not action_pulse_ok:
        warnings += 1

    secret_hygiene = load_json_file(SECRET_HYGIENE_FILE) or {}
    secret_hygiene_ok, secret_hygiene_detail = secret_hygiene_status(secret_hygiene)
    lines.append(summarize_status("Secret hygiene", secret_hygiene_ok, secret_hygiene_detail))
    if not secret_hygiene_ok:
        warnings += 1

    research_cycle = load_json_file(RESEARCH_CYCLE_FILE) or {}
    research_cycle_ok, research_cycle_detail = research_cycle_status(research_cycle)
    lines.append(summarize_status("Research cycle", research_cycle_ok, research_cycle_detail))
    if not research_cycle_ok:
        warnings += 1

    fill_ingest = load_json_file(TOS_FILL_INGEST_FILE) or {}
    fill_ingest_today = in_current_service_cycle(str(fill_ingest.get("generatedAt", "")), now=now)
    fill_ingest_ok = fill_ingest_today and fill_ingest.get("processedRows") is not None
    fill_ingest_detail = (
        f"{fill_ingest.get('importedRows', 0)} imported | {fill_ingest.get('closedRows', 0)} closed"
        if fill_ingest_ok
        else json.dumps(
            {
                "generatedAt": fill_ingest.get("generatedAt"),
                "processedRows": fill_ingest.get("processedRows"),
            }
        )
    )
    lines.append(summarize_status("paper fill ingest", fill_ingest_ok, fill_ingest_detail))
    if not fill_ingest_ok:
        warnings += 1

    cloud_control_plane = load_json_file(CLOUD_CONTROL_PLANE_FILE) or {}
    cloud_recent = recent_or_today(str(cloud_control_plane.get("generatedAt", "")), max_age_hours=72)
    cloud_verdict = str(cloud_control_plane.get("verdict") or "")
    cloud_ok = cloud_recent and cloud_verdict in {"deployable", "ready"}
    cloud_detail = (
        f"{cloud_verdict} | {cloud_control_plane.get('message')}"
        if cloud_recent
        else json.dumps(
            {
                "generatedAt": cloud_control_plane.get("generatedAt"),
                "verdict": cloud_verdict,
            }
        )
    )
    lines.append(summarize_status("Cloud control plane", cloud_ok, cloud_detail))
    if not cloud_ok:
        warnings += 1

    cloud_state = load_json_file(CLOUD_STATE_FILE) or {}
    cloud_state_ok = not cloud_state or bool(cloud_state.get("ok", True))
    cloud_state_detail = (
        "not configured locally"
        if not cloud_state or not cloud_state.get("enabled")
        else (
            f"{cloud_state.get('mode')} | restored {len(cloud_state.get('restored', []))} | "
            f"persisted {len(cloud_state.get('persisted', []))} | bucket {cloud_state.get('bucket') or 'none'}"
        )
    )
    lines.append(summarize_status("Cloud state vault", cloud_state_ok, cloud_state_detail))
    if not cloud_state_ok:
        warnings += 1

    cloud_execution_ok = cloud_execution_today and cloud_execution_verdict == "healthy"
    cloud_execution_detail = (
        f"{cloud_execution_verdict} | {cloud_execution.get('projectId')} | {cloud_execution.get('region')}"
        if cloud_execution_today
        else json.dumps(
            {
                "generatedAt": cloud_execution.get("generatedAt"),
                "verdict": cloud_execution_verdict,
            }
        )
    )
    lines.append(summarize_status("Cloud execution audit", cloud_execution_ok, cloud_execution_detail))
    if not cloud_execution_ok:
        warnings += 1

    lines.append("")
    if warnings == 0:
        lines.append("Desk status: healthy")
    else:
        lines.append(f"Desk status: {warnings} item(s) need attention")

    output = "\n".join(lines)
    payload = {
        "generatedAt": now.isoformat(),
        "stage": "inferno-doctor",
        "researchOnly": True,
        "promotable": False,
        "healthy": warnings == 0,
        "warningCount": warnings,
        "lines": lines,
    }
    ensure_dirs()
    atomic_write_json(DOCTOR_ARTIFACT_FILE, payload)
    atomic_write_text(DOCTOR_TEXT_FILE, output + "\n")
    print(output)
    return 0 if warnings == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
