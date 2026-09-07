from __future__ import annotations

"""Event-move calibration from the desk's own price history (research-only).

Why this exists
---------------
The premium hurdle in ``inferno_expected_move_ledger`` compares an *event*
implied move to a *daily* ATR. Earnings gaps on the desk's universe (semis,
construction/infrastructure, high-beta "big movers") are routinely 2-4x a
daily range, so a daily-ATR yardstick labels normal event pricing as
"extreme" and demotes exactly the names the desk trades. This module measures
what these names actually do so the hurdle can be judged against evidence
instead of a fixed multiple.

Method (inferred, labelled as such)
-----------------------------------
For every symbol with >= ``MIN_CANDLES`` daily candles in the Schwab price
history tape, take the largest absolute close-to-close moves that also carry
a volume surge (``MIN_VOLUME_RATIO`` x the trailing 20-day average), keep at
most ``MAX_EVENTS_PER_SYMBOL`` events spaced >= ``MIN_EVENT_SPACING_DAYS``
trading days apart (roughly quarterly), and record for each:

    realizedAbsMovePct   |close_t / close_{t-1} - 1|
    atrPercent           trailing 20-day mean true range / prior close
    moveAtrMultiple      realizedAbsMovePct / atrPercent

No earnings calendar is consulted; a picked day is a *large-move day*.
``eventSource`` is "inferred-large-move-volume-surge" on every row. When a
curated earnings history backfill exists it is preferred per symbol and
labelled.

Known biases (Codex review, 2026-09-07) — this is DESCRIPTIVE, not a fitted
or unbiased calibration:
  * Outcome selection: the largest volume-confirmed moves of a year are a
    tail sample; non-earnings shocks inflate the medians upward.
  * Horizon mismatch: an option's implied move spans days-to-expiration,
    the realized move here is one close-to-close session, so
    implied/realized ratios sit above 1 even when premium is fair.
Consumers therefore treat inferred rows as context only; only curated
earnings rows may drive a hurdle label.

Outputs
-------
``data/inferno_event_move_calibration.json`` and
``reports/event_move_calibration_latest.txt``: per-symbol median event move,
median move/ATR multiple, sample size, and a universe-level quartile table
that ``premium_hurdle`` may consume as an evidence-based benchmark.

Boundary: research-only. No gate, threshold, authority, risk constant,
universe, or ticket is changed here.
"""

import argparse
import json
import statistics
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


EVENT_MOVE_CALIBRATION_STAGE = "event-move-calibration-research-only"
PRICE_HISTORY_FILE = DATA_DIR / "inferno_schwab_price_history.json"
EARNINGS_BACKFILL_FILE = DATA_DIR / "inferno_earnings_history_backfill.json"
EVENT_MOVE_CALIBRATION_FILE = DATA_DIR / "inferno_event_move_calibration.json"
EVENT_MOVE_CALIBRATION_TEXT_FILE = REPORTS_DIR / "event_move_calibration_latest.txt"

MIN_CANDLES = 120
ATR_WINDOW = 20
MIN_VOLUME_RATIO = 1.8
MIN_EVENT_SPACING_DAYS = 45
MAX_EVENTS_PER_SYMBOL = 4
MIN_EVENTS_FOR_SYMBOL_BENCHMARK = 2
INFERRED_SOURCE = "inferred-large-move-volume-surge"
CURATED_SOURCE = "curated-earnings-history-backfill"

CITATIONS = [
    "Dubinsky, Johannes, Kaeck & Seeger (2019), 'Option Pricing of Earnings Announcement Risks' — event jumps dominate short-dated option variance; a daily-range yardstick understates event risk.",
    "Desk artifact: data/inferno_schwab_price_history.json (Schwab daily candles, read-only).",
]


def number(value: Any) -> float | None:
    """Coerce loosely typed artifact values into floats."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def quantile(values: list[float], q: float) -> float | None:
    """Nearest-rank quantile on a sorted copy; None when empty."""
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return round(ordered[index], 4)


def daily_rows(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn raw candles into per-day true-range %, move %, and volume rows."""
    rows: list[dict[str, Any]] = []
    for prev, cur in zip(candles, candles[1:]):
        prev_close = number(prev.get("close"))
        high = number(cur.get("high"))
        low = number(cur.get("low"))
        close = number(cur.get("close"))
        if not prev_close or high is None or low is None or close is None:
            continue
        true_range = max(high - low, abs(high - prev_close), abs(low - prev_close))
        rows.append(
            {
                "date": str(cur.get("datetime") or cur.get("date") or "")[:10],
                "trueRangePct": true_range / prev_close * 100.0,
                "absMovePct": abs(close - prev_close) / prev_close * 100.0,
                "volume": number(cur.get("volume")) or 0.0,
            }
        )
    return rows


def infer_events(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pick the symbol's largest volume-confirmed move days, roughly quarterly spaced."""
    rows = daily_rows(candles)
    if len(rows) <= ATR_WINDOW:
        return []
    scored: list[dict[str, Any]] = []
    for index in range(ATR_WINDOW, len(rows)):
        window = rows[index - ATR_WINDOW : index]
        atr_pct = statistics.mean(r["trueRangePct"] for r in window)
        avg_volume = statistics.mean(r["volume"] for r in window) or 1.0
        row = rows[index]
        if atr_pct <= 0:
            continue
        scored.append(
            {
                "index": index,
                "date": row["date"],
                "realizedAbsMovePct": round(row["absMovePct"], 4),
                "atrPercent": round(atr_pct, 4),
                "moveAtrMultiple": round(row["absMovePct"] / atr_pct, 4),
                "volumeRatio": round(row["volume"] / avg_volume, 4),
                "eventSource": INFERRED_SOURCE,
            }
        )
    scored.sort(key=lambda r: r["realizedAbsMovePct"], reverse=True)
    picked: list[dict[str, Any]] = []
    for candidate in scored:
        if candidate["volumeRatio"] < MIN_VOLUME_RATIO:
            continue
        if any(abs(candidate["index"] - p["index"]) < MIN_EVENT_SPACING_DAYS for p in picked):
            continue
        picked.append(candidate)
        if len(picked) >= MAX_EVENTS_PER_SYMBOL:
            break
    picked.sort(key=lambda r: r["date"])
    return [{k: v for k, v in p.items() if k != "index"} for p in picked]


def curated_events(backfill: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """Group curated earnings-history rows by ticker when a backfill exists."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in (backfill or {}).get("events") or (backfill or {}).get("items") or []:
        ticker = str(item.get("ticker") or "").upper().strip()
        realized = number(item.get("realizedAbsMovePct"))
        if not ticker or realized is None:
            continue
        grouped.setdefault(ticker, []).append(
            {
                "date": str(item.get("earningsDate") or "")[:10],
                "realizedAbsMovePct": round(realized, 4),
                "impliedMovePct": number(item.get("impliedMovePct")),
                "atrPercent": number(item.get("atrPercent")),
                "moveAtrMultiple": None,
                "eventSource": CURATED_SOURCE,
            }
        )
    return grouped


def symbol_summary(symbol: str, events: list[dict[str, Any]], source: str) -> dict[str, Any]:
    """Summarize one symbol's event history into benchmark numbers."""
    moves = [e["realizedAbsMovePct"] for e in events if e.get("realizedAbsMovePct") is not None]
    multiples = [e["moveAtrMultiple"] for e in events if e.get("moveAtrMultiple") is not None]
    return {
        "symbol": symbol,
        "eventCount": len(events),
        "eventSource": source,
        "benchmarkReady": len(moves) >= MIN_EVENTS_FOR_SYMBOL_BENCHMARK,
        "medianRealizedAbsMovePct": round(statistics.median(moves), 4) if moves else None,
        "maxRealizedAbsMovePct": round(max(moves), 4) if moves else None,
        "medianMoveAtrMultiple": round(statistics.median(multiples), 4) if multiples else None,
        "events": events,
    }


def build_calibration(
    price_history: dict[str, Any] | None = None,
    backfill: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the research-only event-move calibration payload."""
    history = price_history if price_history is not None else (load_json_file(PRICE_HISTORY_FILE) or {})
    curated = curated_events(backfill if backfill is not None else load_json_file(EARNINGS_BACKFILL_FILE))
    symbols: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in history.get("rows") or []:
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        if symbol in curated:
            symbols.append(symbol_summary(symbol, curated[symbol], CURATED_SOURCE))
            continue
        candles = row.get("candles") or []
        if len(candles) < MIN_CANDLES:
            skipped.append({"symbol": symbol, "reason": f"only {len(candles)} candles (< {MIN_CANDLES})"})
            continue
        events = infer_events(candles)
        if not events:
            skipped.append({"symbol": symbol, "reason": "no volume-confirmed large-move day"})
            continue
        symbols.append(symbol_summary(symbol, events, INFERRED_SOURCE))
    for symbol, events in curated.items():
        if not any(s["symbol"] == symbol for s in symbols):
            symbols.append(symbol_summary(symbol, events, CURATED_SOURCE))
    symbols.sort(key=lambda s: s["symbol"])

    all_moves = [e["realizedAbsMovePct"] for s in symbols for e in s["events"] if e.get("realizedAbsMovePct") is not None]
    all_multiples = [e["moveAtrMultiple"] for s in symbols for e in s["events"] if e.get("moveAtrMultiple") is not None]
    universe = {
        "eventCount": len(all_moves),
        "symbolCount": len(symbols),
        "realizedAbsMovePct": {"p25": quantile(all_moves, 0.25), "median": quantile(all_moves, 0.5), "p75": quantile(all_moves, 0.75), "p90": quantile(all_moves, 0.9)},
        "moveAtrMultiple": {"p25": quantile(all_multiples, 0.25), "median": quantile(all_multiples, 0.5), "p75": quantile(all_multiples, 0.75), "p90": quantile(all_multiples, 0.9)},
        "shareAbove1p25Atr": round(sum(m > 1.25 for m in all_multiples) / len(all_multiples), 4) if all_multiples else None,
        "shareAbove3Atr": round(sum(m > 3.0 for m in all_multiples) / len(all_multiples), 4) if all_multiples else None,
    }
    ready = sum(1 for s in symbols if s["benchmarkReady"])
    return {
        "generatedAt": local_now().isoformat(),
        "stage": EVENT_MOVE_CALIBRATION_STAGE,
        "verdict": "descriptive" if len(all_moves) >= 20 and ready >= 5 else "insufficient-data",
        "biasDisclosure": [
            "inferred events are the largest volume-confirmed moves of the year: outcome-selected tail evidence, medians biased upward",
            "realized move is one close-to-close session; option implied moves span days-to-expiration",
            "inferred rows are descriptive context only; hurdle labels use curated earnings rows or the ATR ladder",
        ],
        "counts": {"symbols": len(symbols), "benchmarkReady": ready, "events": len(all_moves), "skipped": len(skipped)},
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "sourceGeneratedAt": history.get("generatedAt"),
        "method": {
            "atrWindow": ATR_WINDOW,
            "minVolumeRatio": MIN_VOLUME_RATIO,
            "minEventSpacingDays": MIN_EVENT_SPACING_DAYS,
            "maxEventsPerSymbol": MAX_EVENTS_PER_SYMBOL,
            "inferredSource": INFERRED_SOURCE,
            "note": "Inferred events are large-move days, not verified earnings dates; curated backfill rows override per symbol.",
        },
        "universe": universe,
        "symbols": symbols,
        "skipped": skipped,
        "citations": CITATIONS,
        "reminders": [
            "research-only; no threshold, gate, authority, or ticket changes",
            "descriptive tail evidence, not a fitted calibration; see biasDisclosure",
            "inferred events are labelled; prefer a curated earnings backfill when available",
        ],
    }


def symbol_benchmarks(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Return {symbol: summary} for benchmark-ready symbols from a saved payload."""
    result: dict[str, dict[str, Any]] = {}
    for item in (payload or {}).get("symbols") or []:
        if item.get("benchmarkReady") and item.get("symbol"):
            result[str(item["symbol"]).upper()] = item
    return result


def calibration_text(payload: dict[str, Any]) -> str:
    """Render the human report."""
    universe = payload.get("universe") or {}
    mult = universe.get("moveAtrMultiple") or {}
    move = universe.get("realizedAbsMovePct") or {}
    lines = [
        "Inferno Event-Move Calibration (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')} | verdict: {payload.get('verdict')}",
        f"Source price history: {payload.get('sourceGeneratedAt')}",
        "",
        f"Universe: {universe.get('symbolCount')} symbols | {universe.get('eventCount')} events",
        f"- realized |move| %: p25 {move.get('p25')} | median {move.get('median')} | p75 {move.get('p75')} | p90 {move.get('p90')}",
        f"- move / daily ATR:  p25 {mult.get('p25')} | median {mult.get('median')} | p75 {mult.get('p75')} | p90 {mult.get('p90')}",
        f"- share of events > 1.25x ATR: {universe.get('shareAbove1p25Atr')} | > 3.0x ATR: {universe.get('shareAbove3Atr')}",
        "",
        "Per symbol (median |move| %, median move/ATR, events, source):",
    ]
    for item in payload.get("symbols") or []:
        lines.append(
            f"- {item['symbol']}: {item.get('medianRealizedAbsMovePct')}% | {item.get('medianMoveAtrMultiple')}x | "
            f"{item.get('eventCount')} | {item.get('eventSource')}{'' if item.get('benchmarkReady') else ' | not benchmark-ready'}"
        )
    if payload.get("skipped"):
        lines.append("")
        lines.append("Skipped:")
        for item in payload["skipped"]:
            lines.append(f"- {item['symbol']}: {item['reason']}")
    lines.append("")
    lines.append("Bias disclosure:")
    for item in payload.get("biasDisclosure") or []:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("Reminders:")
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines) + "\n"


def save_calibration(payload: dict[str, Any]) -> None:
    """Persist JSON + text artifacts."""
    ensure_dirs()
    atomic_write_json(EVENT_MOVE_CALIBRATION_FILE, payload)
    atomic_write_text(EVENT_MOVE_CALIBRATION_TEXT_FILE, calibration_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only event-move calibration from local price history.")
    parser.add_argument("command", nargs="?", choices=("run", "status"), default="run")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        payload = load_json_file(EVENT_MOVE_CALIBRATION_FILE)
        if not payload:
            print("no event-move calibration artifact yet; run `python3 inferno_event_move_calibration.py run`")
            return 1
    else:
        payload = build_calibration()
        save_calibration(payload)
    print(json.dumps(payload, indent=2) if args.json else calibration_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
