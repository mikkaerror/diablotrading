from __future__ import annotations

"""Automation watcher for export intake and paper fill processing.

This watcher can optionally trigger the experimental thinkorswim export bridge,
then scans Downloads, imports supported CSVs, and ingests the resulting fill
rows into the Inferno paper ledger. It is designed for paper-only evidence
building, not live order routing.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from inferno_config import (
    DOWNLOADS_WATCH_ALLOWED_WEEKDAYS,
    DOWNLOADS_WATCH_WINDOW_END,
    DOWNLOADS_WATCH_WINDOW_START,
    TOS_BACKGROUND_EXPORT_ALLOWED,
    in_time_window,
    local_now,
)
from inferno_downloads_manager import import_downloads
from inferno_tos_export_bridge import run_export_bridge
from inferno_tos_export_verifier import verify_export_bridge
from inferno_tos_fill_ingest import ingest_fill_log
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


DOWNLOADS_WATCH_FILE = DATA_DIR / "inferno_downloads_watch.json"
DOWNLOADS_WATCH_TEXT_FILE = REPORTS_DIR / "downloads_watch_latest.txt"


def automation_skip_reason() -> str | None:
    """Return a skip reason when the watcher should stay idle."""
    now = local_now()
    if now.weekday() not in DOWNLOADS_WATCH_ALLOWED_WEEKDAYS:
        return "downloads watch skipped outside allowed weekdays"
    if not in_time_window(now, DOWNLOADS_WATCH_WINDOW_START, DOWNLOADS_WATCH_WINDOW_END):
        return (
            "downloads watch skipped outside window "
            f"{DOWNLOADS_WATCH_WINDOW_START}-{DOWNLOADS_WATCH_WINDOW_END}"
        )
    return None


def run_watch(source_dir: Path | None = None, lookback_hours: int | None = None, export_first: bool = False, automation: bool = False) -> dict[str, Any]:
    """Run one full watch cycle."""
    ensure_dirs()
    skip_reason = automation_skip_reason() if automation else None
    report: dict[str, Any] = {
        "generatedAt": local_now().isoformat(),
        "automation": automation,
        "exportFirst": export_first,
        "skipped": bool(skip_reason),
        "skipReason": skip_reason,
    }
    if skip_reason:
        save_watch_report(report)
        return report

    if export_first:
        export_preflight = verify_export_bridge(require_enabled=False, allow_recovery=False)
        export_verdict = str(export_preflight.get("verdict") or "")
        export_enabled = bool(export_preflight.get("enabled"))
        report["exportVerifier"] = {
            "verdict": export_verdict,
            "message": export_preflight.get("message"),
            "appRunning": export_preflight.get("appRunning"),
            "shortcutValid": export_preflight.get("shortcutValid"),
            "systemEventsOk": export_preflight.get("systemEventsOk"),
            "sessionSummary": (export_preflight.get("sessionProbe") or {}).get("summary"),
            "currentPanel": (export_preflight.get("sessionProbe") or {}).get("currentPanel"),
            "currentPanelSafety": (export_preflight.get("sessionProbe") or {}).get("currentPanelSafety"),
        }
        export_ready = export_verdict in {"ready", "ready-live-readonly"} or (export_verdict == "inactive-safe" and not export_enabled)
        if export_ready and automation and not TOS_BACKGROUND_EXPORT_ALLOWED:
            # Background launchd agents must never foreground TOS unless the
            # operator explicitly opts in. This keeps the watch loop useful for
            # ingesting existing exports without constantly activating the app.
            report["exportBridge"] = {
                "ok": False,
                "status": "background-export-disabled",
                "message": "background TOS export disabled; set TOS_BACKGROUND_EXPORT_ALLOWED=1 for supervised opt-in",
            }
        elif export_ready:
            report["exportBridge"] = run_export_bridge(dry_run=False)
        else:
            report["exportBridge"] = {
                "ok": False,
                "status": "preflight-blocked",
                "message": export_preflight.get("message"),
            }
    downloads_report = import_downloads(source_dir=source_dir, lookback_hours=lookback_hours)
    fill_report = ingest_fill_log()
    report["downloadsManager"] = {
        "importedFiles": downloads_report.get("importedFiles", 0),
        "importedRows": downloads_report.get("importedRows", 0),
        "quarantinedFiles": downloads_report.get("quarantinedFiles", 0),
        "sourceDir": downloads_report.get("sourceDir"),
    }
    report["fillIngest"] = {
        "processedRows": fill_report.get("processedRows", 0),
        "importedRows": fill_report.get("importedRows", 0),
        "closedRows": fill_report.get("closedRows", 0),
        "unmatchedRows": len(fill_report.get("unmatchedRows") or []),
    }
    save_watch_report(report)
    return report


def watch_report_text(report: dict[str, Any]) -> str:
    """Render the watcher status into a human-readable report."""
    lines = [
        "Inferno Downloads Watch",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Automation: {report.get('automation')}",
        f"Export first: {report.get('exportFirst')}",
        f"Skipped: {report.get('skipped')}",
    ]
    if report.get("skipReason"):
        lines.append(f"Skip reason: {report.get('skipReason')}")
    if report.get("exportBridge"):
        bridge = report["exportBridge"]
        lines.append(f"Export bridge: {bridge.get('status')} | {bridge.get('message')}")
    if report.get("exportVerifier"):
        verifier = report["exportVerifier"]
        lines.append(
            f"Export verifier: {verifier.get('verdict')} | "
            f"app-running {verifier.get('appRunning')} | "
            f"system-events {verifier.get('systemEventsOk')}"
        )
        if verifier.get("sessionSummary"):
            lines.append(f"Session: {verifier.get('sessionSummary')}")
        if verifier.get("currentPanel"):
            lines.append(
                f"Panel gate: {verifier.get('currentPanel')} | "
                f"safety {verifier.get('currentPanelSafety')}"
            )
    manager = report.get("downloadsManager")
    if manager:
        lines.append(
            f"Downloads manager: {manager.get('importedFiles', 0)} files | "
            f"{manager.get('importedRows', 0)} rows | "
            f"{manager.get('quarantinedFiles', 0)} quarantined"
        )
    fill = report.get("fillIngest")
    if fill:
        lines.append(
            f"Fill ingest: {fill.get('processedRows', 0)} processed | "
            f"{fill.get('importedRows', 0)} imported | "
            f"{fill.get('closedRows', 0)} closed | "
            f"{fill.get('unmatchedRows', 0)} unmatched"
        )
    return "\n".join(lines).rstrip() + "\n"


def save_watch_report(report: dict[str, Any]) -> None:
    """Persist the watch JSON and text reports."""
    ensure_dirs()
    DOWNLOADS_WATCH_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    DOWNLOADS_WATCH_TEXT_FILE.write_text(watch_report_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the Downloads watch runner."""
    parser = argparse.ArgumentParser(description="Run the Downloads export/intake watcher.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--source-dir", default="", help="Optional override for the directory to scan")
    parser.add_argument("--lookback-hours", type=int, default=0, help="Optional override for recent file window")
    parser.add_argument("--export-first", action="store_true", help="Trigger the experimental thinkorswim export bridge first")
    parser.add_argument("--automation", action="store_true", help="Honor the configured weekday/time window")
    return parser.parse_args()


def main() -> int:
    """Run or show the Downloads watch report."""
    args = parse_args()
    if args.command == "status" and DOWNLOADS_WATCH_TEXT_FILE.exists():
        print(DOWNLOADS_WATCH_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = run_watch(
        source_dir=Path(args.source_dir).expanduser() if args.source_dir else None,
        lookback_hours=args.lookback_hours or None,
        export_first=args.export_first,
        automation=args.automation,
    )
    print(watch_report_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
