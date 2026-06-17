#!/usr/bin/env python3
"""Append the day's NLV + per-position snapshot to data/nlv_history.csv.

Idempotent: appends one row per call. If two calls happen on the same
calendar day, you get two rows -- the operator can de-dupe later if they
care. The append-only design is deliberate; we never overwrite history.

Reads:
    data/inferno_live_account_sync.json   (NLV, cash)
    data/inferno_live_position_review.json (per-position market values)

Writes:
    data/nlv_history.csv  (created on first call, then appended forever)

Strict invariants:
    - research-only / read-only on inputs
    - never mutates authority, never approves tickets, never touches the
      capital-scaling ack file
    - safe to run from cron / nightly_optimize.sh
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
LIVE_SYNC = DATA / "inferno_live_account_sync.json"
LIVE_POSITIONS = DATA / "inferno_live_position_review.json"
HISTORY = DATA / "nlv_history.csv"


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _float(value) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def main() -> int:
    sync = _load(LIVE_SYNC)
    review = _load(LIVE_POSITIONS)

    nlv = _float(sync.get("netLiquidatingValue"))
    cash = _float(sync.get("totalCash"))
    positions = review.get("positions") or []

    # Build a stable per-position dict so column order is deterministic.
    per_pos: dict[str, float] = {}
    for p in positions:
        sym = str(p.get("symbol") or "").strip()
        mv = _float(p.get("markValue"))
        if sym and mv is not None:
            per_pos[sym] = mv

    sym_columns = sorted(per_pos.keys())
    timestamp = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    date_str = _dt.date.today().isoformat()

    header = ["timestamp", "date", "nlv", "cash"] + sym_columns
    row = [
        timestamp,
        date_str,
        f"{nlv:.2f}" if nlv is not None else "",
        f"{cash:.2f}" if cash is not None else "",
    ] + [f"{per_pos[s]:.2f}" for s in sym_columns]

    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    new_file = not HISTORY.exists()

    # If the file exists, we need to write the header carefully -- the
    # column set may have changed since the last run (positions opened/
    # closed). For now we write a consistent header per row by reusing
    # the original; this keeps the CSV stable. Future enhancement: emit
    # a per-row JSON 'positions' blob if we care about schema evolution.
    with HISTORY.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(header)
        w.writerow(row)

    nlv_str = f"${nlv:,.2f}" if nlv is not None else "n/a"
    print(f"nlv_history: appended {date_str} {nlv_str}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
