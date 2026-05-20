from __future__ import annotations

"""Scenario observation ledger for the paper evidence bottleneck.

The paper execution ledger measures real simulated fills. The shadow evidence
ledger measures hypothetical option tickets. This module is deliberately one
step lighter: it records the daily paper bottleneck reducer slate as
underlying-price observations so the desk can learn which setups move without
pretending those observations were tradable fills.

Nothing in this file can approve, stage, submit, or promote a trade. It is a
research-only memory layer for "what happened after we cared about this name?"
"""

import argparse
import os
from collections import Counter
from datetime import date, datetime
from typing import Any, Callable

import pandas as pd

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_outcome_reviewer import latest_underlying_price
from inferno_paper_bottleneck_reducer import PAPER_BOTTLENECK_REDUCER_FILE
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


SCENARIO_EVIDENCE_FILE = DATA_DIR / "inferno_scenario_evidence.json"
SCENARIO_EVIDENCE_TEXT_FILE = REPORTS_DIR / "scenario_evidence_latest.txt"
SCENARIO_EVIDENCE_STAGE = "scenario-evidence-research-only"

SCENARIO_EVIDENCE_VERSION = 1
DEFAULT_REVIEW_HORIZON_DAYS = int(os.environ.get("INFERNO_SCENARIO_EVIDENCE_REVIEW_DAYS", "1"))
CALL_MOVE_THRESHOLD_PCT = float(os.environ.get("INFERNO_SCENARIO_CALL_MOVE_THRESHOLD_PCT", "1.0"))
STRADDLE_MOVE_THRESHOLD_PCT = float(os.environ.get("INFERNO_SCENARIO_STRADDLE_MOVE_THRESHOLD_PCT", "2.0"))
CONDOR_STABILITY_THRESHOLD_PCT = float(os.environ.get("INFERNO_SCENARIO_CONDOR_STABILITY_THRESHOLD_PCT", "1.0"))
CONDOR_BREAK_THRESHOLD_PCT = float(os.environ.get("INFERNO_SCENARIO_CONDOR_BREAK_THRESHOLD_PCT", "3.0"))

PriceLookup = Callable[[str], float | None]


def text(value: Any) -> str:
    """Normalize loose artifact values to stripped strings."""
    return str(value or "").strip()


def norm(value: Any) -> str:
    """Normalize tickers and strategy names for stable matching."""
    return text(value).upper()


def number(value: Any, default: float | None = None) -> float | None:
    """Coerce display values into floats while tolerating blanks."""
    cleaned = text(value).replace("$", "").replace(",", "").replace("%", "")
    try:
        return float(cleaned)
    except ValueError:
        return default


def parse_date(value: Any) -> date | None:
    """Parse a date-like value into a local calendar date."""
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def now_date(now: datetime | None = None) -> date:
    """Return the date used for deterministic tests and production runs."""
    return (now or local_now()).date()


def strategy_family(value: Any) -> str:
    """Collapse strategy/setup text into broad families for observation scoring."""
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
    """Bucket days-to-earnings so observations match the scenario backtest."""
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


def load_scenario_evidence() -> dict[str, Any]:
    """Load the scenario evidence ledger with a safe empty fallback."""
    ledger = load_json_file(SCENARIO_EVIDENCE_FILE)
    if ledger and isinstance(ledger.get("observations"), list):
        return ledger
    return {
        "version": SCENARIO_EVIDENCE_VERSION,
        "generatedAt": None,
        "updatedAt": None,
        "stage": SCENARIO_EVIDENCE_STAGE,
        "observations": [],
    }


def observation_key(scenario: dict[str, Any], *, now: datetime | None = None) -> str:
    """Return a stable daily key for one scenario observation."""
    scenario_id = text(scenario.get("scenarioId"))
    if scenario_id:
        return scenario_id
    ticker = norm(scenario.get("ticker"))
    lane = text(scenario.get("evidenceLane") or scenario.get("sourceLane") or "scenario")
    return f"{now_date(now).isoformat()}:{ticker}:{lane}"


def cached_price_lookup(price_lookup: PriceLookup) -> PriceLookup:
    """Wrap a price lookup so one build never fetches the same ticker twice."""
    cache: dict[str, float | None] = {}

    def lookup(ticker: str) -> float | None:
        symbol = norm(ticker)
        if symbol not in cache:
            cache[symbol] = price_lookup(symbol)
        return cache[symbol]

    return lookup


def baseline_price_from_scenario(
    scenario: dict[str, Any],
    *,
    price_lookup: PriceLookup,
) -> tuple[float | None, str]:
    """Find the best baseline price for an observation.

    The reducer can carry prices from different upstream artifacts. If no
    artifact price exists, we fetch the latest underlying price once and mark
    the source so later reviews know how the baseline was born.
    """
    context = scenario.get("marketContextSummary") or {}
    for field in (
        scenario.get("underlyingPrice"),
        scenario.get("price"),
        context.get("price"),
        context.get("last"),
        context.get("mark"),
    ):
        value = number(field)
        if value and value > 0:
            return round(value, 4), "scenario-artifact"

    ticker = norm(scenario.get("ticker"))
    if not ticker:
        return None, "missing-ticker"
    fetched = price_lookup(ticker)
    if fetched and fetched > 0:
        return round(float(fetched), 4), "price-lookup"
    return None, "price-unavailable"


def build_observation_from_scenario(
    scenario: dict[str, Any],
    *,
    price_lookup: PriceLookup,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create one research-only observation from a reducer scenario."""
    timestamp = (now or local_now()).isoformat()
    baseline_price, baseline_source = baseline_price_from_scenario(scenario, price_lookup=price_lookup)
    strategy = scenario.get("strategy") or scenario.get("setupRec")
    family = strategy_family(strategy)
    return {
        "observationId": observation_key(scenario, now=now),
        "scenarioId": text(scenario.get("scenarioId")) or observation_key(scenario, now=now),
        "ticker": norm(scenario.get("ticker")),
        "tradeDate": now_date(now).isoformat(),
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "source": "paper-bottleneck-reducer",
        "sourceLane": scenario.get("sourceLane"),
        "evidenceLane": scenario.get("evidenceLane"),
        "rank": scenario.get("rank"),
        "strategy": text(strategy),
        "setupRec": text(scenario.get("setupRec")),
        "family": family,
        "dteBucket": dte_bucket(scenario.get("daysUntilEarnings")),
        "daysUntilEarnings": scenario.get("daysUntilEarnings"),
        "scenarioScore": scenario.get("scenarioScore"),
        "readiness": scenario.get("readiness"),
        "confidence": scenario.get("confidence"),
        "baselineUnderlyingPrice": baseline_price,
        "baselinePriceSource": baseline_source,
        "reviewHorizonDays": DEFAULT_REVIEW_HORIZON_DAYS,
        "status": "open" if baseline_price else "price-missing",
        "outcome": {
            "status": "open" if baseline_price else "price-missing",
            "notes": "scenario observation; not a paper fill or broker ticket",
        },
        "safety": {
            "researchOnly": True,
            "diagnosticOnly": True,
            "promotable": False,
            "paperOnly": True,
            "liveTradingAllowed": False,
            "brokerSubmitAllowed": False,
            "authorityEligible": False,
        },
    }


def merge_observation(existing: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    """Refresh scenario metadata while preserving baseline and outcome history."""
    return {
        **existing,
        "rank": scenario.get("rank", existing.get("rank")),
        "sourceLane": scenario.get("sourceLane", existing.get("sourceLane")),
        "evidenceLane": scenario.get("evidenceLane", existing.get("evidenceLane")),
        "scenarioScore": scenario.get("scenarioScore", existing.get("scenarioScore")),
        "readiness": scenario.get("readiness", existing.get("readiness")),
        "confidence": scenario.get("confidence", existing.get("confidence")),
        "updatedAt": local_now().isoformat(),
    }


def observation_days_open(observation: dict[str, Any], *, now: datetime | None = None) -> int:
    """Return calendar days since the observation was created."""
    trade_date = parse_date(observation.get("tradeDate"))
    if not trade_date:
        return 0
    return max(0, (now_date(now) - trade_date).days)


def classify_move(family: str, return_pct: float) -> tuple[str, float, str]:
    """Classify an underlying move for the strategy family being observed.

    This is not option P/L. It is a proxy for whether the underlying moved in
    the direction the setup would generally want before real fill evidence is
    available.
    """
    family = norm(family)
    if family == "PUT_VERTICAL":
        score = -return_pct
        if score >= CALL_MOVE_THRESHOLD_PCT:
            return "favorable", round(score, 4), "put bias got downside movement"
        if score <= -CALL_MOVE_THRESHOLD_PCT:
            return "unfavorable", round(score, 4), "put bias fought upside movement"
        return "neutral", round(score, 4), "put bias move was too small to count"

    if family in {"CALL_VERTICAL", "VERTICAL"}:
        score = return_pct
        if score >= CALL_MOVE_THRESHOLD_PCT:
            return "favorable", round(score, 4), "call bias got upside movement"
        if score <= -CALL_MOVE_THRESHOLD_PCT:
            return "unfavorable", round(score, 4), "call bias fought downside movement"
        return "neutral", round(score, 4), "call bias move was too small to count"

    if family == "STRADDLE":
        score = abs(return_pct)
        if score >= STRADDLE_MOVE_THRESHOLD_PCT:
            return "favorable", round(score, 4), "straddle got enough movement"
        if score <= CONDOR_STABILITY_THRESHOLD_PCT:
            return "unfavorable", round(score, 4), "straddle stayed too quiet"
        return "neutral", round(score, 4), "straddle move was meaningful but not decisive"

    if family == "IRON_CONDOR":
        move = abs(return_pct)
        score = CONDOR_STABILITY_THRESHOLD_PCT - move
        if move <= CONDOR_STABILITY_THRESHOLD_PCT:
            return "favorable", round(score, 4), "condor got stable movement"
        if move >= CONDOR_BREAK_THRESHOLD_PCT:
            return "unfavorable", round(score, 4), "condor saw too much movement"
        return "neutral", round(score, 4), "condor move was not clean enough either way"

    score = return_pct
    if score >= CALL_MOVE_THRESHOLD_PCT:
        return "favorable", round(score, 4), "generic upside observation"
    if score <= -CALL_MOVE_THRESHOLD_PCT:
        return "unfavorable", round(score, 4), "generic downside observation"
    return "neutral", round(score, 4), "generic move was too small to count"


def review_observation(
    observation: dict[str, Any],
    *,
    price_lookup: PriceLookup,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Update or close one observation when its review horizon has elapsed."""
    outcome = observation.get("outcome") or {}
    if outcome.get("status") == "closed":
        return observation

    ticker = norm(observation.get("ticker"))
    timestamp = (now or local_now()).isoformat()
    baseline = number(observation.get("baselineUnderlyingPrice"))
    if not baseline or baseline <= 0:
        baseline, source = baseline_price_from_scenario(observation, price_lookup=price_lookup)
        if not baseline:
            return {
                **observation,
                "updatedAt": timestamp,
                "status": "price-missing",
                "baselinePriceSource": source,
                "outcome": {
                    **outcome,
                    "status": "price-missing",
                    "reviewedAt": timestamp,
                    "notes": "could not establish baseline underlying price",
                },
            }
        observation = {
            **observation,
            "baselineUnderlyingPrice": baseline,
            "baselinePriceSource": source,
            "status": "open",
        }

    current = price_lookup(ticker) if ticker else None
    if not current or current <= 0:
        return {
            **observation,
            "updatedAt": timestamp,
            "outcome": {
                **outcome,
                "status": "open",
                "reviewedAt": timestamp,
                "notes": "latest underlying price unavailable; observation remains open",
            },
        }

    return_pct = round(((float(current) - float(baseline)) / float(baseline)) * 100.0, 4)
    result_class, observation_score, note = classify_move(text(observation.get("family")), return_pct)
    days_open = observation_days_open(observation, now=now)
    review_horizon = int(number(observation.get("reviewHorizonDays"), DEFAULT_REVIEW_HORIZON_DAYS) or 1)
    status = "closed" if days_open >= review_horizon else "open"

    return {
        **observation,
        "updatedAt": timestamp,
        "status": status,
        "currentUnderlyingPrice": round(float(current), 4),
        "currentUnderlyingReturnPct": return_pct,
        "daysOpen": days_open,
        "outcome": {
            **outcome,
            "status": status,
            "reviewedAt": timestamp,
            "exitUnderlyingPrice": round(float(current), 4) if status == "closed" else None,
            "currentUnderlyingPrice": round(float(current), 4),
            "underlyingReturnPct": return_pct,
            "observationScore": observation_score,
            "resultClass": result_class if status == "closed" else None,
            "currentResultClass": result_class,
            "notes": note,
        },
    }


def build_scenario_evidence(
    *,
    reducer: dict[str, Any] | None = None,
    ledger: dict[str, Any] | None = None,
    price_lookup: PriceLookup = latest_underlying_price,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the scenario observation ledger from the latest reducer slate."""
    reducer = reducer if reducer is not None else (load_json_file(PAPER_BOTTLENECK_REDUCER_FILE) or {})
    ledger = ledger if ledger is not None else load_scenario_evidence()
    lookup = cached_price_lookup(price_lookup)
    timestamp = (now or local_now()).isoformat()

    observations_by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for observation in ledger.get("observations") or []:
        if not isinstance(observation, dict):
            continue
        key = text(observation.get("observationId"))
        if not key:
            continue
        observations_by_id[key] = observation
        order.append(key)

    added = 0
    refreshed = 0
    for scenario in reducer.get("scenarioSlate") or []:
        if not isinstance(scenario, dict):
            continue
        key = observation_key(scenario, now=now)
        if key in observations_by_id:
            observations_by_id[key] = merge_observation(observations_by_id[key], scenario)
            refreshed += 1
            continue
        observations_by_id[key] = build_observation_from_scenario(scenario, price_lookup=lookup, now=now)
        order.append(key)
        added += 1

    reviewed_items = [
        review_observation(observations_by_id[key], price_lookup=lookup, now=now)
        for key in order
        if key in observations_by_id
    ]
    counts = observation_counts(reviewed_items)
    return {
        "version": SCENARIO_EVIDENCE_VERSION,
        "generatedAt": timestamp,
        "updatedAt": timestamp,
        "stage": SCENARIO_EVIDENCE_STAGE,
        "researchOnly": True,
        "diagnosticOnly": True,
        "promotable": False,
        "paperOnly": True,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "sourceReducerGeneratedAt": reducer.get("generatedAt"),
        "sourceScenarioCount": len(reducer.get("scenarioSlate") or []),
        "addedObservations": added,
        "refreshedObservations": refreshed,
        "counts": counts,
        "observations": reviewed_items,
        "rules": [
            "Scenario observations are not fills, orders, approvals, or option P/L.",
            "They measure whether the underlying moved in the direction a setup wanted.",
            "Only paper and shadow option ledgers can feed option evidence verdicts.",
            "This artifact can inform research, but it cannot promote broker authority.",
        ],
    }


def observation_counts(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize observation states and result classes."""
    status_counts = Counter(text((item.get("outcome") or {}).get("status") or item.get("status")) for item in observations)
    result_counts = Counter(
        text((item.get("outcome") or {}).get("resultClass"))
        for item in observations
        if text((item.get("outcome") or {}).get("status") or item.get("status")) == "closed"
    )
    result_counts.pop("", None)
    return {
        "observations": len(observations),
        "open": status_counts.get("open", 0),
        "closed": status_counts.get("closed", 0),
        "priceMissing": status_counts.get("price-missing", 0),
        "statusCounts": dict(sorted(status_counts.items())),
        "resultCounts": dict(sorted(result_counts.items())),
    }


def scenario_evidence_text(payload: dict[str, Any]) -> str:
    """Render the scenario evidence ledger into a concise desk memo."""
    counts = payload.get("counts") or {}
    lines = [
        "Inferno Scenario Evidence (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Source scenarios: {payload.get('sourceScenarioCount', 0)}",
        f"Observations: {counts.get('observations', 0)}",
        f"Open: {counts.get('open', 0)}",
        f"Closed: {counts.get('closed', 0)}",
        f"Price missing: {counts.get('priceMissing', 0)}",
        f"Promotable from this artifact: {payload.get('promotable')}",
        "",
        "Closed result mix:",
    ]
    result_counts = counts.get("resultCounts") or {}
    if result_counts:
        for result, count in result_counts.items():
            lines.append(f"- {result}: {count}")
    else:
        lines.append("- none yet")

    lines.extend(["", "Latest observations:"])
    for item in (payload.get("observations") or [])[-10:]:
        outcome = item.get("outcome") or {}
        result = outcome.get("resultClass") or outcome.get("currentResultClass") or "pending"
        lines.append(
            f"- {item.get('ticker')} | {item.get('family')} | {outcome.get('status')} | "
            f"move={outcome.get('underlyingReturnPct')}% | current={result} | "
            f"{outcome.get('notes')}"
        )

    lines.extend(["", "Rules:"])
    for rule in payload.get("rules") or []:
        lines.append(f"- {rule}")
    return "\n".join(lines).rstrip() + "\n"


def save_scenario_evidence(payload: dict[str, Any]) -> None:
    """Persist the scenario evidence JSON and text report."""
    ensure_dirs()
    atomic_write_json(SCENARIO_EVIDENCE_FILE, payload)
    atomic_write_text(SCENARIO_EVIDENCE_TEXT_FILE, scenario_evidence_text(payload))


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for build/status commands."""
    parser = argparse.ArgumentParser(description="Build the research-only scenario observation ledger.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    if args.command == "status" and SCENARIO_EVIDENCE_TEXT_FILE.exists():
        print(SCENARIO_EVIDENCE_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_scenario_evidence()
    save_scenario_evidence(payload)
    print(scenario_evidence_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
