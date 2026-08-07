from __future__ import annotations

"""Persist immutable, read-only daily Schwab normalized-chain snapshots.

This is the evidence-collection prerequisite for any future per-ticker IV
calibration.  It reads only the already-normalized local Schwab market-data
artifact; it performs no network request and has no ticket, broker, or
authority surface.  Each captured market date is written once and never
rewritten, so later calibration can distinguish genuine history from a
retroactively refreshed quote.
"""

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


SCHWAB_OPTIONS_FILE = DATA_DIR / "inferno_schwab_options.json"
CHAIN_HISTORY_FILE = DATA_DIR / "inferno_chain_history.json"
CHAIN_HISTORY_MANIFEST_FILE = DATA_DIR / "inferno_chain_history_manifest.json"
CHAIN_HISTORY_TEXT_FILE = REPORTS_DIR / "chain_history_latest.txt"
CHAIN_HISTORY_ROOT = DATA_DIR / "chain_history"
CHAIN_HISTORY_HOT_DIR = CHAIN_HISTORY_ROOT / "hot"
CHAIN_HISTORY_ARCHIVE_DIR = CHAIN_HISTORY_ROOT / "archive"

CHAIN_HISTORY_STAGE = "schwab-chain-history-research-only"
HOT_RETENTION_DAYS = 90
ARCHIVE_RETENTION_DAYS = 365
CALIBRATION_MINIMUM_DAYS = 60
ACCEPTED_SOURCE_STATUSES = frozenset({"ok"})


def empty_manifest() -> dict[str, Any]:
    """Return the versioned manifest for immutable local chain snapshots."""
    return {
        "version": 1,
        "generatedAt": None,
        "stage": CHAIN_HISTORY_STAGE,
        "researchOnly": True,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "hotSnapshots": [],
        "archiveSnapshots": [],
    }


def _parse_iso_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=local_now().tzinfo)
    return parsed


def _capture_date(value: Any) -> date | None:
    parsed = _parse_iso_datetime(value)
    return parsed.date() if parsed else None


def _safe_descriptors(value: Any) -> list[dict[str, Any]]:
    """Keep only manifest descriptors with a valid, local capture date."""
    if not isinstance(value, list):
        return []
    return [
        dict(item)
        for item in value
        if isinstance(item, dict) and _capture_date(item.get("captureDate"))
    ]


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    """Load a history manifest safely without accepting altered authority flags."""
    payload = load_json_file(path or CHAIN_HISTORY_MANIFEST_FILE) or {}
    manifest = empty_manifest()
    if not isinstance(payload, dict):
        return manifest
    manifest["version"] = int(payload.get("version") or manifest["version"])
    manifest["generatedAt"] = payload.get("generatedAt")
    manifest["hotSnapshots"] = _safe_descriptors(payload.get("hotSnapshots"))
    manifest["archiveSnapshots"] = _safe_descriptors(payload.get("archiveSnapshots"))
    return manifest


def snapshot_path(capture_day: date, *, archived: bool = False) -> Path:
    """Return the controlled local path for one daily immutable snapshot."""
    directory = CHAIN_HISTORY_ARCHIVE_DIR if archived else CHAIN_HISTORY_HOT_DIR
    return directory / f"{capture_day.isoformat()}.json"


def _relative_path(path: Path) -> str:
    """Render a manifest path rooted under the ignored data directory."""
    try:
        return str(path.relative_to(DATA_DIR))
    except ValueError:
        return str(path)


def _descriptor_path(descriptor: dict[str, Any]) -> Path | None:
    raw = str(descriptor.get("path") or "").strip()
    if not raw:
        return None
    candidate = (DATA_DIR / raw).resolve()
    root = CHAIN_HISTORY_ROOT.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def source_errors(source: dict[str, Any]) -> list[str]:
    """Return fail-closed reasons a source cannot become calibration history."""
    errors: list[str] = []
    if source.get("researchOnly") is not True:
        errors.append("source is not marked research-only")
    if source.get("authorityChanged") is not False:
        errors.append("source authorityChanged is not false")
    if str(source.get("status") or "") not in ACCEPTED_SOURCE_STATUSES:
        errors.append("source status is not a complete Schwab chain report")
    if not _capture_date(source.get("generatedAt")):
        errors.append("source generatedAt is invalid")
    rows = source.get("rows")
    if not isinstance(rows, list) or not rows:
        errors.append("source has no normalized chain rows")
    elif any(not isinstance(row, dict) or row.get("status") != "ok" for row in rows):
        errors.append("source contains an incomplete normalized chain row")
    return errors


def _descriptor_for_snapshot(
    *,
    capture_day: date,
    captured_at: datetime,
    source: dict[str, Any],
    path: Path,
) -> dict[str, Any]:
    rows = source.get("rows") or []
    symbols = [str(row.get("symbol") or "").upper() for row in rows if row.get("symbol")]
    return {
        "captureDate": capture_day.isoformat(),
        "capturedAt": captured_at.isoformat(),
        "sourceGeneratedAt": source.get("generatedAt"),
        "sourceStatus": source.get("status"),
        "rowCount": len(rows),
        "symbols": symbols,
        "path": _relative_path(path),
    }


def _snapshot_payload(
    *,
    capture_day: date,
    captured_at: datetime,
    source: dict[str, Any],
) -> dict[str, Any]:
    """Preserve the full normalized rows for later surface calculations."""
    return {
        "version": 1,
        "stage": CHAIN_HISTORY_STAGE,
        "researchOnly": True,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "captureDate": capture_day.isoformat(),
        "capturedAt": captured_at.isoformat(),
        "source": {
            "artifact": SCHWAB_OPTIONS_FILE.name,
            "stage": source.get("stage"),
            "status": source.get("status"),
            "generatedAt": source.get("generatedAt"),
            "symbolCount": source.get("symbolCount"),
        },
        "rows": source.get("rows") or [],
        "reminders": [
            "normalized local market-data snapshot only; no network request was made",
            "history is diagnostic-only and cannot change tickets, promotion, risk, or broker authority",
            "each capture date is immutable; missing dates remain visible rather than backfilled",
        ],
    }


def _recoverable_snapshot(path: Path, *, capture_day: date, source: dict[str, Any]) -> dict[str, Any] | None:
    """Return an unindexed local snapshot only when its provenance is intact.

    This handles an interrupted manifest write without rewriting the immutable
    snapshot.  A pre-existing file with any authority, source-date, or stage
    mismatch remains rejected rather than being adopted into history.
    """
    payload = load_json_file(path) or {}
    if not isinstance(payload, dict):
        return None
    source_meta = payload.get("source") or {}
    safe = (
        payload.get("stage") == CHAIN_HISTORY_STAGE
        and payload.get("researchOnly") is True
        and payload.get("authorityChanged") is False
        and payload.get("brokerSubmitAllowed") is False
        and payload.get("liveTradingAllowed") is False
        and payload.get("captureDate") == capture_day.isoformat()
        and source_meta.get("status") == "ok"
        and source_meta.get("generatedAt") == source.get("generatedAt")
        and payload.get("rows") == source.get("rows")
    )
    return payload if safe else None


def prune_history(manifest: dict[str, Any], *, now: datetime) -> dict[str, int]:
    """Move controlled old snapshots to archive and expire only aged archives."""
    hot_cutoff = now.date() - timedelta(days=HOT_RETENTION_DAYS)
    # Archive retention begins after a snapshot leaves the hot tier.  Keep the
    # documented 90-day hot window *plus* the full 365-day archive window.
    archive_cutoff = now.date() - timedelta(days=HOT_RETENTION_DAYS + ARCHIVE_RETENTION_DAYS)
    moved = 0
    removed = 0
    retained_hot: list[dict[str, Any]] = []
    archived = _safe_descriptors(manifest.get("archiveSnapshots"))

    for descriptor in _safe_descriptors(manifest.get("hotSnapshots")):
        captured = _capture_date(descriptor.get("captureDate"))
        source_path = _descriptor_path(descriptor)
        if captured is None or captured >= hot_cutoff:
            retained_hot.append(descriptor)
            continue
        destination = snapshot_path(captured, archived=True)
        if source_path is None or not source_path.exists() or destination.exists():
            retained_hot.append(descriptor)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_path.replace(destination)
        archived.append({**descriptor, "path": _relative_path(destination)})
        moved += 1

    retained_archive: list[dict[str, Any]] = []
    for descriptor in archived:
        captured = _capture_date(descriptor.get("captureDate"))
        path = _descriptor_path(descriptor)
        if captured is None or captured >= archive_cutoff:
            retained_archive.append(descriptor)
            continue
        if path is None or not path.exists():
            retained_archive.append(descriptor)
            continue
        path.unlink()
        removed += 1

    manifest["hotSnapshots"] = sorted(retained_hot, key=lambda item: item["captureDate"])
    manifest["archiveSnapshots"] = sorted(retained_archive, key=lambda item: item["captureDate"])
    return {"movedToArchive": moved, "expiredFromArchive": removed}


def history_readiness(manifest: dict[str, Any]) -> dict[str, Any]:
    """Expose evidence coverage without claiming an IV calibration is ready early."""
    descriptors = _safe_descriptors(manifest.get("hotSnapshots")) + _safe_descriptors(
        manifest.get("archiveSnapshots")
    )
    latest = max(descriptors, key=lambda item: item["captureDate"], default=None)
    missing_files = sum(
        1
        for descriptor in descriptors
        if (path := _descriptor_path(descriptor)) is None or not path.exists()
    )
    recorded_days = len(descriptors)
    return {
        "recordedDays": recorded_days,
        "minimumDaysForCalibration": CALIBRATION_MINIMUM_DAYS,
        "readyForCalibration": recorded_days >= CALIBRATION_MINIMUM_DAYS and missing_files == 0,
        "latestCaptureDate": latest.get("captureDate") if latest else None,
        "missingSnapshotFiles": missing_files,
    }


def build_chain_history(
    *,
    source_report: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Capture one safe source date, then apply the bounded retention policy."""
    current = now or local_now()
    source = source_report if source_report is not None else (load_json_file(SCHWAB_OPTIONS_FILE) or {})
    current_manifest = manifest if manifest is not None else load_manifest()
    normalized_manifest = empty_manifest()
    normalized_manifest.update(current_manifest if isinstance(current_manifest, dict) else {})
    normalized_manifest["hotSnapshots"] = _safe_descriptors(normalized_manifest.get("hotSnapshots"))
    normalized_manifest["archiveSnapshots"] = _safe_descriptors(normalized_manifest.get("archiveSnapshots"))

    errors = source_errors(source if isinstance(source, dict) else {})
    capture: dict[str, Any]
    if errors:
        capture = {"status": "source-rejected", "reason": "; ".join(errors), "captureDate": None}
    else:
        source = dict(source)
        capture_day = _capture_date(source.get("generatedAt"))
        assert capture_day is not None  # guarded by source_errors
        existing = {
            item["captureDate"]
            for item in normalized_manifest["hotSnapshots"] + normalized_manifest["archiveSnapshots"]
        }
        path = snapshot_path(capture_day)
        if capture_day.isoformat() in existing:
            capture = {
                "status": "history-unchanged",
                "reason": "immutable snapshot already recorded for source date",
                "captureDate": capture_day.isoformat(),
            }
        elif path.exists():
            recovered = _recoverable_snapshot(path, capture_day=capture_day, source=source)
            if recovered is None:
                capture = {
                    "status": "source-rejected",
                    "reason": "unindexed snapshot path already exists; refusing to overwrite immutable history",
                    "captureDate": capture_day.isoformat(),
                }
            else:
                captured_at = _parse_iso_datetime(recovered.get("capturedAt")) or current
                normalized_manifest["hotSnapshots"].append(
                    _descriptor_for_snapshot(
                        capture_day=capture_day,
                        captured_at=captured_at,
                        source=source,
                        path=path,
                    )
                )
                capture = {
                    "status": "history-recovered",
                    "reason": "recovered an intact immutable snapshot after an interrupted manifest write",
                    "captureDate": capture_day.isoformat(),
                }
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(
                path,
                _snapshot_payload(capture_day=capture_day, captured_at=current, source=source),
            )
            normalized_manifest["hotSnapshots"].append(
                _descriptor_for_snapshot(
                    capture_day=capture_day,
                    captured_at=current,
                    source=source,
                    path=path,
                )
            )
            capture = {
                "status": "history-captured",
                "reason": "immutable normalized snapshot recorded",
                "captureDate": capture_day.isoformat(),
            }

    retention = prune_history(normalized_manifest, now=current)
    normalized_manifest.update(
        {
            "generatedAt": current.isoformat(),
            "stage": CHAIN_HISTORY_STAGE,
            "researchOnly": True,
            "authorityChanged": False,
            "brokerSubmitAllowed": False,
            "liveTradingAllowed": False,
        }
    )
    readiness = history_readiness(normalized_manifest)
    payload = {
        "generatedAt": current.isoformat(),
        "stage": CHAIN_HISTORY_STAGE,
        "verdict": "history-ready" if readiness["readyForCalibration"] else "history-bootstrapping",
        "researchOnly": True,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "source": {
            "artifact": SCHWAB_OPTIONS_FILE.name,
            "status": source.get("status") if isinstance(source, dict) else None,
            "generatedAt": source.get("generatedAt") if isinstance(source, dict) else None,
        },
        "capture": capture,
        "counts": {
            "hotSnapshots": len(normalized_manifest["hotSnapshots"]),
            "archiveSnapshots": len(normalized_manifest["archiveSnapshots"]),
            **retention,
        },
        "readiness": readiness,
        "reminders": [
            "reads only the local normalized Schwab chain artifact; no market-data request is made",
            "does not feed strike selection, paper tickets, promotion, risk settings, or broker authority",
            f"per-ticker IV calibration stays unavailable until at least {CALIBRATION_MINIMUM_DAYS} complete local capture dates exist",
        ],
    }
    return payload, normalized_manifest


def render_chain_history(payload: dict[str, Any]) -> str:
    """Render a concise provenance-first history-collection report."""
    capture = payload.get("capture") or {}
    counts = payload.get("counts") or {}
    readiness = payload.get("readiness") or {}
    lines = [
        "Inferno Schwab Chain History",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        "Authority: research-only; broker submit OFF; live trading OFF",
        "",
        "Capture:",
        f"- status: {capture.get('status')}",
        f"- source date: {capture.get('captureDate') or '-'}",
        f"- detail: {capture.get('reason') or '-'}",
        "",
        "Retention:",
        f"- hot snapshots: {counts.get('hotSnapshots', 0)} / {HOT_RETENTION_DAYS} day window",
        f"- archived snapshots: {counts.get('archiveSnapshots', 0)} / {ARCHIVE_RETENTION_DAYS} day window",
        f"- moved this run: {counts.get('movedToArchive', 0)}",
        f"- expired this run: {counts.get('expiredFromArchive', 0)}",
        "",
        "Calibration readiness:",
        f"- recorded dates: {readiness.get('recordedDays', 0)} / {readiness.get('minimumDaysForCalibration', CALIBRATION_MINIMUM_DAYS)}",
        f"- latest capture: {readiness.get('latestCaptureDate') or '-'}",
        f"- missing snapshot files: {readiness.get('missingSnapshotFiles', 0)}",
        f"- ready for calibration: {readiness.get('readyForCalibration')}",
        "",
        "Reminders:",
    ]
    lines.extend(f"- {item}" for item in payload.get("reminders") or [])
    return "\n".join(lines) + "\n"


def save_chain_history(payload: dict[str, Any], manifest: dict[str, Any]) -> None:
    """Persist only research-only history metadata and its text report."""
    ensure_dirs()
    CHAIN_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(CHAIN_HISTORY_MANIFEST_FILE, manifest)
    atomic_write_json(CHAIN_HISTORY_FILE, payload)
    atomic_write_text(CHAIN_HISTORY_TEXT_FILE, render_chain_history(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture local read-only Schwab chain history.")
    parser.add_argument("command", nargs="?", default="run", choices=("run", "status"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        if CHAIN_HISTORY_TEXT_FILE.exists():
            print(CHAIN_HISTORY_TEXT_FILE.read_text(encoding="utf-8"), end="")
        else:
            print("(no Schwab chain-history report yet)")
        return 0
    payload, manifest = build_chain_history()
    save_chain_history(payload, manifest)
    print(render_chain_history(payload), end="")
    return 0 if payload.get("capture", {}).get("status") in {"history-captured", "history-unchanged", "history-recovered"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
