from __future__ import annotations

"""Research-only expected-move ledger for long-vol option structures.

Long straddles and strangles do not merely need direction; they need realised
movement large enough to outrun premium, spread, and time decay. This module
audits closed long-vol records against the move implied by breakevens or, when
breakevens are absent, by the entry debit.

Strict contract:
- diagnostic-only and research-only
- no broker calls, approvals, order creation, or authority promotion
- the debit-implied move is a desk proxy, not an exchange or broker IV feed
"""

import argparse
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


EXPECTED_MOVE_LEDGER_FILE = DATA_DIR / "inferno_expected_move_ledger.json"
EXPECTED_MOVE_LEDGER_TEXT_FILE = REPORTS_DIR / "expected_move_ledger_latest.txt"
EXPECTED_MOVE_LEDGER_STAGE = "expected-move-ledger-research-only"

PAPER_EXECUTION_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
SHADOW_EVIDENCE_FILE = DATA_DIR / "inferno_shadow_evidence.json"
PAPER_BOTTLENECK_REDUCER_FILE = DATA_DIR / "inferno_paper_bottleneck_reducer.json"
SCHWAB_PRICE_HISTORY_FILE = DATA_DIR / "inferno_schwab_price_history.json"

MIN_EXPECTED_MOVE_SAMPLE = 10
CONTRACT_MULTIPLIER = 100.0
CHRONOLOGICAL_COHORT_COUNT = 4
EVENT_DATE_CLUSTER_DAYS = 3
IMPLAUSIBLE_EARNINGS_MOVE_PCT = 40.0

HURDLE_REASONABLE_ATR_MULTIPLE = 1.25
HURDLE_STRETCH_ATR_MULTIPLE = 2.0
HURDLE_HARD_ATR_MULTIPLE = 3.0
HURDLE_PENALTIES = {
    "reasonable": 0.0,
    "stretch": 6.0,
    "hard": 12.0,
    "extreme": 20.0,
    "unknown": 0.0,
    "unpriced": 0.0,
}


def text(value: Any) -> str:
    """Normalize loose artifact values into stripped text."""
    return str(value or "").strip()


def number(value: Any, default: float | None = None) -> float | None:
    """Coerce artifact values to floats while tolerating display strings."""
    if isinstance(value, (int, float)):
        return float(value)
    raw = text(value).replace("$", "").replace(",", "").replace("%", "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def norm(value: Any) -> str:
    """Uppercase normalization for strategy/ticker matching."""
    return text(value).upper()


def is_long_vol_strategy(value: Any) -> bool:
    """Return True for long-vol structures where movement is the main hurdle."""
    raw = norm(value).replace("_", " ")
    return "STRADDLE" in raw or "STRANGLE" in raw


def long_vol_family(value: Any) -> str:
    """Collapse strategy names into expected-move families."""
    raw = norm(value).replace("_", " ")
    if "STRANGLE" in raw:
        return "LONG_STRANGLE"
    if "STRADDLE" in raw:
        return "LONG_STRADDLE"
    return "OTHER"


def first_number(*values: Any) -> float | None:
    """Return the first parseable numeric value from a candidate list."""
    for value in values:
        parsed = number(value)
        if parsed is not None:
            return parsed
    return None


def parse_date(value: Any) -> date | None:
    """Normalize loose date/datetime artifact values to a calendar date."""
    raw = text(value)
    if not raw:
        return None
    if "|" in raw:
        raw = raw.rsplit("|", 1)[-1]
    if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_datetime(value: Any) -> datetime | None:
    """Normalize loose artifact timestamps for snapshot ordering."""
    raw = text(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        parsed = parse_date(raw)
        return datetime.combine(parsed, datetime.min.time()) if parsed else None


def entry_reference_date(entry: dict[str, Any]) -> date | None:
    """Return the date used to infer legacy earnings events."""
    for field in ("tradeDate", "createdAt", "sourceStrikePlanGeneratedAt", "generatedAt", "refreshedAt"):
        parsed = parse_date(entry.get(field))
        if parsed:
            return parsed
    return None


def entry_reference_datetime(entry: dict[str, Any]) -> datetime | None:
    """Return the best timestamp for choosing the last pre-event snapshot."""
    for field in ("createdAt", "sourceStrikePlanGeneratedAt", "refreshedAt", "tradeDate", "generatedAt"):
        parsed = parse_datetime(entry.get(field))
        if parsed:
            return parsed
    return None


EVENT_DATE_FIELDS = (
    "eventId",
    "nextEarnings",
    "earningsDate",
    "reportDate",
    "eventDate",
    "earningsAt",
    "earningsDateTime",
)
EVENT_CONTEXT_FIELDS = ("trackerContext", "marketContext", "marketContextSummary", "strikePlan")


def earnings_event_candidate(entry: dict[str, Any]) -> tuple[date | None, str]:
    """Return the best available earnings event date plus provenance."""
    for field in EVENT_DATE_FIELDS:
        parsed = parse_date(entry.get(field))
        if parsed:
            return parsed, f"explicit-{field}"
    for context_field in EVENT_CONTEXT_FIELDS:
        context = entry.get(context_field) or {}
        if not isinstance(context, dict):
            continue
        for field in EVENT_DATE_FIELDS:
            parsed = parse_date(context.get(field))
            if parsed:
                return parsed, f"explicit-{context_field}.{field}"

    base = entry_reference_date(entry)
    days = number(entry.get("daysUntilEarnings"))
    if base and days is not None:
        return base + timedelta(days=int(days)), "derived-tradeDate-plus-daysUntilEarnings"

    expiration = parse_date(entry.get("expiration") or (entry.get("strikePlan") or {}).get("expiration"))
    if expiration:
        return expiration, "fallback-expiration"
    return None, "missing-event-date"


def candle_date(candle: dict[str, Any]) -> date | None:
    """Return a daily candle date from Schwab-style history rows."""
    parsed = parse_date(candle.get("datetime") or candle.get("date"))
    if parsed:
        return parsed
    raw = number(candle.get("datetime"))
    if raw is not None:
        try:
            return datetime.utcfromtimestamp(raw / 1000.0).date()
        except (OverflowError, OSError, ValueError):
            return None
    return None


def price_history_by_symbol(payload: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """Index daily close history by ticker symbol."""
    if not payload:
        return {}
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if rows is None and isinstance(payload, dict):
        rows = [
            {"symbol": symbol, "candles": row.get("candles") if isinstance(row, dict) else row}
            for symbol, row in payload.items()
            if isinstance(row, (dict, list))
        ]
    indexed: dict[str, list[dict[str, Any]]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        symbol = norm(row.get("symbol") or row.get("ticker"))
        candles: list[dict[str, Any]] = []
        for candle in row.get("candles") or []:
            if not isinstance(candle, dict):
                continue
            parsed_date = candle_date(candle)
            close = number(candle.get("close") or candle.get("Close"))
            if parsed_date and close is not None and close > 0:
                candles.append({"date": parsed_date, "close": close})
        if symbol and candles:
            indexed[symbol] = sorted(candles, key=lambda item: item["date"])
    return indexed


def earnings_day_reaction(
    *,
    ticker: str,
    event_date: date,
    price_history: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Compute abs(close(T+1) / close(T-1) - 1) from daily candles."""
    candles = price_history.get(norm(ticker)) or []
    before = [row for row in candles if row["date"] < event_date]
    after = [row for row in candles if row["date"] > event_date]
    if not before or not after:
        return {
            "status": "missing-price-history",
            "realizedAbsMovePct": None,
            "reactionStartDate": before[-1]["date"].isoformat() if before else None,
            "reactionEndDate": after[0]["date"].isoformat() if after else None,
            "reactionStartClose": before[-1]["close"] if before else None,
            "reactionEndClose": after[0]["close"] if after else None,
        }
    start = before[-1]
    end = after[0]
    realized = abs((end["close"] / start["close"]) - 1.0) * 100.0
    return {
        "status": "computed",
        "realizedAbsMovePct": round(realized, 4),
        "reactionStartDate": start["date"].isoformat(),
        "reactionEndDate": end["date"].isoformat(),
        "reactionStartClose": round(start["close"], 4),
        "reactionEndClose": round(end["close"], 4),
        "realizedMoveSource": "schwab-daily-close-t-plus-1-over-t-minus-1",
    }


def underlying_entry_price(entry: dict[str, Any]) -> float | None:
    """Return the best available underlying price at trade/scenario entry."""
    market = entry.get("marketContextSummary") or {}
    return first_number(
        entry.get("underlyingPrice"),
        entry.get("entryUnderlyingPrice"),
        entry.get("baselineUnderlyingPrice"),
        entry.get("currentUnderlyingPrice"),
        entry.get("price"),
        market.get("underlyingPrice"),
        market.get("price"),
    )


def underlying_exit_price(entry: dict[str, Any]) -> float | None:
    """Return the best available underlying exit/review price."""
    outcome = entry.get("outcome") or {}
    return first_number(
        outcome.get("exitUnderlyingPrice"),
        outcome.get("currentUnderlyingPrice"),
        entry.get("exitUnderlyingPrice"),
    )


def entry_debit(entry: dict[str, Any]) -> float | None:
    """Return the per-share debit proxy for one long-vol structure."""
    direct = first_number(entry.get("entryLimit"), entry.get("debit"), entry.get("entryDebit"))
    if direct and direct > 0:
        return direct
    max_loss = first_number(entry.get("estimatedMaxLoss"), entry.get("maxLossDollars"))
    if max_loss and max_loss > 0:
        multiplier = first_number(entry.get("contractMultiplier")) or CONTRACT_MULTIPLIER
        return max_loss / multiplier
    return None


def implied_move_pct(entry: dict[str, Any], baseline: float) -> tuple[float | None, str]:
    """Return the minimum breakeven move or a debit proxy as percent of price."""
    lower = number(entry.get("lowerBreakEven"))
    upper = number(entry.get("upperBreakEven"))
    candidates: list[float] = []
    if lower is not None and lower < baseline:
        candidates.append(((baseline - lower) / baseline) * 100.0)
    if upper is not None and upper > baseline:
        candidates.append(((upper - baseline) / baseline) * 100.0)
    positive = [value for value in candidates if value > 0]
    if positive:
        return round(min(positive), 4), "breakeven-min"
    debit = entry_debit(entry)
    if debit and debit > 0:
        return round((debit / baseline) * 100.0, 4), "debit-proxy"
    return None, "missing-premium"


def atr_percent(entry: dict[str, Any], baseline: float | None = None) -> float | None:
    """Return ATR percent from reducer context, or derive it from ATR dollars."""
    market = entry.get("marketContextSummary") or {}
    direct = first_number(entry.get("atrPercent"), market.get("atrPercent"))
    if direct and direct > 0:
        return direct
    atr = first_number(entry.get("atr20Day"), market.get("atr20Day"))
    if atr and baseline and baseline > 0:
        return round((atr / baseline) * 100.0, 4)
    return None


def premium_hurdle(
    *,
    entry: dict[str, Any],
    implied_pct: float | None,
    baseline: float | None,
) -> dict[str, Any]:
    """Classify the premium hurdle relative to ATR for diagnostic ranking pressure."""
    scenario_score = number(entry.get("scenarioScore"))
    if implied_pct is None:
        label = "unpriced"
        penalty = HURDLE_PENALTIES[label]
        return {
            "label": label,
            "atrPercent": atr_percent(entry, baseline),
            "requiredMoveAtrMultiple": None,
            "rankPenalty": penalty,
            "rankPressureScore": scenario_score,
            "action": "cannot evaluate premium hurdle until the candidate has a priced move",
        }

    atr = atr_percent(entry, baseline)
    if atr is None or atr <= 0:
        label = "unknown"
        penalty = HURDLE_PENALTIES[label]
        return {
            "label": label,
            "atrPercent": atr,
            "requiredMoveAtrMultiple": None,
            "rankPenalty": penalty,
            "rankPressureScore": scenario_score,
            "action": "missing ATR context; do not reward the long-vol structure for price alone",
        }

    multiple = round(implied_pct / atr, 4)
    if multiple <= HURDLE_REASONABLE_ATR_MULTIPLE:
        label = "reasonable"
        action = "no premium demotion from ATR hurdle"
    elif multiple <= HURDLE_STRETCH_ATR_MULTIPLE:
        label = "stretch"
        action = "require catalyst and IV-expansion confirmation before favoring long vol"
    elif multiple <= HURDLE_HARD_ATR_MULTIPLE:
        label = "hard"
        action = "demote long vol unless alternatives have worse defined-risk math"
    else:
        label = "extreme"
        action = "prefer a defined-risk alternative unless the catalyst is exceptional"
    penalty = HURDLE_PENALTIES[label]
    adjusted = round(max(0.0, scenario_score - penalty), 4) if scenario_score is not None else None
    return {
        "label": label,
        "atrPercent": round(atr, 4),
        "requiredMoveAtrMultiple": multiple,
        "rankPenalty": penalty,
        "rankPressureScore": adjusted,
        "action": action,
    }


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
    """Return closed outcome return in R units if enough data exists."""
    outcome = entry.get("outcome") or {}
    direct = number(outcome.get("estimatedReturnOnRisk"))
    if direct is not None:
        return round(direct, 6)
    pnl = number(outcome.get("estimatedPnl"))
    risk = max_loss(entry)
    if pnl is None or risk <= 0:
        return None
    return round(pnl / risk, 6)


def closed_long_vol_candidate(entry: dict[str, Any]) -> bool:
    """Return True when a source item is closed long-vol evidence."""
    strategy = entry.get("strategy") or entry.get("setupRec")
    outcome = entry.get("outcome") or {}
    return is_long_vol_strategy(strategy) and text(outcome.get("status")).lower() == "closed"


def event_group_key(row: dict[str, Any]) -> tuple[str, str]:
    """Return the dedupe key for one normalized source row."""
    return norm(row.get("ticker")), text(row.get("canonicalEventDate"))


def canonicalize_event_dates(
    rows: list[dict[str, Any]],
    *,
    cluster_days: int = EVENT_DATE_CLUSTER_DAYS,
) -> dict[str, Any]:
    """Collapse adjacent inferred dates for the same ticker into one event."""
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_ticker[norm(row.get("ticker"))].append(row)

    clustered_events: list[dict[str, Any]] = []
    for ticker, ticker_rows in by_ticker.items():
        explicit = [row for row in ticker_rows if text(row.get("eventDateSource")).startswith("explicit")]
        inferred = [row for row in ticker_rows if row not in explicit]

        for row in explicit:
            row["canonicalEventDate"] = row["eventDate"].isoformat()
            row["canonicalEventDateSource"] = row["eventDateSource"]

        ordered_dates = sorted({row["eventDate"] for row in inferred if row.get("eventDate")})
        clusters: list[list[date]] = []
        for candidate in ordered_dates:
            if not clusters or (candidate - clusters[-1][-1]).days > cluster_days:
                clusters.append([candidate])
            else:
                clusters[-1].append(candidate)

        for cluster in clusters:
            counts = {
                candidate: sum(1 for row in inferred if row.get("eventDate") == candidate)
                for candidate in cluster
            }
            canonical = sorted(counts, key=lambda item: (-counts[item], item))[0]
            for row in inferred:
                if row.get("eventDate") in set(cluster):
                    row["canonicalEventDate"] = canonical.isoformat()
                    row["canonicalEventDateSource"] = "inferred-clustered-daysUntilEarnings"
            clustered_events.append(
                {
                    "ticker": ticker,
                    "canonicalEventDate": canonical.isoformat(),
                    "candidateDates": [item.isoformat() for item in cluster],
                    "snapshotCount": sum(counts.values()),
                    "dateCounts": {item.isoformat(): count for item, count in counts.items()},
                }
            )

    return {
        "clusteredInferredEvents": clustered_events,
        "clusterWindowDays": cluster_days,
    }


def choose_event_snapshot(rows: list[dict[str, Any]], event_date: date) -> dict[str, Any]:
    """Choose the actual paper row or latest pre-event shadow snapshot."""
    def sort_key(row: dict[str, Any]) -> tuple[int, int, str, str]:
        entry = row["entry"]
        ref = entry_reference_datetime(entry) or datetime.min
        ref_date = ref.date()
        is_pre_event = ref_date <= event_date
        source_priority = 1 if row.get("source") == "paper" else 0
        status_priority = 1 if text(entry.get("status")).lower() == "paper-staged" else 0
        return (
            source_priority,
            status_priority,
            ref.isoformat() if is_pre_event else "",
            text(entry.get("ticketId")),
        )

    pre_event = [row for row in rows if (entry_reference_date(row["entry"]) or date.max) <= event_date]
    candidates = pre_event or rows
    return sorted(candidates, key=sort_key)[-1]


def closed_expected_move_record(
    entry: dict[str, Any],
    source: str,
    *,
    event_date: date,
    event_date_source: str,
    duplicate_entries: list[dict[str, Any]],
    price_history: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    """Normalize one closed long-vol record into expected-move evidence."""
    strategy = entry.get("strategy") or entry.get("setupRec")
    if not closed_long_vol_candidate(entry):
        return None
    outcome = entry.get("outcome") or {}
    baseline = underlying_entry_price(entry)
    if baseline is None or baseline <= 0:
        return None
    implied, implied_source = implied_move_pct(entry, baseline)
    if implied is None:
        return None
    reaction = earnings_day_reaction(
        ticker=norm(entry.get("ticker")),
        event_date=event_date,
        price_history=price_history,
    )
    realized = number(reaction.get("realizedAbsMovePct"))
    if realized is None:
        return None
    edge = round(realized - implied, 4)
    event_id = f"{norm(entry.get('ticker'))}|{event_date.isoformat()}"
    return {
        "source": source,
        "ticketId": entry.get("ticketId") or entry.get("scenarioId"),
        "eventId": event_id,
        "earningsDate": event_date.isoformat(),
        "earningsDateSource": event_date_source,
        "ticker": norm(entry.get("ticker")),
        "strategy": text(strategy),
        "family": long_vol_family(strategy),
        "baselineUnderlyingPrice": round(baseline, 4),
        "exitUnderlyingPrice": underlying_exit_price(entry),
        "impliedMovePct": implied,
        "impliedMoveSource": implied_source,
        "realizedAbsMovePct": realized,
        "realizedMoveStatus": reaction.get("status"),
        "realizedMoveSource": reaction.get("realizedMoveSource"),
        "reactionStartDate": reaction.get("reactionStartDate"),
        "reactionEndDate": reaction.get("reactionEndDate"),
        "reactionStartClose": reaction.get("reactionStartClose"),
        "reactionEndClose": reaction.get("reactionEndClose"),
        "moveEdgePct": edge,
        "moveRatio": round(realized / implied, 4) if implied > 0 else None,
        "beatImpliedMove": realized >= implied,
        "entryDebit": entry_debit(entry),
        "outcomeR": outcome_r(entry),
        "reviewedAt": outcome.get("reviewedAt"),
        "selectedSnapshotAt": (
            entry_reference_datetime(entry).isoformat()
            if entry_reference_datetime(entry)
            else None
        ),
        "dedupedSnapshotCount": len(duplicate_entries),
        "dedupedTicketIds": sorted(
            text(item.get("ticketId") or item.get("scenarioId"))
            for item in duplicate_entries
            if text(item.get("ticketId") or item.get("scenarioId"))
        ),
    }


def closed_expected_move_evidence(
    *,
    paper_ledger: dict[str, Any] | None = None,
    shadow_ledger: dict[str, Any] | None = None,
    price_history: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return deduped closed long-vol records plus construction diagnostics."""
    paper = paper_ledger if paper_ledger is not None else (load_json_file(PAPER_EXECUTION_LEDGER_FILE) or {})
    shadow = shadow_ledger if shadow_ledger is not None else (load_json_file(SHADOW_EVIDENCE_FILE) or {})
    history_payload = price_history if price_history is not None else (load_json_file(SCHWAB_PRICE_HISTORY_FILE) or {})
    history_index = price_history_by_symbol(history_payload)
    source_rows: list[dict[str, Any]] = []
    for source, payload in (("paper", paper), ("shadow", shadow)):
        for item in payload.get("items") or []:
            if not closed_long_vol_candidate(item):
                continue
            event_date, event_source = earnings_event_candidate(item)
            if not event_date:
                continue
            source_rows.append(
                {
                    "source": source,
                    "entry": item,
                    "ticker": norm(item.get("ticker")),
                    "eventDate": event_date,
                    "eventDateSource": event_source,
                }
            )

    cluster_diagnostics = canonicalize_event_dates(source_rows)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in source_rows:
        if row.get("canonicalEventDate"):
            grouped[event_group_key(row)].append(row)

    records: list[dict[str, Any]] = []
    missing_realized: list[dict[str, Any]] = []
    for key, group in sorted(grouped.items()):
        _, event_text = key
        event_date = parse_date(event_text)
        if not event_date:
            continue
        selected = choose_event_snapshot(group, event_date)
        duplicate_entries = [row["entry"] for row in group]
        record = closed_expected_move_record(
            selected["entry"],
            selected["source"],
            event_date=event_date,
            event_date_source=text(selected.get("canonicalEventDateSource") or selected.get("eventDateSource")),
            duplicate_entries=duplicate_entries,
            price_history=history_index,
        )
        if record:
            records.append(record)
        else:
            missing_realized.append(
                {
                    "eventId": f"{key[0]}|{event_text}",
                    "ticker": key[0],
                    "earningsDate": event_text,
                    "snapshotCount": len(group),
                }
            )

    diagnostics = {
        "sourceClosedLongVolRows": len(source_rows),
        "dedupedEventCount": len(grouped),
        "dedupedExcessSnapshots": max(0, len(source_rows) - len(grouped)),
        "priceHistorySymbols": sorted(history_index),
        "missingRealizedEvents": missing_realized,
        **cluster_diagnostics,
    }
    return records, diagnostics


def closed_expected_move_records(
    *,
    paper_ledger: dict[str, Any] | None = None,
    shadow_ledger: dict[str, Any] | None = None,
    price_history: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return deduped closed paper/shadow long-vol records with move evidence."""
    records, _ = closed_expected_move_evidence(
        paper_ledger=paper_ledger,
        shadow_ledger=shadow_ledger,
        price_history=price_history,
    )
    return records


def current_long_vol_candidate(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Summarize a current slate long-vol candidate without pretending it is evidence."""
    strategy = entry.get("strategy") or entry.get("setupRec")
    if not is_long_vol_strategy(strategy):
        return None
    baseline = underlying_entry_price(entry)
    candidate = {
        "ticker": norm(entry.get("ticker")),
        "rank": entry.get("rank"),
        "strategy": text(strategy),
        "family": long_vol_family(strategy),
        "readiness": number(entry.get("readiness")),
        "scenarioScore": number(entry.get("scenarioScore")),
        "estimatedMaxLoss": number(entry.get("estimatedMaxLoss")),
        "baselineUnderlyingPrice": baseline,
        "paperAutoSelected": bool(entry.get("paperAutoSelected")),
        "shadowOnly": bool(entry.get("shadowOnly")),
        "brokerSubmitAllowed": bool(entry.get("brokerSubmitAllowed")),
        "liveTradingAllowed": bool(entry.get("liveTradingAllowed")),
    }
    if baseline is None or baseline <= 0:
        candidate["status"] = "missing-underlying-price"
        candidate["impliedMovePct"] = None
        candidate["impliedMoveSource"] = None
        hurdle = premium_hurdle(entry=entry, implied_pct=None, baseline=baseline)
        candidate.update(
            {
                "atrPercent": hurdle["atrPercent"],
                "requiredMoveAtrMultiple": hurdle["requiredMoveAtrMultiple"],
                "premiumHurdleLabel": hurdle["label"],
                "rankPenalty": hurdle["rankPenalty"],
                "rankPressureScore": hurdle["rankPressureScore"],
                "hurdleAction": hurdle["action"],
            }
        )
        return candidate
    implied, implied_source = implied_move_pct(entry, baseline)
    candidate["impliedMovePct"] = implied
    candidate["impliedMoveSource"] = implied_source
    candidate["status"] = "priced" if implied is not None else implied_source
    hurdle = premium_hurdle(entry=entry, implied_pct=implied, baseline=baseline)
    candidate.update(
        {
            "atrPercent": hurdle["atrPercent"],
            "requiredMoveAtrMultiple": hurdle["requiredMoveAtrMultiple"],
            "premiumHurdleLabel": hurdle["label"],
            "rankPenalty": hurdle["rankPenalty"],
            "rankPressureScore": hurdle["rankPressureScore"],
            "hurdleAction": hurdle["action"],
        }
    )
    return candidate


def current_long_vol_candidates(
    paper_reducer: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return current reducer long-vol candidates for operator visibility."""
    reducer = paper_reducer if paper_reducer is not None else (load_json_file(PAPER_BOTTLENECK_REDUCER_FILE) or {})
    rows: list[dict[str, Any]] = []
    for item in reducer.get("scenarioSlate") or []:
        candidate = current_long_vol_candidate(item)
        if candidate:
            rows.append(candidate)
    return rows


def mean(values: list[float]) -> float | None:
    """Return a rounded arithmetic mean for non-empty samples."""
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def rate(count: int, total: int) -> float | None:
    """Return a rounded count/total rate."""
    if total <= 0:
        return None
    return round(count / total, 4)


def move_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute expected-move summary stats for a record set."""
    beat_count = sum(1 for record in records if record.get("beatImpliedMove"))
    r_values = [number(record.get("outcomeR")) for record in records if number(record.get("outcomeR")) is not None]
    implied = [number(record.get("impliedMovePct")) for record in records if number(record.get("impliedMovePct")) is not None]
    realized = [
        number(record.get("realizedAbsMovePct"))
        for record in records
        if number(record.get("realizedAbsMovePct")) is not None
    ]
    edges = [number(record.get("moveEdgePct")) for record in records if number(record.get("moveEdgePct")) is not None]
    ratios = [number(record.get("moveRatio")) for record in records if number(record.get("moveRatio")) is not None]
    return {
        "sampleCount": len(records),
        "beatCount": beat_count,
        "missCount": len(records) - beat_count,
        "beatRate": rate(beat_count, len(records)),
        "meanImpliedMovePct": mean([value for value in implied if value is not None]),
        "meanRealizedAbsMovePct": mean([value for value in realized if value is not None]),
        "meanMoveEdgePct": mean([value for value in edges if value is not None]),
        "meanMoveRatio": mean([value for value in ratios if value is not None]),
        "meanOutcomeR": mean([value for value in r_values if value is not None]),
    }


def data_integrity(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Detect pseudo-replication and implausible earnings-day realized moves."""
    by_name: dict[str, set[float]] = defaultdict(set)
    by_event: dict[str, int] = defaultdict(int)
    for record in records:
        realized = number(record.get("realizedAbsMovePct"))
        if realized is not None:
            by_name[text(record.get("ticker"))].add(round(realized, 2))
        event_id = text(record.get("eventId"))
        if event_id:
            by_event[event_id] += 1

    n_records = sum(1 for record in records if number(record.get("realizedAbsMovePct")) is not None)
    n_distinct = sum(len(values) for values in by_name.values())
    implausible = sum(
        1
        for record in records
        if (number(record.get("realizedAbsMovePct"), 0.0) or 0.0) > IMPLAUSIBLE_EARNINGS_MOVE_PCT
    )
    frozen = [
        ticker
        for ticker, values in by_name.items()
        if len(values) == 1 and sum(1 for record in records if text(record.get("ticker")) == ticker) > 2
    ]
    duplicate_events = [event_id for event_id, count in by_event.items() if count > 1]
    replication_ratio = (n_records / n_distinct) if n_distinct else float("inf")
    reliable = n_records == 0 or (
        replication_ratio <= 1.5
        and implausible == 0
        and not frozen
        and not duplicate_events
    )
    return {
        "records": n_records,
        "distinctRealizedValues": n_distinct,
        "effectiveObservations": n_distinct,
        "replicationRatio": round(replication_ratio, 2) if n_distinct else None,
        "implausibleMagnitudeRecords": implausible,
        "implausibleMagnitudeThresholdPct": IMPLAUSIBLE_EARNINGS_MOVE_PCT,
        "frozenRealizedNames": sorted(frozen),
        "duplicateEventIds": sorted(duplicate_events),
        "duplicateEventCount": len(duplicate_events),
        "reliable": reliable,
        "ok": reliable,
    }


def group_stats(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Compute move stats grouped by a record key."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[text(record.get(key)) or "unknown"].append(record)
    rows: list[dict[str, Any]] = []
    for label, group in groups.items():
        row = {"group": label, **move_stats(group)}
        rows.append(row)
    return sorted(rows, key=lambda row: (-row["sampleCount"], row["group"]))


def outcome_r_sum(records: list[dict[str, Any]]) -> float | None:
    """Return summed R for records that contain normalized outcomes."""
    values = [
        value
        for record in records
        if (value := number(record.get("outcomeR"))) is not None
    ]
    return round(sum(values), 4) if values else None


def ticker_contribution_stats(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Show which tickers actually contribute the aggregate long-vol result."""
    rows = group_stats(records, "ticker")
    for row in rows:
        ticker_records = [
            record for record in records if (text(record.get("ticker")) or "unknown") == row["group"]
        ]
        row["sumOutcomeR"] = outcome_r_sum(ticker_records)
    return sorted(
        rows,
        key=lambda row: (
            -(number(row.get("sumOutcomeR"), float("-inf")) or 0.0),
            row["group"],
        ),
    )


def chronological_cohorts(
    records: list[dict[str, Any]],
    *,
    cohort_count: int = CHRONOLOGICAL_COHORT_COUNT,
) -> list[dict[str, Any]]:
    """Split dated records into equal chronological cohorts without causal claims."""
    ordered = sorted(
        records,
        key=lambda record: (
            text(record.get("reviewedAt")),
            text(record.get("ticketId")),
        ),
    )
    if not ordered or cohort_count <= 0:
        return []
    cohort_size = max(1, (len(ordered) + cohort_count - 1) // cohort_count)
    rows: list[dict[str, Any]] = []
    for index, start in enumerate(range(0, len(ordered), cohort_size), start=1):
        cohort = ordered[start : start + cohort_size]
        row = {
            "cohort": index,
            "oldestReviewedAt": cohort[0].get("reviewedAt"),
            "newestReviewedAt": cohort[-1].get("reviewedAt"),
            **move_stats(cohort),
            "sumOutcomeR": outcome_r_sum(cohort),
        }
        rows.append(row)
    return rows


def implied_move_bucket(value: Any) -> str:
    """Return the desk's non-overlapping implied-move evidence bucket."""
    parsed = number(value)
    if parsed is None or parsed < 0:
        return "unknown"
    if parsed < 10:
        return "0-10%"
    if parsed < 20:
        return "10-20%"
    if parsed < 30:
        return "20-30%"
    if parsed < 50:
        return "30-50%"
    if parsed < 100:
        return "50-100%"
    return "100%+"


def implied_move_bucket_stats(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize result shape by the premium hurdle the market charged."""
    order = ["0-10%", "10-20%", "20-30%", "30-50%", "50-100%", "100%+", "unknown"]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[implied_move_bucket(record.get("impliedMovePct"))].append(record)
    rows: list[dict[str, Any]] = []
    for label in order:
        group = groups.get(label) or []
        if group:
            rows.append({"bucket": label, **move_stats(group), "sumOutcomeR": outcome_r_sum(group)})
    return rows


def evidence_quality_diagnostics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Surface internal conflicts and repeated scenario fingerprints."""
    metric_conflicts = [
        record
        for record in records
        if number(record.get("outcomeR"), 0.0) > 0 and not record.get("beatImpliedMove")
    ]
    fingerprints: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for record in records:
        fingerprint = (
            record.get("ticker"),
            record.get("baselineUnderlyingPrice"),
            record.get("exitUnderlyingPrice"),
            record.get("impliedMovePct"),
            record.get("entryDebit"),
            record.get("outcomeR"),
        )
        fingerprints[fingerprint].append(text(record.get("ticketId")))
    repeated = [
        {"count": len(ticket_ids), "ticketIds": ticket_ids}
        for ticket_ids in fingerprints.values()
        if len(ticket_ids) > 1
    ]
    repeated.sort(key=lambda row: -row["count"])
    return {
        "positiveRButMissedImpliedMoveCount": len(metric_conflicts),
        "positiveRButMissedImpliedMoveTicketIds": [
            record.get("ticketId") for record in metric_conflicts
        ],
        "repeatedFingerprintGroups": len(repeated),
        "repeatedFingerprintExcessRecords": sum(row["count"] - 1 for row in repeated),
        "largestRepeatedFingerprintGroups": repeated[:10],
        "interpretation": (
            "Outcome-R and expected-move math are different measures, but positive R while "
            "missing the implied move requires reconciliation before promotion. Repeated "
            "fingerprints after per-event dedupe remain visible for reconciliation."
        ),
    }


def concentration_diagnostics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure how much aggregate R depends on the best historical tickers."""
    contributions = ticker_contribution_stats(records)
    positive = [
        row for row in contributions if (number(row.get("sumOutcomeR"), 0.0) or 0.0) > 0
    ]
    top = positive[:2]
    top_tickers = [row["group"] for row in top]
    top_sum = sum(number(row.get("sumOutcomeR"), 0.0) or 0.0 for row in top)
    positive_sum = sum(number(row.get("sumOutcomeR"), 0.0) or 0.0 for row in positive)
    remaining = [
        record for record in records if text(record.get("ticker")) not in set(top_tickers)
    ]
    return {
        "topPositiveContributors": top,
        "topPositiveContributorTickers": top_tickers,
        "topTwoSumOutcomeR": round(top_sum, 4),
        "shareOfPositiveOutcomeR": (
            round(top_sum / positive_sum, 4) if positive_sum > 0 else None
        ),
        "excludingTopTwo": {
            **move_stats(remaining),
            "sumOutcomeR": outcome_r_sum(remaining),
        },
        "interpretation": (
            "Concentration is descriptive, not a repeatable edge. The leave-top-two-out "
            "result is the conservative prior until fresh, risk-passed evidence exists."
        ),
    }


def regime_diagnostics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Build concentration, recency, premium-bucket, and data-quality diagnostics."""
    cohorts = chronological_cohorts(records)
    recent = cohorts[-1] if cohorts else {}
    concentration = concentration_diagnostics(records)
    quality = evidence_quality_diagnostics(records)
    recent_mean_r = number(recent.get("meanOutcomeR"))
    recent_beat_rate = number(recent.get("beatRate"))
    leave_out_mean_r = number((concentration.get("excludingTopTwo") or {}).get("meanOutcomeR"))
    fragile = any(
        value is not None and value < 0
        for value in (recent_mean_r, leave_out_mean_r)
    ) or (recent_beat_rate is not None and recent_beat_rate < 0.25)
    return {
        "verdict": "historical-edge-not-admissible" if fragile else "historical-edge-watch",
        "tickerContributions": ticker_contribution_stats(records),
        "concentration": concentration,
        "chronologicalCohorts": cohorts,
        "recentCohort": recent,
        "impliedMoveBuckets": implied_move_bucket_stats(records),
        "evidenceQuality": quality,
        "causalClaimAllowed": False,
        "promotionEvidenceEligible": False,
        "policyInference": (
            "Keep long-vol above a 20% implied move shadow-only until fresh risk-passed "
            "evidence overturns the negative recent and leave-out priors."
        ),
    }


def hurdle_counts(candidates: list[dict[str, Any]]) -> dict[str, int]:
    """Count current candidates by premium-hurdle label."""
    counts: dict[str, int] = {}
    for item in candidates:
        label = text(item.get("premiumHurdleLabel")) or "unknown"
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def top_pressure_candidates(candidates: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    """Return candidates most pressured by the premium hurdle."""
    pressured = [
        item
        for item in candidates
        if number(item.get("rankPenalty"), 0.0)
    ]
    pressured.sort(
        key=lambda item: (
            -(number(item.get("rankPenalty"), 0.0) or 0.0),
            -(number(item.get("requiredMoveAtrMultiple"), 0.0) or 0.0),
            text(item.get("ticker")),
        )
    )
    return pressured[:limit]


def ledger_verdict(stats: dict[str, Any]) -> str:
    """Return a conservative expected-move verdict."""
    sample_count = int(stats.get("sampleCount") or 0)
    if sample_count < MIN_EXPECTED_MOVE_SAMPLE:
        return "insufficient-data"
    mean_edge = number(stats.get("meanMoveEdgePct"), 0.0) or 0.0
    beat_rate = number(stats.get("beatRate"), 0.0) or 0.0
    if mean_edge > 0 and beat_rate >= 0.55:
        return "move-edge-positive"
    if mean_edge < 0 or beat_rate < 0.45:
        return "move-edge-negative"
    return "move-edge-watch"


def build_expected_move_ledger(
    *,
    paper_ledger: dict[str, Any] | None = None,
    shadow_ledger: dict[str, Any] | None = None,
    paper_reducer: dict[str, Any] | None = None,
    price_history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the research-only expected-move ledger."""
    ensure_dirs()
    closed_records, construction = closed_expected_move_evidence(
        paper_ledger=paper_ledger,
        shadow_ledger=shadow_ledger,
        price_history=price_history,
    )
    current_candidates = current_long_vol_candidates(paper_reducer)
    stats = move_stats(closed_records)
    integrity = data_integrity(closed_records)
    priced_current = [
        item
        for item in current_candidates
        if item.get("status") == "priced"
    ]
    missing_current = [
        item
        for item in current_candidates
        if item.get("status") != "priced"
    ]
    pressure_candidates = top_pressure_candidates(current_candidates)
    diagnostics = regime_diagnostics(closed_records)
    return {
        "generatedAt": local_now().isoformat(),
        "stage": EXPECTED_MOVE_LEDGER_STAGE,
        "verdict": ledger_verdict(stats),
        "researchOnly": True,
        "diagnosticOnly": True,
        "promotable": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "counts": {
            "closedLongVolRecords": len(closed_records),
            "withExpectedMove": len(closed_records),
            "sourceClosedLongVolRows": construction.get("sourceClosedLongVolRows", len(closed_records)),
            "dedupedEventCount": construction.get("dedupedEventCount", len(closed_records)),
            "dedupedExcessSnapshots": construction.get("dedupedExcessSnapshots", 0),
            "missingRealizedEvents": len(construction.get("missingRealizedEvents") or []),
            "currentLongVolCandidates": len(current_candidates),
            "currentPricedCandidates": len(priced_current),
            "currentMissingPriceOrPremium": len(missing_current),
            "currentPremiumPressured": len(pressure_candidates),
        },
        "overall": stats,
        "dataIntegrity": integrity,
        "constructionDiagnostics": construction,
        "byFamily": group_stats(closed_records, "family"),
        "bySource": group_stats(closed_records, "source"),
        "regimeDiagnostics": diagnostics,
        "currentHurdleCounts": hurdle_counts(current_candidates),
        "currentPressureCandidates": pressure_candidates,
        "closedRecords": closed_records,
        "currentCandidates": current_candidates,
        "reminders": [
            "A long-vol ticket needs realised move to clear premium, spread, and decay; direction alone is not enough.",
            "Breakeven distance is preferred; debit/underlying is used only when breakevens are absent.",
            "Closed evidence is one row per ticker plus earnings date; repeated snapshots are collapsed before stats.",
            "Realised move is the earnings-day close reaction, not entry-to-expiration drift.",
            "This artifact is diagnostic only and cannot promote live or paper authority.",
        ],
    }


def pct(value: Any) -> str:
    """Render a decimal rate as a compact percentage."""
    parsed = number(value)
    if parsed is None:
        return "n/a"
    return f"{parsed * 100:.1f}%"


def fmt(value: Any, *, suffix: str = "") -> str:
    """Render optional numeric values compactly."""
    parsed = number(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:.4g}{suffix}"


def expected_move_ledger_text(payload: dict[str, Any]) -> str:
    """Render the expected-move ledger memo."""
    counts = payload.get("counts") or {}
    overall = payload.get("overall") or {}
    diagnostics = payload.get("regimeDiagnostics") or {}
    integrity = payload.get("dataIntegrity") or {}
    construction = payload.get("constructionDiagnostics") or {}
    concentration = diagnostics.get("concentration") or {}
    recent = diagnostics.get("recentCohort") or {}
    quality = diagnostics.get("evidenceQuality") or {}
    lines = [
        "Inferno Expected Move Ledger",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Verdict: {payload.get('verdict')}",
        "Authority: research-only; promotable=False; liveTradingAllowed=False",
        "",
        "Counts:",
        f"- closed long-vol records: {counts.get('closedLongVolRecords', 0)}",
        f"- source closed long-vol rows: {counts.get('sourceClosedLongVolRows', 0)}",
        f"- deduped excess snapshots: {counts.get('dedupedExcessSnapshots', 0)}",
        f"- missing realized events: {counts.get('missingRealizedEvents', 0)}",
        f"- current long-vol candidates: {counts.get('currentLongVolCandidates', 0)}",
        f"- current priced candidates: {counts.get('currentPricedCandidates', 0)}",
        f"- current missing price/premium: {counts.get('currentMissingPriceOrPremium', 0)}",
        f"- current premium-pressured: {counts.get('currentPremiumPressured', 0)}",
        "",
        "Closed long-vol expected-move summary:",
        f"- beat rate: {pct(overall.get('beatRate'))} "
        f"({overall.get('beatCount', 0)}/{overall.get('sampleCount', 0)})",
        f"- mean implied move: {fmt(overall.get('meanImpliedMovePct'), suffix='%')}",
        f"- mean realised abs move: {fmt(overall.get('meanRealizedAbsMovePct'), suffix='%')}",
        f"- mean move edge: {fmt(overall.get('meanMoveEdgePct'), suffix='%')}",
        f"- mean outcome R: {fmt(overall.get('meanOutcomeR'))}",
        "",
        "Data integrity:",
        f"- reliable: {integrity.get('reliable')}",
        f"- records/distinct realized: {integrity.get('records')}/{integrity.get('distinctRealizedValues')}",
        f"- replication ratio: {fmt(integrity.get('replicationRatio'))}",
        f"- >{fmt(integrity.get('implausibleMagnitudeThresholdPct'), suffix='%')} moves: "
        f"{integrity.get('implausibleMagnitudeRecords')}",
        f"- frozen names: {', '.join(integrity.get('frozenRealizedNames') or []) or 'none'}",
        f"- duplicate events: {integrity.get('duplicateEventCount')}",
        f"- price-history symbols: {len(construction.get('priceHistorySymbols') or [])}",
        "",
        "Regime and evidence diagnostics:",
        f"- verdict: {diagnostics.get('verdict')}",
        f"- top positive contributors: "
        f"{', '.join(concentration.get('topPositiveContributorTickers') or []) or 'none'}",
        f"- excluding top two: n={((concentration.get('excludingTopTwo') or {}).get('sampleCount', 0))} | "
        f"beat={pct((concentration.get('excludingTopTwo') or {}).get('beatRate'))} | "
        f"mean R={fmt((concentration.get('excludingTopTwo') or {}).get('meanOutcomeR'))}",
        f"- recent cohort: n={recent.get('sampleCount', 0)} | "
        f"beat={pct(recent.get('beatRate'))} | mean R={fmt(recent.get('meanOutcomeR'))}",
        f"- positive-R / missed-implied conflicts: "
        f"{quality.get('positiveRButMissedImpliedMoveCount', 0)}",
        f"- repeated fingerprint excess records: "
        f"{quality.get('repeatedFingerprintExcessRecords', 0)}",
        "",
        "Implied-move buckets:",
    ]
    for row in diagnostics.get("impliedMoveBuckets") or []:
        lines.append(
            f"- {row.get('bucket')}: n={row.get('sampleCount')} | "
            f"beat={pct(row.get('beatRate'))} | mean R={fmt(row.get('meanOutcomeR'))} | "
            f"sum R={fmt(row.get('sumOutcomeR'))}"
        )
    lines.extend([
        "",
        f"Current premium hurdle counts: {json.dumps(payload.get('currentHurdleCounts') or {})}",
        "",
        "By family:",
    ])
    if not payload.get("byFamily"):
        lines.append("- no closed long-vol records with expected-move math yet")
    for row in payload.get("byFamily") or []:
        lines.append(
            f"- {row.get('group')}: n={row.get('sampleCount')} | "
            f"beat={pct(row.get('beatRate'))} | "
            f"edge={fmt(row.get('meanMoveEdgePct'), suffix='%')} | "
            f"mean R={fmt(row.get('meanOutcomeR'))}"
        )
    lines.extend(["", "Current long-vol candidates:"])
    if not payload.get("currentCandidates"):
        lines.append("- none")
    for item in payload.get("currentCandidates") or []:
        lines.append(
            f"- {item.get('ticker')}: {item.get('strategy')} | "
            f"status={item.get('status')} | "
            f"score={fmt(item.get('scenarioScore'))} | "
            f"implied={fmt(item.get('impliedMovePct'), suffix='%')} | "
            f"ATRx={fmt(item.get('requiredMoveAtrMultiple'))} | "
            f"hurdle={item.get('premiumHurdleLabel')} | "
            f"pressureScore={fmt(item.get('rankPressureScore'))} | "
            f"paperAutoSelected={item.get('paperAutoSelected')}"
        )
        action = text(item.get("hurdleAction"))
        if action:
            lines.append(f"  hurdle action: {action}")
    lines.extend(["", "Recent closed records:"])
    if not payload.get("closedRecords"):
        lines.append("- none")
    for record in (payload.get("closedRecords") or [])[-8:]:
        lines.append(
            f"- {record.get('ticker')} {record.get('family')}: "
            f"realised={fmt(record.get('realizedAbsMovePct'), suffix='%')} | "
            f"required={fmt(record.get('impliedMovePct'), suffix='%')} "
            f"({record.get('impliedMoveSource')}) | "
            f"edge={fmt(record.get('moveEdgePct'), suffix='%')} | "
            f"beat={record.get('beatImpliedMove')} | R={fmt(record.get('outcomeR'))}"
        )
    lines.extend(["", "Reminders:"])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_expected_move_ledger(payload: dict[str, Any]) -> None:
    """Persist expected-move JSON and text artifacts."""
    ensure_dirs()
    atomic_write_json(EXPECTED_MOVE_LEDGER_FILE, payload)
    atomic_write_text(EXPECTED_MOVE_LEDGER_TEXT_FILE, expected_move_ledger_text(payload))


def parse_args() -> argparse.Namespace:
    """Parse the expected-move CLI."""
    parser = argparse.ArgumentParser(description="Build Inferno long-vol expected-move diagnostics.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    """Run the expected-move ledger CLI."""
    args = parse_args()
    if args.command == "status" and EXPECTED_MOVE_LEDGER_TEXT_FILE.exists():
        print(EXPECTED_MOVE_LEDGER_TEXT_FILE.read_text(encoding="utf-8"))
        latest = json.loads(EXPECTED_MOVE_LEDGER_FILE.read_text(encoding="utf-8")) if EXPECTED_MOVE_LEDGER_FILE.exists() else {}
        return 0 if latest.get("promotable") is False else 1
    payload = build_expected_move_ledger()
    save_expected_move_ledger(payload)
    print(expected_move_ledger_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
