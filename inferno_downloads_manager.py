from __future__ import annotations

"""Downloads intake manager for broker-style CSV artifacts.

This module scans a source directory, usually macOS Downloads, for trading-like
CSV files. It normalizes supported files into the canonical Inferno paper fill
log, archives a copy for audit, quarantines suspicious unsupported files, and
records a detailed intake report so automation stays explainable.
"""

import argparse
import csv
import hashlib
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from inferno_config import DOWNLOADS_LOOKBACK_HOURS, DOWNLOADS_SCAN_DIR, local_now
from inferno_tos_fill_ingest import row_fingerprint, text
from inferno_tos_sandbox import FILL_LOG_COLUMNS, TOS_FILL_LOG_WORK_FILE, write_fill_log_template
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


DOWNLOADS_MANAGER_FILE = DATA_DIR / "inferno_downloads_manager.json"
DOWNLOADS_MANAGER_STATE_FILE = DATA_DIR / "inferno_downloads_manager_state.json"
DOWNLOADS_MANAGER_TEXT_FILE = REPORTS_DIR / "downloads_manager_latest.txt"
DOWNLOADS_ARCHIVE_DIR = DATA_DIR / "downloads_archive"
PROCESSED_ARCHIVE_DIR = DOWNLOADS_ARCHIVE_DIR / "processed"
QUARANTINE_ARCHIVE_DIR = DOWNLOADS_ARCHIVE_DIR / "quarantine"

TRADING_FILENAME_TOKENS = (
    "tos",
    "thinkorswim",
    "paper",
    "trade",
    "trades",
    "fill",
    "fills",
    "order",
    "orders",
    "transaction",
    "activity",
    "accountstatement",
    "statement",
)
GENERIC_ALIAS_GROUPS = {
    "ticketId": ("ticketid", "ticket_id", "ticket id"),
    "ticker": ("ticker", "symbol", "underlying", "stock"),
    "strategy": ("strategy", "spread", "order strategy", "strategy type"),
    "expiration": ("expiration", "expiry", "exp date", "expiration date"),
    "environment": ("environment", "platform"),
    "paperAccount": ("paperaccount", "paper account", "account", "account name", "account number"),
    "routeFamily": ("routefamily", "route family", "route", "setup", "setuprec"),
    "orderType": ("ordertype", "order type", "type"),
    "contracts": ("contracts", "qty", "quantity", "filled qty", "filled quantity"),
    "entryPrice": ("entryprice", "entry price", "price", "fill price", "avg price", "average price"),
    "exitPrice": ("exitprice", "exit price", "close price", "closing price"),
    "realizedPnl": ("realizedpnl", "realized pnl", "p/l", "pnl", "profit/loss", "realized gain/loss"),
    "status": ("status", "state", "order status", "trade status"),
    "openedAt": ("openedat", "opened at", "exec time", "filled time", "entry time", "time", "date"),
    "closedAt": ("closedat", "closed at", "exit time", "closing time", "closed time"),
    "notes": ("notes", "memo", "comment", "description"),
}
TRADING_HEADER_HINTS = {alias for aliases in GENERIC_ALIAS_GROUPS.values() for alias in aliases}


def normalize_header(value: Any) -> str:
    """Normalize a CSV header for case-insensitive mapper lookup."""
    return "".join(char for char in text(value).lower() if char.isalnum())


def file_sha256(path: Path) -> str:
    """Return a stable content fingerprint for one intake file."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_manager_state() -> dict[str, Any]:
    """Load the downloads manager state file or return a clean shell."""
    if DOWNLOADS_MANAGER_STATE_FILE.exists():
        try:
            payload = json.loads(DOWNLOADS_MANAGER_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(payload.get("files"), dict):
                return payload
        except json.JSONDecodeError:
            pass
    return {"generatedAt": None, "updatedAt": None, "files": {}}


def save_manager_state(state: dict[str, Any]) -> None:
    """Persist the downloads manager state file."""
    ensure_dirs()
    DOWNLOADS_MANAGER_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def trading_filename(path: Path) -> bool:
    """Return whether a file name looks trading-related."""
    lowered = path.name.lower()
    return any(token in lowered for token in TRADING_FILENAME_TOKENS)


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    """Read one CSV file and return headers plus rows."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        rows = list(reader)
    return headers, rows


def inferno_fill_log_schema(headers: list[str]) -> bool:
    """Return True when a CSV already matches the canonical fill-log schema."""
    normalized = {normalize_header(header) for header in headers}
    required = {normalize_header(column) for column in ("ticker", "status")}
    return required.issubset(normalized) and {normalize_header(column) for column in FILL_LOG_COLUMNS}.issubset(normalized)


def header_map(headers: list[str]) -> dict[str, str]:
    """Build a canonical field map from arbitrary CSV headers."""
    normalized_to_source = {normalize_header(header): header for header in headers}
    mapped: dict[str, str] = {}
    for canonical, aliases in GENERIC_ALIAS_GROUPS.items():
        for alias in aliases:
            normalized = normalize_header(alias)
            if normalized in normalized_to_source:
                mapped[canonical] = normalized_to_source[normalized]
                break
    return mapped


def looks_trading_like(path: Path, headers: list[str]) -> bool:
    """Decide whether a CSV is worth routing through the trading intake desk."""
    if trading_filename(path):
        return True
    normalized_headers = {normalize_header(header) for header in headers}
    return len(normalized_headers & {normalize_header(value) for value in TRADING_HEADER_HINTS}) >= 2


def detect_schema(path: Path, headers: list[str]) -> tuple[str | None, str]:
    """Classify a CSV schema conservatively."""
    if inferno_fill_log_schema(headers):
        return "inferno-fill-log", "matches canonical Inferno fill log columns"
    mapped = header_map(headers)
    if {"ticker", "entryPrice"} <= set(mapped) and ("status" in mapped or "realizedPnl" in mapped or "openedAt" in mapped):
        return "generic-broker-fill", "matched generic broker fill aliases"
    if looks_trading_like(path, headers):
        return None, "trading-like CSV but unsupported schema"
    return None, "non-trading CSV ignored"


def canonical_blank_row() -> dict[str, str]:
    """Return a new empty canonical fill-log row."""
    return {column: "" for column in FILL_LOG_COLUMNS}


def canonicalize_inferno_row(row: dict[str, Any]) -> dict[str, str]:
    """Normalize one already-supported fill-log row."""
    normalized = canonical_blank_row()
    for column in FILL_LOG_COLUMNS:
        normalized[column] = text(row.get(column))
    return normalized


def derived_status(normalized_row: dict[str, str]) -> str:
    """Derive a safe fallback status when the source file omitted one."""
    if normalized_row["status"]:
        return normalized_row["status"]
    if normalized_row["exitPrice"] or normalized_row["realizedPnl"] or normalized_row["closedAt"]:
        return "closed"
    if normalized_row["entryPrice"] or normalized_row["openedAt"]:
        return "open"
    return "pending"


def canonicalize_generic_row(row: dict[str, Any], mapped: dict[str, str], path: Path) -> dict[str, str]:
    """Map a generic broker-like CSV row into the canonical fill-log shape."""
    normalized = canonical_blank_row()
    for canonical, source_header in mapped.items():
        normalized[canonical] = text(row.get(source_header))
    normalized["sessionDate"] = normalized["sessionDate"] or text(normalized["openedAt"])[:10] or text(normalized["closedAt"])[:10]
    normalized["environment"] = normalized["environment"] or (
        "thinkorswim-paperMoney" if "paper" in path.name.lower() or "tos" in path.name.lower() else "broker-import"
    )
    normalized["status"] = derived_status(normalized)
    return normalized


def load_existing_fill_log() -> tuple[list[dict[str, str]], set[str]]:
    """Load the canonical fill log and return rows plus row fingerprints."""
    write_fill_log_template()
    with TOS_FILL_LOG_WORK_FILE.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [{column: text(row.get(column)) for column in FILL_LOG_COLUMNS} for row in reader]
    fingerprints = {row_fingerprint(row) for row in rows if any(text(value) for value in row.values())}
    return rows, fingerprints


def save_fill_log(rows: list[dict[str, str]]) -> None:
    """Persist the canonical fill log with the latest normalized rows."""
    write_fill_log_template()
    with TOS_FILL_LOG_WORK_FILE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FILL_LOG_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def archive_copy(path: Path, destination_root: Path, fingerprint: str) -> str:
    """Copy a source file into the audit archive and return the archived path."""
    ensure_dirs()
    destination_root.mkdir(parents=True, exist_ok=True)
    archived_name = f"{path.stem}--{fingerprint[:12]}{path.suffix.lower()}"
    destination = destination_root / archived_name
    shutil.copy2(path, destination)
    return str(destination)


def recent_csv_files(source_dir: Path, lookback_hours: int) -> list[Path]:
    """Return recent CSV files from the source directory, newest first."""
    if not source_dir.exists():
        return []
    cutoff = local_now() - timedelta(hours=lookback_hours)
    files = [
        path
        for path in source_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() == ".csv"
        and not path.name.startswith(".")
        and datetime.fromtimestamp(path.stat().st_mtime).astimezone() >= cutoff
    ]
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)


def import_downloads(source_dir: Path | None = None, lookback_hours: int | None = None) -> dict[str, Any]:
    """Scan Downloads, normalize supported files, and update the canonical fill log."""
    source_dir = (source_dir or DOWNLOADS_SCAN_DIR).expanduser()
    lookback_hours = lookback_hours or DOWNLOADS_LOOKBACK_HOURS
    ensure_dirs()

    state = load_manager_state()
    files_state = dict(state.get("files") or {})
    fill_rows, existing_fingerprints = load_existing_fill_log()

    imported_files = 0
    imported_rows = 0
    quarantined_files = 0
    ignored_files = 0
    notes: list[str] = []
    processed_files: list[dict[str, Any]] = []

    for path in recent_csv_files(source_dir, lookback_hours):
        fingerprint = file_sha256(path)
        prior = files_state.get(fingerprint)
        if prior and prior.get("sourceMtime") == path.stat().st_mtime:
            continue

        headers, rows = read_csv_rows(path)
        schema, reason = detect_schema(path, headers)
        file_record = {
            "sourcePath": str(path),
            "sourceMtime": path.stat().st_mtime,
            "seenAt": local_now().isoformat(),
            "reason": reason,
            "schema": schema,
        }

        if schema == "inferno-fill-log":
            normalized_rows = [canonicalize_inferno_row(row) for row in rows if any(text(value) for value in row.values())]
        elif schema == "generic-broker-fill":
            mapped = header_map(headers)
            normalized_rows = [canonicalize_generic_row(row, mapped, path) for row in rows if any(text(value) for value in row.values())]
        elif looks_trading_like(path, headers):
            quarantined_files += 1
            archived = archive_copy(path, QUARANTINE_ARCHIVE_DIR, fingerprint)
            file_record.update({"status": "quarantined", "archivedPath": archived, "rowCount": len(rows)})
            files_state[fingerprint] = file_record
            processed_files.append(file_record)
            notes.append(f"{path.name}: quarantined unsupported trading-like CSV")
            continue
        else:
            ignored_files += 1
            file_record.update({"status": "ignored", "rowCount": len(rows)})
            files_state[fingerprint] = file_record
            processed_files.append(file_record)
            continue

        appended = 0
        for row in normalized_rows:
            fingerprint_row = row_fingerprint(row)
            if fingerprint_row in existing_fingerprints:
                continue
            fill_rows.append(row)
            existing_fingerprints.add(fingerprint_row)
            appended += 1

        save_fill_log(fill_rows)
        archived = archive_copy(path, PROCESSED_ARCHIVE_DIR, fingerprint)
        imported_files += 1
        imported_rows += appended
        file_record.update(
            {
                "status": "imported",
                "archivedPath": archived,
                "rowCount": len(normalized_rows),
                "importedRowCount": appended,
            }
        )
        files_state[fingerprint] = file_record
        processed_files.append(file_record)
        notes.append(f"{path.name}: imported {appended} new row(s) via {schema}")

    report = {
        "generatedAt": local_now().isoformat(),
        "sourceDir": str(source_dir),
        "lookbackHours": lookback_hours,
        "importedFiles": imported_files,
        "importedRows": imported_rows,
        "quarantinedFiles": quarantined_files,
        "ignoredFiles": ignored_files,
        "processedFiles": processed_files,
        "notes": notes,
        "knownFileCount": len(files_state),
        "fillLogPath": str(TOS_FILL_LOG_WORK_FILE),
    }
    save_manager_state(
        {
            **state,
            "generatedAt": state.get("generatedAt") or report["generatedAt"],
            "updatedAt": report["generatedAt"],
            "files": files_state,
        }
    )
    save_downloads_report(report)
    return report


def downloads_report_text(report: dict[str, Any]) -> str:
    """Render the latest downloads intake report."""
    lines = [
        "Inferno Downloads Manager",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Source dir: {report.get('sourceDir')}",
        f"Lookback hours: {report.get('lookbackHours')}",
        f"Imported files: {report.get('importedFiles', 0)}",
        f"Imported rows: {report.get('importedRows', 0)}",
        f"Quarantined files: {report.get('quarantinedFiles', 0)}",
        f"Ignored files: {report.get('ignoredFiles', 0)}",
        f"Fill log: {report.get('fillLogPath')}",
        "",
        "Notes:",
    ]
    notes = report.get("notes") or []
    if notes:
        lines.extend(f"- {note}" for note in notes[:25])
    else:
        lines.append("- none")
    lines.extend(["", "Processed files:"])
    processed = report.get("processedFiles") or []
    if processed:
        for file_record in processed[:25]:
            lines.append(
                f"- {Path(file_record.get('sourcePath', '')).name} | "
                f"{file_record.get('status')} | "
                f"{file_record.get('schema') or 'n/a'} | "
                f"{file_record.get('reason')}"
            )
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def save_downloads_report(report: dict[str, Any]) -> None:
    """Persist JSON and text reports for the latest Downloads scan."""
    ensure_dirs()
    DOWNLOADS_MANAGER_FILE.write_text(
        json.dumps(
            {
                "generatedAt": report.get("generatedAt"),
                "sourceDir": report.get("sourceDir"),
                "lookbackHours": report.get("lookbackHours"),
                "importedFiles": report.get("importedFiles"),
                "importedRows": report.get("importedRows"),
                "quarantinedFiles": report.get("quarantinedFiles"),
                "ignoredFiles": report.get("ignoredFiles"),
                "fillLogPath": report.get("fillLogPath"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    DOWNLOADS_MANAGER_TEXT_FILE.write_text(downloads_report_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the downloads manager."""
    parser = argparse.ArgumentParser(description="Scan Downloads for supported broker-style CSVs and normalize them.")
    parser.add_argument("command", nargs="?", default="scan", choices=["scan", "status"])
    parser.add_argument("--source-dir", default=str(DOWNLOADS_SCAN_DIR), help="Directory to scan for CSV files")
    parser.add_argument("--lookback-hours", type=int, default=DOWNLOADS_LOOKBACK_HOURS, help="Recent file window")
    return parser.parse_args()


def main() -> int:
    """Run a Downloads scan or show the last scan report."""
    args = parse_args()
    if args.command == "status" and DOWNLOADS_MANAGER_TEXT_FILE.exists():
        print(DOWNLOADS_MANAGER_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = import_downloads(Path(args.source_dir), args.lookback_hours)
    print(downloads_report_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
