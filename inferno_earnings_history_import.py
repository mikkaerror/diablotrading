#!/usr/bin/env python3
"""Earnings-history CSV importer (research-only).

Turns a manually-exported earnings history CSV into the event ledger the
richness signal reads, so the prove-before-spend test is one command instead of
a formatting chore.

Input CSV columns (header row required; extra columns ignored):
    ticker, earningsDate, impliedMovePct, realizedAbsMovePct
  - earningsDate: YYYY-MM-DD
  - impliedMovePct: pre-earnings ATM implied move at entry, in percent (e.g. 8.5)
  - realizedAbsMovePct: abs earnings-day move, in percent (e.g. 6.2)

Output: data/inferno_earnings_history_backfill.json in the ledger event shape,
deduped to one row per (ticker, earningsDate), with moveRatio computed. Point the
signal at it:

    python3 inferno_earnings_history_import.py --csv my_export.csv
    INFERNO_EXPECTED_MOVE_FILE=data/inferno_earnings_history_backfill.json \
        python3 inferno_earnings_richness_signal.py status

Boundary: research-only. Writes a research artifact; touches no gate/authority/risk
and does not overwrite the live expected-move ledger.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path
from typing import Any, Optional

from inferno_config import local_now
from inferno_io import atomic_write_json
from server import DATA_DIR, ensure_dirs


OUTPUT_FILE = DATA_DIR / "inferno_earnings_history_backfill.json"
LIVE_EXPECTED_MOVE_LEDGER = DATA_DIR / "inferno_expected_move_ledger.json"
REQUIRED = ("ticker", "earningsDate", "impliedMovePct", "realizedAbsMovePct")


def _num(v: Any) -> Optional[float]:
    try:
        return float(str(v).strip().replace("%", ""))
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> str | None:
    raw = str(value or "").strip()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return None


def parse_rows(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Return (clean records, warnings). One record per (ticker, earningsDate)."""
    warnings: list[str] = []
    seen: dict[tuple, dict] = {}
    for i, row in enumerate(rows, start=2):  # row 1 is the header
        tkr = (row.get("ticker") or "").strip().upper()
        raw_date = (row.get("earningsDate") or "").strip()
        earnings_date = _date(raw_date)
        implied = _num(row.get("impliedMovePct"))
        realized = _num(row.get("realizedAbsMovePct"))
        if not tkr or not raw_date:
            warnings.append(f"row {i}: missing ticker/earningsDate - skipped")
            continue
        if earnings_date is None:
            warnings.append(f"row {i} ({tkr} {raw_date}): bad earningsDate - skipped")
            continue
        if implied is None or implied <= 0:
            warnings.append(f"row {i} ({tkr} {earnings_date}): bad impliedMovePct - skipped")
            continue
        if realized is None or realized < 0:
            warnings.append(f"row {i} ({tkr} {earnings_date}): bad realizedAbsMovePct - skipped")
            continue
        if realized > 40:
            warnings.append(
                f"row {i} ({tkr} {earnings_date}): realized {realized}% >40% - verify it's a "
                "single earnings-day move, not a multi-day window"
            )
        key = (tkr, earnings_date)
        if key in seen:
            warnings.append(f"row {i} ({tkr} {earnings_date}): duplicate event - kept first")
            continue
        seen[key] = {
            "ticker": tkr,
            "earningsDate": earnings_date,
            "eventId": f"{tkr}|{earnings_date}",
            "reviewedAt": f"{earnings_date}T16:00:00-06:00",
            "impliedMovePct": implied,
            "realizedAbsMovePct": realized,
            "moveRatio": round(realized / implied, 4),
            "family": "LONG_STRADDLE",
            "source": "manual-earnings-history-import",
        }
    records = sorted(seen.values(), key=lambda r: (r["ticker"], r["earningsDate"]))
    return records, warnings


def _normalized_reader_rows(reader: csv.DictReader) -> list[dict[str, Any]]:
    normalized = []
    for row in reader:
        normalized.append({str(key or "").strip(): value for key, value in row.items()})
    return normalized


def _assert_safe_output_path(out_path: Path) -> None:
    if out_path.resolve() == LIVE_EXPECTED_MOVE_LEDGER.resolve():
        raise ValueError("Refusing to overwrite the canonical expected-move ledger; choose a backfill output path.")


def import_csv(csv_path: str, out_path: str | Path = OUTPUT_FILE) -> dict[str, Any]:
    output = Path(out_path)
    _assert_safe_output_path(output)
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED if c not in header]
        if missing:
            raise ValueError(
                f"CSV missing required columns: {missing}. Found: {header}. "
                f"Required: {list(REQUIRED)}"
            )
        rows = _normalized_reader_rows(reader)

    records, warnings = parse_rows(rows)
    from collections import Counter
    per_name = Counter(r["ticker"] for r in records)
    payload = {
        "generatedAt": local_now().isoformat(),
        "stage": "earnings-history-backfill-research-only",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "source": csv_path,
        "records": records,
        "summary": {
            "events": len(records),
            "names": len(per_name),
            "namesWith8Plus": sum(1 for c in per_name.values() if c >= 8),
            "namesWith4Plus": sum(1 for c in per_name.values() if c >= 4),
            "warnings": len(warnings),
        },
    }
    ensure_dirs()
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output, payload)
    return {"payload": payload, "warnings": warnings, "out_path": str(output)}


def _report(result: dict) -> str:
    s = result["payload"]["summary"]
    L = ["Earnings-history import (research-only)",
         f"Wrote {result['out_path']}",
         f"Events: {s['events']} | names: {s['names']} | "
         f">=4 events: {s['namesWith4Plus']} | >=8 events: {s['namesWith8Plus']}"]
    if s["namesWith4Plus"] == 0:
        L.append("NOTE: no name has >=4 events yet - the signal needs depth to rank. "
                 "Add more history per name.")
    if result["warnings"]:
        L.append(f"Warnings ({len(result['warnings'])}):")
        L.extend(f"  - {w}" for w in result["warnings"][:20])
        if len(result["warnings"]) > 20:
            L.append(f"  ... and {len(result['warnings']) - 20} more")
    L.append("")
    L.append("Next: INFERNO_EXPECTED_MOVE_FILE=" + result["out_path"] +
             " python3 inferno_earnings_richness_signal.py status")
    return "\n".join(L)


def write_template(path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(list(REQUIRED))
        w.writerow(["AAPL", "2026-05-01", "5.8", "3.9"])
        w.writerow(["AAPL", "2026-01-30", "6.1", "7.2"])
        w.writerow(["MSFT", "2026-04-24", "4.9", "2.1"])


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", help="path to the earnings-history CSV to import")
    ap.add_argument("--out", default=OUTPUT_FILE)
    ap.add_argument("--template", metavar="PATH",
                    help="write a blank CSV template to PATH and exit")
    args = ap.parse_args(argv)
    if args.template:
        write_template(args.template)
        print(f"Template written to {args.template} (columns: {', '.join(REQUIRED)})")
        return 0
    if not args.csv:
        ap.error("provide --csv PATH (or --template PATH to get a blank template)")
    result = import_csv(args.csv, args.out)
    print(_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
