from __future__ import annotations

"""Backtest sensitivity sweep over the strategy-lab thresholds.

Question this module answers: "If we held the desk's evidence constant but
varied the promotion gate, which strategies would clear?" Useful for
calibration without touching the actual conservative gates.

The default gate set (from ``inferno_strategy_lab``) is intentionally strict.
This module recomputes verdicts against a small grid of *looser* thresholds,
each tagged with a profile name, so the operator can see how close the desk
actually is to a defensible promotion.

Hard contract:
- diagnostic / research-only. Cannot mutate any artifact.
- the production strategy lab gates remain at the committed values.
- this module writes only to ``data/inferno_threshold_sensitivity.json`` and
  ``reports/threshold_sensitivity_latest.txt``.
- cannot affect authority manifest or any other state.
"""

import argparse
import json
from typing import Any

from inferno_config import local_now
from inferno_strategy_lab import (
    MAX_DRAWDOWN_RISK_UNITS,
    MAX_FALSE_POSITIVE_RATE,
    MIN_EXPECTANCY_LOWER_BOUND,
    MIN_PROFIT_FACTOR,
    MIN_SCORED_TRADES_FOR_PROMOTION,
    MIN_WIN_RATE_LOWER_BOUND,
    STRATEGY_LAB_FILE,
    build_strategy_lab,
)
from inferno_strategy_replay import normalize_shadow_item
from inferno_shadow_evidence import SHADOW_EVIDENCE_FILE
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


SENSITIVITY_FILE = DATA_DIR / "inferno_threshold_sensitivity.json"
SENSITIVITY_TEXT_FILE = REPORTS_DIR / "threshold_sensitivity_latest.txt"
SENSITIVITY_STAGE = "threshold-sensitivity-research-only"


# Threshold profiles. Each tuple is (name, description, thresholds dict).
# These are intentionally ordered strict → loose. The strict profile mirrors
# the committed production gate. The loose profiles are *theoretical only* —
# nothing here changes the real lab's behavior.
def default_threshold_profiles() -> list[dict[str, Any]]:
    return [
        {
            "name": "production",
            "description": "Current committed strategy-lab thresholds.",
            "minScored": MIN_SCORED_TRADES_FOR_PROMOTION,
            "minWinRateLowerBound": MIN_WIN_RATE_LOWER_BOUND,
            "minExpectancyLowerBound": MIN_EXPECTANCY_LOWER_BOUND,
            "minProfitFactor": MIN_PROFIT_FACTOR,
            "maxFalsePositiveRate": MAX_FALSE_POSITIVE_RATE,
            "maxDrawdownRiskUnits": MAX_DRAWDOWN_RISK_UNITS,
        },
        {
            "name": "moderate",
            "description": "Halved sample requirement, otherwise identical.",
            "minScored": max(10, MIN_SCORED_TRADES_FOR_PROMOTION // 2),
            "minWinRateLowerBound": MIN_WIN_RATE_LOWER_BOUND,
            "minExpectancyLowerBound": MIN_EXPECTANCY_LOWER_BOUND,
            "minProfitFactor": MIN_PROFIT_FACTOR,
            "maxFalsePositiveRate": MAX_FALSE_POSITIVE_RATE,
            "maxDrawdownRiskUnits": MAX_DRAWDOWN_RISK_UNITS,
        },
        {
            "name": "exploratory",
            "description": (
                "Smaller sample and slightly relaxed win-rate floor — useful "
                "for spotting strategies trending toward promotion."
            ),
            "minScored": 10,
            "minWinRateLowerBound": 0.35,
            "minExpectancyLowerBound": MIN_EXPECTANCY_LOWER_BOUND,
            "minProfitFactor": 1.10,
            "maxFalsePositiveRate": 0.6,
            "maxDrawdownRiskUnits": MAX_DRAWDOWN_RISK_UNITS,
        },
        {
            "name": "permissive",
            "description": (
                "Diagnostic-only: shows what would happen with very loose "
                "gates. Not safe to promote against."
            ),
            "minScored": 5,
            "minWinRateLowerBound": 0.30,
            "minExpectancyLowerBound": MIN_EXPECTANCY_LOWER_BOUND,
            "minProfitFactor": 1.00,
            "maxFalsePositiveRate": 0.7,
            "maxDrawdownRiskUnits": MAX_DRAWDOWN_RISK_UNITS,
        },
    ]


def verdict_under_thresholds(strategy: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, Any]:
    """Recompute a promotion verdict for one strategy using a custom threshold set."""
    scored = int(strategy.get("scoredCount") or 0)
    win_lower = strategy.get("winRateLowerBound")
    expectancy_lower = (strategy.get("expectancyPerRiskConfidence") or {}).get("lower")
    profit_factor = strategy.get("profitFactor")
    drawdown = strategy.get("maxDrawdownRiskUnits")
    false_positive = strategy.get("falsePositiveRate")

    blockers: list[str] = []
    if scored <= 0:
        blockers.append("no closed scored trades")
    if scored < thresholds["minScored"]:
        blockers.append(f"need {thresholds['minScored'] - scored} more scored trades")
    if expectancy_lower is None or expectancy_lower <= thresholds["minExpectancyLowerBound"]:
        blockers.append("expectancy lower bound not positive")
    if win_lower is None or win_lower < thresholds["minWinRateLowerBound"]:
        blockers.append(f"win-rate lower bound below {thresholds['minWinRateLowerBound']}")
    if profit_factor is None or profit_factor < thresholds["minProfitFactor"]:
        blockers.append(f"profit factor below {thresholds['minProfitFactor']}")
    if drawdown is not None and drawdown < thresholds["maxDrawdownRiskUnits"]:
        blockers.append(f"drawdown worse than {thresholds['maxDrawdownRiskUnits']} R")
    warnings: list[str] = []
    if false_positive is not None and false_positive > thresholds["maxFalsePositiveRate"]:
        warnings.append(f"false-positive rate above {thresholds['maxFalsePositiveRate']}")

    return {
        "promotable": not blockers,
        "blockers": blockers,
        "warnings": warnings,
    }


def sweep_strategy(strategy: dict[str, Any], profiles: list[dict[str, Any]]) -> dict[str, Any]:
    """Run every threshold profile against one strategy summary."""
    results = []
    promoted_under: list[str] = []
    for profile in profiles:
        verdict = verdict_under_thresholds(strategy, profile)
        results.append(
            {
                "profile": profile["name"],
                "promotable": verdict["promotable"],
                "blockerCount": len(verdict["blockers"]),
                "topBlocker": verdict["blockers"][0] if verdict["blockers"] else None,
                "warnings": verdict["warnings"],
            }
        )
        if verdict["promotable"]:
            promoted_under.append(profile["name"])
    return {
        "strategy": strategy.get("strategy"),
        "scoredCount": int(strategy.get("scoredCount") or 0),
        "winRateLowerBound": strategy.get("winRateLowerBound"),
        "profitFactor": strategy.get("profitFactor"),
        "promotedUnder": promoted_under,
        "loosestPromotingProfile": promoted_under[-1] if promoted_under else None,
        "results": results,
    }


def normalize_lab_for_sensitivity(source: str) -> dict[str, Any]:
    """Build a lab payload from either the production lab or the shadow replay.

    ``production`` returns the actual paper-ledger lab artifact.
    ``shadow-replay`` re-uses ``normalize_shadow_item`` so the sweep sees
    hypothetical closed outcomes — which is the only way to get non-trivial
    samples today, since the production lab has 0 scored tickets.
    """
    if source == "shadow-replay":
        shadow = load_json_file(SHADOW_EVIDENCE_FILE) or {}
        items = [normalize_shadow_item(item) for item in (shadow.get("items") or [])]
        return build_strategy_lab({"updatedAt": shadow.get("updatedAt"), "items": items})
    return load_json_file(STRATEGY_LAB_FILE) or {}


def build_sensitivity(
    *,
    lab: dict[str, Any] | None = None,
    profiles: list[dict[str, Any]] | None = None,
    source: str = "shadow-replay",
) -> dict[str, Any]:
    """Build the full sensitivity sweep."""
    profiles = profiles or default_threshold_profiles()
    if lab is None:
        lab = normalize_lab_for_sensitivity(source)
    strategies = lab.get("strategies") or []
    overall = lab.get("overall")
    rows = [sweep_strategy(strat, profiles) for strat in strategies]
    overall_row = sweep_strategy(overall, profiles) if overall else None

    promoted_any_under = sorted({
        profile_name
        for row in rows
        for profile_name in row["promotedUnder"]
    })

    return {
        "generatedAt": local_now().isoformat(),
        "stage": SENSITIVITY_STAGE,
        "researchOnly": True,
        "promotable": False,
        "source": source,
        "sourceLabGeneratedAt": lab.get("generatedAt"),
        "profiles": profiles,
        "strategies": rows,
        "overall": overall_row,
        "promotedAnyUnder": promoted_any_under,
        "tightestPromotingProfile": promoted_any_under[0] if promoted_any_under else None,
        "researchNotes": [
            "diagnostic only; cannot change production thresholds",
            "shadow-replay source uses hypothetical outcomes, not real fills",
            "loose profiles exist to surface calibration data, not to promote against",
        ],
    }


def sensitivity_text(report: dict[str, Any]) -> str:
    lines = [
        "Inferno Threshold Sensitivity Sweep (research-only)",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Stage: {report.get('stage')}",
        f"Source: {report.get('source')}",
        f"Source lab generated at: {report.get('sourceLabGeneratedAt')}",
        "",
        "Profiles (strict → loose):",
    ]
    for profile in report.get("profiles") or []:
        lines.append(
            f"- {profile['name']}: scored>={profile['minScored']} | "
            f"WRlow>={profile['minWinRateLowerBound']} | "
            f"PF>={profile['minProfitFactor']} | "
            f"FPR<={profile['maxFalsePositiveRate']} | "
            f"DD>={profile['maxDrawdownRiskUnits']}"
        )

    lines.extend([
        "",
        f"Promotable under any profile: {report.get('promotedAnyUnder') or 'none'}",
        f"Tightest profile that still promotes anything: {report.get('tightestPromotingProfile') or 'none'}",
        "",
        "Per-strategy verdicts:",
    ])
    for strat in report.get("strategies") or []:
        lines.append(
            f"- {strat['strategy']}: scored={strat['scoredCount']} | "
            f"WRlow={strat['winRateLowerBound']} | PF={strat['profitFactor']} "
            f"| promotedUnder={strat['promotedUnder'] or '-'}"
        )
        for result in strat.get("results") or []:
            mark = "PASS" if result["promotable"] else "FAIL"
            top = result.get("topBlocker") or "-"
            lines.append(f"  [{mark}] profile={result['profile']:<11} topBlocker={top}")

    overall = report.get("overall")
    if overall:
        lines.extend(["", "Overall (ALL_STRATEGIES):"])
        for result in overall.get("results") or []:
            mark = "PASS" if result["promotable"] else "FAIL"
            top = result.get("topBlocker") or "-"
            lines.append(f"  [{mark}] profile={result['profile']:<11} topBlocker={top}")

    lines.extend([
        "",
        "Reminders:",
        "- production thresholds are unchanged; this sweep is read-only",
        "- shadow-replay source is hypothetical and cannot unlock authority",
    ])
    return "\n".join(lines).rstrip() + "\n"


def save_sensitivity(report: dict[str, Any]) -> None:
    ensure_dirs()
    SENSITIVITY_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    SENSITIVITY_TEXT_FILE.write_text(sensitivity_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Threshold sensitivity sweep over the strategy-lab gates. Read-only."
        )
    )
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    parser.add_argument(
        "--source",
        default="shadow-replay",
        choices=["shadow-replay", "production"],
        help="Which evidence to sweep against.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and SENSITIVITY_TEXT_FILE.exists():
        print(SENSITIVITY_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = build_sensitivity(source=args.source)
    save_sensitivity(report)
    print(sensitivity_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
