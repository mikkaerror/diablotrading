from __future__ import annotations

"""Research-only score calibration lab for the Inferno desk.

The daily slate produces useful ranking numbers, but a rank is not automatically
a probability. This module compares historical score buckets against closed
scenario-observation outcomes so the desk can see whether higher scores are
actually lining up with better observed results.

Strict contract:
- diagnostic-only and research-only
- no broker calls, approvals, order creation, or authority promotion
- scores are treated as ranking surfaces, not calibrated posterior odds
"""

import argparse
import json
import math
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


SCORE_CALIBRATION_FILE = DATA_DIR / "inferno_score_calibration.json"
SCORE_CALIBRATION_TEXT_FILE = REPORTS_DIR / "score_calibration_latest.txt"
SCORE_CALIBRATION_STAGE = "score-calibration-research-only"

SCENARIO_EVIDENCE_FILE = DATA_DIR / "inferno_scenario_evidence.json"
PAPER_EXECUTION_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
SHADOW_EVIDENCE_FILE = DATA_DIR / "inferno_shadow_evidence.json"

MIN_CALIBRATION_SAMPLE = 30
MIN_MONOTONIC_BUCKET_SAMPLE = 3
SCORE_FIELDS = ("scenarioScore", "readiness", "priorityScore")


def text(value: Any) -> str:
    """Normalize loose artifact values into stripped text."""
    return str(value or "").strip()


def number(value: Any, default: float | None = None) -> float | None:
    """Coerce strings/numbers from artifacts without trusting formatting."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else default
    raw = text(value).replace("$", "").replace(",", "").replace("%", "")
    if not raw:
        return default
    try:
        parsed = float(raw)
        return parsed if math.isfinite(parsed) else default
    except ValueError:
        return default


def clamp_score(value: Any) -> float | None:
    """Return a score clipped to the desk's 0-100 display range."""
    parsed = number(value)
    if parsed is None:
        return None
    return max(0.0, min(100.0, parsed))


def score_value(value: Any, field: str) -> float | None:
    """Priority is a native rank, not a bounded percentage."""
    return number(value) if field == "priorityScore" else clamp_score(value)


def entry_scores(item: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Prefer immutable captured scores; never backfill missing captured values."""
    snapshot = item.get("entryScoreSnapshot")
    if item.get("entryScoreSnapshotVersion") == 1 and isinstance(snapshot, dict):
        return snapshot, "entry-frozen"
    return item, "legacy-entry-unverified"


def evidence_metadata(item: dict[str, Any]) -> dict[str, Any]:
    """Keep timing and group provenance beside raw descriptive rows."""
    return {key: item.get(key) for key in (
        "createdAt", "tradeDate", "expiration", "eventId", "reviewHorizonDays",
    )}


def score_bucket(value: Any) -> dict[str, Any] | None:
    """Map a numeric score into a stable calibration bucket."""
    score = clamp_score(value)
    if score is None:
        return None
    if score < 50:
        return {"bucket": "0-49", "order": 0, "scoreMidpoint": 24.5}
    if score < 60:
        return {"bucket": "50-59", "order": 1, "scoreMidpoint": 54.5}
    if score < 70:
        return {"bucket": "60-69", "order": 2, "scoreMidpoint": 64.5}
    if score < 80:
        return {"bucket": "70-79", "order": 3, "scoreMidpoint": 74.5}
    if score < 90:
        return {"bucket": "80-89", "order": 4, "scoreMidpoint": 84.5}
    return {"bucket": "90-100", "order": 5, "scoreMidpoint": 95.0}


def mean(values: list[float]) -> float | None:
    """Return a rounded arithmetic mean for non-empty samples."""
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def rate(count: int, total: int) -> float | None:
    """Return a rounded rate or None when the denominator is empty."""
    if total <= 0:
        return None
    return round(count / total, 4)


def observation_result_class(outcome: dict[str, Any]) -> str:
    """Normalize the closed scenario outcome class."""
    raw = text(outcome.get("resultClass") or outcome.get("currentResultClass")).lower()
    if raw in {"favorable", "neutral", "unfavorable"}:
        return raw
    score = number(outcome.get("observationScore"), 0.0) or 0.0
    if score > 0:
        return "favorable"
    if score < 0:
        return "unfavorable"
    return "neutral"


def scenario_observation_rows(
    scenario_evidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return closed scenario observations with score fields preserved."""
    payload = (
        scenario_evidence
        if scenario_evidence is not None
        else (load_json_file(SCENARIO_EVIDENCE_FILE) or {})
    )
    rows: list[dict[str, Any]] = []
    for item in payload.get("observations") or []:
        outcome = item.get("outcome") or {}
        if text(outcome.get("status")).lower() != "closed":
            continue
        result = observation_result_class(outcome)
        observation_score = number(outcome.get("observationScore"), 0.0) or 0.0
        underlying_return = number(outcome.get("underlyingReturnPct"), 0.0) or 0.0
        row = {
            **evidence_metadata(item),
            "source": "scenario-observation",
            "ticker": text(item.get("ticker")).upper(),
            "strategy": text(item.get("strategy") or item.get("setupRec")),
            "setupRec": text(item.get("setupRec")),
            "family": text(item.get("family")),
            "dteBucket": text(item.get("dteBucket")),
            "resultClass": result,
            "observationScore": observation_score,
            "underlyingReturnPct": underlying_return,
            "absUnderlyingMovePct": abs(underlying_return),
            "reviewedAt": outcome.get("reviewedAt"),
            "observationId": item.get("observationId"),
        }
        scores, row["scoreProvenance"] = entry_scores(item)
        for field in SCORE_FIELDS:
            score = score_value(scores.get(field), field)
            if score is not None:
                row[field] = score
        rows.append(row)
    return rows


def max_loss(entry: dict[str, Any]) -> float:
    """Return the best available max-loss estimate for option R-unit math."""
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


def option_r(entry: dict[str, Any]) -> float | None:
    """Return closed option outcome in R units when available."""
    outcome = entry.get("outcome") or {}
    direct = number(outcome.get("estimatedReturnOnRisk"))
    if direct is not None:
        return round(direct, 6)
    pnl = number(outcome.get("estimatedPnl"))
    risk = max_loss(entry)
    if pnl is None or risk <= 0:
        return None
    return round(pnl / risk, 6)


def option_score_rows(
    *,
    paper_ledger: dict[str, Any] | None = None,
    shadow_ledger: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return closed paper/shadow option outcomes that still carry scores."""
    paper = paper_ledger if paper_ledger is not None else (load_json_file(PAPER_EXECUTION_LEDGER_FILE) or {})
    shadow = shadow_ledger if shadow_ledger is not None else (load_json_file(SHADOW_EVIDENCE_FILE) or {})
    rows: list[dict[str, Any]] = []
    for source, payload in (("paper", paper), ("shadow", shadow)):
        for item in payload.get("items") or []:
            outcome = item.get("outcome") or {}
            if text(outcome.get("status")).lower() != "closed":
                continue
            r_value = option_r(item)
            if r_value is None:
                continue
            result = "favorable" if r_value > 0 else "unfavorable" if r_value < 0 else "neutral"
            row = {
                **evidence_metadata(item),
                "source": source,
                "ticker": text(item.get("ticker")).upper(),
                "strategy": text(item.get("strategy") or item.get("setupRec")),
                "resultClass": result,
                "r": r_value,
                "reviewedAt": outcome.get("reviewedAt"),
                "ticketId": item.get("ticketId"),
                "expirationPriceEvidence": outcome.get("expirationPriceEvidence"),
            }
            scores, row["scoreProvenance"] = entry_scores(item)
            for field in SCORE_FIELDS:
                score = score_value(scores.get(field), field)
                if score is not None:
                    row[field] = score
            rows.append(row)
    return rows


def has_entry_score(item: dict[str, Any]) -> bool:
    """Return True when a paper/shadow entry carries any rank score."""
    scores, _ = entry_scores(item)
    return any(score_value(scores.get(field), field) is not None for field in SCORE_FIELDS)


def option_entry_score_coverage(
    *,
    paper_ledger: dict[str, Any] | None = None,
    shadow_ledger: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Count score preservation on current paper/shadow option entries."""
    paper = paper_ledger if paper_ledger is not None else (load_json_file(PAPER_EXECUTION_LEDGER_FILE) or {})
    shadow = shadow_ledger if shadow_ledger is not None else (load_json_file(SHADOW_EVIDENCE_FILE) or {})
    total = 0
    scored = 0
    open_total = 0
    open_scored = 0
    closed_total = 0
    closed_scored = 0
    for payload in (paper, shadow):
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            total += 1
            scored_entry = has_entry_score(item)
            if scored_entry:
                scored += 1
            status = text((item.get("outcome") or {}).get("status")).lower()
            if status == "open":
                open_total += 1
                if scored_entry:
                    open_scored += 1
            if status == "closed":
                closed_total += 1
                if scored_entry:
                    closed_scored += 1
    return {
        "optionEntryRecords": total,
        "optionEntryScoreRows": scored,
        "openOptionEntryRecords": open_total,
        "openOptionEntryScoreRows": open_scored,
        "closedOptionEntryRecords": closed_total,
        "closedOptionEntryScoreRows": closed_scored,
    }


def bucket_summary(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    """Summarize observed outcomes by score bucket for one field."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    bucket_meta: dict[str, dict[str, Any]] = {}
    # Empirical rank groups retain native priority units and never split ties.
    values = sorted(score_value(row.get(field), field) for row in rows
                    if score_value(row.get(field), field) is not None)
    for row in rows:
        value = score_value(row.get(field), field)
        if field == "priorityScore" and value is not None:
            order = min(3, 4 * bisect_left(values, value) // len(values))
            bucket = {"bucket": f"rank-Q{order + 1}", "order": order, "scoreMidpoint": None}
        else:
            bucket = score_bucket(row.get(field))
        if not bucket:
            continue
        groups[bucket["bucket"]].append(row)
        bucket_meta[bucket["bucket"]] = bucket

    summaries: list[dict[str, Any]] = []
    for label, bucket_rows in groups.items():
        total = len(bucket_rows)
        favorable = sum(1 for row in bucket_rows if row.get("resultClass") == "favorable")
        neutral = sum(1 for row in bucket_rows if row.get("resultClass") == "neutral")
        unfavorable = sum(1 for row in bucket_rows if row.get("resultClass") == "unfavorable")
        scores = [number(row.get(field), 0.0) or 0.0 for row in bucket_rows]
        obs_scores = [
            number(row.get("observationScore"))
            for row in bucket_rows
            if number(row.get("observationScore")) is not None
        ]
        returns = [
            number(row.get("underlyingReturnPct"))
            for row in bucket_rows
            if number(row.get("underlyingReturnPct")) is not None
        ]
        abs_moves = [
            number(row.get("absUnderlyingMovePct"))
            for row in bucket_rows
            if number(row.get("absUnderlyingMovePct")) is not None
        ]
        r_values = [number(row.get("r")) for row in bucket_rows if number(row.get("r")) is not None]
        midpoint = bucket_meta[label]["scoreMidpoint"]
        favorable_rate = rate(favorable, total)
        # Retain legacy keys as null for consumers, without implying probability calibration.
        gap = None
        summaries.append(
            {
                "bucket": label,
                "order": bucket_meta[label]["order"],
                "scoreMidpoint": midpoint,
                "sampleCount": total,
                "scoreMean": mean(scores),
                "scoreMin": min(scores),
                "scoreMax": max(scores),
                "favorableCount": favorable,
                "neutralCount": neutral,
                "unfavorableCount": unfavorable,
                "favorableRate": favorable_rate,
                "neutralRate": rate(neutral, total),
                "unfavorableRate": rate(unfavorable, total),
                "favorableGapVsScoreMidpoint": gap,
                "meanObservationScore": mean([value for value in obs_scores if value is not None]),
                "meanUnderlyingReturnPct": mean([value for value in returns if value is not None]),
                "meanAbsUnderlyingMovePct": mean([value for value in abs_moves if value is not None]),
                "meanR": mean([value for value in r_values if value is not None]),
                "tickers": sorted({text(row.get("ticker")).upper() for row in bucket_rows if text(row.get("ticker"))})[:10],
            }
        )
    return sorted(summaries, key=lambda item: item["order"])


def monotonic_violations(buckets: list[dict[str, Any]], *, metric: str = "favorableRate") -> list[dict[str, Any]]:
    """Find descriptive rank inversions; these are not significance tests."""
    useful = [
        item
        for item in buckets
        if item.get("sampleCount", 0) >= MIN_MONOTONIC_BUCKET_SAMPLE
        and item.get(metric) is not None
    ]
    violations: list[dict[str, Any]] = []
    for lower, higher in zip(useful, useful[1:]):
        if higher[metric] < lower[metric]:
            violations.append(
                {
                    "lowerBucket": lower["bucket"],
                    "higherBucket": higher["bucket"],
                    "lowerFavorableRate": lower["favorableRate"],
                    "higherFavorableRate": higher["favorableRate"],
                    "metric": metric,
                    "lowerValue": lower[metric],
                    "higherValue": higher[metric],
                    "gap": round(lower[metric] - higher[metric], 4),
                }
            )
    return violations


def calibration_table(rows: list[dict[str, Any]], field: str, *, lane: str) -> dict[str, Any]:
    """Build one calibration table for a score field."""
    score_rows = [row for row in rows if score_value(row.get(field), field) is not None]
    buckets = bucket_summary(score_rows, field)
    total = len(score_rows)
    weighted_gap = None
    metric = "meanR" if any(row.get("r") is not None for row in score_rows) else "favorableRate"
    violations = monotonic_violations(buckets, metric=metric)
    if total < MIN_CALIBRATION_SAMPLE:
        verdict = "insufficient-data"
    elif len(buckets) < 2:
        verdict = "single-bucket-watch"
    elif violations:
        verdict = "calibration-watch"
    else:
        verdict = "calibration-building"
    return {
        "lane": lane,
        "field": field,
        "interpretation": "descriptive-rank-diagnostic-not-probability-calibration",
        "bucketMethod": "empirical-rank-quartiles-ties-preserved" if field == "priorityScore" else "fixed-score-bands",
        "outcomeMetric": metric,
        "sampleCount": total,
        "bucketCount": len(buckets),
        "weightedAbsCalibrationGap": weighted_gap,
        "monotonicViolations": violations,
        "verdict": verdict,
        "buckets": buckets,
    }


def overall_verdict(tables: list[dict[str, Any]]) -> str:
    """Collapse table-level diagnostics into one visible desk verdict."""
    useful = [table for table in tables if table.get("sampleCount", 0) >= MIN_CALIBRATION_SAMPLE]
    if not useful:
        return "insufficient-data"
    if any(table.get("verdict") in {"calibration-watch", "single-bucket-watch"} for table in useful):
        return "calibration-watch"
    return "calibration-building"


def shadow_timing_status(row: dict[str, Any]) -> str:
    """Flag definitely premature intrinsic outcomes, without guessing a close.

    A review before expiration-day regular open cannot observe that session's
    expiration payoff. Later reviews remain unverified without a timestamped
    settlement price. This deliberately avoids holiday/early-close assumptions.
    """
    if row.get("source") != "shadow":
        return "not-shadow"
    try:
        expiration = date.fromisoformat(text(row.get("expiration")))
        reviewed = datetime.fromisoformat(text(row.get("reviewedAt")).replace("Z", "+00:00"))
        if reviewed.tzinfo is None:
            return "unverified-settlement-time"
        eastern = reviewed.astimezone(ZoneInfo("America/New_York"))
        if eastern.date() < expiration or (eastern.date() == expiration and eastern.time() < time(9, 30)):
            return "closed-before-expiration-session"
        proof = row.get("expirationPriceEvidence") or {}
        captured = datetime.fromisoformat(text(proof.get("sourceGeneratedAt")).replace("Z", "+00:00"))
        if (proof.get("source") == "schwab-daily-expiration-close-intrinsic-proxy"
                and proof.get("priceDate") == expiration.isoformat()
                and (number(proof.get("price")) or 0) > 0
                and captured.tzinfo is not None
                and captured <= reviewed
                and captured.astimezone(ZoneInfo("America/New_York")).date() > expiration):
            return "expiration-close-proxy-recorded"
    except (TypeError, ValueError):
        pass
    return "unverified-settlement-time"


def evidence_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Expose source, score provenance and repeated exposure denominators.

    Ticker/expiration is an exposure proxy, not an independent earnings event.
    No statistical confidence or model-fit eligibility is inferred from it.
    """
    groups: Counter[tuple[str, str, str]] = Counter()
    missing = 0
    for row in rows:
        ticker = text(row.get("ticker"))
        boundary = text(row.get("expiration"))
        if ticker and boundary:
            groups[(text(row.get("source")), ticker, boundary)] += 1
        else:
            missing += 1
    return {
        "sourceRows": dict(sorted(Counter(text(row.get("source")) for row in rows).items())),
        "scoreProvenanceRows": dict(sorted(Counter(text(row.get("scoreProvenance")) for row in rows).items())),
        "shadowTimingRows": dict(sorted(Counter(shadow_timing_status(row) for row in rows if row.get("source") == "shadow").items())),
        "exposureGroupKey": "source+ticker+expiration; proxy only, not independent events",
        "exposureGroups": len(groups),
        "repeatedExposureRows": sum(count - 1 for count in groups.values()),
        "rowsWithoutExposureKey": missing,
        "largestExposureGroup": max(groups.values(), default=0),
        "modelFitAllowed": False,
        "reason": "Descriptive archive only: legacy score provenance, settlement-price lineage and independent temporal validation remain unresolved.",
    }


def build_score_calibration(
    *,
    scenario_evidence: dict[str, Any] | None = None,
    paper_ledger: dict[str, Any] | None = None,
    shadow_ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the research-only score calibration payload."""
    ensure_dirs()
    # Read each input once so counts and tables refer to the same evidence snapshot.
    scenario_evidence = scenario_evidence if scenario_evidence is not None else (load_json_file(SCENARIO_EVIDENCE_FILE) or {})
    paper_ledger = paper_ledger if paper_ledger is not None else (load_json_file(PAPER_EXECUTION_LEDGER_FILE) or {})
    shadow_ledger = shadow_ledger if shadow_ledger is not None else (load_json_file(SHADOW_EVIDENCE_FILE) or {})
    scenario_rows = scenario_observation_rows(scenario_evidence)
    option_rows = option_score_rows(paper_ledger=paper_ledger, shadow_ledger=shadow_ledger)
    entry_coverage = option_entry_score_coverage(paper_ledger=paper_ledger, shadow_ledger=shadow_ledger)
    scenario_tables = [
        calibration_table(scenario_rows, field, lane="scenario-observations")
        for field in SCORE_FIELDS
    ]
    option_tables = [
        calibration_table(option_rows, field, lane="paper-shadow-options")
        for field in SCORE_FIELDS
    ]
    source_tables = [
        calibration_table([row for row in option_rows if row["source"] == source], field, lane=f"{source}-options")
        for source in ("paper", "shadow") for field in SCORE_FIELDS
    ]
    diagnostics = evidence_diagnostics(option_rows)
    scenario_provenance = Counter(row["scoreProvenance"] for row in scenario_rows)
    tables = scenario_tables + option_tables
    return {
        "generatedAt": local_now().isoformat(),
        "stage": SCORE_CALIBRATION_STAGE,
        "verdict": overall_verdict(scenario_tables + source_tables),
        "researchOnly": True,
        "diagnosticOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "counts": {
            "closedScenarioObservations": len(scenario_rows),
            "closedOptionRecords": len(option_rows),
            "scenarioScoreRows": sum(1 for row in scenario_rows if row.get("scenarioScore") is not None),
            "readinessRows": sum(1 for row in scenario_rows if row.get("readiness") is not None),
            "optionScoreRows": sum(
                1
                for row in option_rows
                if any(row.get(field) is not None for field in SCORE_FIELDS)
            ),
            **entry_coverage,
            "tables": len(tables) + len(source_tables),
        },
        "scenarioCalibration": scenario_tables,
        "optionCalibration": option_tables,
        "optionCalibrationBySource": source_tables,
        "evidenceDiagnostics": diagnostics,
        "scenarioScoreProvenance": dict(sorted(scenario_provenance.items())),
        "sourceGeneratedAt": {
            "scenario": scenario_evidence.get("updatedAt") or scenario_evidence.get("generatedAt"),
            "paper": paper_ledger.get("updatedAt") or paper_ledger.get("generatedAt"),
            "shadow": shadow_ledger.get("updatedAt") or shadow_ledger.get("generatedAt"),
        },
        "reminders": [
            "Scores are ranking surfaces, not posterior probabilities.",
            "No probability-gap metric is computed; priorityScore uses native-value rank quartiles with ties preserved.",
            "Pooled option tables are legacy archive views. Paper and shadow source tables must be read separately.",
            "Counts are rows, not independent events; ticker/expiration groups describe repeated exposure only.",
            "Entry-frozen scores prevent refresh leakage going forward; legacy scores remain unverified.",
            "Shadow payoff timing and settlement-price lineage must be repaired before fitting a challenger model.",
            "This artifact cannot promote strategies, create orders, or relax live-trading gates.",
        ],
    }


def pct(value: Any) -> str:
    """Render a decimal rate as a compact percentage."""
    parsed = number(value)
    if parsed is None:
        return "n/a"
    return f"{parsed * 100:.1f}%"


def fmt(value: Any) -> str:
    """Render optional numeric values without noise."""
    parsed = number(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:.4g}"


def score_calibration_text(payload: dict[str, Any]) -> str:
    """Render the score calibration report."""
    counts = payload.get("counts") or {}
    lines = [
        "Inferno Score Calibration Lab",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Verdict: {payload.get('verdict')}",
        "Authority: research-only; promotable=False; liveTradingAllowed=False",
        "",
        "Counts:",
        f"- closed scenario observations: {counts.get('closedScenarioObservations', 0)}",
        f"- closed paper/shadow option records: {counts.get('closedOptionRecords', 0)}",
        f"- scenario score rows: {counts.get('scenarioScoreRows', 0)}",
        f"- readiness rows: {counts.get('readinessRows', 0)}",
        f"- option rows carrying scores: {counts.get('optionScoreRows', 0)}",
        (
            "- current option entries carrying scores: "
            f"{counts.get('optionEntryScoreRows', 0)} / {counts.get('optionEntryRecords', 0)} "
            f"(open {counts.get('openOptionEntryScoreRows', 0)} / {counts.get('openOptionEntryRecords', 0)})"
        ),
        "",
        "Scenario observation calibration:",
    ]
    for table in payload.get("scenarioCalibration") or []:
        lines.append(
            f"- {table.get('field')}: {table.get('verdict')} | "
            f"n={table.get('sampleCount')} | buckets={table.get('bucketCount')}"
        )
        if table.get("monotonicViolations"):
            lines.append(f"  monotonic violations: {len(table.get('monotonicViolations') or [])}")
        for bucket in table.get("buckets") or []:
            lines.append(
                "  "
                f"{bucket.get('bucket')}: n={bucket.get('sampleCount')} | "
                f"fav={pct(bucket.get('favorableRate'))} | "
                f"neutral={pct(bucket.get('neutralRate'))} | "
                f"unfav={pct(bucket.get('unfavorableRate'))} | "
                f"mean obs={fmt(bucket.get('meanObservationScore'))} | "
                f"mean abs move={fmt(bucket.get('meanAbsUnderlyingMovePct'))}% | "
                f"tickers={', '.join(bucket.get('tickers') or []) or 'none'}"
            )
    lines.extend(["", "Paper/shadow option score calibration (separate sources; raw archive rows):"])
    for table in payload.get("optionCalibrationBySource") or payload.get("optionCalibration") or []:
        if not table.get("sampleCount"):
            continue
        lines.append(
            f"- {table.get('lane')} / {table.get('field')}: {table.get('verdict')} | "
            f"n={table.get('sampleCount')} | buckets={table.get('bucketCount')}"
        )
        for bucket in table.get("buckets") or []:
            lines.append(
                "  "
                f"{bucket.get('bucket')}: n={bucket.get('sampleCount')} | "
                f"fav={pct(bucket.get('favorableRate'))} | mean R={fmt(bucket.get('meanR'))}"
            )
    if not any(table.get("sampleCount") for table in payload.get("optionCalibration") or []):
        lines.append("- no closed option records currently carry score fields")
    diagnostics = payload.get("evidenceDiagnostics") or {}
    lines.extend([
        "", "Evidence integrity (required before model fitting):",
        f"- option sources: {json.dumps(diagnostics.get('sourceRows', {}), sort_keys=True)}",
        f"- option score provenance: {json.dumps(diagnostics.get('scoreProvenanceRows', {}), sort_keys=True)}",
        f"- scenario score provenance: {json.dumps(payload.get('scenarioScoreProvenance', {}), sort_keys=True)}",
        f"- shadow timing: {json.dumps(diagnostics.get('shadowTimingRows', {}), sort_keys=True)}",
        f"- source/ticker/expiration exposure groups: {diagnostics.get('exposureGroups', 0)}; repeated rows: {diagnostics.get('repeatedExposureRows', 0)}; missing keys: {diagnostics.get('rowsWithoutExposureKey', 0)}",
        f"- model fitting allowed: {diagnostics.get('modelFitAllowed', False)}; {diagnostics.get('reason', 'unverified')}",
    ])
    lines.extend(["", "Reminders:"])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_score_calibration(payload: dict[str, Any]) -> None:
    """Persist the score calibration JSON and text artifacts."""
    ensure_dirs()
    atomic_write_json(SCORE_CALIBRATION_FILE, payload)
    atomic_write_text(SCORE_CALIBRATION_TEXT_FILE, score_calibration_text(payload))


def parse_args() -> argparse.Namespace:
    """Parse the score calibration CLI."""
    parser = argparse.ArgumentParser(description="Build Inferno score calibration diagnostics.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    """Run the score calibration CLI."""
    args = parse_args()
    if args.command == "status" and SCORE_CALIBRATION_TEXT_FILE.exists():
        print(SCORE_CALIBRATION_TEXT_FILE.read_text(encoding="utf-8"))
        latest = json.loads(SCORE_CALIBRATION_FILE.read_text(encoding="utf-8")) if SCORE_CALIBRATION_FILE.exists() else {}
        return 0 if latest.get("promotable") is False else 1
    payload = build_score_calibration()
    save_score_calibration(payload)
    print(score_calibration_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
