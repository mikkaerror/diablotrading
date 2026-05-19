from __future__ import annotations

"""Operator daily-loop runner.

This is the master read-only routine the operator runs each morning and each
afternoon. It does *not* refresh upstream system artifacts (that is
``inferno_ops_maintenance``'s job); it synthesizes the operator-facing
diagnostics that consume those artifacts and emits one combined digest.

Diagnostics chained, in order:
1. approval cadence and decision briefs
2. promotion, threshold, replay, and success checks
3. breathing checks for TOS, skills, and heartbeat
4. research/math layers, including normalized slate ranks
5. paper bootstrap, math verify, command center, and cycle journal

The loop also emits a short natural-language narrative paragraph that
summarises the run as if it were a colleague handing over a verbal brief.

Each step is independently failure-isolated: one failing diagnostic produces a
``failed`` status entry in the digest but does not abort the loop. The combined
digest is written to ``data/inferno_daily_loop.json`` and
``reports/daily_loop_latest.txt``.

Strict contract:
- read-only. Cannot approve, reject, mutate the queue, change authority, or
  alter performance/strategy state.
- writes only to its own clearly-labeled artifact paths.
- safe to run on a launchd schedule.
"""

import argparse
import json
from typing import Any, Callable

from inferno_approval_cadence import build_cadence, save_cadence
from inferno_brain_cycle_journal import save_journal_memo, snapshot_cycle
from inferno_config import local_now
from inferno_counterfactual import build_counterfactual, save_counterfactual
from inferno_devils_advocate import (
    build_falsification,
    save_falsification,
)
from inferno_evidence_strength import (
    build_strength as build_evidence_strength,
    save_strength as save_evidence_strength,
)
from inferno_kelly_sizing import build_kelly_sizing, save_kelly_sizing
from inferno_vol_premium import build_vol_premium, save_vol_premium
from inferno_bayesian_winrate import (
    build_bayesian_winrate,
    save_bayesian_winrate,
)
from inferno_regime_drift import build_regime_drift, save_regime_drift
from inferno_information_gain import (
    build_information_gain,
    save_information_gain,
)
from inferno_walk_forward import build_walk_forward, save_walk_forward
from inferno_factor_regression import (
    build_factor_regression,
    save_factor_regression,
)
from inferno_math_verify import build_math_verify, save_math_verify
from inferno_paper_bootstrap import build_bootstrap, save_bootstrap
from inferno_paper_bottleneck_reducer import build_reducer, save_reducer
from inferno_slate_normalizer import build_normalized, save_normalized
from inferno_daily_success import build_daily_success, save_daily_success
from inferno_decision_brief import build_decision_briefs, save_decision_briefs
from inferno_trade_conviction_audit import (
    build_conviction_audit,
    save_conviction_audit,
)
from inferno_conviction_research import (
    build_conviction_research,
    save_conviction_research,
)
from inferno_heartbeat import (
    build_heartbeat_report,
    record_heartbeat,
    save_heartbeat_report,
)
from inferno_hypothesis_lab import build_hypothesis_lab, save_hypothesis_lab
from inferno_hypothesis_ledger import (
    build_ledger_report,
    save_ledger_report,
    update_ledger,
)
from inferno_io import append_text, atomic_write_json, atomic_write_text
from inferno_model_command_center import build_command_center, onboard_digest
from inferno_promotion_gap import build_promotion_gap, save_promotion_gap
from inferno_skills_audit import build_skills_audit, save_skills_audit
from inferno_strategy_replay import build_replay, save_replay
from inferno_theme_synthesizer import build_theme_report, save_theme_report
from inferno_threshold_sensitivity import build_sensitivity, save_sensitivity
from inferno_tos_export_stability import (
    build_stability_report,
    save_stability_report,
)
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


DAILY_LOOP_FILE = DATA_DIR / "inferno_daily_loop.json"
DAILY_LOOP_TEXT_FILE = REPORTS_DIR / "daily_loop_latest.txt"
DAILY_LOOP_STAGE = "daily-loop-operator-routine"

# Append-only stream-of-consciousness narration log. Each cycle writes one
# JSON row so an operator can ``tail -f`` the file to watch the brain over
# time. Self-bounded to MAX_NARRATION_ROWS via a simple rewrite-on-overflow
# strategy (cheap because rows are small and weekday firings stay under
# 365 in a 9-month window).
NARRATION_LOG_FILE = DATA_DIR / "inferno_brain_narrations.jsonl"
MAX_NARRATION_ROWS = 365


def _append_narration_row(payload: dict[str, Any]) -> None:
    """Append one narration row to the stream-of-consciousness log.

    Each row is a single-line JSON object so the file stays valid JSONL.
    When the file exceeds MAX_NARRATION_ROWS we rewrite it with the tail
    only, which is cheap because rows are small (~1 KB each).
    """
    ensure_dirs()
    timestamp = local_now().isoformat()
    cadence = payload.get("decideTodayTickers") or []
    top_hypothesis = None
    for step in payload.get("steps") or []:
        if step.get("name") != "hypothesisLab":
            continue
        summary = step.get("summary") or {}
        top_list = summary.get("topHypotheses") or []
        if top_list:
            top_hypothesis = top_list[0]
        break
    row = {
        "at": timestamp,
        "verdict": payload.get("deskVerdict"),
        "decide": cadence,
        "topHypothesisId": (top_hypothesis or {}).get("id"),
        "topHypothesisTemplate": (top_hypothesis or {}).get("template"),
        "topHypothesisConfidence": (top_hypothesis or {}).get("testConfidence"),
        "narrative": payload.get("narrative"),
    }
    append_text(NARRATION_LOG_FILE, json.dumps(row) + "\n")
    _trim_narration_log()


def _trim_narration_log() -> None:
    """Keep only the most recent MAX_NARRATION_ROWS narrations."""
    if not NARRATION_LOG_FILE.exists():
        return
    try:
        lines = NARRATION_LOG_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= MAX_NARRATION_ROWS:
        return
    trimmed = lines[-MAX_NARRATION_ROWS:]
    atomic_write_text(NARRATION_LOG_FILE, "\n".join(trimmed) + "\n")


def _run_step(
    name: str,
    builder: Callable[[], dict[str, Any]],
    *,
    saver: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run one diagnostic step in failure-isolated mode."""
    try:
        result = builder()
        if saver is not None:
            saver(result)
    except Exception as exc:  # noqa: BLE001
        return {
            "name": name,
            "ok": False,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "name": name,
        "ok": True,
        "status": "built",
        "summary": _extract_summary(name, result),
    }


def _extract_summary(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Pull a small, presentation-stable subset out of each diagnostic payload."""
    if name == "approvalCadence":
        return {
            "pending": (payload.get("counts") or {}).get("pending", 0),
            "decideTodayQueue": (payload.get("counts") or {}).get("decideTodayQueue", 0),
            "decideTodayTickers": payload.get("decideTodayTickers") or [],
            "oldestPendingSince": payload.get("oldestPendingSince"),
        }
    if name == "decisionBriefs":
        return {
            "pendingCount": payload.get("pendingCount", 0),
            "briefedTickers": [
                brief.get("ticker") for brief in (payload.get("briefs") or [])
            ],
        }
    if name == "promotionGap":
        overall = payload.get("overall") or {}
        return {
            "overallPromotable": overall.get("promotable"),
            "gatesOpen": overall.get("gatesOpen"),
            "gatesTotal": overall.get("gatesTotal"),
            "tradesToWinRateFloor": overall.get("tradesToWinRateFloor"),
        }
    if name == "thresholdSensitivity":
        return {
            "tightestPromotingProfile": payload.get("tightestPromotingProfile"),
            "promotedAnyUnder": payload.get("promotedAnyUnder") or [],
        }
    if name == "strategyReplay":
        desk = payload.get("deskVerdictReplay") or {}
        return {
            "replayVerdict": desk.get("level"),
            "closedShadowCount": payload.get("closedShadowCount"),
            "promotionCandidatesReplay": payload.get("promotionCandidatesReplay") or [],
        }
    if name == "dailySuccess":
        return {
            "verdict": payload.get("verdict"),
            "passCount": payload.get("passCount"),
            "totalCount": payload.get("totalCount"),
        }
    if name == "commandCenter":
        return {
            "missionCount": len(payload.get("activeMissions") or []),
            "noteCount": len(payload.get("recentNotes") or []),
            "headline": (payload.get("headlineMetrics") or {}),
        }
    if name == "tosExportStability":
        return {
            "verdict": payload.get("verdict"),
            "okCount": payload.get("okCount"),
            "attempts": payload.get("attempts"),
            "dominantFailMode": payload.get("dominantFailMode"),
        }
    if name == "skillsAudit":
        counts = payload.get("counts") or {}
        return {
            "verdict": payload.get("verdict"),
            "totalSkills": payload.get("totalSkills"),
            "freshCount": counts.get("fresh"),
            "staleCount": counts.get("stale"),
            "silentCount": counts.get("silent"),
            "unknownCount": counts.get("unknown"),
        }
    if name == "heartbeat":
        return {
            "verdict": payload.get("verdict"),
            "totalSources": payload.get("totalSources"),
            "freshCount": payload.get("freshCount"),
            "staleCount": payload.get("staleCount"),
            "silentCount": payload.get("silentCount"),
            "missingExpected": payload.get("missingExpected") or [],
        }
    if name == "themeSynthesizer":
        return {
            "totalCells": payload.get("totalCells"),
            "sufficientCells": payload.get("sufficientCells"),
            "edgeCount": len(payload.get("edges") or []),
            "antiEdgeCount": len(payload.get("antiEdges") or []),
        }
    if name == "hypothesisLab":
        return {
            "shadowRecordCount": payload.get("shadowRecordCount"),
            "pendingRecordCount": payload.get("pendingRecordCount"),
            "totalHypotheses": payload.get("totalHypotheses"),
            "templateCounts": payload.get("templateCounts") or {},
            "topHypotheses": [
                {
                    "id": h.get("id"),
                    "template": h.get("template"),
                    "testConfidence": h.get("testConfidence"),
                }
                for h in (payload.get("topHypotheses") or [])[:3]
            ],
        }
    if name == "hypothesisLedger":
        return {
            "totalHypotheses": payload.get("totalHypotheses"),
            "trajectoryCounts": payload.get("trajectoryCounts") or {},
        }
    if name == "cycleJournal":
        return {
            "cycleId": payload.get("cycleId"),
            "copiedCount": len(payload.get("copied") or []),
            "missingCount": len(payload.get("missing") or []),
            "totalCyclesOnDisk": payload.get("totalCyclesOnDisk"),
            "prunedCount": len(payload.get("pruned") or []),
        }
    if name == "counterfactual":
        rankings = payload.get("rankings") or {}
        return {
            "verdict": payload.get("verdict"),
            "closedRecordCount": payload.get("closedRecordCount"),
            "bestByMeanR": rankings.get("bestByMeanR"),
            "bestByWilsonLower": rankings.get("bestByWilsonLower"),
            "bestByProfitFactor": rankings.get("bestByProfitFactor"),
        }
    if name == "paperBottleneckReducer":
        counts = payload.get("counts") or {}
        return {
            "verdict": payload.get("verdict"),
            "scenarioTarget": payload.get("scenarioTarget"),
            "scenarios": counts.get("scenarios"),
            "executablePaper": counts.get("executablePaper"),
            "shadowOnly": counts.get("shadowOnly"),
            "topFive": [
                item.get("ticker")
                for item in (payload.get("topFiveFocus") or [])
            ],
        }
    if name == "convictionResearch":
        return {
            "stage": payload.get("stage"),
            "behemoths": [
                item.get("ticker")
                for item in (payload.get("behemoths") or [])[:5]
            ],
            "sleepers": [
                item.get("ticker")
                for item in (payload.get("sleepers") or [])[:5]
            ],
            "nearTermWinners": [
                item.get("ticker")
                for item in (payload.get("nearTermWinners") or [])[:5]
            ],
        }
    return {"generatedAt": payload.get("generatedAt")}


def build_daily_loop() -> dict[str, Any]:
    """Run all chained diagnostics and assemble the combined digest.

    Order matters slightly: the command center is rebuilt last so the
    onboarding digest includes whatever the other diagnostics surfaced.
    """
    cadence_payload: dict[str, Any] = {}
    briefs_payload: dict[str, Any] = {}
    gap_payload: dict[str, Any] = {}
    sensitivity_payload: dict[str, Any] = {}
    replay_payload: dict[str, Any] = {}
    success_payload: dict[str, Any] = {}
    command_payload: dict[str, Any] = {}
    stability_payload: dict[str, Any] = {}
    skills_payload: dict[str, Any] = {}
    heartbeat_payload: dict[str, Any] = {}
    theme_payload: dict[str, Any] = {}
    hypothesis_payload: dict[str, Any] = {}
    ledger_payload: dict[str, Any] = {}
    cycle_payload: dict[str, Any] = {}
    counterfactual_payload: dict[str, Any] = {}
    narrative_text: str | None = None

    steps: list[dict[str, Any]] = []

    def cadence_builder() -> dict[str, Any]:
        nonlocal cadence_payload
        cadence_payload = build_cadence()
        save_cadence(cadence_payload)
        return cadence_payload

    def briefs_builder() -> dict[str, Any]:
        nonlocal briefs_payload
        briefs_payload = build_decision_briefs()
        save_decision_briefs(briefs_payload)
        return briefs_payload

    def conviction_audit_builder() -> dict[str, Any]:
        # Runs after evidence-strength and devil's-advocate so the audit can
        # cite the freshest sample counts. Diagnostic only.
        payload = build_conviction_audit()
        save_conviction_audit(payload)
        return payload

    def gap_builder() -> dict[str, Any]:
        nonlocal gap_payload
        gap_payload = build_promotion_gap()
        save_promotion_gap(gap_payload)
        return gap_payload

    def sensitivity_builder() -> dict[str, Any]:
        nonlocal sensitivity_payload
        sensitivity_payload = build_sensitivity()
        save_sensitivity(sensitivity_payload)
        return sensitivity_payload

    def replay_builder() -> dict[str, Any]:
        nonlocal replay_payload
        replay_payload = build_replay()
        save_replay(replay_payload)
        return replay_payload

    def success_builder() -> dict[str, Any]:
        nonlocal success_payload
        success_payload = build_daily_success()
        save_daily_success(success_payload)
        return success_payload

    def stability_builder() -> dict[str, Any]:
        nonlocal stability_payload
        # Keep attempts/backoff small in the loop so we don't add minutes to
        # the scheduled run. The verifier already handles its own timing.
        stability_payload = build_stability_report(attempts=2, backoff_seconds=1.0)
        save_stability_report(stability_payload)
        return stability_payload

    def skills_builder() -> dict[str, Any]:
        nonlocal skills_payload
        skills_payload = build_skills_audit()
        save_skills_audit(skills_payload)
        return skills_payload

    def heartbeat_builder() -> dict[str, Any]:
        nonlocal heartbeat_payload
        # The daily loop itself counts as a heartbeat source; record it
        # before reading the ledger so the summary reflects this run.
        record_heartbeat(
            "daily_loop",
            status="ok",
            summary="daily loop chained diagnostics",
        )
        heartbeat_payload = build_heartbeat_report()
        save_heartbeat_report(heartbeat_payload)
        return heartbeat_payload

    def theme_builder() -> dict[str, Any]:
        nonlocal theme_payload
        theme_payload = build_theme_report()
        save_theme_report(theme_payload)
        return theme_payload

    def hypothesis_builder() -> dict[str, Any]:
        nonlocal hypothesis_payload
        hypothesis_payload = build_hypothesis_lab()
        save_hypothesis_lab(hypothesis_payload)
        return hypothesis_payload

    def ledger_builder() -> dict[str, Any]:
        nonlocal ledger_payload
        # Feed the freshly-generated hypotheses into the ledger so the
        # trajectory tracker has something to update against.
        new_hypotheses = (hypothesis_payload or {}).get("allHypotheses") or []
        update_ledger(new_hypotheses)
        ledger_payload = build_ledger_report()
        save_ledger_report(ledger_payload)
        return ledger_payload

    def counterfactual_builder() -> dict[str, Any]:
        nonlocal counterfactual_payload
        counterfactual_payload = build_counterfactual()
        save_counterfactual(counterfactual_payload)
        return counterfactual_payload

    devils_advocate_payload: dict[str, Any] | None = None
    evidence_strength_payload: dict[str, Any] | None = None

    def devils_advocate_builder() -> dict[str, Any]:
        nonlocal devils_advocate_payload
        devils_advocate_payload = build_falsification()
        save_falsification(devils_advocate_payload)
        return devils_advocate_payload

    def evidence_strength_builder() -> dict[str, Any]:
        # Must run *after* devil's advocate so the falsification component
        # of the composite has fresh input.
        nonlocal evidence_strength_payload
        evidence_strength_payload = build_evidence_strength()
        save_evidence_strength(evidence_strength_payload)
        return evidence_strength_payload

    kelly_payload: dict[str, Any] | None = None
    vol_premium_payload: dict[str, Any] | None = None

    def kelly_builder() -> dict[str, Any]:
        nonlocal kelly_payload
        kelly_payload = build_kelly_sizing()
        save_kelly_sizing(kelly_payload)
        return kelly_payload

    def vol_premium_builder() -> dict[str, Any]:
        nonlocal vol_premium_payload
        vol_premium_payload = build_vol_premium()
        save_vol_premium(vol_premium_payload)
        return vol_premium_payload

    bayesian_payload: dict[str, Any] | None = None
    drift_payload: dict[str, Any] | None = None
    information_gain_payload: dict[str, Any] | None = None

    def bayesian_builder() -> dict[str, Any]:
        nonlocal bayesian_payload
        bayesian_payload = build_bayesian_winrate()
        save_bayesian_winrate(bayesian_payload)
        return bayesian_payload

    def drift_builder() -> dict[str, Any]:
        nonlocal drift_payload
        drift_payload = build_regime_drift()
        save_regime_drift(drift_payload)
        return drift_payload

    def information_gain_builder() -> dict[str, Any]:
        nonlocal information_gain_payload
        information_gain_payload = build_information_gain()
        save_information_gain(information_gain_payload)
        return information_gain_payload

    walk_forward_payload: dict[str, Any] | None = None
    factor_regression_payload: dict[str, Any] | None = None
    math_verify_payload: dict[str, Any] | None = None
    slate_normalizer_payload: dict[str, Any] | None = None

    def walk_forward_builder() -> dict[str, Any]:
        nonlocal walk_forward_payload
        walk_forward_payload = build_walk_forward()
        save_walk_forward(walk_forward_payload)
        return walk_forward_payload

    def factor_regression_builder() -> dict[str, Any]:
        nonlocal factor_regression_payload
        factor_regression_payload = build_factor_regression()
        save_factor_regression(factor_regression_payload)
        return factor_regression_payload

    def math_verify_builder() -> dict[str, Any]:
        # Math verify must run *last* in the thinking layer so it can
        # check every other module's freshly-written artifact.
        nonlocal math_verify_payload
        math_verify_payload = build_math_verify()
        save_math_verify(math_verify_payload)
        return math_verify_payload

    def slate_normalizer_builder() -> dict[str, Any]:
        # Scale-invariant ranks are research-only; they help the operator
        # inspect relative strength without changing live authority.
        nonlocal slate_normalizer_payload
        slate_normalizer_payload = build_normalized()
        save_normalized(slate_normalizer_payload)
        return slate_normalizer_payload

    paper_bootstrap_payload: dict[str, Any] | None = None
    paper_reducer_payload: dict[str, Any] | None = None

    def paper_bootstrap_builder() -> dict[str, Any]:
        # Seeds the paper ledger at relaxed gating so the promotion math
        # can earn its way to Phase 2. Never proposes a live trade.
        nonlocal paper_bootstrap_payload
        paper_bootstrap_payload = build_bootstrap()
        save_bootstrap(paper_bootstrap_payload)
        return paper_bootstrap_payload

    def paper_reducer_builder() -> dict[str, Any]:
        # Builds a larger research slate so the desk can collect evidence
        # without relaxing paperMoney or live authority gates.
        nonlocal paper_reducer_payload
        paper_reducer_payload = build_reducer()
        save_reducer(paper_reducer_payload)
        return paper_reducer_payload

    def conviction_research_builder() -> dict[str, Any]:
        # Research-only gut-check layer: giants, sleepers, winners, and
        # contradictions. No queue, broker, or authority mutation.
        report = build_conviction_research()
        save_conviction_research(report)
        return report

    def command_builder() -> dict[str, Any]:
        nonlocal command_payload
        command_payload = build_command_center()
        return command_payload

    def cycle_journal_builder() -> dict[str, Any]:
        # The cycle journal must run *after* all other steps so it picks up
        # the freshest artifacts. We also pass the narrative so the cycle
        # directory contains a human-readable handoff memo.
        nonlocal cycle_payload
        cycle_payload = snapshot_cycle(narrative=narrative_text)
        save_journal_memo(cycle_payload)
        return cycle_payload

    steps.append(_run_step("approvalCadence", cadence_builder))
    steps.append(_run_step("decisionBriefs", briefs_builder))
    steps.append(_run_step("promotionGap", gap_builder))
    steps.append(_run_step("thresholdSensitivity", sensitivity_builder))
    steps.append(_run_step("strategyReplay", replay_builder))
    steps.append(_run_step("dailySuccess", success_builder))
    steps.append(_run_step("tosExportStability", stability_builder))
    steps.append(_run_step("skillsAudit", skills_builder))
    steps.append(_run_step("heartbeat", heartbeat_builder))
    steps.append(_run_step("themeSynthesizer", theme_builder))
    steps.append(_run_step("hypothesisLab", hypothesis_builder))
    steps.append(_run_step("hypothesisLedger", ledger_builder))
    steps.append(_run_step("counterfactual", counterfactual_builder))
    steps.append(_run_step("devilsAdvocate", devils_advocate_builder))
    steps.append(_run_step("bayesianWinrate", bayesian_builder))
    steps.append(_run_step("regimeDrift", drift_builder))
    steps.append(_run_step("informationGain", information_gain_builder))
    steps.append(_run_step("volPremium", vol_premium_builder))
    steps.append(_run_step("walkForward", walk_forward_builder))
    steps.append(_run_step("factorRegression", factor_regression_builder))
    steps.append(_run_step("kellySizing", kelly_builder))
    steps.append(_run_step("evidenceStrength", evidence_strength_builder))
    steps.append(_run_step("slateNormalizer", slate_normalizer_builder))
    steps.append(_run_step("paperBootstrap", paper_bootstrap_builder))
    steps.append(_run_step("paperBottleneckReducer", paper_reducer_builder))
    steps.append(_run_step("tradeConvictionAudit", conviction_audit_builder))
    steps.append(_run_step("convictionResearch", conviction_research_builder))
    steps.append(_run_step("mathVerify", math_verify_builder))
    steps.append(_run_step("commandCenter", command_builder))
    # cycleJournal must run last so it snapshots the freshest artifacts. The
    # narrative is filled in before this fires (see below) so the journal
    # entry includes the same prose the operator sees.
    cycle_step_index = len(steps)
    steps.append({"name": "cycleJournal", "ok": False, "status": "pending"})

    success_verdict = (success_payload.get("verdict") or "unknown") if success_payload else "unknown"
    decide_today = (
        (cadence_payload.get("decideTodayTickers") or []) if cadence_payload else []
    )

    narrative = compose_narrative(
        success_payload=success_payload,
        cadence_payload=cadence_payload,
        gap_payload=gap_payload,
        replay_payload=replay_payload,
        stability_payload=stability_payload,
        skills_payload=skills_payload,
        heartbeat_payload=heartbeat_payload,
        theme_payload=theme_payload,
        hypothesis_payload=hypothesis_payload,
        ledger_payload=ledger_payload,
        counterfactual_payload=counterfactual_payload,
    )
    # The cycle journal needs the narrative; we set it before firing the
    # final step. ``narrative_text`` is the nonlocal seen by
    # ``cycle_journal_builder``.
    nonlocal_namespace = locals()  # narrative is now ready
    narrative_text_assigned = narrative  # for readability below
    # Run the cycle journal as the final step now that narrative is ready.
    cycle_step = _run_step("cycleJournal", _make_cycle_step_builder(
        snapshot_cycle, save_journal_memo, narrative_text_assigned, cycle_payload
    ))
    steps[cycle_step_index] = cycle_step

    digest = {
        "generatedAt": local_now().isoformat(),
        "stage": DAILY_LOOP_STAGE,
        "diagnosticOnly": True,
        "deskVerdict": success_verdict,
        "decideTodayTickers": decide_today,
        "narrative": narrative,
        "steps": steps,
        "stepCount": len(steps),
        "okCount": sum(1 for step in steps if step["ok"]),
        "failedCount": sum(1 for step in steps if not step["ok"]),
        "researchNotes": [
            "diagnostic only; cannot change desk state",
            "operator should walk the decideTodayTickers list using the brief memos",
            "see reports/decision_briefs_latest.txt for per-ticker context",
            "see reports/trade_conviction_audit_latest.txt for the bull/bear/disagreement math case per ticket",
            "see reports/conviction_research_latest.txt for whole-universe giants, sleepers, winners, and contradictions",
        ],
    }
    # Append the stream-of-consciousness row. Done outside _run_step so a
    # narration-log failure doesn't poison the digest's failed-count.
    try:
        _append_narration_row(digest)
    except Exception:  # noqa: BLE001
        # The log is a convenience; never let it abort a daily run.
        pass
    return digest


def _make_cycle_step_builder(snapshot_fn, save_fn, narrative: str, _payload_slot: dict):
    """Build the cycle-journal closure used by the final daily-loop step.

    Extracted so the snapshot call is replaceable in tests and the closure
    has a single obvious place where the narrative is plumbed in.
    """
    def _builder() -> dict[str, Any]:
        payload = snapshot_fn(narrative=narrative)
        save_fn(payload)
        return payload
    return _builder


def compose_narrative(
    *,
    success_payload: dict[str, Any],
    cadence_payload: dict[str, Any],
    gap_payload: dict[str, Any],
    replay_payload: dict[str, Any],
    stability_payload: dict[str, Any],
    skills_payload: dict[str, Any],
    heartbeat_payload: dict[str, Any],
    theme_payload: dict[str, Any] | None = None,
    hypothesis_payload: dict[str, Any] | None = None,
    ledger_payload: dict[str, Any] | None = None,
    counterfactual_payload: dict[str, Any] | None = None,
) -> str:
    """Compose a short natural-language narrative for the daily-loop memo.

    The goal is a "colleague-handoff" feel: three short paragraphs that say
    where the desk stands, what to act on, and what to keep an eye on. The
    text is built deterministically from the payloads — no LLM call, no
    randomness — so the output is reproducible and testable.
    """
    desk_verdict = str((success_payload or {}).get("verdict") or "unknown").upper()
    pass_count = (success_payload or {}).get("passCount")
    total_count = (success_payload or {}).get("totalCount")

    decide_today = list((cadence_payload or {}).get("decideTodayTickers") or [])
    pending_count = ((cadence_payload or {}).get("counts") or {}).get("pending", 0)

    gap_overall = (gap_payload or {}).get("overall") or {}
    gates_open = gap_overall.get("gatesOpen")
    gates_total = gap_overall.get("gatesTotal")
    trades_to_wr_floor = gap_overall.get("tradesToWinRateFloor")

    replay_verdict = (
        ((replay_payload or {}).get("deskVerdictReplay") or {}).get("level") or "unknown"
    )
    closed_shadow = (replay_payload or {}).get("closedShadowCount")

    stability_verdict = (stability_payload or {}).get("verdict") or "unknown"
    stability_dominant = (stability_payload or {}).get("dominantFailMode") or "n/a"

    skills_verdict = (skills_payload or {}).get("verdict") or "unknown"
    skills_counts = (skills_payload or {}).get("counts") or {}
    silent_skills = skills_counts.get("silent", 0)
    stale_skills = skills_counts.get("stale", 0)

    heartbeat_verdict = (heartbeat_payload or {}).get("verdict") or "unknown"
    silent_sources = (heartbeat_payload or {}).get("silentCount", 0)
    missing_expected = list((heartbeat_payload or {}).get("missingExpected") or [])

    # Paragraph 1 — desk verdict + decide-today
    where_we_are: list[str] = []
    where_we_are.append(
        f"Desk verdict: {desk_verdict}"
        + (
            f" ({pass_count}/{total_count} scorecard criteria green)."
            if pass_count is not None and total_count is not None
            else "."
        )
    )
    if decide_today:
        where_we_are.append(
            "The decide-today queue has "
            f"{len(decide_today)} ticker(s): {', '.join(decide_today)}. "
            "Walk the decision briefs and approve/reject each."
        )
    elif pending_count:
        where_we_are.append(
            f"No tickers urgent enough to decide today, but {pending_count} ticket(s) "
            "are still pending — keep them moving."
        )
    else:
        where_we_are.append("The approval queue is empty.")

    # Paragraph 2 — promotion gap + replay
    where_we_are_going: list[str] = []
    if gates_open is not None and gates_total is not None:
        where_we_are_going.append(
            f"Promotion gates: {gates_open}/{gates_total} open. "
        )
    if trades_to_wr_floor is not None:
        where_we_are_going.append(
            f"At the current hit rate the strategy lab needs roughly "
            f"{trades_to_wr_floor} more closed paper trades to clear the win-rate floor."
        )
    else:
        where_we_are_going.append(
            "The strategy lab is still in insufficient-data territory; the "
            f"shadow ledger has {closed_shadow or 0} closed item(s) so far."
        )
    where_we_are_going.append(
        f"Strategy-replay verdict on the shadow set: {replay_verdict}."
    )

    # Paragraph 3 — living / breathing pieces
    living: list[str] = []
    if stability_verdict == "stable-ready":
        living.append("TOS export path is stable.")
    elif stability_verdict == "transient-recovered":
        living.append("TOS export path recovered after a transient probe blip.")
    elif stability_verdict == "inactive-safe":
        if stability_dominant == "tos-closed-low-power":
            living.append(
                "TOS is intentionally closed for low-performance mode; open it only "
                "for supervised export or manual order staging."
            )
        else:
            living.append("TOS export automation is intentionally disabled.")
    else:
        living.append(
            f"TOS export path is currently {stability_verdict} "
            f"(dominant symptom: {stability_dominant})."
        )

    if skills_verdict == "healthy":
        living.append("All audited skills produced fresh artifacts.")
    elif silent_skills:
        living.append(
            f"{silent_skills} skill(s) have gone silent and {stale_skills} are stale "
            "— consider running or retiring them."
        )
    elif stale_skills:
        living.append(f"{stale_skills} skill(s) are stale but not yet silent.")

    if heartbeat_verdict == "alive":
        living.append("All expected subsystems are beating.")
    else:
        if missing_expected:
            living.append(
                "Heartbeat: missing expected sources "
                f"{', '.join(missing_expected)}."
            )
        elif silent_sources:
            living.append(
                f"Heartbeat: {silent_sources} subsystem(s) have gone silent."
            )
        else:
            living.append(f"Heartbeat verdict: {heartbeat_verdict}.")

    # Paragraph 4 — what the brain is currently thinking about
    theme_edges = len((theme_payload or {}).get("edges") or [])
    theme_anti = len((theme_payload or {}).get("antiEdges") or [])
    total_hypotheses = (hypothesis_payload or {}).get("totalHypotheses", 0)
    top_hypothesis = next(
        iter((hypothesis_payload or {}).get("topHypotheses") or []), None
    )
    ledger_counts = (ledger_payload or {}).get("trajectoryCounts") or {}
    strengthening = ledger_counts.get("strengthening", 0)
    weakening = ledger_counts.get("weakening", 0)

    thinking: list[str] = []
    if theme_edges or theme_anti:
        thinking.append(
            f"Theme cube: {theme_edges} edge(s) and {theme_anti} anti-edge(s) "
            "stand out at the desk's win-rate floor."
        )
    if total_hypotheses:
        thinking.append(f"Lab generated {total_hypotheses} testable hypotheses this cycle.")
    if top_hypothesis:
        thinking.append(
            "Top idea: "
            f"{(top_hypothesis.get('claim') or '')[:160]}"
        )
    if strengthening or weakening:
        thinking.append(
            f"Ledger: {strengthening} hypothesis(es) strengthening, "
            f"{weakening} weakening since last cycle."
        )
    # Counterfactual: tell the operator which policy would have won on history.
    cf_verdict = (counterfactual_payload or {}).get("verdict")
    cf_rankings = (counterfactual_payload or {}).get("rankings") or {}
    if cf_verdict == "ranked":
        best_mean = cf_rankings.get("bestByMeanR")
        best_wilson = cf_rankings.get("bestByWilsonLower")
        if best_mean and best_wilson:
            if best_mean == best_wilson:
                thinking.append(
                    f"Counterfactual: policy '{best_mean}' would have won "
                    "on both mean R and Wilson lower over the closed shadow set."
                )
            else:
                thinking.append(
                    f"Counterfactual: best by mean R was '{best_mean}', "
                    f"best by Wilson lower was '{best_wilson}'; small N — "
                    "disagreement is informative, not decisive."
                )

    if not thinking:
        thinking.append("Thinking layer is warming up — no testable hypotheses yet.")

    return "\n\n".join([
        " ".join(where_we_are).strip(),
        " ".join(where_we_are_going).strip(),
        " ".join(living).strip(),
        " ".join(thinking).strip(),
    ])


def daily_loop_text(payload: dict[str, Any]) -> str:
    """Render the operator-facing daily-loop memo."""
    lines = [
        "Inferno Daily Loop (read-only operator routine)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Desk verdict: {(payload.get('deskVerdict') or '').upper()}",
        f"Steps ok / total: {payload.get('okCount')}/{payload.get('stepCount')}",
    ]
    narrative = payload.get("narrative")
    if narrative:
        lines.extend(["", "Narrative:", narrative])
    lines.extend([
        "",
        "Decide-today queue:",
    ])
    decide = payload.get("decideTodayTickers") or []
    if not decide:
        lines.append("- none")
    for ticker in decide:
        lines.append(f"- {ticker}")
    lines.extend(["", "Step results:"])
    for step in payload.get("steps") or []:
        mark = "OK" if step["ok"] else "FAIL"
        lines.append(f"- [{mark}] {step['name']}")
        summary = step.get("summary") or {}
        for key, value in summary.items():
            lines.append(f"    {key}: {value}")
        if not step["ok"]:
            lines.append(f"    error: {step.get('error')}")
    lines.extend([
        "",
        "Where to look next:",
        "- reports/approval_cadence_latest.txt    — batting order",
        "- reports/decision_briefs_latest.txt     — per-ticker context",
        "- reports/trade_conviction_audit_latest.txt — per-ticket bull/bear/disagreement math case",
        "- reports/promotion_gap_latest.txt       — distance to lab gates",
        "- reports/threshold_sensitivity_latest.txt — gate calibration",
        "- reports/strategy_replay_latest.txt     — shadow-as-paper backtest",
        "- reports/daily_success_latest.txt       — green/yellow/red scorecard",
        "- reports/tos_export_stability_latest.txt — TOS export stability narrative",
        "- reports/skills_audit_latest.txt        — stale-skill auditor",
        "- reports/heartbeat_latest.txt           — subsystem liveness ledger",
        "- reports/theme_synthesizer_latest.txt   — evidence cube (edges + anti-edges)",
        "- reports/hypothesis_lab_latest.txt      — generated + backtested hypotheses",
        "- reports/hypothesis_ledger_latest.txt   — hypothesis trajectory memory",
        "- reports/counterfactual_latest.txt      — historical policy replay (ranked)",
        "- reports/conviction_research_latest.txt — giants, sleepers, winners, contradictions",
        "- reports/cycle_journal_latest.txt       — last cycle snapshot summary",
        "- reports/brain_console_latest.txt       — single-screen brain console (--save)",
        "- reports/model_command_center_latest.txt — onboarding digest",
        "",
        "Watch the brain operate:",
        "- python3 inferno_brain_console.py          — one-screen current state",
        "- python3 inferno_brain_console.py --watch  — re-render every 30 s",
        "- tail -f data/inferno_brain_narrations.jsonl — stream the brain's narratives",
        "- ls data/cycles/                            — list past cycle snapshots",
        "",
        "Reminders:",
        "- read-only; nothing here changes desk state",
        "- approve/reject decisions still flow through inferno_approval_queue.py",
    ])
    return "\n".join(lines).rstrip() + "\n"


def save_daily_loop(payload: dict[str, Any]) -> None:
    """Persist the daily-loop JSON and text artifacts.

    Uses ``inferno_io.atomic_write_*`` so transient errno-35 deadlocks under
    overlapping local writers absorb cleanly instead of losing the digest.
    """
    ensure_dirs()
    atomic_write_json(DAILY_LOOP_FILE, payload)
    atomic_write_text(DAILY_LOOP_TEXT_FILE, daily_loop_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Operator daily-loop runner. Chains the read-only diagnostics into "
            "one combined digest. Read-only; cannot change desk state."
        )
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "status", "onboard"],
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and DAILY_LOOP_TEXT_FILE.exists():
        print(DAILY_LOOP_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    if args.command == "onboard":
        # Convenience: build the command center first, then print onboard digest.
        payload = build_command_center()
        print(onboard_digest(payload))
        return 0
    payload = build_daily_loop()
    save_daily_loop(payload)
    print(daily_loop_text(payload))
    return 0 if payload.get("failedCount", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
