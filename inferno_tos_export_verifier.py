from __future__ import annotations

"""Preflight verifier for the experimental thinkorswim export bridge.

This module does not place orders and does not fire the export shortcut. Its
job is to double-check the fragile parts of UI automation before the Downloads
watcher tries to use them.
"""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from inferno_config import (
    DESKTOP_AUTOMATION_LABEL,
    DOWNLOADS_WATCH_LABEL,
    LOCAL_ENV_FILE,
    TOS_APP_PATH,
    TOS_ALLOWED_ACCOUNT_SUFFIXES,
    TOS_ALLOW_LIVE_READONLY,
    TOS_EXPORT_AUTOMATION_ENABLED,
    TOS_EXPORT_POST_DELAY_SECONDS,
    TOS_EXPORT_PRE_DELAY_SECONDS,
    TOS_EXPORT_SHORTCUT,
    TOS_MAIN_WINDOW_TOKEN,
    TOS_PROCESS_CANDIDATES,
    local_now,
)
from inferno_tos_export_bridge import build_applescript, parse_shortcut, text
from inferno_tos_session_probe import probe_tos_session
from inferno_tos_ui_route import bring_tos_frontmost, recover_tos_window, route_to_account_statement
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


EXPORT_VERIFIER_FILE = DATA_DIR / "inferno_tos_export_verifier.json"
EXPORT_VERIFIER_TEXT_FILE = REPORTS_DIR / "tos_export_verifier_latest.txt"


def run_command(*args: str) -> subprocess.CompletedProcess[str]:
    """Run a command and capture text output without raising."""
    return subprocess.run(args, text=True, capture_output=True, check=False)


def launch_agent_loaded(label: str) -> bool:
    """Check whether the given LaunchAgent is currently loaded."""
    domain = f"gui/{os.getuid()}/{label}"
    return run_command("launchctl", "print", domain).returncode == 0


def app_running(app_name: str) -> bool:
    """Return whether thinkorswim appears to be running for the current user."""
    result = run_command("pgrep", "-if", app_name)
    return result.returncode == 0 and bool(text(result.stdout))


def frontmost_app_name() -> tuple[bool, str]:
    """Return the current frontmost app using System Events.

    This also acts as a light-weight accessibility permission probe because
    macOS will reject this call when System Events automation is not allowed.
    """
    script = """
tell application "System Events"
  try
    return name of first application process whose frontmost is true
  on error
    return ""
  end try
end tell
"""
    result = run_command("osascript", "-e", script)
    if result.returncode != 0:
        return False, text(result.stderr) or text(result.stdout) or "frontmost app lookup failed"
    return True, text(result.stdout)


def verify_export_bridge(require_enabled: bool = False, *, allow_recovery: bool = False) -> dict[str, Any]:
    """Run a guarded preflight against the export automation path.

    By default this verifier is observation-only. Background services should
    not change broker UI state just because a window is hidden, minimized, or
    sitting on another macOS Space. Recovery actions are therefore opt-in and
    reserved for explicit operator runs.
    """
    ensure_dirs()
    report: dict[str, Any] = {
        "generatedAt": local_now().isoformat(),
        "enabled": TOS_EXPORT_AUTOMATION_ENABLED,
        "requireEnabled": require_enabled,
        "localConfigFile": str(LOCAL_ENV_FILE),
        "localConfigPresent": LOCAL_ENV_FILE.exists(),
        "appPath": str(TOS_APP_PATH),
        "appPathExists": TOS_APP_PATH.exists(),
        "appRunning": False,
        "watchAgentLoaded": launch_agent_loaded(DOWNLOADS_WATCH_LABEL),
        "desktopAutomationLoaded": launch_agent_loaded(DESKTOP_AUTOMATION_LABEL),
        "shortcut": TOS_EXPORT_SHORTCUT,
        "processCandidates": list(TOS_PROCESS_CANDIDATES),
        "mainWindowToken": TOS_MAIN_WINDOW_TOKEN,
        "shortcutValid": False,
        "allowedLiveReadonly": TOS_ALLOW_LIVE_READONLY,
        "allowedAccountSuffixes": list(TOS_ALLOWED_ACCOUNT_SUFFIXES),
        "preDelaySeconds": TOS_EXPORT_PRE_DELAY_SECONDS,
        "postDelaySeconds": TOS_EXPORT_POST_DELAY_SECONDS,
        "scriptBuildOk": False,
        "scriptPreview": None,
        "systemEventsOk": False,
        "frontmostApp": None,
        "sessionProbe": None,
        "sessionRecovery": [],
        "uiRoute": None,
        "verdict": "blocked",
        "message": None,
        "checks": [],
        "allowRecovery": allow_recovery,
    }

    app_name = TOS_APP_PATH.stem
    report["appRunning"] = app_running(app_name)
    report["checks"].append({"name": "app-path", "ok": report["appPathExists"], "detail": str(TOS_APP_PATH)})
    local_agent_ok = bool(report["watchAgentLoaded"] or report["desktopAutomationLoaded"])
    local_agent_detail = ", ".join(
        label
        for label, loaded in (
            (DOWNLOADS_WATCH_LABEL, report["watchAgentLoaded"]),
            (DESKTOP_AUTOMATION_LABEL, report["desktopAutomationLoaded"]),
        )
        if loaded
    ) or "no local automation agent loaded"
    report["checks"].append({"name": "watch-agent", "ok": local_agent_ok, "detail": local_agent_detail})

    if require_enabled and not TOS_EXPORT_AUTOMATION_ENABLED:
        report["verdict"] = "inactive-safe"
        report["message"] = "export automation intentionally disabled"
        save_export_verifier_report(report)
        return report

    try:
        parse_shortcut(TOS_EXPORT_SHORTCUT)
        report["shortcutValid"] = True
        report["checks"].append({"name": "shortcut-parse", "ok": True, "detail": TOS_EXPORT_SHORTCUT})
    except Exception as exc:  # noqa: BLE001
        report["checks"].append({"name": "shortcut-parse", "ok": False, "detail": str(exc)})
        report["message"] = str(exc)
        save_export_verifier_report(report)
        return report

    if not report["appPathExists"]:
        report["message"] = f"thinkorswim app not found at {TOS_APP_PATH}"
        save_export_verifier_report(report)
        return report

    try:
        script = build_applescript(TOS_APP_PATH, TOS_EXPORT_SHORTCUT, TOS_EXPORT_PRE_DELAY_SECONDS, TOS_EXPORT_POST_DELAY_SECONDS)
        report["scriptBuildOk"] = True
        report["scriptPreview"] = script
        report["checks"].append({"name": "script-build", "ok": True, "detail": "AppleScript compiled locally"})
    except Exception as exc:  # noqa: BLE001
        report["checks"].append({"name": "script-build", "ok": False, "detail": str(exc)})
        report["message"] = f"script build failed: {exc}"
        save_export_verifier_report(report)
        return report

    system_events_ok, system_events_detail = frontmost_app_name()
    report["systemEventsOk"] = system_events_ok
    if system_events_ok:
        report["frontmostApp"] = system_events_detail
    report["checks"].append({"name": "system-events", "ok": system_events_ok, "detail": system_events_detail})

    if not system_events_ok:
        report["verdict"] = "blocked"
        report["message"] = "System Events automation is not available"
        save_export_verifier_report(report)
        return report

    session_probe = probe_tos_session()
    if report["appRunning"] and not session_probe.get("mainWindowPresent"):
        # Observation-only reprobe absorbs brief accessibility blinks without
        # fronting or reopening the broker window in the background.
        time.sleep(TOS_EXPORT_POST_DELAY_SECONDS)
        reprobe = probe_tos_session()
        report["sessionRecovery"].append(
            {
                "step": "stabilize-reprobe",
                "ok": bool(reprobe.get("mainWindowPresent")),
                "detail": reprobe.get("summary") or reprobe.get("message") or "session reprobed",
            }
        )
        if reprobe.get("ok"):
            session_probe = reprobe

    if allow_recovery and report["appRunning"] and not session_probe.get("mainWindowPresent"):
        frontmost = bring_tos_frontmost()
        report["sessionRecovery"].append(
            {
                "step": "bring-frontmost",
                "ok": bool(frontmost.get("ok")),
                "detail": frontmost.get("frontmostProcess") or frontmost.get("stderr") or "no process promoted",
            }
        )
        reprobe = probe_tos_session()
        if reprobe.get("ok"):
            session_probe = reprobe

    if allow_recovery and report["appRunning"] and not session_probe.get("mainWindowPresent"):
        recovered = recover_tos_window()
        report["sessionRecovery"].append(
            {
                "step": "recover-window",
                "ok": bool(recovered.get("ok")),
                "detail": recovered.get("sessionSummary") or recovered.get("stderr") or "window recovery attempted",
            }
        )
        reprobe = probe_tos_session()
        if reprobe.get("ok"):
            session_probe = reprobe

    report["sessionProbe"] = {
        "ok": session_probe.get("ok"),
        "message": session_probe.get("message"),
        "summary": session_probe.get("summary"),
        "matchedProcessName": session_probe.get("matchedProcessName"),
        "mainWindowPresent": session_probe.get("mainWindowPresent"),
        "currentPanel": session_probe.get("currentPanel"),
        "currentPanelSafety": session_probe.get("currentPanelSafety"),
        "accountMode": session_probe.get("accountMode"),
        "accountEvidence": session_probe.get("accountEvidence"),
        "windowNames": session_probe.get("windowNames"),
        "currentTabGroups": session_probe.get("currentTabGroups"),
    }
    report["checks"].append(
        {
            "name": "session-probe",
            "ok": bool(session_probe.get("ok")),
            "detail": session_probe.get("summary") or session_probe.get("message"),
        }
    )
    for recovery in report.get("sessionRecovery") or []:
        report["checks"].append(
            {
                "name": f"session-recovery:{recovery.get('step')}",
                "ok": bool(recovery.get("ok")),
                "detail": recovery.get("detail"),
            }
        )
    report["checks"].append(
        {
            "name": "main-window",
            "ok": bool(session_probe.get("mainWindowPresent")),
            "detail": ", ".join(session_probe.get("windowNames") or []) or "no main thinkorswim window detected",
        }
    )
    panel_safety = str(session_probe.get("currentPanelSafety") or "unknown")
    panel_name = str(session_probe.get("currentPanel") or "unknown")
    account_mode = str(session_probe.get("accountMode") or "unknown")
    suffix_candidates = [str(value) for value in (session_probe.get("accountSuffixCandidates") or []) if str(value)]
    allowed_suffix_match = any(
        candidate.endswith(allowed_suffix) or allowed_suffix.endswith(candidate)
        for candidate in suffix_candidates
        for allowed_suffix in TOS_ALLOWED_ACCOUNT_SUFFIXES
    )
    report["checks"].append(
        {
            "name": "panel-safety",
            "ok": panel_safety != "unsafe",
            "detail": f"{panel_name} | safety {panel_safety}",
        }
    )
    report["checks"].append(
        {
            "name": "account-mode",
            "ok": account_mode == "paper" or (TOS_ALLOW_LIVE_READONLY and allowed_suffix_match),
            "detail": f"{account_mode} | suffixes {', '.join(suffix_candidates) or '-'}",
        }
    )
    if panel_name == "Monitor":
        monitor_subpanel = str(session_probe.get("monitorSubpanel") or "unknown")
        report["checks"].append(
            {
                "name": "monitor-subpanel",
                "ok": monitor_subpanel != "unknown",
                "detail": monitor_subpanel,
            }
        )

    if report["appRunning"] and not session_probe.get("mainWindowPresent"):
        report["verdict"] = "manual-check"
        report["message"] = (
            session_probe.get("summary")
            or "thinkorswim is running, but the main trading window is not visible yet"
        )
        if not allow_recovery:
            report["message"] += " | background verifier stayed observation-only"
        save_export_verifier_report(report)
        return report

    if account_mode == "live" and TOS_ALLOW_LIVE_READONLY and allowed_suffix_match:
        report["verdict"] = "ready-live-readonly"
        report["message"] = f"allowed live account suffix matched ({', '.join(TOS_ALLOWED_ACCOUNT_SUFFIXES)}) | export/monitor only"
        route_report = route_to_account_statement(dry_run=True, allow_recovery=False)
        report["uiRoute"] = {
            "ok": route_report.get("ok"),
            "status": route_report.get("status"),
            "message": route_report.get("message"),
        }
        report["checks"].append(
            {
                "name": "ui-route-dry-run",
                "ok": bool(route_report.get("ok")),
                "detail": route_report.get("message"),
            }
        )
        save_export_verifier_report(report)
        return report

    if account_mode != "paper":
        report["verdict"] = "manual-check"
        if TOS_ALLOW_LIVE_READONLY:
            report["message"] = (
                "account mode is not provably paperMoney or the allowed live account suffix is not visible yet"
            )
        else:
            report["message"] = "account mode is not provably paperMoney yet"
        save_export_verifier_report(report)
        return report

    if panel_safety == "unsafe":
        report["verdict"] = "manual-check"
        report["message"] = f"thinkorswim is on an unsafe panel for automation: {panel_name}"
        save_export_verifier_report(report)
        return report

    route_report = route_to_account_statement(dry_run=True)
    report["uiRoute"] = {
        "ok": route_report.get("ok"),
        "status": route_report.get("status"),
        "message": route_report.get("message"),
    }
    report["checks"].append(
        {
            "name": "ui-route-dry-run",
            "ok": bool(route_report.get("ok")),
            "detail": route_report.get("message"),
        }
    )

    if not TOS_EXPORT_AUTOMATION_ENABLED:
        report["verdict"] = "inactive-safe"
        report["message"] = "export automation disabled, but the preflight path is healthy"
    elif report["appRunning"]:
        report["verdict"] = "ready"
        report["message"] = "export bridge preflight passed"
    else:
        report["verdict"] = "manual-check"
        report["message"] = "thinkorswim is not running yet; launch it before expecting unattended export"

    save_export_verifier_report(report)
    return report


def export_verifier_report_text(report: dict[str, Any]) -> str:
    """Render the latest export verifier report into plain text."""
    lines = [
        "Inferno thinkorswim Export Verifier",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Verdict: {report.get('verdict')}",
        f"Message: {report.get('message')}",
        f"Enabled: {report.get('enabled')}",
        f"Local config present: {report.get('localConfigPresent')}",
        f"Watch agent loaded: {report.get('watchAgentLoaded')}",
        f"App path exists: {report.get('appPathExists')}",
        f"App running: {report.get('appRunning')}",
        f"Shortcut: {report.get('shortcut')}",
        f"Shortcut valid: {report.get('shortcutValid')}",
        f"Allowed live readonly: {report.get('allowedLiveReadonly')}",
        f"Allowed account suffixes: {', '.join(report.get('allowedAccountSuffixes') or []) or '-'}",
        f"Allow recovery: {report.get('allowRecovery')}",
        f"System Events ok: {report.get('systemEventsOk')}",
        f"Main window token: {report.get('mainWindowToken')}",
    ]
    if report.get("frontmostApp"):
        lines.append(f"Frontmost app: {report.get('frontmostApp')}")
    session_probe = report.get("sessionProbe") or {}
    if session_probe:
        lines.append(f"Session probe: {session_probe.get('summary')}")
    if report.get("sessionRecovery"):
        lines.append("Session recovery:")
        for step in report.get("sessionRecovery") or []:
            marker = "PASS" if step.get("ok") else "WARN"
            lines.append(f"- [{marker}] {step.get('step')}: {step.get('detail')}")
    ui_route = report.get("uiRoute") or {}
    if ui_route:
        lines.append(f"UI route: {ui_route.get('status')} | {ui_route.get('message')}")
    lines.append("")
    lines.append("Checks:")
    for item in report.get("checks") or []:
        marker = "PASS" if item.get("ok") else "WARN"
        lines.append(f"- [{marker}] {item.get('name')}: {item.get('detail')}")
    return "\n".join(lines).rstrip() + "\n"


def save_export_verifier_report(report: dict[str, Any]) -> None:
    """Persist the export verifier JSON and text reports."""
    ensure_dirs()
    EXPORT_VERIFIER_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    EXPORT_VERIFIER_TEXT_FILE.write_text(export_verifier_report_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the export verifier."""
    parser = argparse.ArgumentParser(description="Run a non-destructive preflight for thinkorswim export automation.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--require-enabled", action="store_true", help="Fail preflight if export automation is disabled")
    parser.add_argument(
        "--allow-recovery",
        action="store_true",
        help="Allow an explicit operator run to bring thinkorswim frontmost or reopen its main window",
    )
    return parser.parse_args()


def main() -> int:
    """Run or print the export preflight verifier."""
    args = parse_args()
    if args.command == "status" and EXPORT_VERIFIER_TEXT_FILE.exists():
        print(EXPORT_VERIFIER_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = verify_export_bridge(require_enabled=args.require_enabled, allow_recovery=args.allow_recovery)
    print(export_verifier_report_text(report))
    return 0 if report.get("verdict") in {"ready", "ready-live-readonly", "inactive-safe", "manual-check"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
