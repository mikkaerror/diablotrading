from __future__ import annotations

"""Inferno Watchlist Autorefresh — the closed-loop coordinator.

What it does:
    Runs every 5 minutes from a LaunchAgent. On each tick:

    1. ``inferno_tos_watchlist_extract`` reads the TOS watchlist.
    2. If the extract produced new tickers (vs the last cycle's snapshot),
       ``inferno_watchlist_ingest`` apply runs with the confirmation flag
       implicitly set (env var INFERNO_WATCHLIST_CONFIRM=1).
    3. ``inferno_watchlist_reconciler`` cross-checks TOS / Sheet / tracker.
    4. If anything changed, the dawn pipeline gets a "refresh requested"
       breadcrumb the morning loop honours.

    Each tick writes a structured ledger entry to
    ``data/inferno_watchlist_autorefresh.json`` and a memo to
    ``reports/watchlist_autorefresh_latest.txt``. Failures in one step never
    abort the others — same failure-isolated chain pattern as the daily loop.

What it does NOT do:
    - Place trades. Place orders. Touch authority. Mutate paper ledger.
    - Open a new TOS window.
    - Bypass the ingest module's confirmation gate — it sets
      ``INFERNO_WATCHLIST_CONFIRM=1`` in its own subprocess env, but only
      for runs that explicitly opt in via ``--auto-apply``.

Strict contract: read-only on the desk's safety surfaces; the only writes
this module triggers go through the existing ingest module's
already-gated Sheet appender. Without ``--auto-apply``, the coordinator
runs in surveillance mode — extract + reconcile only.

CLI::

    python3 inferno_watchlist_autorefresh.py             # surveillance (no apply)
    python3 inferno_watchlist_autorefresh.py --auto-apply # full closed loop
    python3 inferno_watchlist_autorefresh.py status      # show last memo
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


WATCHLIST_AUTOREFRESH_FILE = DATA_DIR / "inferno_watchlist_autorefresh.json"
WATCHLIST_AUTOREFRESH_TEXT_FILE = REPORTS_DIR / "watchlist_autorefresh_latest.txt"
WATCHLIST_AUTOREFRESH_LEDGER_FILE = DATA_DIR / "inferno_watchlist_autorefresh_ledger.json"
WATCHLIST_AUTOREFRESH_STAGE = "watchlist-autorefresh-research-only"
WATCHLIST_AUTOREFRESH_LEDGER_MAX_ENTRIES = 288  # 24h of 5-min ticks


def _last_snapshot_tickers(
    path: Path = WATCHLIST_AUTOREFRESH_FILE,
) -> list[str]:
    """Best-effort read of the previous tick's ticker snapshot."""
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    tickers = payload.get("lastSnapshotTickers") or []
    return [str(t).strip().upper() for t in tickers if t]


def _run_step(name: str, func: Callable[[], Any]) -> dict[str, Any]:
    """Failure-isolated step runner. Mirrors the daily loop pattern."""
    try:
        result = func()
    except Exception as exc:  # noqa: BLE001
        return {
            "name": name,
            "ok": False,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {"name": name, "ok": True, "status": "built", "result": result}


# ---------------------------------------------------------------------------
# Step implementations — each replaceable in tests.
# ---------------------------------------------------------------------------


def _step_extract(extractor: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    if extractor is None:
        from inferno_tos_watchlist_extract import build_extract, save_extract, write_input_slot
        payload = build_extract()
        save_extract(payload)
        slot_path = write_input_slot(payload)
        if slot_path is not None:
            payload["inputSlotWritten"] = str(slot_path)
        return payload
    return extractor()


def _step_ingest(
    auto_apply: bool,
    ingester: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run ingest in preview by default; in apply mode only when --auto-apply."""
    mode = "apply" if auto_apply else "preview"
    confirm = bool(auto_apply)
    if ingester is None:
        from inferno_watchlist_ingest import run_ingest, save_ingest_report
        payload = run_ingest(mode=mode, confirm=confirm)
        save_ingest_report(payload)
        return payload
    return ingester(mode=mode, confirm=confirm)


def _step_reconcile(reconciler: Callable[[], dict[str, Any]] | None = None) -> dict[str, Any]:
    if reconciler is None:
        from inferno_watchlist_reconciler import build_reconciliation, save_reconciliation
        payload = build_reconciliation()
        save_reconciliation(payload)
        return payload
    return reconciler()


def _request_dawn_refresh() -> dict[str, Any]:
    """Drop a breadcrumb the morning loop picks up.

    We don't trigger the dawn pipeline directly — it's heavy. We write a tiny
    file the next scheduled dawn run honours. Operator can also poke it from
    the command line.
    """
    refresh_request = DATA_DIR / "inferno_dawn_refresh_request.json"
    ensure_dirs()
    atomic_write_json(refresh_request, {
        "requestedAt": local_now().isoformat(),
        "requestedBy": WATCHLIST_AUTOREFRESH_STAGE,
        "reason": "watchlist delta detected by autorefresh coordinator",
    })
    return {"breadcrumb": str(refresh_request)}


# ---------------------------------------------------------------------------
# Pure builder.
# ---------------------------------------------------------------------------


def build_autorefresh(
    *,
    auto_apply: bool = False,
    extractor: Callable[..., dict[str, Any]] | None = None,
    ingester: Callable[..., dict[str, Any]] | None = None,
    reconciler: Callable[[], dict[str, Any]] | None = None,
    snapshot_loader: Callable[[], list[str]] | None = None,
    dawn_refresh: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run a single autorefresh tick. Pure-ish: writes only own artifacts +
    delegates to step modules (which write their own)."""
    steps: list[dict[str, Any]] = []

    extract_step = _run_step("extract", lambda: _step_extract(extractor))
    steps.append(extract_step)

    new_tickers: list[str] = []
    extract_result = extract_step.get("result") if extract_step.get("ok") else None
    if isinstance(extract_result, dict):
        new_tickers = extract_result.get("tickers") or []

    previous = (snapshot_loader or _last_snapshot_tickers)()
    previous_set = set(previous)
    delta = [ticker for ticker in new_tickers if ticker.upper() not in previous_set]
    departed = [ticker for ticker in previous if ticker.upper() not in {t.upper() for t in new_tickers}]
    has_delta = bool(delta or departed)

    # Always run ingest preview so the operator gets a daily memo of what's
    # in the input slot vs the universe. apply only on delta + auto_apply.
    should_apply = auto_apply and bool(delta) and extract_step.get("ok")
    ingest_step = _run_step(
        "ingest",
        lambda: _step_ingest(should_apply, ingester),
    )
    steps.append(ingest_step)

    reconcile_step = _run_step("reconcile", lambda: _step_reconcile(reconciler))
    steps.append(reconcile_step)

    dawn_step = None
    if has_delta:
        dawn_step = _run_step(
            "dawn-refresh-request",
            lambda: (dawn_refresh or _request_dawn_refresh)(),
        )
        steps.append(dawn_step)

    ok_count = sum(1 for step in steps if step.get("ok"))
    failed = [step for step in steps if not step.get("ok")]
    failed_count = len(failed)

    if failed_count == 0 and has_delta and should_apply:
        verdict = "delta-applied"
        narrative = (
            f"Detected {len(delta)} new ticker(s) ({', '.join(delta[:6])}{'…' if len(delta) > 6 else ''}); "
            f"ingest apply ran and dawn refresh was requested."
        )
    elif failed_count == 0 and has_delta:
        verdict = "delta-detected"
        narrative = (
            f"Detected {len(delta)} new ticker(s) — surveillance mode, no apply. "
            "Run with --auto-apply (or run inferno_watchlist_ingest.py apply --confirm) "
            "to push them to the sheet."
        )
    elif failed_count == 0:
        verdict = "no-change"
        narrative = (
            f"No watchlist delta this tick ({len(new_tickers)} ticker(s) snapshot)."
        )
    else:
        verdict = "step-failures"
        narrative = (
            f"{failed_count} step(s) failed: " +
            "; ".join(f"{step['name']} ({step.get('error')})" for step in failed)
        )

    reconcile_result = reconcile_step.get("result") if reconcile_step.get("ok") else None
    reconcile_verdict = (
        reconcile_result.get("verdict") if isinstance(reconcile_result, dict) else "unknown"
    )

    return {
        "generatedAt": local_now().isoformat(),
        "stage": WATCHLIST_AUTOREFRESH_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "autoApply": auto_apply,
        "tickerSnapshotCount": len(new_tickers),
        "lastSnapshotTickers": new_tickers,
        "previousSnapshotCount": len(previous),
        "delta": delta,
        "departed": departed,
        "hasDelta": has_delta,
        "reconcileVerdict": reconcile_verdict,
        "steps": steps,
        "okCount": ok_count,
        "failedCount": failed_count,
        "reminders": [
            "coordinator never bypasses the ingest confirmation gate; --auto-apply enables it",
            "delta detection is by comparing this tick to the last persisted snapshot",
            "reconcile result is the source of truth for drift, not the snapshot diff",
        ],
    }


def autorefresh_text(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno Watchlist Autorefresh (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}  autoApply={payload.get('autoApply')}",
        f"Snapshot count: {payload.get('tickerSnapshotCount')}  "
        f"Delta: {len(payload.get('delta') or [])}  "
        f"Departed: {len(payload.get('departed') or [])}  "
        f"Reconcile: {payload.get('reconcileVerdict')}",
        "",
        f"Narrative: {payload.get('narrative')}",
    ]
    delta = payload.get("delta") or []
    if delta:
        lines.extend(["", f"New tickers this tick ({len(delta)}):"])
        for ticker in delta:
            lines.append(f"- {ticker}")
    departed = payload.get("departed") or []
    if departed:
        lines.extend(["", f"Tickers no longer visible ({len(departed)}):"])
        for ticker in departed:
            lines.append(f"- {ticker}")
    steps = payload.get("steps") or []
    if steps:
        lines.extend(["", "Step results:"])
        for step in steps:
            status_glyph = "✓" if step.get("ok") else "✗"
            error = f"  ERROR: {step['error']}" if not step.get("ok") and step.get("error") else ""
            lines.append(f"- {status_glyph} {step.get('name')}{error}")
    lines.extend(["", "Reminders:"])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_autorefresh(payload: dict[str, Any]) -> None:
    """Persist the per-tick artifact, the text memo, and append to a ledger."""
    ensure_dirs()
    atomic_write_json(WATCHLIST_AUTOREFRESH_FILE, payload)
    atomic_write_text(WATCHLIST_AUTOREFRESH_TEXT_FILE, autorefresh_text(payload))

    # Append to a bounded ledger so we can see drift over time.
    ledger: list[Any] = []
    if WATCHLIST_AUTOREFRESH_LEDGER_FILE.exists():
        try:
            existing = json.loads(WATCHLIST_AUTOREFRESH_LEDGER_FILE.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                ledger = existing
            elif isinstance(existing, dict):
                ledger = existing.get("entries") or []
        except (OSError, json.JSONDecodeError):
            ledger = []
    ledger.append({
        "at": payload.get("generatedAt"),
        "verdict": payload.get("verdict"),
        "deltaCount": len(payload.get("delta") or []),
        "departedCount": len(payload.get("departed") or []),
        "snapshotCount": payload.get("tickerSnapshotCount"),
        "reconcileVerdict": payload.get("reconcileVerdict"),
        "okCount": payload.get("okCount"),
        "failedCount": payload.get("failedCount"),
    })
    if len(ledger) > WATCHLIST_AUTOREFRESH_LEDGER_MAX_ENTRIES:
        ledger = ledger[-WATCHLIST_AUTOREFRESH_LEDGER_MAX_ENTRIES:]
    atomic_write_json(WATCHLIST_AUTOREFRESH_LEDGER_FILE, {"entries": ledger})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Coordinator that ties extract → ingest → reconcile into a "
            "5-minute closed loop. Surveillance by default; --auto-apply "
            "enables the implicit confirm gate."
        )
    )
    parser.add_argument(
        "command", nargs="?", default="run", choices=["run", "status"]
    )
    parser.add_argument(
        "--auto-apply", action="store_true",
        help="Apply detected deltas to the sheet automatically. Equivalent to "
             "setting INFERNO_WATCHLIST_CONFIRM=1 for the ingest step.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and WATCHLIST_AUTOREFRESH_TEXT_FILE.exists():
        print(WATCHLIST_AUTOREFRESH_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    auto_apply = bool(args.auto_apply) or str(os.environ.get("INFERNO_WATCHLIST_AUTO_APPLY", "")).strip() == "1"
    payload = build_autorefresh(auto_apply=auto_apply)
    save_autorefresh(payload)
    print(autorefresh_text(payload))
    if payload.get("verdict") == "step-failures":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
