from __future__ import annotations

"""Evidence-capacity plan: season shape vs. the desk's own throughput caps (research-only).

Why
---
The paper-velocity projection extrapolates the trailing closed-outcome rate
in a straight line ("~58 weeks to 30"). Earnings evidence does not arrive in
a straight line: it arrives in bursts when the universe reports. This module
reads the tracker's own next-earnings dates, lays them out by week, screens
them with the same front-of-funnel filters the pipeline uses (confidence,
setup label, days-to-earnings window), and then pushes that eligible flow
through the desk's configured caps — execution-queue limit, max open paper
tickets, tickets per event, daily budget, and an assumed hold time — to show
how many *scored outcomes* the caps can physically produce per week, and
which cap binds.

Every projection is capacity, not a forecast of fills: the operator still
records each paperMoney fill by hand, and the historical fill rate is the
lowest ceiling of all. That ceiling is reported next to the capacity so the
gap is visible.

Boundary: research-only. It changes no cap, gate, universe, or ticket. It
recommends nothing that would widen live authority.
"""

import argparse
import json
from collections import Counter
from datetime import timedelta
from typing import Any

from inferno_config import (
    CANDIDATE_MAX_DAYS_UNTIL_EARNINGS,
    CANDIDATE_MIN_CONFIDENCE,
    EXECUTION_QUEUE_LIMIT,
    MAX_ACTIVE_EXECUTION_INTENTS,
    MAX_OPEN_PAPER_TICKETS,
    MAX_PAPER_TICKETS_PER_EVENT,
    PAPER_DAILY_BUDGET_DOLLARS,
    PAPER_TICKET_BUDGET_DOLLARS,
    local_now,
)
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


EVIDENCE_CAPACITY_STAGE = "evidence-capacity-plan-research-only"
SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
PAPER_VELOCITY_FILE = DATA_DIR / "inferno_paper_velocity.json"
EVIDENCE_CAPACITY_FILE = DATA_DIR / "inferno_evidence_capacity_plan.json"
EVIDENCE_CAPACITY_TEXT_FILE = REPORTS_DIR / "evidence_capacity_plan_latest.txt"

PROMOTION_TARGET = 30
HORIZON_WEEKS = 20
DEFAULT_HOLD_DAYS = 3.0          # earnings tickets open just before, close just after the print
TRADING_DAYS_PER_WEEK = 5
ELIGIBLE_SETUPS = {"Straddle", "Vertical Call", "Vertical Put", "Strangle"}


def number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def season_profile(rows: list[dict[str, Any]], *, horizon_weeks: int = HORIZON_WEEKS) -> list[dict[str, Any]]:
    """Names reporting per week ahead, total and after the front-of-funnel screens."""
    total: Counter[int] = Counter()
    eligible: Counter[int] = Counter()
    for row in rows:
        days = number(row.get("daysUntilEarnings"))
        if days is None or days < 0 or days >= horizon_weeks * 7:
            continue
        week = int(days // 7)
        total[week] += 1
        confidence = number(row.get("confidence")) or 0
        if confidence >= CANDIDATE_MIN_CONFIDENCE and str(row.get("setupRec") or "") in ELIGIBLE_SETUPS:
            eligible[week] += 1
    return [{"week": w, "reporting": total.get(w, 0), "eligible": eligible.get(w, 0)} for w in range(horizon_weeks)]


def weekly_capacity(*, hold_days: float = DEFAULT_HOLD_DAYS) -> dict[str, float]:
    """Scored outcomes per week each cap allows on its own, and the binding one."""
    turnover = max(1.0, TRADING_DAYS_PER_WEEK / max(hold_days, 0.5))  # ticket slots recycled per week
    caps = {
        "queueLimit": EXECUTION_QUEUE_LIMIT * TRADING_DAYS_PER_WEEK,           # intents priced per week
        "activeIntents": MAX_ACTIVE_EXECUTION_INTENTS * turnover,
        "openPaperTickets": MAX_OPEN_PAPER_TICKETS * turnover,
        "dailyBudget": (PAPER_DAILY_BUDGET_DOLLARS / max(PAPER_TICKET_BUDGET_DOLLARS, 1.0)) * TRADING_DAYS_PER_WEEK,
    }
    binding = min(caps, key=caps.get)
    return {**{k: round(v, 2) for k, v in caps.items()}, "bindingCap": binding, "weeklyCapacity": round(caps[binding], 2), "holdDaysAssumed": hold_days}


def project(profile: list[dict[str, Any]], capacity_per_week: float, *, per_event_cap: int = MAX_PAPER_TICKETS_PER_EVENT, historical_rate: float | None = None, scored_so_far: int = 0) -> dict[str, Any]:
    """Push eligible flow through the weekly capacity; compare with the historical fill rate."""
    cumulative_capacity = scored_so_far
    cumulative_historical = scored_so_far
    weeks: list[dict[str, Any]] = []
    clear_week_capacity = None
    clear_week_historical = None
    for item in profile:
        flow = min(item["eligible"] * per_event_cap, item["eligible"] * per_event_cap)  # tickets the events could host
        capacity_bound = min(flow, capacity_per_week)
        cumulative_capacity += capacity_bound
        historical_bound = min(flow, historical_rate) if historical_rate is not None else None
        if historical_bound is not None:
            cumulative_historical += historical_bound
        weeks.append({**item, "ticketsCapacityBound": round(capacity_bound, 2), "cumulativeCapacityBound": round(cumulative_capacity, 2), "ticketsHistoricalRate": round(historical_bound, 2) if historical_bound is not None else None, "cumulativeHistoricalRate": round(cumulative_historical, 2) if historical_rate is not None else None})
        if clear_week_capacity is None and cumulative_capacity >= PROMOTION_TARGET:
            clear_week_capacity = item["week"]
        if historical_rate is not None and clear_week_historical is None and cumulative_historical >= PROMOTION_TARGET:
            clear_week_historical = item["week"]
    return {"weeks": weeks, "clearWeekAtCapacity": clear_week_capacity, "clearWeekAtHistoricalRate": clear_week_historical, "cumulativeAtHorizonCapacity": round(cumulative_capacity, 2), "cumulativeAtHorizonHistorical": round(cumulative_historical, 2) if historical_rate is not None else None}


def build_plan(*, snapshot: Any = None, velocity: dict[str, Any] | None = None, hold_days: float = DEFAULT_HOLD_DAYS) -> dict[str, Any]:
    """Build the research-only evidence-capacity plan."""
    snap = snapshot if snapshot is not None else (load_json_file(SNAPSHOT_FILE) or [])
    rows = snap.get("rows") if isinstance(snap, dict) else snap
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    vel = velocity if velocity is not None else (load_json_file(PAPER_VELOCITY_FILE) or {})
    velocity_block = vel.get("velocity") if isinstance(vel.get("velocity"), dict) else vel
    historical_rate = number(velocity_block.get("weeklyRate30dWindow") or velocity_block.get("weeklyRate30d"))
    scored = int(number(velocity_block.get("totalClosed")) or 0)
    profile = season_profile(rows)
    capacity = weekly_capacity(hold_days=hold_days)
    projection = project(profile, capacity["weeklyCapacity"], historical_rate=historical_rate, scored_so_far=scored)
    in_window = sum(p["reporting"] for p in profile if p["week"] * 7 < CANDIDATE_MAX_DAYS_UNTIL_EARNINGS)
    peak = max(profile, key=lambda p: p["eligible"]) if profile else {"week": None, "eligible": 0}
    today = local_now().date()
    verdict = (
        "calendar-starved-now" if in_window <= 5 and peak["eligible"] >= 20
        else "capacity-bound" if projection["clearWeekAtCapacity"] is not None and (projection["clearWeekAtHistoricalRate"] is None or projection["clearWeekAtHistoricalRate"] > projection["clearWeekAtCapacity"])
        else "insufficient-flow"
    )
    return {
        "generatedAt": local_now().isoformat(),
        "stage": EVIDENCE_CAPACITY_STAGE,
        "verdict": verdict,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "counts": {"universe": len(rows), "reportingInCandidateWindow": in_window, "peakWeekEligible": peak["eligible"], "scoredSoFar": scored},
        "candidateWindowDays": CANDIDATE_MAX_DAYS_UNTIL_EARNINGS,
        "peakWeek": {"week": peak["week"], "startsOn": (today + timedelta(days=7 * peak["week"])).isoformat() if peak["week"] is not None else None, "eligible": peak["eligible"], "reporting": peak["reporting"]},
        "caps": {"executionQueueLimit": EXECUTION_QUEUE_LIMIT, "maxActiveExecutionIntents": MAX_ACTIVE_EXECUTION_INTENTS, "maxOpenPaperTickets": MAX_OPEN_PAPER_TICKETS, "maxPaperTicketsPerEvent": MAX_PAPER_TICKETS_PER_EVENT, "paperDailyBudget": PAPER_DAILY_BUDGET_DOLLARS, "paperTicketBudget": PAPER_TICKET_BUDGET_DOLLARS},
        "capacity": capacity,
        "historicalWeeklyFillRate": historical_rate,
        "projection": projection,
        "seasonProfile": profile,
        "reminders": [
            "capacity is what the caps allow, not a forecast of operator fills; the historical fill rate is the real ceiling until it changes",
            "research-only; caps and gates are operator-owned and unchanged here",
        ],
    }


def plan_text(payload: dict[str, Any]) -> str:
    counts = payload.get("counts") or {}
    cap = payload.get("capacity") or {}
    proj = payload.get("projection") or {}
    peak = payload.get("peakWeek") or {}
    lines = [
        "Inferno Evidence-Capacity Plan (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Universe: {counts.get('universe')} | reporting inside the {payload.get('candidateWindowDays')}-day candidate window now: {counts.get('reportingInCandidateWindow')}",
        f"Peak week: week {peak.get('week')} (from {peak.get('startsOn')}) | {peak.get('reporting')} reporting, {peak.get('eligible')} eligible after confidence/setup screens",
        "",
        f"Weekly scored-outcome capacity by cap (hold {cap.get('holdDaysAssumed')}d): queue {cap.get('queueLimit')} | active intents {cap.get('activeIntents')} | open paper tickets {cap.get('openPaperTickets')} | daily budget {cap.get('dailyBudget')}",
        f"Binding cap: {cap.get('bindingCap')} -> {cap.get('weeklyCapacity')} / week",
        f"Historical operator fill rate: {payload.get('historicalWeeklyFillRate')} / week",
        "",
        f"30-outcome clearance: at capacity -> week {proj.get('clearWeekAtCapacity')} | at historical fill rate -> week {proj.get('clearWeekAtHistoricalRate')} (None = not within {HORIZON_WEEKS} weeks)",
        f"Cumulative at horizon: capacity {proj.get('cumulativeAtHorizonCapacity')} | historical {proj.get('cumulativeAtHorizonHistorical')} (starting from {counts.get('scoredSoFar')} scored)",
        "",
        "Week | reporting | eligible | capacity-bound tickets | cumulative",
    ]
    for w in proj.get("weeks") or []:
        if w["reporting"] or w["ticketsCapacityBound"]:
            lines.append(f"  {w['week']:>2} | {w['reporting']:>9} | {w['eligible']:>8} | {w['ticketsCapacityBound']:>22} | {w['cumulativeCapacityBound']}")
    lines.extend(["", "Reminders:"] + [f"- {r}" for r in payload.get("reminders") or []])
    return "\n".join(lines) + "\n"


def save_plan(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(EVIDENCE_CAPACITY_FILE, payload)
    atomic_write_text(EVIDENCE_CAPACITY_TEXT_FILE, plan_text(payload))


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only evidence-capacity plan.")
    parser.add_argument("command", nargs="?", choices=("run", "status"), default="run")
    parser.add_argument("--hold-days", type=float, default=DEFAULT_HOLD_DAYS)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.command == "status":
        payload = load_json_file(EVIDENCE_CAPACITY_FILE)
        if not payload:
            print("no evidence-capacity plan yet; run `python3 inferno_evidence_capacity_plan.py run`")
            return 1
    else:
        payload = build_plan(hold_days=args.hold_days)
        save_plan(payload)
    print(json.dumps(payload, indent=2) if args.json else plan_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
