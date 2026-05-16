from __future__ import annotations

"""Desktop automation coordinator for the Inferno paper-execution lane.

This module is the desk's safe local conductor. It does not place trades,
does not unlock live broker authority, and does not bypass any approval gate.
Its job is to chain the existing guarded desktop tools into one explainable
cycle:

1. verify the thinkorswim export path
2. optionally trigger the export/downloads intake lane
3. ingest any paper fills found in Downloads
4. rebuild the paperMoney sandbox packet

The result is a single source of truth for "is the local broker-adjacent
automation lane ready, blocked, or healthy right now?"
"""

import argparse
import json
from pathlib import Path
from typing import Any

from inferno_config import local_now
from inferno_downloads_watch import run_watch
from inferno_tos_account_statement_scraper import scrape_account_statement
from inferno_tos_export_verifier import verify_export_bridge
from inferno_tos_sandbox import build_tos_sandbox_session, save_tos_sandbox_session
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


DESKTOP_AUTOMATION_FILE = DATA_DIR / "inferno_desktop_automation.json"
DESKTOP_AUTOMATION_TEXT_FILE = REPORTS_DIR / "desktop_automation_latest.txt"


def text(value: Any) -> str:
    """Normalize arbitrary values into trimmed text."""
    return str(value or "").strip()


def verifier_allows_local_cycle(verifier: dict[str, Any], *, require_tos_running: bool) -> tuple[bool, str]:
    """Return whether the current export/session verifier permits a local cycle.

    We allow a cycle to continue when the export lane is healthy enough to be
    supervised manually (`ready`, `inactive-safe`, or `manual-check`). A hard
    `blocked` verdict means something fundamental is wrong, usually System
    Events permissions or a broken shortcut.
    """
    verdict = text(verifier.get("verdict"))
    if verdict == "blocked":
        return False, text(verifier.get("message")) or "export verifier blocked the desktop lane"
    if require_tos_running and not verifier.get("appRunning"):
        return False, "thinkorswim is not running, and this cycle requires a live desktop session"
    return True, ""


def desktop_verdict(
    verifier_ok: bool,
    verifier_verdict: str,
    watch_report: dict[str, Any] | None,
    sandbox: dict[str, Any] | None,
) -> str:
    """Collapse the local cycle into a desk-level verdict."""
    if not verifier_ok:
        return "blocked"
    if watch_report and watch_report.get("skipped"):
        return "scheduled-idle"
    export_bridge = (watch_report or {}).get("exportBridge") or {}
    export_status = text(export_bridge.get("status"))
    if export_status and export_status not in {"triggered", "disabled", "dry-run", "cooldown-skipped"}:
        return "review"
    if verifier_verdict not in {"ready", "ready-live-readonly"}:
        # `manual-check` and `inactive-safe` are both acceptable states for
        # continuing the local paper lane, but neither should advertise the
        # desk as fully ready for hands-off desktop interaction.
        return "review"
    if sandbox and sandbox.get("sandboxReady"):
        return "ready"
    return "review"


def build_message(report: dict[str, Any]) -> str:
    """Render a concise status line for the latest desktop automation cycle."""
    verdict = text(report.get("verdict"))
    sandbox = report.get("sandbox") or {}
    stageable = sandbox.get("stageableCount", 0)
    watchlist = sandbox.get("watchlistCount", 0)
    sandbox_ready = sandbox.get("sandboxReady")

    if verdict == "blocked":
        return text(report.get("blockReason")) or "desktop automation blocked"
    if verdict == "scheduled-idle":
        return text((report.get("downloadsWatch") or {}).get("skipReason")) or "desktop automation idle by schedule"
    if verdict == "review":
        bridge_status = text(((report.get("downloadsWatch") or {}).get("exportBridge")) or "")
        return (
            f"desktop lane needs review | "
            f"export {bridge_status or 'not-run'} | "
            f"sandbox ready={sandbox_ready} | stageable={stageable} | watchlist={watchlist}"
        )
    return f"desktop lane ready | sandbox ready={sandbox_ready} | stageable={stageable} | watchlist={watchlist}"


def run_desktop_cycle(
    *,
    export_first: bool = False,
    automation: bool = False,
    require_tos_running: bool = False,
) -> dict[str, Any]:
    """Run one full guarded local desktop cycle.

    The cycle always starts with a non-destructive export verifier so the desk
    never pretends UI automation is safe when the local broker surface is not
    actually in a usable state.
    """
    ensure_dirs()

    verifier = verify_export_bridge(require_enabled=False, allow_recovery=False)
    verifier_ok, block_reason = verifier_allows_local_cycle(
        verifier,
        require_tos_running=require_tos_running,
    )

    report: dict[str, Any] = {
        "generatedAt": local_now().isoformat(),
        "exportFirst": export_first,
        "automation": automation,
        "requireTosRunning": require_tos_running,
        "verifier": {
            "verdict": verifier.get("verdict"),
            "message": verifier.get("message"),
            "appRunning": verifier.get("appRunning"),
            "systemEventsOk": verifier.get("systemEventsOk"),
            "currentPanel": (verifier.get("sessionProbe") or {}).get("currentPanel"),
            "currentPanelSafety": (verifier.get("sessionProbe") or {}).get("currentPanelSafety"),
        },
        "verifierOk": verifier_ok,
        "blockReason": block_reason,
        "downloadsWatch": None,
        "sandbox": None,
        "accountStatement": None,
        "verdict": "blocked" if not verifier_ok else "review",
        "message": "",
    }

    if verifier_ok:
        watch_report = run_watch(export_first=export_first, automation=automation)
        sandbox = build_tos_sandbox_session()
        save_tos_sandbox_session(sandbox)
        report["downloadsWatch"] = {
            "skipped": watch_report.get("skipped"),
            "skipReason": watch_report.get("skipReason"),
            "exportBridge": (watch_report.get("exportBridge") or {}).get("status"),
            "downloadsManager": watch_report.get("downloadsManager"),
            "fillIngest": watch_report.get("fillIngest"),
        }
        report["sandbox"] = {
            "sandboxReady": sandbox.get("sandboxReady"),
            "stageableCount": sandbox.get("stageableCount", 0),
            "watchlistCount": sandbox.get("watchlistCount", 0),
            "blockedCount": sandbox.get("blockedCount", 0),
            "environment": sandbox.get("environment"),
            "authorityLevel": sandbox.get("authorityLevel"),
        }
        statement = scrape_account_statement()
        report["accountStatement"] = {
            "ok": statement.get("ok"),
            "message": statement.get("message"),
            "accountMode": statement.get("accountMode"),
            "accountSuffixCandidates": statement.get("accountSuffixCandidates") or [],
            "positionCount": len(statement.get("positions") or []),
            "netLiquidatingValue": statement.get("netLiquidatingValue"),
            "totalCash": statement.get("totalCash"),
        }
        report["verdict"] = desktop_verdict(
            verifier_ok,
            text(verifier.get("verdict")),
            watch_report,
            sandbox,
        )

    report["message"] = build_message(report)
    save_desktop_report(report)
    return report


def desktop_report_text(report: dict[str, Any]) -> str:
    """Render the latest desktop automation cycle into a readable report."""
    lines = [
        "Inferno Desktop Automation",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Verdict: {report.get('verdict')}",
        f"Message: {report.get('message')}",
        f"Export first: {report.get('exportFirst')}",
        f"Automation window mode: {report.get('automation')}",
        f"Require thinkorswim running: {report.get('requireTosRunning')}",
        "",
        "Verifier:",
    ]
    verifier = report.get("verifier") or {}
    lines.extend(
        [
            f"- verdict: {verifier.get('verdict')}",
            f"- message: {verifier.get('message')}",
            f"- app running: {verifier.get('appRunning')}",
            f"- system events ok: {verifier.get('systemEventsOk')}",
            f"- panel: {verifier.get('currentPanel')} | safety {verifier.get('currentPanelSafety')}",
        ]
    )
    if report.get("blockReason"):
        lines.extend(["", f"Block reason: {report.get('blockReason')}"])

    watch = report.get("downloadsWatch") or {}
    if watch:
        manager = watch.get("downloadsManager") or {}
        fill = watch.get("fillIngest") or {}
        lines.extend(
            [
                "",
                "Downloads watch:",
                f"- skipped: {watch.get('skipped')}",
                f"- skip reason: {watch.get('skipReason') or '-'}",
                f"- export bridge: {watch.get('exportBridge') or '-'}",
                f"- files imported: {manager.get('importedFiles', 0)}",
                f"- rows imported: {manager.get('importedRows', 0)}",
                f"- files quarantined: {manager.get('quarantinedFiles', 0)}",
                f"- fill rows processed: {fill.get('processedRows', 0)}",
                f"- fills imported: {fill.get('importedRows', 0)}",
                f"- fills closed: {fill.get('closedRows', 0)}",
                f"- fills unmatched: {fill.get('unmatchedRows', 0)}",
            ]
        )

    sandbox = report.get("sandbox") or {}
    if sandbox:
        lines.extend(
            [
                "",
                "paperMoney sandbox:",
                f"- ready: {sandbox.get('sandboxReady')}",
                f"- authority: {sandbox.get('authorityLevel')}",
                f"- stageable: {sandbox.get('stageableCount', 0)}",
                f"- watchlist: {sandbox.get('watchlistCount', 0)}",
                f"- blocked: {sandbox.get('blockedCount', 0)}",
            ]
        )

    statement = report.get("accountStatement") or {}
    if statement:
        lines.extend(
            [
                "",
                "Account statement scrape:",
                f"- ok: {statement.get('ok')}",
                f"- message: {statement.get('message')}",
                f"- account mode: {statement.get('accountMode')}",
                f"- suffixes: {', '.join(statement.get('accountSuffixCandidates') or []) or '-'}",
                f"- positions: {statement.get('positionCount', 0)}",
                f"- net liq: {statement.get('netLiquidatingValue') or '-'}",
                f"- total cash: {statement.get('totalCash') or '-'}",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def save_desktop_report(report: dict[str, Any]) -> None:
    """Persist the latest desktop automation JSON and text reports."""
    ensure_dirs()
    DESKTOP_AUTOMATION_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    DESKTOP_AUTOMATION_TEXT_FILE.write_text(desktop_report_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the desktop automation cycle."""
    parser = argparse.ArgumentParser(description="Run the guarded Inferno desktop automation cycle.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--export-first", action="store_true", help="Trigger the export/downloads lane during the cycle")
    parser.add_argument("--automation", action="store_true", help="Honor the downloads watcher time-window gate")
    parser.add_argument(
        "--require-tos-running",
        action="store_true",
        help="Block the cycle unless thinkorswim is already running",
    )
    return parser.parse_args()


def main() -> int:
    """Run the local desktop automation cycle or print the latest report."""
    args = parse_args()
    if args.command == "status" and DESKTOP_AUTOMATION_TEXT_FILE.exists():
        print(DESKTOP_AUTOMATION_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = run_desktop_cycle(
        export_first=args.export_first,
        automation=args.automation,
        require_tos_running=args.require_tos_running,
    )
    print(desktop_report_text(report))
    return 0 if report.get("verdict") in {"ready", "review", "scheduled-idle"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
