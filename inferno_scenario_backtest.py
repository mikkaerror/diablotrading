from __future__ import annotations

"""Scenario backtest scorecard for the daily paper/shadow slate.

The paper bottleneck reducer gives the desk 10+ scenarios to follow each day.
This module closes the evidence loop around that slate: for every current
scenario, it looks backward at closed paper and shadow outcomes and asks,
"What has this type of trade taught us so far?"

Strict contract:
- research-only and diagnostic-only
- no broker calls, no approvals, no order creation, no authority promotion
- all stats are descriptive; small samples must remain visibly small
"""

import argparse
from collections import defaultdict
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_paper_bottleneck_reducer import PAPER_BOTTLENECK_REDUCER_FILE
from inferno_paper_execution import PAPER_EXECUTION_LEDGER_FILE
from inferno_scenario_evidence import SCENARIO_EVIDENCE_FILE
from inferno_shadow_evidence import SHADOW_EVIDENCE_FILE
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


SCENARIO_BACKTEST_FILE = DATA_DIR / "inferno_scenario_backtest.json"
SCENARIO_BACKTEST_TEXT_FILE = REPORTS_DIR / "scenario_backtest_latest.txt"
SCENARIO_BACKTEST_STAGE = "scenario-backtest-research-only"

MIN_USEFUL_SAMPLE = 3
SUPPORTIVE_MEAN_R = 0.15
CONTRADICTORY_MEAN_R = -0.15
SUPPORTIVE_PROFIT_FACTOR = 1.20
CONTRADICTORY_PROFIT_FACTOR = 0.80
SUPPORTIVE_OBSERVATION_MEAN = 0.25
CONTRADICTORY_OBSERVATION_MEAN = -0.25
SUPPORTIVE_OBSERVATION_RATE = 0.60
CONTRADICTORY_OBSERVATION_RATE = 0.50


def text(value: Any) -> str:
    """Normalize loose artifact values to stripped strings."""
    return str(value or "").strip()


def number(value: Any, default: float | None = None) -> float | None:
    """Safely coerce a loose value to float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def norm(value: Any) -> str:
    """Normalize values for matching across paper, shadow, and scenario rows."""
    return text(value).upper()


def strategy_family(value: Any) -> str:
    """Collapse verbose strategy/setup names into comparable families."""
    raw = norm(value).replace("_", " ")
    if "STRADDLE" in raw:
        return "STRADDLE"
    if "IRON CONDOR" in raw:
        return "IRON_CONDOR"
    if "CALL" in raw:
        return "CALL_VERTICAL"
    if "PUT" in raw:
        return "PUT_VERTICAL"
    if "VERTICAL" in raw:
        return "VERTICAL"
    return raw or "UNKNOWN"


def dte_bucket(value: Any) -> str:
    """Bucket days-to-earnings so scenarios can be compared without exact dates."""
    days = number(value)
    if days is None:
        return "unknown-dte"
    if days < 0:
        return "post-event"
    if days <= 7:
        return "hot-window"
    if days <= 21:
        return "earnings-window"
    return "longer-window"


def max_loss(entry: dict[str, Any]) -> float:
    """Return the best available max-loss estimate for R-unit math."""
    metrics = ((entry.get("riskVerdict") or {}).get("metrics") or {})
    for candidate in (
        metrics.get("maxLossDollars"),
        entry.get("estimatedMaxLoss"),
        entry.get("maxLossDollars"),
    ):
        value = number(candidate)
        if value and value > 0:
            return value
    return 0.0


def outcome_r(entry: dict[str, Any]) -> float | None:
    """Return closed outcome return in R units when enough information exists."""
    outcome = entry.get("outcome") or {}
    direct = number(outcome.get("estimatedReturnOnRisk"))
    if direct is not None:
        return round(direct, 6)
    pnl = number(outcome.get("estimatedPnl"))
    risk = max_loss(entry)
    if pnl is None or risk <= 0:
        return None
    return round(pnl / risk, 6)


def evidence_record(entry: dict[str, Any], source: str) -> dict[str, Any] | None:
    """Normalize one closed paper/shadow item into a comparable evidence row."""
    outcome = entry.get("outcome") or {}
    if text(outcome.get("status")).lower() != "closed":
        return None
    r_value = outcome_r(entry)
    if r_value is None:
        return None
    strategy = entry.get("strategy") or entry.get("setupRec")
    return {
        "source": source,
        "ticker": norm(entry.get("ticker")),
        "setupRec": text(entry.get("setupRec")),
        "strategy": text(strategy),
        "family": strategy_family(strategy),
        "dteBucket": dte_bucket(entry.get("daysUntilEarnings")),
        "r": r_value,
        "estimatedPnl": number(outcome.get("estimatedPnl"), 0.0),
        "reviewedAt": outcome.get("reviewedAt"),
        "ticketId": entry.get("ticketId"),
    }


def closed_evidence_records(
    *,
    paper_ledger: dict[str, Any] | None = None,
    shadow_ledger: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return closed evidence from both paper and shadow ledgers."""
    paper_ledger = paper_ledger if paper_ledger is not None else (load_json_file(PAPER_EXECUTION_LEDGER_FILE) or {})
    shadow_ledger = shadow_ledger if shadow_ledger is not None else (load_json_file(SHADOW_EVIDENCE_FILE) or {})
    records: list[dict[str, Any]] = []
    for item in paper_ledger.get("items") or []:
        record = evidence_record(item, "paper")
        if record:
            records.append(record)
    for item in shadow_ledger.get("items") or []:
        record = evidence_record(item, "shadow")
        if record:
            records.append(record)
    return records


def scenario_observation_record(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one closed scenario observation for separate research stats."""
    outcome = entry.get("outcome") or {}
    if text(outcome.get("status")).lower() != "closed":
        return None
    score = number(outcome.get("observationScore"))
    if score is None:
        return None
    strategy = entry.get("strategy") or entry.get("setupRec")
    return {
        "source": "scenario-observation",
        "ticker": norm(entry.get("ticker")),
        "setupRec": text(entry.get("setupRec")),
        "strategy": text(strategy),
        "family": strategy_family(strategy),
        "dteBucket": entry.get("dteBucket") or dte_bucket(entry.get("daysUntilEarnings")),
        "observationScore": score,
        "resultClass": text(outcome.get("resultClass")),
        "underlyingReturnPct": number(outcome.get("underlyingReturnPct"), 0.0),
        "reviewedAt": outcome.get("reviewedAt"),
        "observationId": entry.get("observationId"),
    }


def closed_scenario_observation_records(
    *,
    scenario_evidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return closed scenario observations without mixing them into option P/L."""
    scenario_evidence = (
        scenario_evidence
        if scenario_evidence is not None
        else (load_json_file(SCENARIO_EVIDENCE_FILE) or {})
    )
    records: list[dict[str, Any]] = []
    for item in scenario_evidence.get("observations") or []:
        record = scenario_observation_record(item)
        if record:
            records.append(record)
    return records


def stats_block(samples: list[float]) -> dict[str, Any]:
    """Compute compact descriptive stats for a set of R-unit outcomes."""
    wins = [value for value in samples if value > 0]
    losses = [value for value in samples if value < 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    profit_factor = gross_win / gross_loss if gross_loss > 0 else None
    mean_r = sum(samples) / len(samples) if samples else None
    return {
        "sampleCount": len(samples),
        "winCount": len(wins),
        "lossCount": len(losses),
        "winRate": round(len(wins) / len(samples), 4) if samples else None,
        "meanR": round(mean_r, 4) if mean_r is not None else None,
        "totalR": round(sum(samples), 4),
        "bestR": round(max(samples), 4) if samples else None,
        "worstR": round(min(samples), 4) if samples else None,
        "profitFactor": round(profit_factor, 4) if profit_factor is not None else None,
    }


def evidence_verdict(stats: dict[str, Any]) -> str:
    """Classify the historical evidence without pretending tiny samples are proof."""
    sample_count = int(stats.get("sampleCount") or 0)
    mean_r = number(stats.get("meanR"), 0.0) or 0.0
    profit_factor = stats.get("profitFactor")
    if sample_count < MIN_USEFUL_SAMPLE:
        return "insufficient-data"
    if mean_r >= SUPPORTIVE_MEAN_R and (profit_factor is None or profit_factor >= SUPPORTIVE_PROFIT_FACTOR):
        return "supportive"
    if mean_r <= CONTRADICTORY_MEAN_R or (
        profit_factor is not None and profit_factor <= CONTRADICTORY_PROFIT_FACTOR
    ):
        return "contradictory"
    return "mixed"


def observation_stats_block(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute descriptive stats for closed scenario observations.

    These stats use underlying-move proxy scores, not option R units. They are
    shown next to the option evidence verdict instead of replacing it.
    """
    scores = [number(record.get("observationScore"), 0.0) or 0.0 for record in records]
    results = [text(record.get("resultClass")) for record in records]
    favorable = sum(1 for result in results if result == "favorable")
    unfavorable = sum(1 for result in results if result == "unfavorable")
    neutral = sum(1 for result in results if result == "neutral")
    mean_score = sum(scores) / len(scores) if scores else None
    returns = [number(record.get("underlyingReturnPct"), 0.0) or 0.0 for record in records]
    return {
        "sampleCount": len(records),
        "favorableCount": favorable,
        "neutralCount": neutral,
        "unfavorableCount": unfavorable,
        "favorableRate": round(favorable / len(records), 4) if records else None,
        "unfavorableRate": round(unfavorable / len(records), 4) if records else None,
        "meanObservationScore": round(mean_score, 4) if mean_score is not None else None,
        "avgUnderlyingReturnPct": round(sum(returns) / len(returns), 4) if returns else None,
        "bestObservationScore": round(max(scores), 4) if scores else None,
        "worstObservationScore": round(min(scores), 4) if scores else None,
    }


def observation_verdict(stats: dict[str, Any]) -> str:
    """Classify scenario observations while preserving small-sample humility."""
    sample_count = int(stats.get("sampleCount") or 0)
    mean_score = number(stats.get("meanObservationScore"), 0.0) or 0.0
    favorable_rate = number(stats.get("favorableRate"), 0.0) or 0.0
    unfavorable_rate = number(stats.get("unfavorableRate"), 0.0) or 0.0
    if sample_count < MIN_USEFUL_SAMPLE:
        return "insufficient-observation-data"
    if mean_score >= SUPPORTIVE_OBSERVATION_MEAN and favorable_rate >= SUPPORTIVE_OBSERVATION_RATE:
        return "supportive-observation"
    if mean_score <= CONTRADICTORY_OBSERVATION_MEAN or unfavorable_rate >= CONTRADICTORY_OBSERVATION_RATE:
        return "contradictory-observation"
    return "mixed-observation"


def scenario_matches(scenario: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Return evidence matches from most specific to broadest."""
    ticker = norm(scenario.get("ticker"))
    family = strategy_family(scenario.get("strategy") or scenario.get("setupRec"))
    bucket = dte_bucket(scenario.get("daysUntilEarnings"))
    matches: dict[str, list[dict[str, Any]]] = {
        "ticker": [],
        "familyAndWindow": [],
        "family": [],
        "allClosed": list(records),
    }
    for record in records:
        if record.get("ticker") == ticker:
            matches["ticker"].append(record)
        if record.get("family") == family and record.get("dteBucket") == bucket:
            matches["familyAndWindow"].append(record)
        if record.get("family") == family:
            matches["family"].append(record)
    return matches


def observation_matches(
    scenario: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Return closed observation matches from most specific to broadest."""
    ticker = norm(scenario.get("ticker"))
    family = strategy_family(scenario.get("strategy") or scenario.get("setupRec"))
    bucket = dte_bucket(scenario.get("daysUntilEarnings"))
    matches: dict[str, list[dict[str, Any]]] = {
        "ticker": [],
        "familyAndWindow": [],
        "family": [],
        "allClosed": list(records),
    }
    for record in records:
        if record.get("ticker") == ticker:
            matches["ticker"].append(record)
        if record.get("family") == family and record.get("dteBucket") == bucket:
            matches["familyAndWindow"].append(record)
        if record.get("family") == family:
            matches["family"].append(record)
    return matches


def best_scope(match_stats: dict[str, dict[str, Any]]) -> str:
    """Pick the most useful evidence scope for the scenario headline."""
    # Broad all-closed evidence is context, not proof for a specific trade.
    # Using it as the headline would let unrelated call-spread history bless a
    # straddle or condor, which is exactly the kind of false confidence this
    # module is meant to prevent.
    for scope in ("ticker", "familyAndWindow", "family"):
        if int(match_stats.get(scope, {}).get("sampleCount") or 0) >= MIN_USEFUL_SAMPLE:
            return scope
    for scope in ("ticker", "familyAndWindow", "family"):
        if int(match_stats.get(scope, {}).get("sampleCount") or 0) > 0:
            return scope
    return "none"


def best_observation_scope(match_stats: dict[str, dict[str, Any]]) -> str:
    """Pick the most useful observation scope without blessing unrelated names."""
    for scope in ("ticker", "familyAndWindow", "family"):
        if int(match_stats.get(scope, {}).get("sampleCount") or 0) >= MIN_USEFUL_SAMPLE:
            return scope
    for scope in ("ticker", "familyAndWindow", "family"):
        if int(match_stats.get(scope, {}).get("sampleCount") or 0) > 0:
            return scope
    return "none"


def scenario_scorecard(
    scenario: dict[str, Any],
    records: list[dict[str, Any]],
    observation_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one scenario's backtest scorecard."""
    matches = scenario_matches(scenario, records)
    match_stats = {
        scope: stats_block([record["r"] for record in scoped_records])
        for scope, scoped_records in matches.items()
    }
    scope = best_scope(match_stats)
    headline_stats = match_stats.get(scope) or stats_block([])
    verdict = evidence_verdict(headline_stats)
    observation_records = observation_records or []
    obs_matches = observation_matches(scenario, observation_records)
    obs_match_stats = {
        scope_name: observation_stats_block(scoped_records)
        for scope_name, scoped_records in obs_matches.items()
    }
    obs_scope = best_observation_scope(obs_match_stats)
    obs_stats = obs_match_stats.get(obs_scope) or observation_stats_block([])
    return {
        "rank": scenario.get("rank"),
        "ticker": norm(scenario.get("ticker")),
        "sourceLane": scenario.get("sourceLane"),
        "evidenceLane": scenario.get("evidenceLane"),
        "strategy": scenario.get("strategy"),
        "setupRec": scenario.get("setupRec"),
        "family": strategy_family(scenario.get("strategy") or scenario.get("setupRec")),
        "dteBucket": dte_bucket(scenario.get("daysUntilEarnings")),
        "scenarioScore": scenario.get("scenarioScore"),
        "executableInPaperMoney": bool(scenario.get("executableInPaperMoney")),
        "shadowOnly": bool(scenario.get("shadowOnly")),
        "bestEvidenceScope": scope,
        "evidenceVerdict": verdict,
        "headlineStats": headline_stats,
        "matchStats": match_stats,
        "bestObservationScope": obs_scope,
        "observationEvidenceVerdict": observation_verdict(obs_stats),
        "observationHeadlineStats": obs_stats,
        "observationMatchStats": obs_match_stats,
        "researchOnly": True,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
    }


def group_summary(scorecards: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize scenario verdicts by evidence state and strategy family."""
    verdict_counts: dict[str, int] = defaultdict(int)
    observation_verdict_counts: dict[str, int] = defaultdict(int)
    family_counts: dict[str, int] = defaultdict(int)
    for card in scorecards:
        verdict_counts[str(card.get("evidenceVerdict"))] += 1
        observation_verdict_counts[str(card.get("observationEvidenceVerdict"))] += 1
        family_counts[str(card.get("family"))] += 1
    return {
        "verdictCounts": dict(sorted(verdict_counts.items())),
        "observationVerdictCounts": dict(sorted(observation_verdict_counts.items())),
        "familyCounts": dict(sorted(family_counts.items())),
    }


def build_scenario_backtest(
    *,
    reducer: dict[str, Any] | None = None,
    paper_ledger: dict[str, Any] | None = None,
    shadow_ledger: dict[str, Any] | None = None,
    scenario_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the research-only scenario backtest artifact."""
    reducer = reducer if reducer is not None else (load_json_file(PAPER_BOTTLENECK_REDUCER_FILE) or {})
    scenarios = [item for item in reducer.get("scenarioSlate") or [] if isinstance(item, dict)]
    records = closed_evidence_records(paper_ledger=paper_ledger, shadow_ledger=shadow_ledger)
    observation_records = closed_scenario_observation_records(scenario_evidence=scenario_evidence)
    scorecards = [
        scenario_scorecard(scenario, records, observation_records)
        for scenario in scenarios
    ]
    top_focus = scorecards[:5]
    summary = group_summary(scorecards)
    return {
        "generatedAt": local_now().isoformat(),
        "stage": SCENARIO_BACKTEST_STAGE,
        "researchOnly": True,
        "diagnosticOnly": True,
        "promotable": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "sourceReducerGeneratedAt": reducer.get("generatedAt"),
        "scenarioCount": len(scorecards),
        "closedEvidenceCount": len(records),
        "closedObservationCount": len(observation_records),
        "counts": {
            "scenarios": len(scorecards),
            "closedEvidence": len(records),
            "closedObservations": len(observation_records),
            **summary,
        },
        "topFocus": top_focus,
        "scorecards": scorecards,
        "rules": [
            "This is descriptive backtest evidence only.",
            "Insufficient-data means do not infer edge from the match.",
            "Live authority remains controlled by the authority manifest, not this report.",
        ],
    }


def scenario_backtest_text(payload: dict[str, Any]) -> str:
    """Render the scenario scorecard into an operator memo."""
    counts = payload.get("counts") or {}
    lines = [
        "Inferno Scenario Backtest (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Scenarios: {payload.get('scenarioCount', 0)}",
        f"Closed evidence records: {payload.get('closedEvidenceCount', 0)}",
        f"Closed scenario observations: {payload.get('closedObservationCount', 0)}",
        f"Promotable from this artifact: {payload.get('promotable')}",
        "",
        "Option evidence verdict counts:",
    ]
    for verdict, count in (counts.get("verdictCounts") or {}).items():
        lines.append(f"- {verdict}: {count}")
    lines.extend(["", "Scenario observation verdict counts:"])
    for verdict, count in (counts.get("observationVerdictCounts") or {}).items():
        lines.append(f"- {verdict}: {count}")
    lines.extend(["", "Top focus scorecards:"])
    for card in payload.get("topFocus") or []:
        stats = card.get("headlineStats") or {}
        obs_stats = card.get("observationHeadlineStats") or {}
        lines.append(
            f"- #{card.get('rank')} {card.get('ticker')} | {card.get('evidenceVerdict')} | "
            f"scope {card.get('bestEvidenceScope')} | N={stats.get('sampleCount')} | "
            f"meanR={stats.get('meanR')} | PF={stats.get('profitFactor')} | "
            f"obs={card.get('observationEvidenceVerdict')} "
            f"({card.get('bestObservationScope')}, N={obs_stats.get('sampleCount')}, "
            f"fav={obs_stats.get('favorableRate')})"
        )
    lines.extend(["", "Rules:"])
    for rule in payload.get("rules") or []:
        lines.append(f"- {rule}")
    return "\n".join(lines).rstrip() + "\n"


def save_scenario_backtest(payload: dict[str, Any]) -> None:
    """Persist the scenario backtest JSON and text report."""
    ensure_dirs()
    atomic_write_json(SCENARIO_BACKTEST_FILE, payload)
    atomic_write_text(SCENARIO_BACKTEST_TEXT_FILE, scenario_backtest_text(payload))


def parse_args() -> argparse.Namespace:
    """CLI parser for build/status commands."""
    parser = argparse.ArgumentParser(description="Build the research-only scenario backtest scorecard.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    if args.command == "status" and SCENARIO_BACKTEST_TEXT_FILE.exists():
        print(SCENARIO_BACKTEST_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_scenario_backtest()
    save_scenario_backtest(payload)
    print(scenario_backtest_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
