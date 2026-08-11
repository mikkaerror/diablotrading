#!/usr/bin/env python3
"""Compact watchlist-first research brief (research-only).

The desk already produces broad edge and conviction maps, but those reports are
not a practical daily surface for an operator who wants a small answer to
"which names should I research next?"  This module deliberately condenses the
existing rankings; it does not create a new score, loosen a gate, or expose a
ticket workflow.

Source selection is explicit:

* a fresh, operator-labelled ``data/inferno_watchlist_input.json`` narrows the
  brief to the supplied symbols;
* otherwise the current full tracker is the watchlist and the pre-existing
  edge-research watchlist supplies the ordered focus names;
* an old position-derived extract is displayed as stale provenance, never
  silently treated as the operator's current watchlist.

The result is research and monitoring guidance only.  It never approves,
sizes, stages, submits, or otherwise authorizes a trade.
"""

from __future__ import annotations

import argparse
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


EDGE_RESEARCH_FILE = DATA_DIR / "inferno_edge_research.json"
CONVICTION_RESEARCH_FILE = DATA_DIR / "inferno_conviction_research.json"
WATCHLIST_INPUT_FILE = DATA_DIR / "inferno_watchlist_input.json"
WATCHLIST_BRIEF_FILE = DATA_DIR / "inferno_watchlist_brief.json"
WATCHLIST_BRIEF_TEXT_FILE = REPORTS_DIR / "watchlist_brief_latest.txt"
WATCHLIST_BRIEF_STAGE = "watchlist-brief-research-only"
MAX_INPUT_AGE_DAYS = 7


def text(value: Any) -> str:
    """Return a stripped string without turning ``None`` into a ticker."""
    return str(value or "").strip()


def ticker(value: Any) -> str:
    """Normalize a symbol for cross-artifact joins."""
    return text(value).upper()


def number(value: Any, default: float = 0.0) -> float:
    """Coerce a score safely for display ordering only."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _source_date(source: str) -> date | None:
    """Read an ISO date embedded in legacy source provenance when present."""
    match = re.search(r"(?<!\d)(20\d{2}-\d{2}-\d{2})(?!\d)", source)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _unique_tickers(values: Any) -> list[str]:
    """Validate an untrusted list into unique ticker-shaped strings."""
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        symbol = ticker(value)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        result.append(symbol)
    return result


def watchlist_input_status(payload: dict[str, Any] | None, *, now: datetime) -> dict[str, Any]:
    """Describe whether an optional personal list is safe to use for ordering.

    A source labelled as a live-position extract is not a watchlist assertion.
    Treating it as one would make the brief look personalized while silently
    using old holdings context, so it must remain an explicit fallback warning.
    """
    payload = payload if isinstance(payload, dict) else {}
    source = text(payload.get("source")) or "missing"
    symbols = _unique_tickers(payload.get("tickers"))
    source_day = _source_date(source)
    age_days = max((now.date() - source_day).days, 0) if source_day else None
    position_derived = "position" in source.lower()
    fresh = bool(symbols) and (age_days is None or age_days <= MAX_INPUT_AGE_DAYS)
    usable = fresh and not position_derived
    if not symbols:
        reason = "no explicit watchlist input is available"
    elif position_derived:
        reason = "saved input is position-derived, not an operator watchlist assertion"
    elif age_days is not None and age_days > MAX_INPUT_AGE_DAYS:
        reason = f"saved input is {age_days} days old (maximum {MAX_INPUT_AGE_DAYS})"
    elif fresh:
        reason = "fresh operator watchlist input"
    else:
        reason = "watchlist source has no dated provenance; treated as operator supplied"
    return {
        "source": source,
        "tickers": symbols,
        "count": len(symbols),
        "sourceDate": source_day.isoformat() if source_day else None,
        "ageDays": age_days,
        "positionDerived": position_derived,
        "usableForOrdering": usable,
        "reason": reason,
    }


def _index_rows(payload: dict[str, Any], key: str = "ranked") -> dict[str, dict[str, Any]]:
    """Index a ranked artifact by symbol, keeping its existing row values."""
    rows = payload.get(key) if isinstance(payload, dict) else []
    return {
        symbol: row
        for row in rows or []
        if isinstance(row, dict) and (symbol := ticker(row.get("ticker") or row.get("symbol")))
    }


def _brief_row(symbol: str, edge: dict[str, Any] | None, conviction: dict[str, Any] | None) -> dict[str, Any]:
    """Render a joined existing-ranking row without producing a new signal."""
    edge = edge or {}
    conviction = conviction or {}
    flags = [text(flag) for flag in conviction.get("riskFlags") or [] if text(flag)]
    days = conviction.get("daysUntilEarnings", edge.get("daysUntilEarnings"))
    evidence_grade = text(conviction.get("evidenceGrade")) or "unavailable"
    trigger = bool(conviction.get("signalTrigger", edge.get("signalTrigger")))
    if not edge and not conviction:
        label = "DATA CHECK"
        next_step = "No current tracker research row; wait for a fresh tracker refresh."
    elif days is not None and number(days, 999) <= 5:
        label = "WAIT FOR EVENT"
        next_step = "Event timing is close; refresh the watchlist context before relying on it."
    elif evidence_grade in {"A", "B"} and trigger:
        label = "RESEARCH FIRST"
        next_step = "Read the current thesis and price context before considering any action."
    else:
        label = "KEEP ON WATCH"
        next_step = "Monitor for cleaner confirmation; this is not an entry instruction."
    if flags:
        next_step += " Caveat: " + ", ".join(flags[:3]) + "."
    return {
        "ticker": symbol,
        "label": label,
        "category": text(conviction.get("category") or edge.get("category")) or "Unclassified",
        "edgeScore": round(number(edge.get("edgeScore")), 2) if edge else None,
        "convictionAdjustedScore": (
            round(number(conviction.get("convictionAdjustedScore")), 2) if conviction else None
        ),
        "evidenceGrade": evidence_grade,
        "readiness": conviction.get("readiness", edge.get("readiness")),
        "daysUntilEarnings": days,
        "trend": text(conviction.get("trend")) or None,
        "researchAction": text(conviction.get("researchAction")) or "monitor only",
        "thesis": text(conviction.get("thesis") or edge.get("thesis")) or "No current thesis was published.",
        "riskFlags": flags,
        "nextResearchStep": next_step,
    }


def build_watchlist_brief(
    *,
    edge_research: dict[str, Any] | None = None,
    conviction_research: dict[str, Any] | None = None,
    watchlist_input: dict[str, Any] | None = None,
    limit: int = 3,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a compact, watchlist-first research artifact.

    The focus order comes from the already-ranked edge artifact.  This function
    never computes a replacement threshold or treats a score as an order.
    """
    now = now or local_now()
    edge = edge_research if isinstance(edge_research, dict) else (load_json_file(EDGE_RESEARCH_FILE) or {})
    conviction = (
        conviction_research
        if isinstance(conviction_research, dict)
        else (load_json_file(CONVICTION_RESEARCH_FILE) or {})
    )
    input_payload = watchlist_input if isinstance(watchlist_input, dict) else (load_json_file(WATCHLIST_INPUT_FILE) or {})
    input_status = watchlist_input_status(input_payload, now=now)
    edge_map = _index_rows(edge)
    conviction_map = _index_rows(conviction)
    tracker_symbols = list(conviction_map)

    priority_rows = edge.get("researchWatchlist") or []
    ordered_priorities = [
        ticker(row.get("ticker"))
        for row in priority_rows
        if isinstance(row, dict) and ticker(row.get("ticker"))
    ]
    if input_status["usableForOrdering"]:
        ordered = list(input_status["tickers"])
        source = {
            "kind": "operator-watchlist-input",
            "description": "fresh explicit watchlist input, joined to current research artifacts",
            "tickerCount": len(ordered),
        }
    else:
        ordered = ordered_priorities
        source = {
            "kind": "current-tracker-research-priorities",
            "description": "current full tracker narrowed by the existing edge-research watchlist",
            "tickerCount": len(tracker_symbols),
            "priorityCount": len(ordered),
        }
    if not ordered:
        ordered = tracker_symbols
        source["description"] = "current full tracker; no edge-research priority list was available"

    rows = [_brief_row(symbol, edge_map.get(symbol), conviction_map.get(symbol)) for symbol in ordered]
    limit = max(int(limit), 1)
    # Keep the source artifact's ordering inside each label, but place its
    # existing higher-confidence rows ahead of watch-only rows. This is a
    # display grouping, not a replacement score or a new qualification gate.
    focus_first = [row for row in rows if row["label"] == "RESEARCH FIRST"]
    remaining = [row for row in rows if row["label"] != "RESEARCH FIRST"]
    display_rows = focus_first + remaining
    focus = display_rows[:limit]
    monitor = display_rows[limit : limit * 2]
    unavailable = [row for row in rows if row["label"] == "DATA CHECK"]
    usable_rows = [row for row in rows if row["label"] != "DATA CHECK"]
    verdict = "ready" if usable_rows else "no-current-research"

    return {
        "generatedAt": now.isoformat(),
        "stage": WATCHLIST_BRIEF_STAGE,
        "verdict": verdict,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "watchlistSource": source,
        "savedInputStatus": input_status,
        "sourceArtifacts": {
            "edgeResearchGeneratedAt": edge.get("generatedAt"),
            "convictionResearchGeneratedAt": conviction.get("generatedAt"),
            "fullTrackerRows": len(tracker_symbols),
            "edgeResearchPriorityRows": len(ordered_priorities),
        },
        "focus": focus,
        "monitor": monitor,
        "unavailable": unavailable,
        "safety": [
            "Research priorities only; not a buy, sell, or options order.",
            "Does not create or require a ticket tracker, approval, or sizing workflow.",
            "Existing risk, quality, freshness, and authority gates remain unchanged.",
        ],
    }


def _render_row(index: int, row: dict[str, Any]) -> list[str]:
    """Format one operator-readable research item."""
    edge = f"edge {row['edgeScore']:.2f}" if row.get("edgeScore") is not None else "edge unavailable"
    conviction = (
        f"conviction {row['convictionAdjustedScore']:.2f} ({row.get('evidenceGrade')})"
        if row.get("convictionAdjustedScore") is not None
        else "conviction unavailable"
    )
    earnings = row.get("daysUntilEarnings")
    timing = f" | earnings {earnings}d" if earnings is not None else ""
    lines = [
        f"{index}. {row.get('ticker')} — {row.get('label')} | {row.get('category')} | {edge} | {conviction}{timing}",
        f"   {row.get('thesis')}",
        f"   Next: {row.get('nextResearchStep')}",
    ]
    return lines


def watchlist_brief_text(payload: dict[str, Any]) -> str:
    """Render the one-screen watchlist research brief."""
    source = payload.get("watchlistSource") or {}
    saved = payload.get("savedInputStatus") or {}
    lines = [
        "Inferno Watchlist Brief — research only",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Source: {source.get('kind')} — {source.get('description')}",
        "",
        "FOCUS — research these first (not orders):",
    ]
    focus = payload.get("focus") or []
    if focus:
        for index, row in enumerate(focus, start=1):
            lines.extend(_render_row(index, row))
    else:
        lines.append("- No current research rows are available; wait for a tracker refresh.")

    monitor = payload.get("monitor") or []
    if monitor:
        lines.extend(["", "KEEP ON WATCH:"])
        for index, row in enumerate(monitor, start=1):
            lines.extend(_render_row(index, row))

    unavailable = payload.get("unavailable") or []
    if unavailable:
        lines.extend(["", "DATA TO REFRESH:"])
        lines.append("- " + ", ".join(row.get("ticker") or "?" for row in unavailable))

    if saved.get("count") and not saved.get("usableForOrdering"):
        lines.extend(
            [
                "",
                "SAVED PERSONAL-LIST NOTE:",
                f"- {saved.get('source')} contains {saved.get('count')} symbol(s), but it was not used: {saved.get('reason')}.",
            ]
        )

    lines.extend(["", "Safety:"])
    for item in payload.get("safety") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def save_watchlist_brief(payload: dict[str, Any]) -> None:
    """Persist only this read-only reporting artifact."""
    ensure_dirs()
    atomic_write_json(WATCHLIST_BRIEF_FILE, payload)
    atomic_write_text(WATCHLIST_BRIEF_TEXT_FILE, watchlist_brief_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a compact research-only watchlist brief.")
    parser.add_argument("command", nargs="?", default="run", choices=("run", "status"))
    parser.add_argument("--limit", type=int, default=3, help="Number of focus names to display.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and WATCHLIST_BRIEF_TEXT_FILE.exists():
        print(WATCHLIST_BRIEF_TEXT_FILE.read_text(encoding="utf-8"), end="")
        return 0
    payload = build_watchlist_brief(limit=args.limit)
    save_watchlist_brief(payload)
    print(watchlist_brief_text(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
