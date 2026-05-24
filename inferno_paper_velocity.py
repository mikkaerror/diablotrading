from __future__ import annotations

"""Paper-evidence velocity tracker (research-only).

The desk's deepest promotion bottleneck is closed paper outcomes. The
30-closed-outcome gate has been live for weeks while the ledger sat at
zero closed, and nothing in the reporting surface made that visible
until you went looking. This module turns the ledger into a single
read-once-per-day artifact that answers four questions:

1. How many closed paper outcomes do we have right now?
2. At the current rate, when do we project clearing the 30 gate?
3. Why is the auto-paper gate refusing tickets that look clean?
4. Which paper-only tickets are about to age out unapproved?

It does not stage, approve, or promote anything. It reads the existing
paper execution ledger, summarises it, and prints a research-only
verdict (``stalled`` / ``slow`` / ``on-track`` / ``promotion-ready``).

Citations (light): The bottleneck framing is Goldratt's Theory of
Constraints (THEORY-CONSTRAINTS-GOLDRATT-1984) -- maximize throughput
of the constraint, not the non-constraints. The 30-outcome promotion
floor is the desk's own decision-rule, not a published threshold.
"""

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta, date
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


PAPER_EXECUTION_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
PAPER_VELOCITY_FILE = DATA_DIR / "inferno_paper_velocity.json"
PAPER_VELOCITY_TEXT_FILE = REPORTS_DIR / "paper_velocity_latest.txt"

PAPER_VELOCITY_STAGE = "paper-velocity-research-only"
PROMOTION_TARGET = 30
AGING_OUT_WINDOW_DAYS = 7
SLOW_THRESHOLD_30D = 4  # < 4 closed in last 30d => slow
ON_TRACK_THRESHOLD_30D = 10  # >= 10 closed in last 30d => on-track


def _parse_iso_date(value: Any) -> date | None:
    """Parse a flexible ISO datetime/date string into a date."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw[:19]).date() if "T" in raw else date.fromisoformat(raw[:10])
    except (ValueError, TypeError):
        return None


def _load_ledger_items() -> list[dict[str, Any]]:
    """Return the items list from the paper execution ledger, or empty."""
    payload = load_json_file(PAPER_EXECUTION_LEDGER_FILE)
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    return items if isinstance(items, list) else []


def _status_distribution(items: list[dict[str, Any]]) -> dict[str, int]:
    """Count tickets by ``status`` field (paper-staged / blocked / rejected)."""
    counts: Counter[str] = Counter()
    for item in items:
        counts[str(item.get("status") or "unknown")] += 1
    return dict(counts)


def _outcome_distribution(items: list[dict[str, Any]]) -> dict[str, int]:
    """Count tickets by outcome status (closed / open / not-opened)."""
    counts: Counter[str] = Counter()
    for item in items:
        outcome = item.get("outcome") or {}
        counts[str(outcome.get("status") or "unknown")] += 1
    return dict(counts)


def _auto_block_reason_distribution(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Frequency table for ``paperAutoBlockReason`` across blocked tickets.

    Sorted descending. ``ok`` and ``not-evaluated`` are excluded -- they
    are not failures and would crowd out the real diagnostic signal.
    """
    counts: Counter[str] = Counter()
    for item in items:
        if item.get("status") != "paper-blocked":
            continue
        reason = item.get("paperAutoBlockReason")
        if not reason or reason in {"ok", "not-evaluated"}:
            continue
        # Normalize the long-form reasons that carry inline values.
        key = str(reason).split(":")[0].strip()
        counts[key] += 1
    return [{"reason": reason, "count": count} for reason, count in counts.most_common()]


def _approval_aging_alert(
    items: list[dict[str, Any]], *, today: date, window_days: int
) -> dict[str, Any]:
    """Compute approval-only aging-out alerts and zombie count.

    Aging-out: paperOnly + approvalStatus=pending + expiration in the
    next ``window_days`` days. The operator needs to know about these
    before the clock runs out -- once expiration passes, the ticket is
    unrecoverable as evidence.

    Zombies: same shape but expiration already past. Diagnostic only;
    these tickets are dead.
    """
    horizon = today + timedelta(days=window_days)
    aging: list[dict[str, Any]] = []
    zombies = 0
    for item in items:
        if not item.get("paperOnly"):
            continue
        if str(item.get("approvalStatus") or "").lower() != "pending":
            continue
        expiration = _parse_iso_date(item.get("expiration"))
        if expiration is None:
            continue
        if expiration < today:
            zombies += 1
            continue
        if expiration <= horizon:
            aging.append(
                {
                    "ticker": item.get("ticker"),
                    "strategy": item.get("strategy"),
                    "expiration": expiration.isoformat(),
                    "daysUntilExpiration": (expiration - today).days,
                    "ticketId": item.get("ticketId"),
                }
            )
    aging.sort(key=lambda row: row["expiration"])
    return {"agingOut": aging, "zombieCount": zombies, "windowDays": window_days}


def _closed_outcome_velocity(items: list[dict[str, Any]], *, today: date) -> dict[str, Any]:
    """Compute closed-outcome counts over rolling windows and project clearance.

    Uses ``outcome.reviewedAt`` as the close timestamp. Tickets without a
    review timestamp are not counted, even if they are marked closed.
    """
    closed_dates: list[date] = []
    for item in items:
        outcome = item.get("outcome") or {}
        if outcome.get("status") != "closed":
            continue
        reviewed = _parse_iso_date(outcome.get("reviewedAt"))
        if reviewed is not None:
            closed_dates.append(reviewed)
    total_closed = len(closed_dates)
    last_7 = sum(1 for d in closed_dates if (today - d).days <= 7)
    last_30 = sum(1 for d in closed_dates if (today - d).days <= 30)
    last_90 = sum(1 for d in closed_dates if (today - d).days <= 90)

    weekly_rate = last_30 / (30.0 / 7.0) if last_30 > 0 else 0.0
    remaining = max(0, PROMOTION_TARGET - total_closed)
    projected_weeks: float | None
    projected_date: str | None
    if remaining == 0:
        projected_weeks = 0.0
        projected_date = today.isoformat()
    elif weekly_rate <= 0:
        projected_weeks = None
        projected_date = None
    else:
        projected_weeks = round(remaining / weekly_rate, 1)
        projected_date = (today + timedelta(weeks=projected_weeks)).isoformat()

    return {
        "totalClosed": total_closed,
        "closedLast7Days": last_7,
        "closedLast30Days": last_30,
        "closedLast90Days": last_90,
        "weeklyRate30dWindow": round(weekly_rate, 2),
        "promotionTarget": PROMOTION_TARGET,
        "remainingToPromotion": remaining,
        "projectedWeeksToPromotion": projected_weeks,
        "projectedClearanceDate": projected_date,
    }


def _verdict(velocity: dict[str, Any]) -> str:
    """Classify the desk's closed-outcome velocity into a short verdict."""
    if velocity["totalClosed"] >= PROMOTION_TARGET:
        return "promotion-ready"
    if velocity["closedLast30Days"] >= ON_TRACK_THRESHOLD_30D:
        return "on-track"
    if velocity["closedLast30Days"] >= SLOW_THRESHOLD_30D:
        return "slow"
    return "stalled"


def build_paper_velocity(*, now: datetime | None = None) -> dict[str, Any]:
    """Build the velocity payload from the current ledger."""
    now = now or local_now()
    today = now.date()
    items = _load_ledger_items()
    status_dist = _status_distribution(items)
    outcome_dist = _outcome_distribution(items)
    auto_block_reasons = _auto_block_reason_distribution(items)
    aging = _approval_aging_alert(items, today=today, window_days=AGING_OUT_WINDOW_DAYS)
    velocity = _closed_outcome_velocity(items, today=today)
    verdict = _verdict(velocity)

    return {
        "generatedAt": now.isoformat(),
        "stage": PAPER_VELOCITY_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "totalTickets": len(items),
        "statusDistribution": status_dist,
        "outcomeDistribution": outcome_dist,
        "velocity": velocity,
        "verdict": verdict,
        "autoPaperBlockReasons": auto_block_reasons,
        "approvalAlerts": aging,
        "citations": ["THEORY-CONSTRAINTS-GOLDRATT-1984"],
        "thresholds": {
            "promotionTarget": PROMOTION_TARGET,
            "slowThreshold30d": SLOW_THRESHOLD_30D,
            "onTrackThreshold30d": ON_TRACK_THRESHOLD_30D,
            "agingOutWindowDays": AGING_OUT_WINDOW_DAYS,
        },
        "reminders": [
            "research-only: no authority changes",
            "the desk graduates only when 30 closed paper outcomes accrue",
            "approval-only zombies cannot be recovered after expiration",
        ],
    }


def paper_velocity_text(payload: dict[str, Any]) -> str:
    """Render a compact operator-friendly velocity report."""
    velocity = payload.get("velocity") or {}
    aging = payload.get("approvalAlerts") or {}
    reasons = payload.get("autoPaperBlockReasons") or []
    lines = [
        "Inferno Paper Evidence Velocity",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Total ledger tickets: {payload.get('totalTickets')}",
        "",
        "Status distribution:",
    ]
    for status, count in sorted((payload.get("statusDistribution") or {}).items()):
        lines.append(f"  {status}: {count}")
    lines.append("")
    lines.append("Outcome distribution:")
    for outcome, count in sorted((payload.get("outcomeDistribution") or {}).items()):
        lines.append(f"  {outcome}: {count}")
    lines.append("")
    lines.append("Closed-outcome velocity:")
    lines.append(f"  Total closed: {velocity.get('totalClosed')}")
    lines.append(f"  Closed last 7d / 30d / 90d: "
                 f"{velocity.get('closedLast7Days')} / "
                 f"{velocity.get('closedLast30Days')} / "
                 f"{velocity.get('closedLast90Days')}")
    lines.append(f"  Weekly rate (30d window): {velocity.get('weeklyRate30dWindow')}")
    lines.append(f"  Promotion target: {velocity.get('promotionTarget')} "
                 f"(remaining: {velocity.get('remainingToPromotion')})")
    weeks = velocity.get("projectedWeeksToPromotion")
    clear_date = velocity.get("projectedClearanceDate")
    if weeks is None:
        lines.append("  Projected clearance: unknown (no recent closes)")
    elif weeks == 0.0:
        lines.append("  Projected clearance: already cleared")
    else:
        lines.append(f"  Projected clearance: ~{weeks} weeks (~{clear_date})")
    lines.append("")
    lines.append("Approval alerts:")
    lines.append(f"  Aging out next {aging.get('windowDays')}d: {len(aging.get('agingOut') or [])}")
    lines.append(f"  Past-expiration zombies: {aging.get('zombieCount')}")
    for row in (aging.get("agingOut") or [])[:10]:
        lines.append(
            f"    {row.get('ticker')} | {row.get('strategy')} | "
            f"exp {row.get('expiration')} | {row.get('daysUntilExpiration')}d left"
        )
    lines.append("")
    lines.append("Auto-paper block-reason frequency (paper-blocked tickets only):")
    if reasons:
        for entry in reasons[:8]:
            lines.append(f"  {entry.get('count'):>3}  {entry.get('reason')}")
    else:
        lines.append("  (no diagnostic reasons captured yet -- run next strike cycle)")
    lines.append("")
    lines.append("Reminders:")
    for reminder in payload.get("reminders") or []:
        lines.append(f"  - {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_paper_velocity(payload: dict[str, Any]) -> None:
    """Persist the velocity payload as JSON + text."""
    ensure_dirs()
    atomic_write_json(PAPER_VELOCITY_FILE, payload)
    atomic_write_text(PAPER_VELOCITY_TEXT_FILE, paper_velocity_text(payload))


def parse_args() -> argparse.Namespace:
    """Parse CLI args for the velocity tracker."""
    parser = argparse.ArgumentParser(description="Inferno paper-evidence velocity tracker (research-only)")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    """Build and emit the velocity report, or print the last cached one."""
    args = parse_args()
    if args.command == "status" and PAPER_VELOCITY_TEXT_FILE.exists():
        print(PAPER_VELOCITY_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_paper_velocity()
    save_paper_velocity(payload)
    print(paper_velocity_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
