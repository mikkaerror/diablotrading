from __future__ import annotations

"""One-command research refresh for the Inferno evidence stack."""

import argparse
import json
from typing import Any

from inferno_config import local_now
from inferno_hypothesis_lab import build_hypothesis_lab, save_hypothesis_lab
from inferno_hypothesis_ledger import build_ledger_report, save_ledger_report, update_ledger
from inferno_io import atomic_write_json, atomic_write_text
from inferno_performance_analytics import build_performance_analytics, save_performance_analytics
from inferno_expected_move_ledger import build_expected_move_ledger, save_expected_move_ledger
from inferno_scenario_backtest import build_scenario_backtest, save_scenario_backtest
from inferno_scenario_evidence import build_scenario_evidence, save_scenario_evidence
from inferno_score_calibration import build_score_calibration, save_score_calibration
from inferno_shadow_evidence import build_shadow_evidence, save_shadow_evidence
from inferno_strategy_alternative_scorer import (
    build_strategy_alternative_scorer,
    save_strategy_alternative_scorer,
)
from inferno_strategy_lab import build_strategy_lab, save_strategy_lab
from inferno_strategy_replay import build_replay, save_replay
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


RESEARCH_CYCLE_FILE = DATA_DIR / "inferno_research_cycle.json"
RESEARCH_CYCLE_TEXT_FILE = REPORTS_DIR / "research_cycle_latest.txt"


def build_research_cycle() -> dict[str, Any]:
    ensure_dirs()
    shadow = build_shadow_evidence()
    save_shadow_evidence(shadow)

    performance = build_performance_analytics()
    save_performance_analytics(performance)

    strategy_lab = build_strategy_lab()
    save_strategy_lab(strategy_lab)

    replay = build_replay(shadow)
    save_replay(replay)

    hypothesis_lab = build_hypothesis_lab()
    save_hypothesis_lab(hypothesis_lab)

    ledger = update_ledger(hypothesis_lab.get("allHypotheses") or [])
    ledger_report = build_ledger_report(payload=ledger)
    save_ledger_report(ledger_report)

    scenario_evidence = build_scenario_evidence()
    save_scenario_evidence(scenario_evidence)

    scenario_backtest = build_scenario_backtest(scenario_evidence=scenario_evidence)
    save_scenario_backtest(scenario_backtest)

    score_calibration = build_score_calibration(scenario_evidence=scenario_evidence, shadow_ledger=shadow)
    save_score_calibration(score_calibration)

    expected_move = build_expected_move_ledger(shadow_ledger=shadow)
    save_expected_move_ledger(expected_move)

    strategy_alternatives = build_strategy_alternative_scorer(expected_move=expected_move)
    save_strategy_alternative_scorer(strategy_alternatives)

    overall = strategy_lab.get("overall") or {}
    performance_desk = performance.get("deskVerdict") or {}
    shadow_overall = shadow.get("overall") or {}
    replay_overall = ((replay.get("lab") or {}).get("overall") or {})
    scenario_counts = scenario_backtest.get("counts") or {}
    return {
        "generatedAt": local_now().isoformat(),
        "ok": True,
        "verdict": "research-refreshed",
        "shadow": {
            "trackedCount": shadow_overall.get("trackedCount", shadow.get("count")),
            "closedCount": shadow_overall.get("closedCount"),
            "avgReturnOnRisk": shadow_overall.get("avgReturnOnRisk"),
        },
        "performance": {
            "verdict": performance_desk.get("level"),
            "message": performance_desk.get("message"),
            "scoredCount": int(((performance.get("closedMetrics") or {}).get("scoredCount")) or 0),
        },
        "strategyLab": {
            "verdict": (strategy_lab.get("deskVerdict") or {}).get("level"),
            "message": (strategy_lab.get("deskVerdict") or {}).get("message"),
            "scoredCount": overall.get("scoredCount"),
            "promotionCandidates": strategy_lab.get("promotionCandidates") or [],
        },
        "strategyReplay": {
            "verdict": (replay.get("deskVerdictReplay") or {}).get("level"),
            "message": (replay.get("deskVerdictReplay") or {}).get("message"),
            "scoredCount": replay_overall.get("scoredCount"),
            "promotionCandidates": replay.get("promotionCandidatesReplay") or [],
        },
        "hypothesisLab": {
            "totalHypotheses": hypothesis_lab.get("totalHypotheses"),
            "topHypothesisIds": [item.get("id") for item in (hypothesis_lab.get("topHypotheses") or [])[:5]],
        },
        "hypothesisLedger": {
            "totalHypotheses": ledger_report.get("totalHypotheses"),
            "trajectoryCounts": ledger_report.get("trajectoryCounts") or {},
        },
        "scenarioBacktest": {
            "stage": scenario_backtest.get("stage"),
            "scenarioCount": scenario_backtest.get("scenarioCount"),
            "closedEvidenceCount": scenario_backtest.get("closedEvidenceCount"),
            "closedObservationCount": scenario_backtest.get("closedObservationCount"),
            "verdictCounts": scenario_counts.get("verdictCounts") or {},
            "observationVerdictCounts": scenario_counts.get("observationVerdictCounts") or {},
            "topFocusTickers": [
                item.get("ticker")
                for item in (scenario_backtest.get("topFocus") or [])[:5]
                if item.get("ticker")
            ],
            "promotable": bool(scenario_backtest.get("promotable")),
        },
        "scoreCalibration": {
            "stage": score_calibration.get("stage"),
            "verdict": score_calibration.get("verdict"),
            "closedScenarioObservations": (score_calibration.get("counts") or {}).get("closedScenarioObservations"),
            "scenarioScoreRows": (score_calibration.get("counts") or {}).get("scenarioScoreRows"),
            "promotable": bool(score_calibration.get("promotable")),
        },
        "expectedMoveLedger": {
            "stage": expected_move.get("stage"),
            "verdict": expected_move.get("verdict"),
            "regimeVerdict": (expected_move.get("regimeDiagnostics") or {}).get("verdict"),
            "closedLongVolRecords": (expected_move.get("counts") or {}).get("closedLongVolRecords"),
            "currentLongVolCandidates": (expected_move.get("counts") or {}).get("currentLongVolCandidates"),
            "beatRate": (expected_move.get("overall") or {}).get("beatRate"),
            "hurdleCounts": expected_move.get("currentHurdleCounts") or {},
            "metricConflictCount": (
                ((expected_move.get("regimeDiagnostics") or {}).get("evidenceQuality") or {}).get(
                    "positiveRButMissedImpliedMoveCount"
                )
            ),
            "repeatedFingerprintExcessRecords": (
                ((expected_move.get("regimeDiagnostics") or {}).get("evidenceQuality") or {}).get(
                    "repeatedFingerprintExcessRecords"
                )
            ),
            "promotable": bool(expected_move.get("promotable")),
        },
        "strategyAlternativeScorer": {
            "stage": strategy_alternatives.get("stage"),
            "verdict": strategy_alternatives.get("verdict"),
            "pressureCandidates": (strategy_alternatives.get("counts") or {}).get("pressureCandidates"),
            "primaryHardExtreme": (strategy_alternatives.get("counts") or {}).get("primaryHardExtreme"),
            "recommendations": (strategy_alternatives.get("counts") or {}).get("recommendations") or {},
            "promotable": bool(strategy_alternatives.get("promotable")),
        },
        "nextActions": [
            "Use shadow replay as research context only; do not confuse it with promotable paper evidence.",
            "Keep filling the paper evidence loop until the real strategy lab exits insufficient-data.",
            "Review top hypotheses for filters worth testing in the next approval cycle.",
            "Use scenario evidence for underlying-move learning, but keep option evidence verdicts tied to paper/shadow option outcomes.",
            "Use score calibration and expected-move reports to pressure-test rankings and long-vol premium assumptions before expanding size.",
            "Use the strategy alternative scorer to price put-credit/condor/put-debit candidates before favoring hard or extreme long vol.",
        ],
    }


def research_cycle_text(report: dict[str, Any]) -> str:
    lines = [
        "Inferno Research Cycle",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Verdict: {report.get('verdict')}",
        "",
        "Shadow lane:",
        f"- tracked: {(report.get('shadow') or {}).get('trackedCount')}",
        f"- closed: {(report.get('shadow') or {}).get('closedCount')}",
        f"- avg R: {(report.get('shadow') or {}).get('avgReturnOnRisk')}",
        "",
        "Real evidence lane:",
        f"- performance: {(report.get('performance') or {}).get('verdict')} | {(report.get('performance') or {}).get('message')}",
        f"- strategy lab: {(report.get('strategyLab') or {}).get('verdict')} | "
        f"scored {(report.get('strategyLab') or {}).get('scoredCount')} | "
        f"candidates {', '.join((report.get('strategyLab') or {}).get('promotionCandidates') or []) or 'none'}",
        "",
        "Shadow replay lane:",
        f"- replay verdict: {(report.get('strategyReplay') or {}).get('verdict')} | "
        f"scored {(report.get('strategyReplay') or {}).get('scoredCount')} | "
        f"candidates {', '.join((report.get('strategyReplay') or {}).get('promotionCandidates') or []) or 'none'}",
        "",
        "Hypothesis lane:",
        f"- total hypotheses: {(report.get('hypothesisLab') or {}).get('totalHypotheses')}",
        f"- top ids: {', '.join((report.get('hypothesisLab') or {}).get('topHypothesisIds') or []) or 'none'}",
        f"- trajectories: {json.dumps((report.get('hypothesisLedger') or {}).get('trajectoryCounts') or {})}",
        "",
        "Scenario backtest lane:",
        f"- scenarios: {(report.get('scenarioBacktest') or {}).get('scenarioCount')}",
        f"- closed evidence records: {(report.get('scenarioBacktest') or {}).get('closedEvidenceCount')}",
        f"- closed scenario observations: {(report.get('scenarioBacktest') or {}).get('closedObservationCount')}",
        f"- verdicts: {json.dumps((report.get('scenarioBacktest') or {}).get('verdictCounts') or {})}",
        f"- observation verdicts: {json.dumps((report.get('scenarioBacktest') or {}).get('observationVerdictCounts') or {})}",
        f"- top focus: {', '.join((report.get('scenarioBacktest') or {}).get('topFocusTickers') or []) or 'none'}",
        f"- promotable: {(report.get('scenarioBacktest') or {}).get('promotable')}",
        "",
        "Calibration lane:",
        f"- score calibration: {(report.get('scoreCalibration') or {}).get('verdict')} | "
        f"closed observations {(report.get('scoreCalibration') or {}).get('closedScenarioObservations')} | "
        f"score rows {(report.get('scoreCalibration') or {}).get('scenarioScoreRows')} | "
        f"promotable {(report.get('scoreCalibration') or {}).get('promotable')}",
        f"- expected move: {(report.get('expectedMoveLedger') or {}).get('verdict')} | "
        f"regime {(report.get('expectedMoveLedger') or {}).get('regimeVerdict')} | "
        f"closed long-vol {(report.get('expectedMoveLedger') or {}).get('closedLongVolRecords')} | "
        f"current long-vol {(report.get('expectedMoveLedger') or {}).get('currentLongVolCandidates')} | "
        f"beat rate {(report.get('expectedMoveLedger') or {}).get('beatRate')} | "
        f"metric conflicts {(report.get('expectedMoveLedger') or {}).get('metricConflictCount')} | "
        f"repeated excess {(report.get('expectedMoveLedger') or {}).get('repeatedFingerprintExcessRecords')} | "
        f"hurdles {json.dumps((report.get('expectedMoveLedger') or {}).get('hurdleCounts') or {})} | "
        f"promotable {(report.get('expectedMoveLedger') or {}).get('promotable')}",
        f"- strategy alternatives: {(report.get('strategyAlternativeScorer') or {}).get('verdict')} | "
        f"pressure candidates {(report.get('strategyAlternativeScorer') or {}).get('pressureCandidates')} | "
        f"hard/extreme {(report.get('strategyAlternativeScorer') or {}).get('primaryHardExtreme')} | "
        f"recommendations {json.dumps((report.get('strategyAlternativeScorer') or {}).get('recommendations') or {})} | "
        f"promotable {(report.get('strategyAlternativeScorer') or {}).get('promotable')}",
        "",
        "Next actions:",
    ]
    for action in report.get("nextActions") or []:
        lines.append(f"- {action}")
    return "\n".join(lines).rstrip() + "\n"


def save_research_cycle(report: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(RESEARCH_CYCLE_FILE, report)
    atomic_write_text(RESEARCH_CYCLE_TEXT_FILE, research_cycle_text(report))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh the full Inferno research/backtest lane.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and RESEARCH_CYCLE_TEXT_FILE.exists():
        print(RESEARCH_CYCLE_TEXT_FILE.read_text(encoding="utf-8"))
        latest = json.loads(RESEARCH_CYCLE_FILE.read_text(encoding="utf-8")) if RESEARCH_CYCLE_FILE.exists() else {}
        return 0 if latest.get("ok", True) else 1
    report = build_research_cycle()
    save_research_cycle(report)
    print(research_cycle_text(report))
    return 0 if report.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
