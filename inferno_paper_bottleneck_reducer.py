from __future__ import annotations

"""Paper bottleneck reducer for high-throughput evidence collection.

The paper-test director answers one strict question: "What can be staged in
paperMoney without weakening risk gates?" That is intentionally conservative.
This reducer answers a different question: "What should the desk track today
so we can learn faster?"

It builds a daily scenario slate with a target of 12 paper/shadow scenarios and
a top-five focus list. Executable paper candidates keep their original safety
classification. Everything else is explicitly marked shadow-only, non-broker,
and non-authority-eligible. That lets the desk gather evidence aggressively
without confusing research scenarios with tradable orders.
"""

import argparse
import csv
import json
import os
from io import StringIO
from typing import Any, Callable

from inferno_config import MAX_SINGLE_TICKET_DOLLARS, local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, SNAPSHOT_FILE, ensure_dirs, load_json_file


PAPER_BOTTLENECK_REDUCER_FILE = DATA_DIR / "inferno_paper_bottleneck_reducer.json"
PAPER_BOTTLENECK_REDUCER_TEXT_FILE = REPORTS_DIR / "paper_bottleneck_reducer_latest.txt"
PAPER_BOTTLENECK_REDUCER_CSV_FILE = REPORTS_DIR / "paper_bottleneck_reducer_latest.csv"
PAPER_TEST_DIRECTOR_FILE = DATA_DIR / "inferno_paper_test_director.json"

DEFAULT_SCENARIO_TARGET = int(os.environ.get("INFERNO_PBR_SCENARIO_TARGET", "12"))
MAX_SCENARIO_LIMIT = int(os.environ.get("INFERNO_PBR_MAX_SCENARIOS", "20"))
TOP_FOCUS_COUNT = 5


def float_value(value: Any, default: float = 0.0) -> float:
    """Coerce loose JSON values into floats without throwing."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def int_value(value: Any, default: int = 0) -> int:
    """Coerce loose JSON values into integers without throwing."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def scenario_rank_score(candidate: dict[str, Any]) -> float:
    """Return the ranking score used for today's evidence slate.

    The score intentionally blends desk priority with learnability. We still
    favor high-readiness names, but we give some lift to cheap tickets and
    nearer earnings because those produce faster paper evidence.
    """
    priority = float_value(candidate.get("priorityScore") or candidate.get("priority"))
    readiness = float_value(candidate.get("readiness"))
    max_loss = float_value(candidate.get("estimatedMaxLoss"), MAX_SINGLE_TICKET_DOLLARS)
    dte = int_value(candidate.get("daysUntilEarnings"), 99)
    confidence = float_value(candidate.get("confidence"))

    cost_bonus = max(0.0, 1.0 - min(max_loss, MAX_SINGLE_TICKET_DOLLARS * 2) / (MAX_SINGLE_TICKET_DOLLARS * 2))
    timing_bonus = max(0.0, 1.0 - min(max(dte, 0), 30) / 30.0)
    score = (priority * 0.45) + (readiness * 0.35) + (confidence * 4.0) + (cost_bonus * 8.0) + (timing_bonus * 6.0)
    return round(score, 2)


def normalize_ticker(value: Any) -> str:
    """Return a stable uppercase ticker symbol."""
    return str(value or "").strip().upper()


def snapshot_row_lookup(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index the latest snapshot rows by ticker for price/context enrichment."""
    lookup: dict[str, dict[str, Any]] = {}
    for row in snapshot.get("rows") or []:
        if not isinstance(row, dict):
            continue
        ticker = normalize_ticker(row.get("ticker"))
        if ticker and ticker not in lookup:
            lookup[ticker] = row
    return lookup


def enrich_scenario_from_snapshot(scenario: dict[str, Any], snapshot_row: dict[str, Any] | None) -> dict[str, Any]:
    """Add non-authority market context already present in the latest snapshot."""
    if not snapshot_row:
        return scenario
    price = snapshot_row.get("price")
    if scenario.get("price") is None and price is not None:
        scenario["price"] = price
        scenario["baselineUnderlyingPrice"] = price
        scenario["priceSource"] = "latest_snapshot.rows"
    context = dict(scenario.get("marketContextSummary") or {})
    for key in (
        "rvol",
        "trend",
        "support",
        "resistance",
        "distanceToSupportPct",
        "distanceToResistancePct",
        "atrPercent",
        "ivRank",
    ):
        if context.get(key) is None and snapshot_row.get(key) is not None:
            context[key] = snapshot_row.get(key)
    scenario["marketContextSummary"] = context
    return scenario


def scenario_from_director_candidate(
    candidate: dict[str, Any],
    *,
    lane: str,
    rank_hint: int,
) -> dict[str, Any]:
    """Convert a director candidate into a reducer scenario.

    The original director category remains intact. The reducer only adds
    evidence labels and a clearer "can this be staged?" boundary.
    """
    ticker = normalize_ticker(candidate.get("ticker"))
    category = str(candidate.get("category") or lane)
    auto_paper_selected = category == "auto-paper-selected" or bool(candidate.get("paperAutoSelected"))
    executable = category in {"stageable-now", "auto-paper-selected"}
    approval_needed = category == "approval-only"
    shadow_only = not executable
    max_loss = float_value(candidate.get("estimatedMaxLoss"))
    capital_gap = max(0.0, max_loss - MAX_SINGLE_TICKET_DOLLARS)

    scenario_score = round(scenario_rank_score(candidate) + max(0, 10 - rank_hint) * 0.01, 2)

    scenario = {
        "scenarioId": f"{local_now().date().isoformat()}:{ticker}:{lane}",
        "ticker": ticker,
        "source": "paper-test-director",
        "sourceLane": lane,
        "directorCategory": category,
        "strategy": candidate.get("strategy"),
        "setupRec": candidate.get("setupRec"),
        "readiness": candidate.get("readiness"),
        "confidence": candidate.get("confidence"),
        "daysUntilEarnings": candidate.get("daysUntilEarnings"),
        "price": candidate.get("price"),
        "baselineUnderlyingPrice": candidate.get("baselineUnderlyingPrice") or candidate.get("price"),
        "priceSource": candidate.get("priceSource"),
        "estimatedMaxLoss": candidate.get("estimatedMaxLoss"),
        "capitalGap": round(capital_gap, 2),
        "priorityScore": candidate.get("priorityScore"),
        "scenarioScore": scenario_score,
        "executableInPaperMoney": executable,
        "requiresApproval": approval_needed,
        "shadowOnly": shadow_only,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "authorityEligible": category == "stageable-now" and not auto_paper_selected,
        "paperAutoSelected": auto_paper_selected,
        "evidenceLane": "paper-auto-stage" if auto_paper_selected else ("paper-stage" if executable else "shadow-scenario"),
        "reducerAction": reducer_action_for_candidate(candidate, category, capital_gap),
        "reasons": candidate.get("reasons") or [],
        "warnings": candidate.get("warnings") or [],
        "marketContextSummary": candidate.get("marketContextSummary") or {},
    }
    return scenario


def reducer_action_for_candidate(candidate: dict[str, Any], category: str, capital_gap: float) -> str:
    """Return the safest next action for one scenario."""
    ticker = normalize_ticker(candidate.get("ticker"))
    if candidate.get("paperAutoSelected"):
        return f"Auto-stage/track {ticker} in paperMoney only; no live order authority."
    if category == "stageable-now":
        return f"Stage {ticker} in paperMoney only; record fill immediately."
    if category == "auto-paper-selected":
        return f"Auto-stage/track {ticker} in paperMoney only; no live order authority."
    if category == "approval-only":
        return f"Approve or reject {ticker}; if approved, rebuild strike cycle before staging."
    if capital_gap > 0:
        return (
            f"Do not stage {ticker}; search for a capped variant at or below "
            f"${MAX_SINGLE_TICKET_DOLLARS:.0f} max loss, then re-run risk."
        )
    return f"Track {ticker} as shadow evidence only; do not stage until a clean ticket exists."


def tracker_shadow_candidates(
    snapshot: dict[str, Any],
    *,
    excluded_tickers: set[str],
    needed: int,
) -> list[dict[str, Any]]:
    """Build supplemental tracker-only scenarios when the director slate is thin.

    These rows do not have option legs yet. They are deliberately marked
    shadow-only so the desk can follow outcomes without pretending a broker
    ticket exists.
    """
    rows = [row for row in (snapshot.get("rows") or []) if isinstance(row, dict)]
    ranked: list[dict[str, Any]] = []
    for row in rows:
        ticker = normalize_ticker(row.get("ticker"))
        if not ticker or ticker in excluded_tickers:
            continue
        if str(row.get("setupRec") or "").strip().lower() == "avoid":
            continue
        dte = int_value(row.get("daysUntilEarnings"), 999)
        if dte < 0:
            continue
        ranked.append({
            "ticker": ticker,
            "source": "tracker-shadow",
            "sourceLane": "tracker-shadow",
            "directorCategory": "tracker-shadow",
            "strategy": row.get("setupRec"),
            "setupRec": row.get("setupRec"),
            "readiness": row.get("readiness"),
            "confidence": row.get("confidence"),
            "daysUntilEarnings": row.get("daysUntilEarnings"),
            "price": row.get("price"),
            "baselineUnderlyingPrice": row.get("price"),
            "priceSource": "latest_snapshot.rows" if row.get("price") is not None else None,
            "estimatedMaxLoss": None,
            "capitalGap": None,
            "priorityScore": row.get("priority"),
            "scenarioScore": scenario_rank_score(row),
            "executableInPaperMoney": False,
            "requiresApproval": False,
            "shadowOnly": True,
            "brokerSubmitAllowed": False,
            "liveTradingAllowed": False,
            "authorityEligible": False,
            "evidenceLane": "tracker-shadow-scenario",
            "reducerAction": f"Monitor {ticker}; not a ticket until strike selector builds a clean plan.",
            "reasons": ["supplemental tracker scenario; no option ticket has been built"],
            "warnings": [],
            "marketContextSummary": row.get("marketContext") or {
                "rvol": row.get("rvol"),
                "trend": row.get("trend"),
                "support": row.get("support"),
                "resistance": row.get("resistance"),
            },
        })

    ranked.sort(
        key=lambda item: (
            -float_value(item.get("scenarioScore")),
            int_value(item.get("daysUntilEarnings"), 999),
            item.get("ticker", ""),
        )
    )
    return ranked[: max(0, needed)]


def collect_director_scenarios(director: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect director cohorts in safety-first priority order."""
    cohorts = [
        ("stageable", director.get("stageableSlate") or []),
        ("auto-paper", director.get("autoPaperSlate") or []),
        ("approval", director.get("approvalSlate") or []),
        ("research", director.get("researchWatchlist") or []),
        ("capital-near-miss", director.get("capitalNearMissSlate") or []),
        ("hard-blocked", director.get("hardBlockedSlate") or []),
    ]
    seen: set[str] = set()
    scenarios: list[dict[str, Any]] = []
    for lane, items in cohorts:
        for item in items:
            ticker = normalize_ticker(item.get("ticker"))
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            scenarios.append(scenario_from_director_candidate(item, lane=lane, rank_hint=len(scenarios)))
    return scenarios


def build_reducer(
    *,
    director_loader: Callable[[], dict[str, Any]] | None = None,
    snapshot_loader: Callable[[], dict[str, Any]] | None = None,
    scenario_target: int = DEFAULT_SCENARIO_TARGET,
) -> dict[str, Any]:
    """Build the daily paper bottleneck reducer artifact."""
    scenario_target = max(1, min(int(scenario_target), MAX_SCENARIO_LIMIT))
    director = (director_loader or (lambda: load_json_file(PAPER_TEST_DIRECTOR_FILE) or {}))()
    snapshot = (snapshot_loader or (lambda: load_json_file(SNAPSHOT_FILE) or {}))()

    scenarios = collect_director_scenarios(director)
    snapshot_rows = snapshot_row_lookup(snapshot)
    scenarios = [
        enrich_scenario_from_snapshot(item, snapshot_rows.get(normalize_ticker(item.get("ticker"))))
        for item in scenarios
    ]
    excluded = {normalize_ticker(item.get("ticker")) for item in scenarios}
    if len(scenarios) < scenario_target:
        scenarios.extend(
            tracker_shadow_candidates(
                snapshot,
                excluded_tickers=excluded,
                needed=scenario_target - len(scenarios),
            )
        )

    scenarios.sort(
        key=lambda item: (
            not bool(item.get("executableInPaperMoney")),
            not bool(item.get("requiresApproval")),
            -float_value(item.get("scenarioScore")),
            int_value(item.get("daysUntilEarnings"), 999),
            item.get("ticker", ""),
        )
    )
    scenarios = scenarios[:scenario_target]
    for index, scenario in enumerate(scenarios, start=1):
        scenario["rank"] = index

    executable = [item for item in scenarios if item.get("executableInPaperMoney")]
    approval = [item for item in scenarios if item.get("requiresApproval")]
    shadow = [item for item in scenarios if item.get("shadowOnly")]
    verdict = "scenario-slate-ready" if len(scenarios) >= scenario_target else "scenario-slate-thin"

    return {
        "generatedAt": local_now().isoformat(),
        "stage": "paper-bottleneck-reducer",
        "diagnosticOnly": True,
        "paperOnly": True,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "scenarioTarget": scenario_target,
        "verdict": verdict,
        "counts": {
            "scenarios": len(scenarios),
            "topFocus": min(TOP_FOCUS_COUNT, len(scenarios)),
            "executablePaper": len(executable),
            "approvalNeeded": len(approval),
            "shadowOnly": len(shadow),
        },
        "topFiveFocus": scenarios[:TOP_FOCUS_COUNT],
        "scenarioSlate": scenarios,
        "directorVerdict": director.get("verdict"),
        "directorCounts": director.get("counts") or {},
        "rules": [
            "Only executablePaper=true can be staged in paperMoney.",
            "All shadowOnly scenarios are evidence collection only and never broker-submit.",
            "Use the top five for operator focus; keep the full slate for after-the-fact scoring.",
        ],
    }


def reducer_text(payload: dict[str, Any]) -> str:
    """Render a concise paper bottleneck reducer memo."""
    counts = payload.get("counts") or {}
    lines = [
        "Inferno Paper Bottleneck Reducer",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Scenario target: {payload.get('scenarioTarget')}",
        f"Director verdict: {payload.get('directorVerdict')}",
        "",
        "Counts:",
        f"- scenarios: {counts.get('scenarios', 0)}",
        f"- executable paper: {counts.get('executablePaper', 0)}",
        f"- approval needed: {counts.get('approvalNeeded', 0)}",
        f"- shadow only: {counts.get('shadowOnly', 0)}",
        "",
        "Top five focus:",
    ]
    for item in payload.get("topFiveFocus") or []:
        lines.append(
            f"- #{item.get('rank')} {item.get('ticker')} | {item.get('evidenceLane')} | "
            f"score {item.get('scenarioScore')} | {item.get('setupRec')} | "
            f"{item.get('daysUntilEarnings')}d | price {item.get('price') or 'n/a'}"
        )
        lines.append(f"  action: {item.get('reducerAction')}")

    lines.extend(["", "Full scenario slate:"])
    for item in payload.get("scenarioSlate") or []:
        tag = "PAPER" if item.get("executableInPaperMoney") else "SHADOW"
        lines.append(
            f"- #{item.get('rank')} {item.get('ticker')} [{tag}] "
            f"{item.get('sourceLane')} | score {item.get('scenarioScore')} | price {item.get('price') or 'n/a'}"
        )

    lines.extend(["", "Rules:"])
    for rule in payload.get("rules") or []:
        lines.append(f"- {rule}")
    return "\n".join(lines).rstrip() + "\n"


def reducer_csv(payload: dict[str, Any]) -> str:
    """Render the scenario slate as a spreadsheet-friendly CSV.

    This is intentionally narrow and stable: the CSV is for quick review,
    sorting, and model handoff. Nested reasons are joined into a plain-text
    cell so the file remains easy to import into Sheets or another analysis
    tool.
    """
    output = StringIO()
    fields = [
        "rank",
        "ticker",
        "evidenceLane",
        "sourceLane",
        "scenarioScore",
        "setupRec",
        "strategy",
        "daysUntilEarnings",
        "price",
        "priceSource",
        "readiness",
        "confidence",
        "estimatedMaxLoss",
        "capitalGap",
        "executableInPaperMoney",
        "paperAutoSelected",
        "requiresApproval",
        "shadowOnly",
        "reducerAction",
        "reasons",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for item in payload.get("scenarioSlate") or []:
        writer.writerow({
            "rank": item.get("rank"),
            "ticker": item.get("ticker"),
            "evidenceLane": item.get("evidenceLane"),
            "sourceLane": item.get("sourceLane"),
            "scenarioScore": item.get("scenarioScore"),
            "setupRec": item.get("setupRec"),
            "strategy": item.get("strategy"),
            "daysUntilEarnings": item.get("daysUntilEarnings"),
            "price": item.get("price"),
            "priceSource": item.get("priceSource"),
            "readiness": item.get("readiness"),
            "confidence": item.get("confidence"),
            "estimatedMaxLoss": item.get("estimatedMaxLoss"),
            "capitalGap": item.get("capitalGap"),
            "executableInPaperMoney": item.get("executableInPaperMoney"),
            "paperAutoSelected": item.get("paperAutoSelected"),
            "requiresApproval": item.get("requiresApproval"),
            "shadowOnly": item.get("shadowOnly"),
            "reducerAction": item.get("reducerAction"),
            "reasons": "; ".join(str(reason) for reason in (item.get("reasons") or [])),
        })
    return output.getvalue()


def save_reducer(payload: dict[str, Any]) -> None:
    """Persist the reducer JSON, text report, and review CSV."""
    ensure_dirs()
    atomic_write_json(PAPER_BOTTLENECK_REDUCER_FILE, payload)
    atomic_write_text(PAPER_BOTTLENECK_REDUCER_TEXT_FILE, reducer_text(payload))
    atomic_write_text(PAPER_BOTTLENECK_REDUCER_CSV_FILE, reducer_csv(payload))


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Build paper evidence scenarios without weakening safety gates.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    parser.add_argument("--target", type=int, default=DEFAULT_SCENARIO_TARGET, help="Daily scenario target.")
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint."""
    args = parse_args()
    if args.command == "status" and PAPER_BOTTLENECK_REDUCER_TEXT_FILE.exists():
        print(PAPER_BOTTLENECK_REDUCER_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_reducer(scenario_target=args.target)
    save_reducer(payload)
    print(reducer_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
