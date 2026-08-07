from __future__ import annotations

"""Compare two immutable local Schwab chain snapshots without taking action.

This diagnostic lane reads only the history collector's local snapshot files.
It never fetches data, selects strikes, writes tickets, or changes promotion,
risk, broker-submit, or live-trading authority.  It stays quiet unless a
contract's spread, volume, or open interest crosses a documented threshold.
"""

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from inferno_chain_history import (
    CHAIN_HISTORY_STAGE,
    EXPECTED_SOURCE_STAGE,
    load_manifest,
)
from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


CHAIN_DIFF_FILE = DATA_DIR / "inferno_chain_diff.json"
CHAIN_DIFF_TEXT_FILE = REPORTS_DIR / "chain_diff_latest.txt"
CHAIN_HISTORY_ROOT = DATA_DIR / "chain_history"

CHAIN_DIFF_STAGE = "schwab-chain-diff-research-only"
SPREAD_WIDENING_THRESHOLD = 0.25
VOLUME_SPIKE_THRESHOLD = 2.0
OPEN_INTEREST_CHANGE_THRESHOLD = 0.10
VALID_VERDICTS = frozenset(
    {"insufficient-history", "no-meaningful-change", "meaningful-changes"}
)


def _capture_date(descriptor: dict[str, Any]) -> str | None:
    value = str(descriptor.get("captureDate") or "").strip()
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return None
    return value


def _snapshot_path(descriptor: dict[str, Any]) -> Path | None:
    """Return a controlled snapshot path, never an arbitrary manifest path."""
    raw = str(descriptor.get("path") or "").strip()
    if not raw:
        return None
    candidate = (DATA_DIR / raw).resolve()
    try:
        candidate.relative_to(CHAIN_HISTORY_ROOT.resolve())
    except ValueError:
        return None
    return candidate


def _ordered_descriptors(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one controlled descriptor per capture date, oldest first."""
    values = list(manifest.get("hotSnapshots") or []) + list(manifest.get("archiveSnapshots") or [])
    indexed: dict[str, dict[str, Any]] = {}
    for item in values:
        if not isinstance(item, dict):
            continue
        capture_date = _capture_date(item)
        if capture_date and capture_date not in indexed:
            indexed[capture_date] = dict(item)
    return [indexed[key] for key in sorted(indexed)]


def _history_manifest_errors(manifest: dict[str, Any]) -> list[str]:
    if not isinstance(manifest, dict):
        return ["history manifest is not an object"]
    errors: list[str] = []
    if manifest.get("stage") != CHAIN_HISTORY_STAGE:
        errors.append("history manifest stage is invalid")
    if manifest.get("researchOnly") is not True:
        errors.append("history manifest is not research-only")
    if manifest.get("promotable") is not False:
        errors.append("history manifest is not explicitly non-promotable")
    if manifest.get("authorityChanged") is not False:
        errors.append("history manifest authorityChanged is not false")
    if manifest.get("brokerSubmitAllowed") is not False:
        errors.append("history manifest broker submit is not disabled")
    if manifest.get("liveTradingAllowed") is not False:
        errors.append("history manifest live trading is not disabled")
    return errors


def _snapshot_errors(snapshot: Any, descriptor: dict[str, Any]) -> list[str]:
    """Validate a snapshot's provenance before it contributes to a diff."""
    if not isinstance(snapshot, dict):
        return ["snapshot is not an object"]
    source = snapshot.get("source") or {}
    errors: list[str] = []
    if snapshot.get("stage") != CHAIN_HISTORY_STAGE:
        errors.append("snapshot stage is invalid")
    if snapshot.get("researchOnly") is not True:
        errors.append("snapshot is not research-only")
    # The initial immutable snapshot predates this explicit field.  Absence is
    # safe legacy data; a true value is never accepted.
    if snapshot.get("promotable") not in (None, False):
        errors.append("snapshot is promotable")
    if snapshot.get("authorityChanged") is not False:
        errors.append("snapshot authorityChanged is not false")
    if snapshot.get("brokerSubmitAllowed") is not False:
        errors.append("snapshot broker submit is not disabled")
    if snapshot.get("liveTradingAllowed") is not False:
        errors.append("snapshot live trading is not disabled")
    if snapshot.get("captureDate") != descriptor.get("captureDate"):
        errors.append("snapshot capture date does not match manifest")
    if source.get("stage") != EXPECTED_SOURCE_STAGE:
        errors.append("snapshot source stage is invalid")
    if source.get("status") != "ok":
        errors.append("snapshot source status is not complete")
    rows = snapshot.get("rows")
    if not isinstance(rows, list) or not rows:
        errors.append("snapshot has no normalized rows")
    elif any(not isinstance(row, dict) or row.get("status") != "ok" for row in rows):
        errors.append("snapshot contains an incomplete normalized row")
    return errors


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _contracts(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index valid contracts by ticker and OCC symbol for deterministic comparison."""
    result: dict[str, dict[str, Any]] = {}
    for row in snapshot.get("rows") or []:
        if not isinstance(row, dict) or row.get("status") != "ok":
            continue
        ticker = str(row.get("symbol") or "").strip().upper()
        if not ticker:
            continue
        for contract in row.get("contracts") or []:
            if not isinstance(contract, dict):
                continue
            symbol = str(contract.get("symbol") or "").strip()
            if not symbol:
                continue
            key = f"{ticker}|{symbol}"
            result.setdefault(key, {"ticker": ticker, "contract": symbol, "values": dict(contract)})
    return result


def _event(
    *,
    event_type: str,
    metric: str,
    ticker: str,
    contract: str,
    previous: float,
    current: float,
) -> dict[str, Any]:
    relative_change = (current - previous) / previous
    return {
        "type": event_type,
        "metric": metric,
        "ticker": ticker,
        "contract": contract,
        "previous": previous,
        "current": current,
        "relativeChange": round(relative_change, 6),
    }


def compare_snapshots(previous: dict[str, Any], current: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return only material contract-level changes between two valid snapshots."""
    prior_contracts = _contracts(previous)
    current_contracts = _contracts(current)
    common = sorted(set(prior_contracts) & set(current_contracts))
    events: list[dict[str, Any]] = []
    counts = {
        "previousContracts": len(prior_contracts),
        "currentContracts": len(current_contracts),
        "comparedContracts": len(common),
        "spreadWidened": 0,
        "volumeSpiked": 0,
        "openInterestChanged": 0,
    }
    for key in common:
        before = prior_contracts[key]
        after = current_contracts[key]
        prior_values = before["values"]
        current_values = after["values"]
        ticker = str(after["ticker"])
        contract = str(after["contract"])

        prior_spread = _finite_number(prior_values.get("spreadPct"))
        current_spread = _finite_number(current_values.get("spreadPct"))
        if prior_spread is not None and current_spread is not None and prior_spread > 0:
            if current_spread > prior_spread * (1 + SPREAD_WIDENING_THRESHOLD):
                events.append(
                    _event(
                        event_type="spread-widened",
                        metric="spreadPct",
                        ticker=ticker,
                        contract=contract,
                        previous=prior_spread,
                        current=current_spread,
                    )
                )
                counts["spreadWidened"] += 1

        prior_volume = _finite_number(prior_values.get("volume"))
        current_volume = _finite_number(current_values.get("volume"))
        if prior_volume is not None and current_volume is not None and prior_volume > 0:
            if current_volume > prior_volume * VOLUME_SPIKE_THRESHOLD:
                events.append(
                    _event(
                        event_type="volume-spiked",
                        metric="volume",
                        ticker=ticker,
                        contract=contract,
                        previous=prior_volume,
                        current=current_volume,
                    )
                )
                counts["volumeSpiked"] += 1

        prior_open_interest = _finite_number(prior_values.get("openInterest"))
        current_open_interest = _finite_number(current_values.get("openInterest"))
        if prior_open_interest is not None and current_open_interest is not None and prior_open_interest > 0:
            if abs(current_open_interest - prior_open_interest) > prior_open_interest * OPEN_INTEREST_CHANGE_THRESHOLD:
                events.append(
                    _event(
                        event_type="open-interest-changed",
                        metric="openInterest",
                        ticker=ticker,
                        contract=contract,
                        previous=prior_open_interest,
                        current=current_open_interest,
                    )
                )
                counts["openInterestChanged"] += 1
    return events, counts


def build_chain_diff(
    *,
    manifest: dict[str, Any] | None = None,
    snapshots: dict[str, dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build one fail-closed, diagnostic-only comparison of the latest pair."""
    current_time = now or local_now()
    history_manifest = manifest if manifest is not None else load_manifest()
    manifest_errors = _history_manifest_errors(history_manifest)
    descriptors = _ordered_descriptors(history_manifest if isinstance(history_manifest, dict) else {})
    selected = descriptors[-2:]
    loaded: list[tuple[dict[str, Any], dict[str, Any]]] = []
    validation_errors = list(manifest_errors)
    for descriptor in selected:
        capture_date = str(descriptor.get("captureDate"))
        snapshot = (snapshots or {}).get(capture_date)
        if snapshot is None:
            path = _snapshot_path(descriptor)
            snapshot = load_json_file(path) if path and path.exists() else None
        errors = _snapshot_errors(snapshot, descriptor)
        if errors:
            validation_errors.extend(f"{capture_date}: {error}" for error in errors)
        elif isinstance(snapshot, dict):
            loaded.append((descriptor, snapshot))

    counts = {
        "availableSnapshots": len(descriptors),
        "validatedSnapshots": len(loaded),
        "events": 0,
        "spreadWidened": 0,
        "volumeSpiked": 0,
        "openInterestChanged": 0,
        "previousContracts": 0,
        "currentContracts": 0,
        "comparedContracts": 0,
    }
    comparison: dict[str, Any] = {"previousCaptureDate": None, "currentCaptureDate": None}
    events: list[dict[str, Any]] = []
    if validation_errors:
        verdict = "history-invalid"
    elif len(descriptors) < 2:
        verdict = "insufficient-history"
    else:
        previous_descriptor, previous = loaded[0]
        current_descriptor, latest = loaded[1]
        events, comparison_counts = compare_snapshots(previous, latest)
        counts.update(comparison_counts)
        counts["events"] = len(events)
        comparison = {
            "previousCaptureDate": previous_descriptor.get("captureDate"),
            "currentCaptureDate": current_descriptor.get("captureDate"),
        }
        verdict = "meaningful-changes" if events else "no-meaningful-change"

    return {
        "generatedAt": current_time.isoformat(),
        "stage": CHAIN_DIFF_STAGE,
        "verdict": verdict,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "history": {
            "stage": CHAIN_HISTORY_STAGE,
            "availableSnapshots": len(descriptors),
            "requiredSnapshots": 2,
        },
        "comparison": comparison,
        "counts": counts,
        "events": events,
        "validationErrors": validation_errors,
        "thresholds": {
            "spreadWideningPct": SPREAD_WIDENING_THRESHOLD,
            "volumeSpikeMultiple": VOLUME_SPIKE_THRESHOLD,
            "openInterestChangePct": OPEN_INTEREST_CHANGE_THRESHOLD,
        },
        "citations": [
            "data/inferno_chain_history_manifest.json",
            "docs/SCHWAB_EDGE_OPPORTUNITIES.md",
        ],
        "reminders": [
            "reads only immutable local chain-history snapshots; no market-data request was made",
            "events are diagnostic observations, not ticket, promotion, risk, or execution instructions",
            "zero events means no documented threshold crossed, not that a trade is safe or recommended",
        ],
    }


def render_chain_diff(payload: dict[str, Any]) -> str:
    """Render the provenance and bounded outcomes of the offline comparison."""
    history = payload.get("history") or {}
    comparison = payload.get("comparison") or {}
    counts = payload.get("counts") or {}
    lines = [
        "Inferno Schwab Chain Diff",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        "Authority: research-only; non-promotable; broker submit OFF; live trading OFF",
        "",
        "History:",
        f"- snapshots: {history.get('availableSnapshots', 0)} / {history.get('requiredSnapshots', 2)} required",
        f"- compared dates: {comparison.get('previousCaptureDate') or '-'} -> {comparison.get('currentCaptureDate') or '-'}",
        "",
        "Results:",
        f"- compared contracts: {counts.get('comparedContracts', 0)}",
        f"- meaningful events: {counts.get('events', 0)}",
        f"- spread widened: {counts.get('spreadWidened', 0)} (> {SPREAD_WIDENING_THRESHOLD:.0%})",
        f"- volume spiked: {counts.get('volumeSpiked', 0)} (> {VOLUME_SPIKE_THRESHOLD:g}x)",
        f"- open interest changed: {counts.get('openInterestChanged', 0)} (> {OPEN_INTEREST_CHANGE_THRESHOLD:.0%})",
    ]
    if payload.get("validationErrors"):
        lines.extend(["", "Validation errors:"])
        lines.extend(f"- {item}" for item in payload["validationErrors"])
    lines.extend(["", "Reminders:"])
    lines.extend(f"- {item}" for item in payload.get("reminders") or [])
    return "\n".join(lines) + "\n"


def save_chain_diff(payload: dict[str, Any]) -> None:
    """Persist the research-only diff artifact and its compact report."""
    ensure_dirs()
    atomic_write_json(CHAIN_DIFF_FILE, payload)
    atomic_write_text(CHAIN_DIFF_TEXT_FILE, render_chain_diff(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diff immutable local Schwab chain history.")
    parser.add_argument("command", nargs="?", default="run", choices=("run", "status"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        if CHAIN_DIFF_TEXT_FILE.exists():
            print(CHAIN_DIFF_TEXT_FILE.read_text(encoding="utf-8"), end="")
        else:
            print("(no Schwab chain-diff report yet)")
        return 0
    payload = build_chain_diff()
    save_chain_diff(payload)
    print(render_chain_diff(payload), end="")
    return 0 if payload.get("verdict") in VALID_VERDICTS else 1


if __name__ == "__main__":
    raise SystemExit(main())
