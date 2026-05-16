from __future__ import annotations

"""Inferno Watchlist Ingest — bridge new tickers from input slot to model.

The operator's morning workflow is: add tickers to the TOS watchlist, then
get those tickers into the Google Sheet that feeds the dawn cycle. This
module sits between those two steps. It supports two input modes:

**Mode A (manual fallback, usable tonight):** the operator writes a tiny
JSON file at ``data/inferno_watchlist_input.json`` containing the new
tickers. The ingest reads that file, diffs against the current ticker
universe, and reports / applies the delta.

**Mode B (TOS automated extraction, future round):** a separate AppleScript
extractor pulls the TOS watchlist via the accessibility tree and writes
the same input file. The ingest module itself stays unchanged — the only
thing that varies is who populated the input file.

CLI:

::

    python3 inferno_watchlist_ingest.py preview        # safe diff against universe
    python3 inferno_watchlist_ingest.py apply          # refuses without --confirm
    python3 inferno_watchlist_ingest.py apply --confirm
    INFERNO_WATCHLIST_CONFIRM=1 python3 inferno_watchlist_ingest.py apply

Strict contract:

- preview mode never writes anything outside this module's own artifacts
- apply mode requires explicit operator confirmation
- the module never modifies authority, never touches the paper ledger,
  never invokes the broker UI, never alters the approval queue
- if the Google-Sheet write helper is unavailable (e.g. credentials
  missing), apply mode short-circuits with a clear FAIL line
"""

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Iterable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


WATCHLIST_INPUT_FILE = DATA_DIR / "inferno_watchlist_input.json"
WATCHLIST_INGEST_FILE = DATA_DIR / "inferno_watchlist_ingest.json"
WATCHLIST_INGEST_TEXT_FILE = REPORTS_DIR / "watchlist_ingest_latest.txt"
WATCHLIST_INGEST_STAGE = "watchlist-ingest-research-only"

# Maximum number of tickers the operator can submit per ingest.
# Conservative cap so a typo doesn't accidentally flood the sheet.
MAX_TICKERS_PER_INGEST = 50

# Allowed ticker shape — uppercase letters, digits, optional dot suffix.
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def load_watchlist_input(
    path: Path = WATCHLIST_INPUT_FILE,
) -> tuple[list[str], str, list[str]]:
    """Load the input file. Returns (tickers, source, validation_errors).

    Validation errors are collected rather than raised so the operator
    sees every problem at once instead of fixing them one at a time.
    """
    errors: list[str] = []
    if not path.exists():
        return [], "missing", [f"input file {path} does not exist"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [], "invalid", [f"{path} unreadable: {exc}"]
    if not isinstance(payload, dict):
        return [], "invalid", [f"{path} top level must be a JSON object"]

    raw_tickers = payload.get("tickers")
    source = str(payload.get("source") or "unspecified")

    if not isinstance(raw_tickers, list):
        errors.append('"tickers" must be a JSON array of strings')
        return [], source, errors

    cleaned: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_tickers):
        if not isinstance(item, str):
            errors.append(f"ticker at index {index} is not a string: {item!r}")
            continue
        symbol = item.strip().upper()
        if not symbol:
            errors.append(f"ticker at index {index} is blank")
            continue
        if not TICKER_PATTERN.match(symbol):
            errors.append(
                f"ticker {symbol!r} at index {index} doesn't match shape "
                f"{TICKER_PATTERN.pattern}"
            )
            continue
        if symbol in seen:
            errors.append(f"duplicate ticker: {symbol}")
            continue
        seen.add(symbol)
        cleaned.append(symbol)

    if len(cleaned) > MAX_TICKERS_PER_INGEST:
        errors.append(
            f"submitted {len(cleaned)} tickers but cap is {MAX_TICKERS_PER_INGEST}; "
            "split into multiple ingests"
        )
        cleaned = cleaned[:MAX_TICKERS_PER_INGEST]

    return cleaned, source, errors


def _default_universe_loader() -> list[str]:
    """Lazy-load the current ticker universe.

    We try a couple of canonical artifact locations. If neither exists we
    return an empty list — diff mode still works (every input ticker is a
    new addition).
    """
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
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(payload, dict):
            # Try a few common shapes.
            rows = (
                payload.get("tickers")
                or payload.get("symbols")
                or payload.get("rows")
                or payload.get("items")
                or []
            )
        elif isinstance(payload, list):
            rows = payload
        else:
            continue
        universe: list[str] = []
        for row in rows:
            if isinstance(row, str):
                symbol = row.strip().upper()
            elif isinstance(row, dict):
                symbol = str(row.get("ticker") or row.get("symbol") or "").strip().upper()
            else:
                continue
            if symbol:
                universe.append(symbol)
        if universe:
            return universe
    return []


def diff_against_universe(
    tickers: list[str], universe: list[str]
) -> dict[str, list[str]]:
    """Split submitted tickers into ``newAdds`` and ``alreadyKnown``."""
    universe_set = {ticker.upper() for ticker in universe}
    new_adds = [ticker for ticker in tickers if ticker not in universe_set]
    already = [ticker for ticker in tickers if ticker in universe_set]
    return {"newAdds": new_adds, "alreadyKnown": already}


def _confirm_present(args: argparse.Namespace) -> bool:
    """Operator-confirmation gate. CLI flag OR environment variable."""
    if getattr(args, "confirm", False):
        return True
    return str(os.environ.get("INFERNO_WATCHLIST_CONFIRM", "")).strip() == "1"


def build_ingest_report(
    *,
    tickers: list[str],
    source: str,
    errors: list[str],
    diff: dict[str, list[str]],
    mode: str,
    applied: bool,
    apply_message: str,
) -> dict[str, Any]:
    """Assemble the structured ingest report."""
    if errors:
        verdict = "input-errors"
        narrative = (
            f"{len(errors)} input validation error(s); preview still ran but "
            "apply will refuse until they are fixed."
        )
    elif not tickers:
        verdict = "empty-input"
        narrative = (
            "Input slot has no tickers. Write a JSON object with a "
            '"tickers" array to ' + str(WATCHLIST_INPUT_FILE) + " and re-run."
        )
    elif mode == "preview":
        verdict = "preview-only"
        narrative = (
            f"Preview only: {len(diff['newAdds'])} new ticker(s) would be added, "
            f"{len(diff['alreadyKnown'])} already in the universe. Run apply with "
            "--confirm to commit."
        )
    elif mode == "apply" and not applied:
        verdict = "apply-blocked"
        narrative = (
            "Apply refused without explicit operator confirmation. Re-run with "
            "--confirm or INFERNO_WATCHLIST_CONFIRM=1."
        )
    elif mode == "apply" and applied:
        verdict = "applied"
        narrative = (
            f"Apply succeeded: {len(diff['newAdds'])} ticker(s) routed to the "
            "morning ingest. " + apply_message
        )
    else:
        verdict = "unknown"
        narrative = "Unexpected ingest state; inspect the raw report."

    return {
        "generatedAt": local_now().isoformat(),
        "stage": WATCHLIST_INGEST_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "mode": mode,
        "applied": applied,
        "applyMessage": apply_message,
        "source": source,
        "submittedCount": len(tickers),
        "submittedTickers": tickers,
        "validationErrors": errors,
        "newAdds": diff["newAdds"],
        "alreadyKnown": diff["alreadyKnown"],
        "maxTickersPerIngest": MAX_TICKERS_PER_INGEST,
        "reminders": [
            "preview mode never writes the sheet",
            "apply mode requires --confirm or INFERNO_WATCHLIST_CONFIRM=1",
            "apply touches only the configured sheet range; never authority "
            "or paper ledger",
        ],
    }


def ingest_text(payload: dict[str, Any]) -> str:
    """Render the ingest payload into an operator memo."""
    lines = [
        "Inferno Watchlist Ingest (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Mode: {payload.get('mode')}",
        f"Verdict: {payload.get('verdict')}",
        f"Source: {payload.get('source')}",
        f"Submitted: {payload.get('submittedCount')} / cap {payload.get('maxTickersPerIngest')}",
        f"Applied: {payload.get('applied')} ({payload.get('applyMessage') or '-'})",
        "",
        f"Narrative: {payload.get('narrative')}",
    ]
    errors = payload.get("validationErrors") or []
    if errors:
        lines.append("")
        lines.append("Validation errors:")
        for err in errors:
            lines.append(f"- {err}")
    new_adds = payload.get("newAdds") or []
    if new_adds:
        lines.append("")
        lines.append(f"New adds ({len(new_adds)}):")
        for ticker in new_adds:
            lines.append(f"- {ticker}")
    already = payload.get("alreadyKnown") or []
    if already:
        lines.append("")
        lines.append(f"Already in universe ({len(already)}):")
        for ticker in already:
            lines.append(f"- {ticker}")
    lines.extend(["", "Reminders:"])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_ingest_report(payload: dict[str, Any]) -> None:
    """Persist the ingest JSON and text artifacts."""
    ensure_dirs()
    atomic_write_json(WATCHLIST_INGEST_FILE, payload)
    atomic_write_text(WATCHLIST_INGEST_TEXT_FILE, ingest_text(payload))


def _stage_to_file(new_tickers: list[str]) -> tuple[bool, str]:
    """Fallback apply writer — stages tickers to a file the morning pipeline picks up.

    Used when the direct-Sheet writer isn't available (no credentials, gspread
    not importable, or operator explicitly disables it via env var). The
    morning pipeline's BC/P/Q/R updater consumes the staged file on its next
    run.
    """
    staged_path = DATA_DIR / "inferno_watchlist_staged.json"
    payload = {
        "stagedAt": local_now().isoformat(),
        "tickers": list(new_tickers),
        "consumedBy": "morning pipeline BC sync",
    }
    try:
        atomic_write_json(staged_path, payload)
    except OSError as exc:
        return False, f"staged-file write failed: {exc}"
    return True, f"staged {len(new_tickers)} ticker(s) at {staged_path}"


def _sheet_apply_writer(new_tickers: list[str]) -> tuple[bool, str]:
    """Direct Sheet writer — appends new tickers to column A of 'Earnings Tracker'.

    Reuses the existing ``morning_inferno_pipeline.make_gspread_client`` /
    ``get_sheet`` helpers so credential handling matches the rest of the desk.
    On any failure (creds missing, network down, gspread missing) we fall back
    to ``_stage_to_file`` so the operator still has a paper trail of what was
    intended.

    Returns ``(applied_ok, human_message)``. Never raises.

    The trigger-formulas pass (BC/P/Q/R fill) is gated behind
    ``INFERNO_WATCHLIST_TRIGGER_FORMULAS=1`` since it can take several
    seconds and the morning loop already runs those syncs on schedule.
    """
    try:
        # Lazy imports so unit tests don't need the gspread stack.
        from inferno_config import DEFAULT_SHEET_NAME, default_backtest_root
        from morning_inferno_pipeline import (
            get_sheet,
            google_sheets_call,
            load_tracker_ticker_rows,
            update_sheet_range,
        )
    except Exception as exc:  # noqa: BLE001
        ok, msg = _stage_to_file(new_tickers)
        return ok, (
            f"sheet-writer-unavailable ({type(exc).__name__}: {exc}); "
            f"fell back to staged file ({msg})"
        )

    try:
        sheet = get_sheet(default_backtest_root(), DEFAULT_SHEET_NAME)
    except Exception as exc:  # noqa: BLE001
        ok, msg = _stage_to_file(new_tickers)
        return ok, (
            f"sheet-open-failed ({type(exc).__name__}: {exc}); "
            f"fell back to staged file ({msg})"
        )

    # Read column A so we don't double-add anything that's already there.
    try:
        _raw, sheet_tickers, _invalid = load_tracker_ticker_rows(sheet)
    except Exception as exc:  # noqa: BLE001
        ok, msg = _stage_to_file(new_tickers)
        return ok, (
            f"sheet-read-failed ({type(exc).__name__}: {exc}); "
            f"fell back to staged file ({msg})"
        )

    existing = {ticker.upper() for ticker in sheet_tickers if ticker}
    fresh = [ticker for ticker in new_tickers if ticker.upper() not in existing]

    if not fresh:
        return True, (
            f"no-op: all {len(new_tickers)} ticker(s) already in column A "
            f"of {DEFAULT_SHEET_NAME!r}"
        )

    # Append to the first empty row below the existing tickers.
    next_row = len(sheet_tickers) + 2  # +2 because column A row 1 is the header.
    range_name = f"A{next_row}:A{next_row + len(fresh) - 1}"
    values = [[ticker] for ticker in fresh]

    try:
        google_sheets_call(
            f"append {len(fresh)} watchlist ticker(s) to {DEFAULT_SHEET_NAME}",
            lambda: update_sheet_range(sheet, range_name, values),
        )
    except Exception as exc:  # noqa: BLE001
        ok, msg = _stage_to_file(new_tickers)
        return ok, (
            f"sheet-append-failed ({type(exc).__name__}: {exc}); "
            f"fell back to staged file ({msg})"
        )

    trigger_formulas = str(os.environ.get("INFERNO_WATCHLIST_TRIGGER_FORMULAS", "")).strip() == "1"
    formula_message = ""
    if trigger_formulas:
        try:
            from morning_inferno_pipeline import (
                sync_bc_columns,
                sync_p_column,
                sync_q_column,
                sync_r_column,
            )
            backtest_root = default_backtest_root()
            sync_bc_columns(backtest_root, DEFAULT_SHEET_NAME)
            sync_p_column(backtest_root, DEFAULT_SHEET_NAME)
            sync_q_column(backtest_root, DEFAULT_SHEET_NAME)
            sync_r_column(backtest_root, DEFAULT_SHEET_NAME)
            formula_message = "; BC/P/Q/R formulas refreshed."
        except Exception as exc:  # noqa: BLE001
            formula_message = (
                f"; BC/P/Q/R refresh skipped after append "
                f"({type(exc).__name__}: {exc})"
            )

    # Also keep a staged file as a recovery artifact.
    _stage_to_file(fresh)

    return True, (
        f"appended {len(fresh)} ticker(s) at {range_name} of "
        f"{DEFAULT_SHEET_NAME!r}{formula_message}"
    )


def _default_apply_writer(new_tickers: list[str]) -> tuple[bool, str]:
    """Top-level apply writer selector.

    Direct sheet write by default; staged-file mode when explicitly disabled
    via ``INFERNO_WATCHLIST_SHEET_DISABLED=1``.
    """
    if str(os.environ.get("INFERNO_WATCHLIST_SHEET_DISABLED", "")).strip() == "1":
        return _stage_to_file(new_tickers)
    return _sheet_apply_writer(new_tickers)


def run_ingest(
    *,
    mode: str,
    confirm: bool,
    universe_loader: Callable[[], list[str]] | None = None,
    apply_writer: Callable[[list[str]], tuple[bool, str]] | None = None,
    input_path: Path = WATCHLIST_INPUT_FILE,
) -> dict[str, Any]:
    """Single entry point shared by the CLI and the test suite."""
    if mode not in {"preview", "apply"}:
        raise ValueError(f"unknown mode: {mode}")

    tickers, source, errors = load_watchlist_input(input_path)
    universe = (universe_loader or _default_universe_loader)()
    diff = diff_against_universe(tickers, universe)

    applied = False
    apply_message = ""
    if mode == "apply":
        if errors:
            apply_message = "refused: input validation errors must be fixed first"
        elif not tickers:
            apply_message = "refused: input slot is empty"
        elif not confirm:
            apply_message = "refused: confirmation gate not satisfied"
        elif not diff["newAdds"]:
            apply_message = "no-op: every submitted ticker is already in the universe"
            applied = True
        else:
            writer = apply_writer or _default_apply_writer
            ok, message = writer(diff["newAdds"])
            applied = ok
            apply_message = message

    return build_ingest_report(
        tickers=tickers,
        source=source,
        errors=errors,
        diff=diff,
        mode=mode,
        applied=applied,
        apply_message=apply_message,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or apply a watchlist diff from "
            "data/inferno_watchlist_input.json. Research-only; "
            "apply requires --confirm."
        )
    )
    parser.add_argument(
        "command", nargs="?", default="preview", choices=["preview", "apply", "status"]
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Operator confirmation; required by apply mode unless "
             "INFERNO_WATCHLIST_CONFIRM=1 is set.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and WATCHLIST_INGEST_TEXT_FILE.exists():
        print(WATCHLIST_INGEST_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    confirm = _confirm_present(args)
    mode = args.command if args.command in {"preview", "apply"} else "preview"
    payload = run_ingest(mode=mode, confirm=confirm)
    save_ingest_report(payload)
    print(ingest_text(payload))
    if payload.get("verdict") in {"input-errors"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
