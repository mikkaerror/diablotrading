from __future__ import annotations

"""Guarded thinkorswim UI routing for export-only automation.

This module is the desk's bridge between a healthy thinkorswim session and the
future export-only automation lane. It does not place orders. It only performs
the minimum safe UI travel we currently trust:

1. Attach to the already-running thinkorswim process.
2. Route to the safe `Monitor` workspace.
3. Route to the `Account Statement` subpanel.

Every step is verified after the click so the desk can fail closed when the
window disappears, the session is stranded, or the UI lands somewhere unsafe.
This module never launches a new thinkorswim instance.
"""

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from inferno_config import (
    TOS_ACCOUNT_STATEMENT_TAB_POINT,
    TOS_MONITOR_TAB_CANDIDATES,
    TOS_MONITOR_TAB_POINT,
    TOS_UI_ROUTE_RECOVERY_DELAY_SECONDS,
    TOS_UI_ROUTE_STEP_DELAY_SECONDS,
    local_now,
)
from inferno_tos_session_probe import probe_tos_session
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


UI_ROUTE_FILE = DATA_DIR / "inferno_tos_ui_route.json"
UI_ROUTE_TEXT_FILE = REPORTS_DIR / "tos_ui_route_latest.txt"
UI_ROUTE_SCREENSHOT = REPORTS_DIR / "tos_ui_route_latest.png"
CLICK_HELPER = Path(__file__).resolve().parent / "scripts" / "mac_click.py"


def text(value: Any) -> str:
    """Normalize arbitrary values into trimmed text."""
    return str(value or "").strip()


def run_command(*args: str) -> subprocess.CompletedProcess[str]:
    """Run a command without raising and capture the textual output."""
    return subprocess.run(args, text=True, capture_output=True, check=False)


def run_osascript(script: str) -> subprocess.CompletedProcess[str]:
    """Run inline AppleScript for safe frontmost/recovery operations."""
    return run_command("osascript", "-e", script)


def dismiss_transient_overlay() -> dict[str, Any]:
    """Dismiss transient popovers without changing workspaces.

    thinkorswim occasionally leaves lightweight overlays open above the main
    workspace tabs, especially around the account selector. A single Escape is
    a safe, reversible way to close those overlays so the Monitor tab remains
    reachable without opening a new TOS instance.
    """
    script = """
tell application "System Events"
  key code 53
end tell
"""
    result = run_osascript(script)
    return {
        "ok": result.returncode == 0,
        "stderr": text(result.stderr),
        "returncode": result.returncode,
    }


def bring_tos_frontmost() -> dict[str, Any]:
    """Ask macOS to put the live thinkorswim process in front."""
    script = """
tell application "System Events"
  if exists process "java-arm" then
    tell process "java-arm"
      set frontmost to true
    end tell
    return "java-arm"
  end if
end tell
return ""
"""
    result = run_osascript(script)
    return {
        "ok": result.returncode == 0,
        "frontmostProcess": text(result.stdout),
        "stderr": text(result.stderr),
        "returncode": result.returncode,
    }


def recover_tos_window() -> dict[str, Any]:
    """Fail closed instead of launching or reopening thinkorswim.

    Older versions used `open -a` here as a convenience recovery path. That was
    too easy to trigger from another automation lane, so recovery is now
    attach-only: the operator can reveal the existing window manually, and the
    desk will sync once the probe sees it.
    """
    time.sleep(TOS_UI_ROUTE_RECOVERY_DELAY_SECONDS)
    session = probe_tos_session()
    ok = bool(session.get("mainWindowPresent"))
    return {
        "ok": ok,
        "stdout": "",
        "stderr": "" if ok else "TOS reopen disabled by attach-only policy",
        "returncode": 0 if ok else 1,
        "sessionSummary": session.get("summary"),
    }


def capture_route_screenshot() -> str:
    """Capture a diagnostic screenshot for the latest routing attempt."""
    run_command("screencapture", "-x", str(UI_ROUTE_SCREENSHOT))
    return str(UI_ROUTE_SCREENSHOT)


def click_point(point: tuple[int, int]) -> dict[str, Any]:
    """Click a known-safe coordinate using the local CoreGraphics helper."""
    x, y = point
    result = run_command("python3", str(CLICK_HELPER), str(x), str(y))
    return {
        "ok": result.returncode == 0,
        "point": [x, y],
        "stdout": text(result.stdout),
        "stderr": text(result.stderr),
        "returncode": result.returncode,
    }


def preferred_center(items: list[dict[str, Any]], label: str) -> tuple[int, int] | None:
    """Return the accessibility-derived click center for a named control.

    Using the live accessibility frame lets us survive layout drift and window
    scaling changes. We keep the fixed coordinate fallback so the route still
    works when the accessibility tree is sparse.
    """
    target = label.strip().lower()
    for item in items:
        if text(item.get("label")).strip().lower() != target:
            continue
        center = item.get("center")
        if isinstance(center, list) and len(center) == 2:
            try:
                return int(center[0]), int(center[1])
            except (TypeError, ValueError):
                return None
    return None


def unique_points(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Return points in order without duplicates."""
    deduped: list[tuple[int, int]] = []
    for point in points:
        if point not in deduped:
            deduped.append(point)
    return deduped


def probe_stable_session(*, recover_when_missing: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Probe the live session with one gentle retry path.

    thinkorswim occasionally blinks the accessibility tree during workspace
    switches. We treat that as a transient first, re-probe once, and only then
    escalate to a gentle app recovery.
    """
    session = probe_tos_session()
    debug_steps: list[dict[str, Any]] = []
    if session.get("mainWindowPresent") and session.get("currentPanel"):
        return session, debug_steps

    time.sleep(TOS_UI_ROUTE_STEP_DELAY_SECONDS)
    session = probe_tos_session()
    debug_steps.append(
        {
            "name": "stabilize-probe",
            "summary": session.get("summary"),
            "currentPanel": session.get("currentPanel"),
            "currentPanelSafety": session.get("currentPanelSafety"),
            "monitorSubpanel": session.get("monitorSubpanel"),
            "mainWindowPresent": session.get("mainWindowPresent"),
        }
    )
    if session.get("mainWindowPresent") and session.get("currentPanel"):
        return session, debug_steps

    if recover_when_missing and not session.get("mainWindowPresent"):
        recovery = recover_tos_window()
        debug_steps.append({"name": "stabilize-recover-window", **recovery})
        session = probe_tos_session()
        debug_steps.append(
            {
                "name": "stabilize-post-recover",
                "summary": session.get("summary"),
                "currentPanel": session.get("currentPanel"),
                "currentPanelSafety": session.get("currentPanelSafety"),
                "monitorSubpanel": session.get("monitorSubpanel"),
                "mainWindowPresent": session.get("mainWindowPresent"),
            }
        )
    return session, debug_steps


def monitor_account_statement_visible(session: dict[str, Any]) -> bool:
    """Return whether Account Statement content is visibly active.

    The TOS accessibility tree is a little quirky here: sometimes the selected
    Monitor subtab reports as `Statement for account ...` rather than the plain
    `Account Statement` tab label. We treat either signal, plus the visible
    `Dump Account` control, as strong proof that the statement pane is active.
    """
    if text(session.get("monitorSubpanel")).strip().lower() == "account statement":
        return True

    selected_subtabs = [
        text(label).strip().lower()
        for label in (session.get("selectedMonitorSubtabs") or [])
        if text(label)
    ]
    if any(label == "account statement" or label.startswith("statement for account") for label in selected_subtabs):
        return True

    buttons = [
        text(item.get("label")).strip().lower()
        for item in (session.get("labeledButtons") or [])
        if isinstance(item, dict)
    ]
    if "dump account" in buttons:
        return True

    static_labels = [
        text(item.get("label")).strip().lower()
        for item in (session.get("staticTexts") or [])
        if isinstance(item, dict)
    ]
    return any(label.startswith("statement for account") for label in static_labels)


def route_to_account_statement(*, dry_run: bool = False, allow_recovery: bool = False) -> dict[str, Any]:
    """Route the live thinkorswim session into `Monitor > Account Statement`.

    The route is safe by construction:
    - it verifies the current panel before and after each click
    - it only uses the pre-approved safe panels
    - it bails out when the main window disappears unless recovery is explicitly enabled
    """

    ensure_dirs()
    initial = probe_tos_session()
    report: dict[str, Any] = {
        "generatedAt": local_now().isoformat(),
        "dryRun": dry_run,
        "monitorPoint": list(TOS_MONITOR_TAB_POINT),
        "monitorCandidates": [list(point) for point in TOS_MONITOR_TAB_CANDIDATES],
        "accountStatementPoint": list(TOS_ACCOUNT_STATEMENT_TAB_POINT),
        "allowRecovery": allow_recovery,
        "initialSession": {
            "summary": initial.get("summary"),
            "currentPanel": initial.get("currentPanel"),
            "currentPanelSafety": initial.get("currentPanelSafety"),
            "monitorSubpanel": initial.get("monitorSubpanel"),
            "mainWindowPresent": initial.get("mainWindowPresent"),
        },
        "steps": [],
        "ok": False,
        "status": "blocked",
        "message": None,
        "screenshot": None,
    }

    if not initial.get("mainWindowPresent"):
        # A single observation-only re-probe absorbs brief accessibility-tree
        # blinks without reopening thinkorswim or altering broker state.
        time.sleep(TOS_UI_ROUTE_STEP_DELAY_SECONDS)
        reprobe = probe_tos_session()
        report["steps"].append(
            {
                "name": "initial-reprobe",
                "summary": reprobe.get("summary"),
                "currentPanel": reprobe.get("currentPanel"),
                "currentPanelSafety": reprobe.get("currentPanelSafety"),
                "monitorSubpanel": reprobe.get("monitorSubpanel"),
                "mainWindowPresent": reprobe.get("mainWindowPresent"),
            }
        )
        if reprobe.get("mainWindowPresent"):
            initial = reprobe

    if not initial.get("mainWindowPresent") and allow_recovery:
        recovery = recover_tos_window()
        report["steps"].append({"name": "recover-window", **recovery})
        if not recovery.get("ok"):
            report["message"] = "thinkorswim main window is not visible; attach-only recovery will not reopen it"
            report["status"] = "no-window"
            report["screenshot"] = capture_route_screenshot()
            save_ui_route_report(report)
            return report
        initial = probe_tos_session()
        report["initialSession"] = {
            "summary": initial.get("summary"),
            "currentPanel": initial.get("currentPanel"),
            "currentPanelSafety": initial.get("currentPanelSafety"),
            "monitorSubpanel": initial.get("monitorSubpanel"),
            "mainWindowPresent": initial.get("mainWindowPresent"),
        }
    elif not initial.get("mainWindowPresent"):
        report["message"] = "thinkorswim main window is not visible; route stayed attach-only and fail-closed"
        report["status"] = "no-window"
        report["screenshot"] = capture_route_screenshot()
        save_ui_route_report(report)
        return report

    frontmost = bring_tos_frontmost()
    report["steps"].append({"name": "frontmost", **frontmost})

    if dry_run:
        report["ok"] = bool(initial.get("mainWindowPresent"))
        report["status"] = "dry-run"
        report["message"] = "route dry-run only; no clicks executed"
        report["screenshot"] = capture_route_screenshot()
        save_ui_route_report(report)
        return report

    if initial.get("currentPanel") != "Monitor" and initial.get("currentPanelSafety") == "safe":
        dismiss = dismiss_transient_overlay()
        report["steps"].append({"name": "dismiss-transient-overlay", **dismiss})
        time.sleep(TOS_UI_ROUTE_STEP_DELAY_SECONDS)
        post_dismiss_session, stabilization_steps = probe_stable_session(recover_when_missing=allow_recovery)
        report["steps"].append(
            {
                "name": "verify-overlay-dismissal",
                "summary": post_dismiss_session.get("summary"),
                "currentPanel": post_dismiss_session.get("currentPanel"),
                "currentPanelSafety": post_dismiss_session.get("currentPanelSafety"),
                "monitorSubpanel": post_dismiss_session.get("monitorSubpanel"),
                "mainWindowPresent": post_dismiss_session.get("mainWindowPresent"),
            }
        )
        report["steps"].extend(stabilization_steps)
        if post_dismiss_session.get("mainWindowPresent"):
            initial = post_dismiss_session

    if initial.get("currentPanel") != "Monitor":
        candidate_points = unique_points(
            [
                point
                for point in [
                    preferred_center(initial.get("currentTabGroups") or [], "Monitor"),
                    *TOS_MONITOR_TAB_CANDIDATES,
                    TOS_MONITOR_TAB_POINT,
                ]
                if point
            ]
        )
        monitor_session: dict[str, Any] | None = None
        for attempt, monitor_point in enumerate(candidate_points, start=1):
            click_monitor = click_point(monitor_point)
            report["steps"].append({"name": f"click-monitor-{attempt}", **click_monitor})
            time.sleep(TOS_UI_ROUTE_STEP_DELAY_SECONDS)
            after_monitor, stabilization_steps = probe_stable_session(recover_when_missing=allow_recovery)
            report["steps"].append(
                {
                    "name": f"verify-monitor-{attempt}",
                    "summary": after_monitor.get("summary"),
                    "currentPanel": after_monitor.get("currentPanel"),
                    "currentPanelSafety": after_monitor.get("currentPanelSafety"),
                    "monitorSubpanel": after_monitor.get("monitorSubpanel"),
                    "mainWindowPresent": after_monitor.get("mainWindowPresent"),
                }
            )
            report["steps"].extend(stabilization_steps)
            if after_monitor.get("currentPanel") == "Monitor":
                monitor_session = after_monitor
                report["monitorPoint"] = list(monitor_point)
                break
        if not monitor_session:
            report["message"] = "failed to route thinkorswim into the Monitor workspace"
            report["status"] = "monitor-route-failed"
            report["screenshot"] = capture_route_screenshot()
            save_ui_route_report(report)
            return report
        initial = monitor_session

    if initial.get("monitorSubpanel") != "Account Statement":
        account_statement_point = (
            preferred_center(initial.get("monitorSubtabs") or [], "Account Statement")
            or TOS_ACCOUNT_STATEMENT_TAB_POINT
        )
        click_statement = click_point(account_statement_point)
        report["steps"].append({"name": "click-account-statement", **click_statement})
        time.sleep(TOS_UI_ROUTE_STEP_DELAY_SECONDS)

    final_session, stabilization_steps = probe_stable_session(recover_when_missing=allow_recovery)
    report["steps"].extend(stabilization_steps)
    report["finalSession"] = {
        "summary": final_session.get("summary"),
        "currentPanel": final_session.get("currentPanel"),
        "currentPanelSafety": final_session.get("currentPanelSafety"),
        "monitorSubpanel": final_session.get("monitorSubpanel"),
        "accountStatementVisible": monitor_account_statement_visible(final_session),
        "mainWindowPresent": final_session.get("mainWindowPresent"),
    }
    report["screenshot"] = capture_route_screenshot()

    if final_session.get("currentPanel") == "Monitor":
        report["ok"] = True
        report["status"] = "monitor-routed"
        if monitor_account_statement_visible(final_session):
            report["status"] = "account-statement-routed"
            report["message"] = "routed thinkorswim into Monitor > Account Statement"
        else:
            report["message"] = (
                "routed thinkorswim into Monitor, but Account Statement still needs visual confirmation"
            )
    else:
        report["status"] = "route-lost"
        report["message"] = "thinkorswim left the safe Monitor workspace during routing"

    save_ui_route_report(report)
    return report


def ui_route_report_text(report: dict[str, Any]) -> str:
    """Render the latest UI route report into operator-friendly text."""
    lines = [
        "Inferno thinkorswim UI Route",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Dry run: {report.get('dryRun')}",
        f"Allow recovery: {report.get('allowRecovery')}",
        f"Status: {report.get('status')}",
        f"Message: {report.get('message')}",
        f"Monitor point: {report.get('monitorPoint')}",
        f"Account Statement point: {report.get('accountStatementPoint')}",
    ]
    initial = report.get("initialSession") or {}
    if initial:
        lines.append(f"Initial session: {initial.get('summary')}")
    final_session = report.get("finalSession") or {}
    if final_session:
        lines.append(f"Final session: {final_session.get('summary')}")
    if report.get("screenshot"):
        lines.append(f"Screenshot: {report.get('screenshot')}")
    if report.get("steps"):
        lines.append("")
        lines.append("Steps:")
        for step in report.get("steps") or []:
            lines.append(f"- {step.get('name')}: {json.dumps(step, default=str)}")
    return "\n".join(lines).rstrip() + "\n"


def save_ui_route_report(report: dict[str, Any]) -> None:
    """Persist the latest JSON/text report for the TOS UI route helper."""
    ensure_dirs()
    UI_ROUTE_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    UI_ROUTE_TEXT_FILE.write_text(ui_route_report_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse CLI args for the guarded TOS route helper."""
    parser = argparse.ArgumentParser(description="Route thinkorswim into Monitor > Account Statement.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--dry-run", action="store_true", help="Verify recover/frontmost state without clicking")
    parser.add_argument(
        "--allow-recovery",
        action="store_true",
        help="Allow an explicit operator run to retry attach-only recovery; never reopens thinkorswim",
    )
    return parser.parse_args()


def main() -> int:
    """Run or show the guarded TOS UI route helper."""
    args = parse_args()
    if args.command == "status" and UI_ROUTE_TEXT_FILE.exists():
        print(UI_ROUTE_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = route_to_account_statement(dry_run=args.dry_run, allow_recovery=args.allow_recovery)
    print(ui_route_report_text(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
