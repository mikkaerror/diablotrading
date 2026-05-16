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
from inferno_shadow_evidence import build_shadow_evidence, save_shadow_evidence
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

    overall = strategy_lab.get("overall") or {}
    performance_desk = performance.get("deskVerdict") or {}
    shadow_overall = shadow.get("overall") or {}
    replay_overall = ((replay.get("lab") or {}).get("overall") or {})
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
        "nextActions": [
            "Use shadow replay as research context only; do not confuse it with promotable paper evidence.",
            "Keep filling the paper evidence loop until the real strategy lab exits insufficient-data.",
            "Review top hypotheses for filters worth testing in the next approval cycle.",
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
