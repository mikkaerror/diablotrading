from __future__ import annotations

"""Approval cadence diagnostic + batting-order generator.

The doctor's block-reason categorizer surfaced ``approval-missing`` as the
single dominant funnel killer. The slowest step on this desk is the human
operator looking at the slate and saying "yes" or "no". This module turns
that step from a vague backlog into a sorted, time-aware decide-list:

- counts pending vs decided vs demoted-stale
- computes days-since-pending and days-to-staleness for each ticker
- ranks pending items by an urgency blend (earnings proximity, staleness
  proximity, readiness) so the operator can walk the queue top-down
- flags items that need a decision today (earnings within 3 days, or
  staleness TTL within 1 market day)

Strict contract:
- this is a diagnostic. It cannot approve, reject, or move any ticker.
- it does not modify the approval queue, performance analytics, strategy
  lab, broker preview, or authority manifest.
- it writes only its own clearly-labeled artifacts.
"""

import argparse
import json
from datetime import datetime, timezone
from typing import Any

from inferno_approval_queue import (
    DEFAULT_STALE_APPROVAL_TTL_MARKET_DAYS,
    count_market_days_between,
    load_queue,
)
from inferno_config import local_now
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


CADENCE_FILE = DATA_DIR / "inferno_approval_cadence.json"
CADENCE_TEXT_FILE = REPORTS_DIR / "approval_cadence_latest.txt"
CADENCE_STAGE = "approval-cadence-diagnostic-only"


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if "T" in text:
            return datetime.fromisoformat(text)
        return datetime.fromisoformat(f"{text}T00:00:00")
    except ValueError:
        return None


def _aware(value: datetime, *, fallback: datetime) -> datetime:
    """Make a datetime tz-aware using fallback's tz when the source is naive."""
    if value.tzinfo is None:
        return value.replace(tzinfo=fallback.tzinfo or timezone.utc)
    return value


def urgency_score(item: dict[str, Any], *, days_pending: int,
                  ttl_market_days: int) -> float:
    """Blend earnings proximity, staleness proximity, and readiness.

    Higher score = decide sooner. The blend is intentionally simple so any
    operator can read it: 60 weight on earnings proximity (the actual reason
    we trade), 25 on staleness pressure, 15 on readiness. Earnings within 3
    days alone produces a high score even if readiness is moderate.
    """
    days_to_earnings = item.get("daysUntilEarnings")
    if days_to_earnings is None:
        earnings_pressure = 0.0
    else:
        # The closer to earnings, the higher the pressure. Cap at 21 days out.
        d = max(0, min(21, int(days_to_earnings)))
        earnings_pressure = (21 - d) / 21
    days_to_stale = max(0, ttl_market_days - days_pending)
    staleness_pressure = (ttl_market_days - days_to_stale) / max(1, ttl_market_days)
    readiness = float(item.get("readiness") or 0) / 100.0
    return round(
        0.60 * earnings_pressure + 0.25 * staleness_pressure + 0.15 * readiness,
        4,
    )


def annotate_pending_item(
    item: dict[str, Any],
    *,
    now: datetime,
    ttl_market_days: int,
) -> dict[str, Any]:
    """Annotate a pending item with cadence-relevant fields."""
    pending_since = _parse_iso(item.get("pendingSince"))
    days_pending = (
        count_market_days_between(_aware(pending_since, fallback=now).date(), now.date())
        if pending_since
        else 0
    )
    days_to_stale = max(0, ttl_market_days - days_pending)
    urgency = urgency_score(item, days_pending=days_pending, ttl_market_days=ttl_market_days)

    days_to_earnings = item.get("daysUntilEarnings")
    decide_today = False
    decide_reasons: list[str] = []
    if days_to_earnings is not None and int(days_to_earnings) <= 3:
        decide_today = True
        decide_reasons.append(f"earnings in {days_to_earnings}d")
    if days_to_stale <= 1:
        decide_today = True
        decide_reasons.append(f"stale demotion in {days_to_stale} market day(s)")

    return {
        "ticker": item.get("ticker"),
        "setupRec": item.get("setupRec"),
        "readiness": item.get("readiness"),
        "daysUntilEarnings": days_to_earnings,
        "signalTrigger": item.get("signalTrigger"),
        "primaryRoute": item.get("primaryRoute"),
        "secondaryRoute": item.get("secondaryRoute"),
        "pendingSince": item.get("pendingSince"),
        "daysPending": days_pending,
        "daysToStaleDemotion": days_to_stale,
        "urgencyScore": urgency,
        "decideToday": decide_today,
        "decideReasons": decide_reasons,
    }


def build_cadence(
    queue: dict[str, Any] | None = None,
    *,
    ttl_market_days: int = DEFAULT_STALE_APPROVAL_TTL_MARKET_DAYS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the full cadence diagnostic from the current approval queue."""
    queue = queue if queue is not None else load_queue()
    moment = now or local_now()
    items = queue.get("items") or []

    by_status: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        status = str(item.get("approvalStatus") or "unknown").lower()
        by_status.setdefault(status, []).append(item)

    pending = by_status.get("pending", [])
    annotated_pending = [
        annotate_pending_item(item, now=moment, ttl_market_days=ttl_market_days)
        for item in pending
    ]
    annotated_pending.sort(key=lambda payload: -payload["urgencyScore"])
    decide_today = [item for item in annotated_pending if item["decideToday"]]

    today = moment.date().isoformat()
    decided_today = [
        item for item in items
        if str(item.get("decisionAt") or "").startswith(today)
        and str(item.get("approvalStatus") or "").lower() in {"approved", "rejected"}
    ]

    counts = {
        "totalItems": len(items),
        "pending": len(pending),
        "approved": len(by_status.get("approved", [])),
        "rejected": len(by_status.get("rejected", [])),
        "researchOnly": len(by_status.get("research-only", [])),
        "decidedToday": len(decided_today),
        "decideTodayQueue": len(decide_today),
    }

    oldest_pending_since = None
    if pending:
        stamps = [
            _parse_iso(item.get("pendingSince"))
            for item in pending
            if item.get("pendingSince")
        ]
        stamps = [stamp for stamp in stamps if stamp is not None]
        if stamps:
            oldest_pending_since = min(stamps).isoformat()

    return {
        "generatedAt": moment.isoformat(),
        "stage": CADENCE_STAGE,
        "diagnosticOnly": True,
        "ttlMarketDays": ttl_market_days,
        "queueGeneratedAt": queue.get("generatedAt"),
        "counts": counts,
        "oldestPendingSince": oldest_pending_since,
        "battingOrder": annotated_pending,
        "decideTodayTickers": [item["ticker"] for item in decide_today],
        "researchNotes": [
            "diagnostic only; cannot approve, reject, or move any ticker",
            "urgency = 0.60 earnings + 0.25 staleness + 0.15 readiness",
        ],
    }


def cadence_text(cadence: dict[str, Any]) -> str:
    """Render the cadence diagnostic as an operator memo."""
    counts = cadence.get("counts") or {}
    lines = [
        "Inferno Approval Cadence (diagnostic-only)",
        "",
        f"Generated: {cadence.get('generatedAt')}",
        f"Stage: {cadence.get('stage')}",
        f"TTL (market days): {cadence.get('ttlMarketDays')}",
        f"Queue generated at: {cadence.get('queueGeneratedAt')}",
        "",
        "Counts:",
        f"- pending:        {counts.get('pending', 0)}",
        f"- approved:       {counts.get('approved', 0)}",
        f"- rejected:       {counts.get('rejected', 0)}",
        f"- research-only:  {counts.get('researchOnly', 0)}",
        f"- decided today:  {counts.get('decidedToday', 0)}",
        f"- decide-today:   {counts.get('decideTodayQueue', 0)}",
        f"Oldest pendingSince: {cadence.get('oldestPendingSince') or '-'}",
        "",
        "Decide-today queue (in priority order):",
    ]
    decide_today_tickers = cadence.get("decideTodayTickers") or []
    if not decide_today_tickers:
        lines.append("- none")
    for item in cadence.get("battingOrder") or []:
        if not item.get("decideToday"):
            continue
        reasons = ", ".join(item.get("decideReasons") or []) or "-"
        lines.append(
            f"- {item['ticker']:<5} setup={item['setupRec']:<14} "
            f"readiness={item['readiness']:>3} "
            f"daysToEarnings={item['daysUntilEarnings']} "
            f"daysToStale={item['daysToStaleDemotion']} "
            f"urgency={item['urgencyScore']} "
            f"reason={reasons}"
        )
    lines.extend(["", "Full batting order:"])
    for item in cadence.get("battingOrder") or []:
        lines.append(
            f"- {item['ticker']:<5} setup={item['setupRec']:<14} "
            f"readiness={item['readiness']:>3} "
            f"daysToEarnings={item['daysUntilEarnings']} "
            f"daysPending={item['daysPending']} "
            f"daysToStale={item['daysToStaleDemotion']} "
            f"urgency={item['urgencyScore']}"
        )
    lines.extend(
        [
            "",
            "Reminders:",
            "- diagnostic only; nothing here changes ticket state",
            "- approve/reject decisions still flow through inferno_approval_queue.py",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def save_cadence(cadence: dict[str, Any]) -> None:
    """Persist cadence JSON and text artifacts."""
    ensure_dirs()
    CADENCE_FILE.write_text(json.dumps(cadence, indent=2), encoding="utf-8")
    CADENCE_TEXT_FILE.write_text(cadence_text(cadence), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Approval cadence diagnostic. Prints the decide-list and saves "
            "data/inferno_approval_cadence.json. Read-only."
        )
    )
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    parser.add_argument(
        "--ttl-market-days",
        type=int,
        default=DEFAULT_STALE_APPROVAL_TTL_MARKET_DAYS,
        help="Market-day TTL used when computing days-to-staleness.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and CADENCE_TEXT_FILE.exists():
        print(CADENCE_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    cadence = build_cadence(ttl_market_days=args.ttl_market_days)
    save_cadence(cadence)
    print(cadence_text(cadence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
