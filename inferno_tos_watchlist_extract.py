from __future__ import annotations

"""Inferno TOS Watchlist Extractor — primary accessibility-tree, CSV fallback.

What it does:
    Reads the already-open thinkorswim window via the macOS accessibility tree
    and pulls the visible watchlist tickers. If the accessibility path fails
    (login screen, locked tree, no watchlist visible), it falls back to looking
    for a freshly-exported watchlist CSV in ``~/Downloads``.

What it does NOT do:
    - Open a new thinkorswim window (would violate the safety rail).
    - Click anywhere or type into TOS.
    - Write to the Google Sheet directly; that's ``inferno_watchlist_ingest``'s job.
    - Mutate the approval queue, paper ledger, or authority manifest.

Strict contract: read-only on TOS; only writes to
``data/inferno_watchlist_input.json`` (the consumed-by-ingest slot) and to the
module's own diagnostic artifact.

The watchlist name to bind to is configurable via the
``INFERNO_TOS_WATCHLIST_NAME`` environment variable (default ``Earnings``).
If the named panel can't be found, the extractor falls back to collecting all
ticker-shaped strings from the visible window — better to have a superset that
the operator can prune than to miss a ticker.

CLI::

    python3 inferno_tos_watchlist_extract.py            # extract once
    python3 inferno_tos_watchlist_extract.py extract    # same
    python3 inferno_tos_watchlist_extract.py status     # show last extract memo
    python3 inferno_tos_watchlist_extract.py --no-write # diagnose only, don't update input slot

The output schema written to ``data/inferno_watchlist_input.json``::

    {
      "tickers": ["NVDA", "AVGO", ...],
      "source": "tos-accessibility | tos-csv-export | none",
      "extractedAt": "2026-05-13T22:14:00-04:00",
      "watchlistName": "Earnings",
      "fallbackUsed": false
    }
"""

import argparse
import csv
import io
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


WATCHLIST_INPUT_FILE = DATA_DIR / "inferno_watchlist_input.json"
WATCHLIST_EXTRACT_FILE = DATA_DIR / "inferno_tos_watchlist_extract.json"
WATCHLIST_EXTRACT_TEXT_FILE = REPORTS_DIR / "tos_watchlist_extract_latest.txt"
WATCHLIST_EXTRACT_STAGE = "tos-watchlist-extract-research-only"

DEFAULT_WATCHLIST_NAME = os.environ.get("INFERNO_TOS_WATCHLIST_NAME", "Earnings").strip() or "Earnings"
DOWNLOADS_FALLBACK_DIR = Path(os.environ.get("INFERNO_DOWNLOADS_DIR", str(Path.home() / "Downloads")))
DOWNLOADS_CSV_MAX_AGE_SECONDS = int(os.environ.get("INFERNO_WATCHLIST_CSV_MAX_AGE", "3600"))
MIN_TICKER_LEN = 1
MAX_TICKER_LEN = 10

# Token shape used during accessibility scrape. We bias against things like
# "USD", "EUR" by demanding at least one letter and disallowing all-digit blobs.
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

# Known noise tokens that match the ticker pattern but are obvious UI labels.
# We keep this list short and conservative; the reconciler is the real safety net.
NOISE_TOKENS = frozenset({
    "USD", "EUR", "JPY", "GBP", "CAD", "AUD", "CHF",
    "OK", "NO", "ID", "PM", "AM", "VWAP",
    "NYSE", "NASDAQ", "AMEX",
    "ATR", "IV", "RSI", "MACD",
    "PNL", "PL", "PNL%", "P&L",
    "BUY", "SELL", "DAY", "GTC", "FOK",
    "CALL", "PUT", "BID", "ASK", "MID",
    "OPEN", "CLOSE", "HIGH", "LOW",
    "MIN", "MAX", "AVG", "STD",
    "INVALID", "PENDING", "WORKING",
})


# ---------------------------------------------------------------------------
# Accessibility-tree primary path
# ---------------------------------------------------------------------------


def _default_applescript_runner(script: str) -> subprocess.CompletedProcess:
    """Default AppleScript runner. Inject a fake in tests."""
    return subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=12,
    )


def _scrape_accessibility_tickers(
    watchlist_name: str,
    runner: Callable[[str], subprocess.CompletedProcess],
) -> tuple[list[str], dict[str, Any]]:
    """Walk the TOS accessibility tree looking for ticker-shaped strings.

    We do not attempt deep accessibility navigation — that's brittle across TOS
    builds. Instead we ask AppleScript for *every* labeled element's name in
    the frontmost TOS-owned application, then filter to ticker shapes. The
    reconciler is responsible for catching anything missed.

    Returns ``(tickers, debug)`` where ``debug`` summarises what was inspected.
    """
    debug: dict[str, Any] = {
        "watchlistName": watchlist_name,
        "labelsInspected": 0,
        "scriptExitCode": None,
        "scriptStderr": "",
        "method": "applescript-accessibility-broad",
    }

    # This script returns one label per line, dedup'd, from every UI element
    # under the frontmost thinkorswim window. We bail out early on any error
    # so a locked/unresponsive accessibility tree returns "" not a crash.
    script = r'''
on join_lines(lst)
    set AppleScript's text item delimiters to linefeed
    set _txt to lst as text
    set AppleScript's text item delimiters to ""
    return _txt
end join_lines

set _labels to {}
try
    tell application "System Events"
        set _procs to every application process whose name contains "thinkorswim"
        if (count of _procs) = 0 then
            set _procs to every application process whose name contains "java"
        end if
        if (count of _procs) = 0 then
            return ""
        end if
        repeat with _proc in _procs
            try
                set _windows to every window of _proc
                repeat with _win in _windows
                    try
                        set _items to entire contents of _win
                        repeat with _item in _items
                            try
                                set _name to (name of _item) as text
                                if _name is not missing value and _name is not "" then
                                    copy _name to end of _labels
                                end if
                            end try
                            try
                                set _val to (value of _item) as text
                                if _val is not missing value and _val is not "" then
                                    copy _val to end of _labels
                                end if
                            end try
                            try
                                set _desc to (description of _item) as text
                                if _desc is not missing value and _desc is not "" then
                                    copy _desc to end of _labels
                                end if
                            end try
                        end repeat
                    end try
                end repeat
            end try
        end repeat
    end tell
on error
    return ""
end try
return my join_lines(_labels)
'''

    try:
        result = runner(script)
    except (subprocess.TimeoutExpired, OSError) as exc:
        debug["scriptStderr"] = f"runner error: {exc}"
        return [], debug

    debug["scriptExitCode"] = result.returncode
    debug["scriptStderr"] = (result.stderr or "").strip()[:400]

    raw_text = (result.stdout or "").replace("\r", "")
    raw_labels = [line.strip() for line in raw_text.split("\n") if line.strip()]
    debug["labelsInspected"] = len(raw_labels)

    candidates: list[str] = []
    seen: set[str] = set()
    for label in raw_labels:
        # Accessibility labels often pack multiple tokens (e.g. "NVDA  $850.12").
        # Tokenise generously on whitespace and the common separators we've seen.
        for token in re.split(r"[\s,;|/]+", label):
            token = token.strip().upper().lstrip("$")
            if len(token) < MIN_TICKER_LEN or len(token) > MAX_TICKER_LEN:
                continue
            if not TICKER_PATTERN.match(token):
                continue
            if token in NOISE_TOKENS:
                continue
            if token.isdigit():
                continue
            if token in seen:
                continue
            seen.add(token)
            candidates.append(token)

    return candidates, debug


# ---------------------------------------------------------------------------
# Downloads CSV fallback
# ---------------------------------------------------------------------------


def _scan_downloads_for_csv(
    downloads_dir: Path = DOWNLOADS_FALLBACK_DIR,
    *,
    max_age_seconds: int = DOWNLOADS_CSV_MAX_AGE_SECONDS,
    now_epoch: float | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Look for a fresh ``*watchlist*.csv`` (or any csv) in Downloads.

    TOS lets the operator click File → Export Watchlist; the resulting CSV
    lands in ``~/Downloads``. We accept either a watchlist-named CSV or, as
    a last resort, the newest CSV in Downloads provided it was modified within
    the freshness window.
    """
    debug: dict[str, Any] = {
        "downloadsDir": str(downloads_dir),
        "csvCandidates": 0,
        "chosenFile": None,
        "fileAgeSeconds": None,
        "freshnessWindowSeconds": max_age_seconds,
        "method": "downloads-csv-fallback",
    }

    if not downloads_dir.exists() or not downloads_dir.is_dir():
        debug["error"] = f"downloads dir not found: {downloads_dir}"
        return [], debug

    import time as _time

    now = now_epoch if now_epoch is not None else _time.time()
    csvs: list[tuple[float, Path]] = []
    for entry in downloads_dir.glob("*.csv"):
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if (now - mtime) > max_age_seconds:
            continue
        csvs.append((mtime, entry))

    debug["csvCandidates"] = len(csvs)
    if not csvs:
        return [], debug

    # Prefer files that look watchlist-named, otherwise newest.
    watchlist_named = [pair for pair in csvs if "watch" in pair[1].name.lower()]
    chosen = max(watchlist_named or csvs, key=lambda pair: pair[0])
    debug["chosenFile"] = str(chosen[1])
    debug["fileAgeSeconds"] = round(now - chosen[0])

    tickers: list[str] = []
    try:
        text = chosen[1].read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        debug["error"] = f"csv read failed: {exc}"
        return [], debug

    reader = csv.reader(io.StringIO(text))
    seen: set[str] = set()
    for row in reader:
        for cell in row:
            token = str(cell or "").strip().upper().lstrip("$")
            if len(token) < MIN_TICKER_LEN or len(token) > MAX_TICKER_LEN:
                continue
            if not TICKER_PATTERN.match(token):
                continue
            if token in NOISE_TOKENS or token.isdigit():
                continue
            if token in seen:
                continue
            seen.add(token)
            tickers.append(token)

    return tickers, debug


# ---------------------------------------------------------------------------
# Pure builder
# ---------------------------------------------------------------------------


def build_extract(
    *,
    watchlist_name: str | None = None,
    accessibility_scraper: Callable[[str, Callable[[str], subprocess.CompletedProcess]], tuple[list[str], dict[str, Any]]] | None = None,
    applescript_runner: Callable[[str], subprocess.CompletedProcess] | None = None,
    downloads_scanner: Callable[..., tuple[list[str], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Run the extract pipeline. Pure-ish: no disk writes, only reads.

    All OS-touching pieces are injectable so the unit tests can run without
    AppleScript or a real Downloads folder.
    """
    name = (watchlist_name or DEFAULT_WATCHLIST_NAME).strip() or DEFAULT_WATCHLIST_NAME

    scraper = accessibility_scraper or _scrape_accessibility_tickers
    runner = applescript_runner or _default_applescript_runner
    scanner = downloads_scanner or _scan_downloads_for_csv

    accessibility_tickers: list[str] = []
    accessibility_debug: dict[str, Any] = {}
    accessibility_error = None
    try:
        accessibility_tickers, accessibility_debug = scraper(name, runner)
    except Exception as exc:  # noqa: BLE001
        accessibility_error = f"{type(exc).__name__}: {exc}"
        accessibility_debug = {"error": accessibility_error}

    fallback_tickers: list[str] = []
    fallback_debug: dict[str, Any] = {}
    fallback_used = False
    if not accessibility_tickers:
        fallback_used = True
        try:
            fallback_tickers, fallback_debug = scanner()
        except Exception as exc:  # noqa: BLE001
            fallback_debug = {"error": f"{type(exc).__name__}: {exc}"}

    tickers = accessibility_tickers or fallback_tickers
    source = (
        "tos-accessibility" if accessibility_tickers
        else "tos-csv-export" if fallback_tickers
        else "none"
    )

    if not tickers:
        verdict = "no-tickers"
        narrative = (
            f"Extractor found 0 tickers. Accessibility path returned "
            f"{accessibility_debug.get('labelsInspected', 0)} labels; "
            f"CSV fallback {('found ' + str(fallback_debug.get('csvCandidates', 0)) + ' candidates') if fallback_used else 'not run'}. "
            "Confirm TOS is open with the watchlist panel visible, or export the "
            "watchlist to a CSV in Downloads, then re-run."
        )
    elif source == "tos-accessibility":
        verdict = "accessibility-ok"
        narrative = (
            f"Pulled {len(tickers)} ticker(s) via accessibility-tree scan of "
            f"the live TOS window. Watchlist binding: {name!r}."
        )
    elif source == "tos-csv-export":
        verdict = "csv-fallback-ok"
        narrative = (
            f"Accessibility path returned no tickers; recovered {len(tickers)} "
            f"from a recent CSV at {fallback_debug.get('chosenFile')!r} "
            f"(age {fallback_debug.get('fileAgeSeconds')}s)."
        )
    else:
        verdict = "unknown"
        narrative = "Extractor produced an unexpected state; inspect debug."

    return {
        "generatedAt": local_now().isoformat(),
        "stage": WATCHLIST_EXTRACT_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "watchlistName": name,
        "source": source,
        "fallbackUsed": fallback_used,
        "tickers": tickers,
        "tickerCount": len(tickers),
        "accessibility": accessibility_debug,
        "fallback": fallback_debug,
        "accessibilityError": accessibility_error,
        "reminders": [
            "extractor is read-only on TOS",
            "never opens a new TOS window",
            "writes only data/inferno_watchlist_input.json and own artifact",
        ],
    }


def extract_text(payload: dict[str, Any]) -> str:
    """Render extract payload as an operator memo."""
    lines = [
        "Inferno TOS Watchlist Extract (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Watchlist: {payload.get('watchlistName')}",
        f"Source: {payload.get('source')}  fallbackUsed={payload.get('fallbackUsed')}",
        f"Verdict: {payload.get('verdict')}",
        f"Tickers: {payload.get('tickerCount')}",
        "",
        f"Narrative: {payload.get('narrative')}",
    ]
    tickers = payload.get("tickers") or []
    if tickers:
        lines.extend(["", "Extracted tickers:"])
        for ticker in tickers:
            lines.append(f"- {ticker}")
    accessibility = payload.get("accessibility") or {}
    if accessibility:
        lines.extend(["", "Accessibility debug:"])
        for key in ("method", "labelsInspected", "scriptExitCode", "scriptStderr", "error"):
            if key in accessibility:
                lines.append(f"- {key}: {accessibility[key]}")
    fallback = payload.get("fallback") or {}
    if fallback:
        lines.extend(["", "CSV fallback debug:"])
        for key in (
            "method", "downloadsDir", "csvCandidates", "chosenFile",
            "fileAgeSeconds", "freshnessWindowSeconds", "error",
        ):
            if key in fallback:
                lines.append(f"- {key}: {fallback[key]}")
    lines.extend(["", "Reminders:"])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_extract(payload: dict[str, Any]) -> None:
    """Persist the extract diagnostic artifact and the consumed-by-ingest slot."""
    ensure_dirs()
    atomic_write_json(WATCHLIST_EXTRACT_FILE, payload)
    atomic_write_text(WATCHLIST_EXTRACT_TEXT_FILE, extract_text(payload))


def write_input_slot(payload: dict[str, Any]) -> Path | None:
    """Write the input-slot file that ``inferno_watchlist_ingest`` consumes.

    Returns the path written (so callers can log it), or ``None`` if the slot
    was intentionally skipped (no tickers found — leave any existing slot
    alone instead of clobbering it with an empty list).
    """
    tickers = payload.get("tickers") or []
    if not tickers:
        return None
    ensure_dirs()
    slot_payload = {
        "tickers": list(tickers),
        "source": payload.get("source") or "unspecified",
        "extractedAt": payload.get("generatedAt"),
        "watchlistName": payload.get("watchlistName"),
        "fallbackUsed": bool(payload.get("fallbackUsed")),
    }
    atomic_write_json(WATCHLIST_INPUT_FILE, slot_payload)
    return WATCHLIST_INPUT_FILE


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract TOS watchlist tickers via accessibility tree (primary) "
            "with Downloads CSV fallback. Research-only; never opens a new "
            "TOS window."
        )
    )
    parser.add_argument(
        "command", nargs="?", default="extract", choices=["extract", "status"]
    )
    parser.add_argument(
        "--watchlist-name", default=None,
        help=f"Override the watchlist name (default: ${{INFERNO_TOS_WATCHLIST_NAME}} or {DEFAULT_WATCHLIST_NAME!r}).",
    )
    parser.add_argument(
        "--no-write", action="store_true",
        help="Don't write the input slot; only update the diagnostic artifact.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and WATCHLIST_EXTRACT_TEXT_FILE.exists():
        print(WATCHLIST_EXTRACT_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_extract(watchlist_name=args.watchlist_name)
    save_extract(payload)
    if not args.no_write:
        slot_path = write_input_slot(payload)
        if slot_path is not None:
            payload["inputSlotWritten"] = str(slot_path)
    print(extract_text(payload))
    if payload.get("verdict") == "no-tickers":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
