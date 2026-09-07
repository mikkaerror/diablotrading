from __future__ import annotations

"""Fetch real past earnings dates and realized moves for the tracker (research-only).

Why
---
The premium hurdle's per-name basis needs verified earnings dates. The morning
pipeline already calls ``yfinance.Ticker.get_earnings_dates`` for every tracker
name to find the *next* date and discards the past ones. This module keeps
them, pairs each past date with the realized move from daily closes, and hands
the rows to ``inferno_earnings_history_import`` so the calibration and hurdle
pick them up on the next refresh — no manual CSV.

Schwab's Trader API has no earnings-calendar endpoint and the thinkorswim
window only shows the next date, so the provider here is yfinance (the same
dependency the strike selector already carries). It must run where the desk
has network for it (the Mac nightly loop), not in a linked-session VM.

Realized move convention
------------------------
``|close(T+1) / close(T-1) - 1|`` where T is the provider's earnings date —
the same two-session window the expected-move ledger uses
(``schwab-daily-close-t-plus-1-over-t-minus-1``), because provider dates do
not reliably say before-open vs after-close. Recorded as
``realizedMoveWindow="t-1-close-to-t+1-close"``.

Pre-print implied moves are not available historically from this provider;
rows are realized-only (``impliedMovePct`` blank). From now on the Schwab
chain history accumulates implied moves for future events.

Boundary: research-only. Fails soft — if the provider returns nothing, the
previous backfill artifact is left untouched (no clobber).
"""

import argparse
import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file

import inferno_earnings_history_import as importer


EARNINGS_HISTORY_FETCH_STAGE = "earnings-history-fetch-research-only"
SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
PRICE_HISTORY_FILE = DATA_DIR / "inferno_schwab_price_history.json"
FETCHED_CSV_FILE = DATA_DIR / "earnings_history_fetched.csv"
FETCH_STATUS_FILE = DATA_DIR / "inferno_earnings_history_fetch.json"
FETCH_TEXT_FILE = REPORTS_DIR / "earnings_history_fetch_latest.txt"
BACKFILL_FILE = importer.OUTPUT_FILE

PROVIDER_SOURCE = "yfinance-earnings-dates+daily-closes"
REALIZED_WINDOW = "t-1-close-to-t+1-close"
MAX_EVENTS_PER_NAME = 12
LOOKBACK_DAYS = 3 * 365
CSV_COLUMNS = ("ticker", "earningsDate", "impliedMovePct", "realizedAbsMovePct", "source", "realizedMoveWindow")


def tracker_symbols(snapshot: dict[str, Any] | list[dict[str, Any]] | None = None) -> list[str]:
    """Return the tracker's ticker list from the latest snapshot."""
    payload = snapshot if snapshot is not None else (load_json_file(SNAPSHOT_FILE) or [])
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    symbols: list[str] = []
    for row in rows or []:
        ticker = str((row or {}).get("ticker") or "").upper().strip()
        if ticker and ticker not in symbols:
            symbols.append(ticker)
    return symbols


def local_closes(price_history: dict[str, Any] | None = None) -> dict[str, dict[str, float]]:
    """Map symbol -> {date: close} from the Schwab price-history tape."""
    payload = price_history if price_history is not None else (load_json_file(PRICE_HISTORY_FILE) or {})
    result: dict[str, dict[str, float]] = {}
    for row in payload.get("rows") or []:
        symbol = str(row.get("symbol") or "").upper().strip()
        closes = {}
        for candle in row.get("candles") or []:
            day = str(candle.get("datetime") or candle.get("date") or "")[:10]
            try:
                closes[day] = float(candle["close"])
            except (KeyError, TypeError, ValueError):
                continue
        if symbol and closes:
            result[symbol] = closes
    return result


def yfinance_provider(symbol: str) -> tuple[list[str], dict[str, float]]:
    """Return (past earnings dates, {date: close}) from yfinance; empty on any failure."""
    try:
        import yfinance as yf  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        return [], {}
    dates: list[str] = []
    closes: dict[str, float] = {}
    try:
        stock = yf.Ticker(symbol)
        frame = stock.get_earnings_dates(limit=MAX_EVENTS_PER_NAME * 2)
        if frame is not None and not frame.empty:
            for raw in frame.index:
                stamp = raw.to_pydatetime() if hasattr(raw, "to_pydatetime") else raw
                if isinstance(stamp, datetime):
                    dates.append(stamp.date().isoformat())
        history = stock.history(period="3y", auto_adjust=False)
        if history is not None and not history.empty:
            for raw, close in history["Close"].items():
                stamp = raw.to_pydatetime() if hasattr(raw, "to_pydatetime") else raw
                if isinstance(stamp, datetime) and close == close:
                    closes[stamp.date().isoformat()] = float(close)
    except Exception:  # noqa: BLE001
        pass
    return dates, closes


def realized_move(closes: dict[str, float], earnings_date: str) -> float | None:
    """|close(T+1)/close(T-1) - 1| in percent using the nearest sessions around T."""
    if not closes:
        return None
    ordered = sorted(closes)
    before = [d for d in ordered if d < earnings_date]
    after = [d for d in ordered if d > earnings_date]
    if not before or not after:
        return None
    start = closes[before[-1]]
    end = closes[after[0]]
    if not start or start <= 0:
        return None
    return round(abs(end / start - 1.0) * 100.0, 4)


def build_rows(
    symbols: list[str],
    *,
    provider: Callable[[str], tuple[list[str], dict[str, float]]] = yfinance_provider,
    local_close_map: dict[str, dict[str, float]] | None = None,
    today: date | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Build CSV rows for every symbol with usable past events."""
    today = today or local_now().date()
    cutoff = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    local_map = local_close_map if local_close_map is not None else local_closes()
    rows: list[dict[str, str]] = []
    diagnostics: list[dict[str, Any]] = []
    for symbol in symbols:
        dates, provider_closes = provider(symbol)
        closes = {**provider_closes, **local_map.get(symbol, {})}  # Schwab closes win where present
        past = sorted({d for d in dates if cutoff <= d < today.isoformat()}, reverse=True)[:MAX_EVENTS_PER_NAME]
        kept = 0
        for earnings_date in past:
            move = realized_move(closes, earnings_date)
            if move is None:
                continue
            rows.append(
                {
                    "ticker": symbol,
                    "earningsDate": earnings_date,
                    "impliedMovePct": "",
                    "realizedAbsMovePct": f"{move:.4f}",
                    "source": PROVIDER_SOURCE,
                    "realizedMoveWindow": REALIZED_WINDOW,
                }
            )
            kept += 1
        diagnostics.append({"symbol": symbol, "providerDates": len(dates), "pastInWindow": len(past), "eventsKept": kept})
    return rows, diagnostics


def write_csv(rows: list[dict[str, str]], path: Path = FETCHED_CSV_FILE) -> Path:
    """Write the fetched rows in the importer's CSV shape."""
    ensure_dirs()
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CSV_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def fetch_text(payload: dict[str, Any]) -> str:
    """Render the human report."""
    lines = [
        "Inferno Earnings-History Fetch (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')} | verdict: {payload.get('verdict')}",
        f"Provider: {PROVIDER_SOURCE} | realized window: {REALIZED_WINDOW}",
        f"Symbols: {payload.get('symbolCount')} | events written: {payload.get('eventCount')} | names with >=2 events: {payload.get('namesWithTwoPlus')}",
        f"Backfill: {payload.get('backfillPath')}",
        "",
    ]
    if payload.get("verdict") == "provider-empty":
        lines.append("Provider returned no usable dates; previous backfill left untouched (no clobber).")
    thin = [d for d in payload.get("diagnostics") or [] if d.get("eventsKept", 0) < 2]
    if thin:
        lines.append(f"Names with <2 usable events ({len(thin)}): " + ", ".join(d["symbol"] for d in thin[:40]) + (" ..." if len(thin) > 40 else ""))
    lines.extend(["", "Reminders:", "- research-only; provider dates, realized-only rows (implied blank)", "- runs where yfinance has network (Mac nightly loop), not in a linked-session VM"])
    return "\n".join(lines) + "\n"


def build_fetch(
    *,
    symbols: list[str] | None = None,
    provider: Callable[[str], tuple[list[str], dict[str, float]]] = yfinance_provider,
    local_close_map: dict[str, dict[str, float]] | None = None,
    csv_path: Path = FETCHED_CSV_FILE,
    backfill_path: Path = BACKFILL_FILE,
) -> dict[str, Any]:
    """Fetch, write the CSV, and import it into the backfill artifact (fail-soft)."""
    ensure_dirs()
    names = symbols if symbols is not None else tracker_symbols()
    rows, diagnostics = build_rows(names, provider=provider, local_close_map=local_close_map)
    per_name: dict[str, int] = {}
    for row in rows:
        per_name[row["ticker"]] = per_name.get(row["ticker"], 0) + 1
    payload: dict[str, Any] = {
        "generatedAt": local_now().isoformat(),
        "stage": EARNINGS_HISTORY_FETCH_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "symbolCount": len(names),
        "eventCount": len(rows),
        "namesWithTwoPlus": sum(1 for c in per_name.values() if c >= 2),
        "diagnostics": diagnostics,
        "backfillPath": str(backfill_path),
        "citations": ["Realized window matches inferno_expected_move_ledger closed-record convention (T-1 close to T+1 close)."],
    }
    if not rows:
        payload["verdict"] = "provider-empty"
        return payload
    write_csv(rows, csv_path)
    result = importer.import_csv(str(csv_path), backfill_path)
    payload["verdict"] = "fetched"
    payload["importWarnings"] = result["warnings"][:50]
    payload["importSummary"] = result["payload"]["summary"]
    return payload


def save_fetch(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(FETCH_STATUS_FILE, payload)
    atomic_write_text(FETCH_TEXT_FILE, fetch_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch past earnings dates + realized moves into the backfill (research-only).")
    parser.add_argument("command", nargs="?", choices=("run", "status"), default="run")
    parser.add_argument("--symbols", nargs="*", help="Override the tracker universe.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        payload = load_json_file(FETCH_STATUS_FILE)
        if not payload:
            print("no earnings-history fetch artifact yet; run `python3 inferno_earnings_history_fetch.py run` on the Mac")
            return 1
    else:
        payload = build_fetch(symbols=[s.upper() for s in args.symbols] if args.symbols else None)
        save_fetch(payload)
    print(json.dumps(payload, indent=2) if args.json else fetch_text(payload))
    return 0 if payload.get("verdict") == "fetched" else 1


if __name__ == "__main__":
    raise SystemExit(main())
