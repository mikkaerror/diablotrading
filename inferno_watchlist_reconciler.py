from __future__ import annotations

"""Inferno Watchlist Reconciler — the double-check pass.

What it does:
    Takes three views of "the ticker universe" — what the TOS watchlist
    extractor saw, what the Google Sheet column A says, and what the local
    tracker artifacts contain — and reports drift between them. Drift is the
    early warning that something fell through the cracks of the ingest path.

What it does NOT do:
    - Write to the Google Sheet (the ingest module owns that).
    - Touch TOS in any way (the extractor module owns that).
    - Mutate authority, paper ledger, or approval queue.

Strict contract: read-only. Outputs a diagnostic JSON + an operator memo.

Three-way drift buckets::

    inTosOnly        — TOS watchlist has it; sheet does not. Operator should
                       run ingest apply.
    inSheetOnly      — sheet has it; TOS does not. Either the operator removed
                       it from TOS deliberately, or the sheet has stale rows.
    inTrackerOnly    — local tracker rows have it; sheet does not. Suggests
                       the sheet got out of sync with a downstream artifact.
    everywhere       — clean. Reported only as a count.

The verdict ladder mirrors the rest of the desk::

    clean        — every TOS ticker is in the sheet and vice versa.
    drift-minor  — small in-tos-only set (operator just hasn't run apply yet).
    drift-major  — anything bigger or any in-sheet-only.
    blocked      — couldn't read one of the three views (no extract, no sheet
                   access). Verdict is "blocked" so the autorefresh stops
                   silently swallowing the problem.
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


WATCHLIST_RECONCILER_FILE = DATA_DIR / "inferno_watchlist_reconciler.json"
WATCHLIST_RECONCILER_TEXT_FILE = REPORTS_DIR / "watchlist_reconciler_latest.txt"
WATCHLIST_RECONCILER_STAGE = "watchlist-reconciler-research-only"

# Tunables — small drift is normal between the extractor pass and the
# operator confirming apply. We don't want to fire major-drift alarms on a
# single new ticker still waiting for an apply.
MINOR_DRIFT_LIMIT = int(os.environ.get("INFERNO_WATCHLIST_MINOR_DRIFT_LIMIT", "3"))


# ---------------------------------------------------------------------------
# Source loaders — each is replaceable in tests.
# ---------------------------------------------------------------------------


def _load_tos_extract_tickers(
    path: Path = DATA_DIR / "inferno_tos_watchlist_extract.json",
) -> tuple[list[str], dict[str, Any]]:
    """Read the TOS extract artifact. Returns (tickers, diagnostic)."""
    diag: dict[str, Any] = {"source": str(path)}
    if not path.exists():
        diag["error"] = "extract artifact missing — run inferno_tos_watchlist_extract.py first"
        return [], diag
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        diag["error"] = f"extract unreadable: {exc}"
        return [], diag
    tickers = payload.get("tickers") or []
    diag["extractedAt"] = payload.get("generatedAt")
    diag["verdict"] = payload.get("verdict")
    diag["fallbackUsed"] = payload.get("fallbackUsed")
    return [str(t).strip().upper() for t in tickers if t], diag


def _load_sheet_tickers() -> tuple[list[str], dict[str, Any]]:
    """Read column A of the Earnings Tracker via the existing pipeline helpers.

    Lazy-imports gspread machinery so tests don't need the dependency stack.
    Returns ``([], {"error": "..."})`` on any failure.
    """
    diag: dict[str, Any] = {"source": "google-sheets:Earnings Tracker"}
    try:
        from inferno_config import DEFAULT_SHEET_NAME, default_backtest_root
        from morning_inferno_pipeline import get_sheet, load_tracker_ticker_rows
    except Exception as exc:  # noqa: BLE001
        diag["error"] = f"sheet-helpers-unavailable: {type(exc).__name__}: {exc}"
        return [], diag
    try:
        sheet = get_sheet(default_backtest_root(), DEFAULT_SHEET_NAME)
        _raw, tickers, _invalid = load_tracker_ticker_rows(sheet)
    except Exception as exc:  # noqa: BLE001
        diag["error"] = f"sheet-read-failed: {type(exc).__name__}: {exc}"
        return [], diag
    return [str(t).strip().upper() for t in tickers if t], diag


def _load_tracker_tickers() -> tuple[list[str], dict[str, Any]]:
    """Read the local tracker universe artifact."""
    diag: dict[str, Any] = {}
    candidates = (
        DATA_DIR / "inferno_ticker_universe_audit.json",
        DATA_DIR / "inferno_tracker.json",
        DATA_DIR / "inferno_score_sheet.json",
    )
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows: list[Any] = []
        if isinstance(payload, dict):
            rows = (
                payload.get("tickers")
                or payload.get("symbols")
                or payload.get("rows")
                or payload.get("items")
                or []
            )
        elif isinstance(payload, list):
            rows = payload
        tickers: list[str] = []
        for row in rows:
            if isinstance(row, str):
                symbol = row.strip().upper()
            elif isinstance(row, dict):
                symbol = str(row.get("ticker") or row.get("symbol") or "").strip().upper()
            else:
                continue
            if symbol:
                tickers.append(symbol)
        if tickers:
            diag["source"] = str(candidate)
            diag["count"] = len(tickers)
            return tickers, diag
    diag["error"] = "no tracker artifact found (tried 3 canonical locations)"
    return [], diag


# ---------------------------------------------------------------------------
# Pure builder.
# ---------------------------------------------------------------------------


def build_reconciliation(
    *,
    tos_loader: Callable[[], tuple[list[str], dict[str, Any]]] | None = None,
    sheet_loader: Callable[[], tuple[list[str], dict[str, Any]]] | None = None,
    tracker_loader: Callable[[], tuple[list[str], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Run the three-way diff. Pure: no disk writes here."""
    tos_tickers, tos_diag = (tos_loader or _load_tos_extract_tickers)()
    sheet_tickers, sheet_diag = (sheet_loader or _load_sheet_tickers)()
    tracker_tickers, tracker_diag = (tracker_loader or _load_tracker_tickers)()

    tos_set = set(tos_tickers)
    sheet_set = set(sheet_tickers)
    tracker_set = set(tracker_tickers)

    in_tos_only = sorted(tos_set - sheet_set)
    in_sheet_only = sorted(sheet_set - tos_set)
    in_tracker_only = sorted(tracker_set - sheet_set)
    everywhere = sorted(tos_set & sheet_set & tracker_set)

    blocked_reasons: list[str] = []
    if "error" in tos_diag:
        blocked_reasons.append(f"tos-extract: {tos_diag['error']}")
    if "error" in sheet_diag:
        blocked_reasons.append(f"sheet: {sheet_diag['error']}")
    if "error" in tracker_diag:
        # Tracker absence is non-fatal — we can still surface tos vs sheet.
        pass

    if blocked_reasons:
        verdict = "blocked"
        narrative = (
            "Reconciler couldn't compare all three views; drift cannot be "
            "trusted. Reasons: " + "; ".join(blocked_reasons)
        )
    elif not in_tos_only and not in_sheet_only:
        verdict = "clean"
        narrative = (
            f"All {len(everywhere)} ticker(s) align across TOS, sheet, and tracker. "
            "No action needed."
        )
    elif not in_sheet_only and len(in_tos_only) <= MINOR_DRIFT_LIMIT:
        verdict = "drift-minor"
        narrative = (
            f"Small drift: {len(in_tos_only)} ticker(s) in TOS but not yet in the "
            f"sheet ({', '.join(in_tos_only)}). Run inferno_watchlist_ingest.py "
            "apply to push them in."
        )
    else:
        verdict = "drift-major"
        pieces = []
        if in_tos_only:
            pieces.append(f"{len(in_tos_only)} in TOS-only ({', '.join(in_tos_only[:6])}{'…' if len(in_tos_only) > 6 else ''})")
        if in_sheet_only:
            pieces.append(f"{len(in_sheet_only)} in sheet-only ({', '.join(in_sheet_only[:6])}{'…' if len(in_sheet_only) > 6 else ''})")
        narrative = (
            "Major drift detected — " + "; ".join(pieces) + ". Operator review recommended."
        )

    return {
        "generatedAt": local_now().isoformat(),
        "stage": WATCHLIST_RECONCILER_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "tosTickerCount": len(tos_set),
        "sheetTickerCount": len(sheet_set),
        "trackerTickerCount": len(tracker_set),
        "everywhereCount": len(everywhere),
        "inTosOnly": in_tos_only,
        "inSheetOnly": in_sheet_only,
        "inTrackerOnly": in_tracker_only,
        "blockedReasons": blocked_reasons,
        "tosDiagnostic": tos_diag,
        "sheetDiagnostic": sheet_diag,
        "trackerDiagnostic": tracker_diag,
        "minorDriftLimit": MINOR_DRIFT_LIMIT,
        "reminders": [
            "reconciler is read-only across all three sources",
            "drift-minor means run ingest apply",
            "drift-major usually means stale sheet rows or TOS panel changed",
        ],
    }


def reconciliation_text(payload: dict[str, Any]) -> str:
    """Render reconciler payload to an operator memo."""
    lines = [
        "Inferno Watchlist Reconciler (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"TOS tickers: {payload.get('tosTickerCount')}  "
        f"Sheet tickers: {payload.get('sheetTickerCount')}  "
        f"Tracker tickers: {payload.get('trackerTickerCount')}  "
        f"Everywhere: {payload.get('everywhereCount')}",
        "",
        f"Narrative: {payload.get('narrative')}",
    ]
    blocked = payload.get("blockedReasons") or []
    if blocked:
        lines.extend(["", "Blocked reasons:"])
        for reason in blocked:
            lines.append(f"- {reason}")
    in_tos = payload.get("inTosOnly") or []
    if in_tos:
        lines.extend(["", f"In TOS but not in sheet ({len(in_tos)}):"])
        for ticker in in_tos:
            lines.append(f"- {ticker}")
    in_sheet = payload.get("inSheetOnly") or []
    if in_sheet:
        lines.extend(["", f"In sheet but not in TOS ({len(in_sheet)}):"])
        for ticker in in_sheet:
            lines.append(f"- {ticker}")
    in_tracker_only = payload.get("inTrackerOnly") or []
    if in_tracker_only:
        lines.extend(["", f"In tracker but not in sheet ({len(in_tracker_only)}):"])
        for ticker in in_tracker_only[:20]:
            lines.append(f"- {ticker}")
        if len(in_tracker_only) > 20:
            lines.append(f"... (+{len(in_tracker_only) - 20} more)")
    lines.extend(["", "Reminders:"])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_reconciliation(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(WATCHLIST_RECONCILER_FILE, payload)
    atomic_write_text(WATCHLIST_RECONCILER_TEXT_FILE, reconciliation_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Three-way drift check across TOS extract, Google Sheet, and local tracker. "
            "Research-only; never writes to TOS or the sheet."
        )
    )
    parser.add_argument(
        "command", nargs="?", default="run", choices=["run", "status"]
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and WATCHLIST_RECONCILER_TEXT_FILE.exists():
        print(WATCHLIST_RECONCILER_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_reconciliation()
    save_reconciliation(payload)
    print(reconciliation_text(payload))
    if payload.get("verdict") in {"blocked", "drift-major"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
