from __future__ import annotations

"""Experimental thinkorswim export bridge for paper-trade CSV workflows.

There is no official paperMoney export API, so this module uses guarded macOS
UI automation to trigger an export shortcut inside thinkorswim. It is disabled
by default, export-only, and intended to work with a user-defined paper export
shortcut or macro. It never places orders.
"""

import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from inferno_config import (
    DOWNLOADS_SCAN_DIR,
    TOS_APP_PATH,
    TOS_EXPORT_AUTOMATION_ENABLED,
    TOS_EXPORT_COOLDOWN_SECONDS,
    TOS_EXPORT_POST_DELAY_SECONDS,
    TOS_EXPORT_PRE_DELAY_SECONDS,
    TOS_MAIN_WINDOW_TOKEN,
    TOS_PROCESS_CANDIDATES,
    TOS_EXPORT_SHORTCUT,
    local_now,
)
from inferno_tos_account_statement_scraper import ACCOUNT_STATEMENT_FILE, ACCOUNT_STATEMENT_TEXT_FILE, scrape_account_statement
from inferno_tos_session_probe import probe_tos_session
from inferno_tos_ui_route import route_to_account_statement
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


EXPORT_BRIDGE_FILE = DATA_DIR / "inferno_tos_export_bridge.json"
EXPORT_BRIDGE_TEXT_FILE = REPORTS_DIR / "tos_export_bridge_latest.txt"
WORKSPACE_ROOT = Path(__file__).resolve().parent
EXPORT_CLIPBOARD_DIR = DATA_DIR / "tos_exports"
EXPORT_SCAN_SUFFIXES = (".csv", ".txt", ".tsv", ".html", ".xml")
EXPORT_SCAN_FALLBACK_DIRS = (
    Path.home() / "Downloads",
    Path.home() / "Documents",
    Path.home() / "Desktop",
    Path.home() / "thinkorswim",
    Path.home() / ".thinkorswim",
)
CLIPBOARD_EXPORT_KEYWORDS = (
    "statement for account",
    "cash & sweep vehicle",
    "trade history",
    "order history",
    "profits and losses",
    "account summary",
    "net liquidating value",
)
HIDDEN_EXPORT_KEYWORDS = (
    "export",
    "statement",
    "account",
    "activity",
    "position",
    "trade",
    "watchlist",
)

MODIFIER_MAP = {
    "command": "command down",
    "cmd": "command down",
    "shift": "shift down",
    "option": "option down",
    "alt": "option down",
    "control": "control down",
    "ctrl": "control down",
}
SPECIAL_KEY_MAP = {
    "return": 36,
    "enter": 36,
    "tab": 48,
    "space": 49,
    "escape": 53,
    "esc": 53,
    "delete": 51,
}


def export_scan_roots(primary_dir: Path) -> list[Path]:
    """Return the deduplicated directory list we watch for export artifacts.

    Downloads stays first because it is the most likely explicit export target.
    The fallback roots cover hidden or app-adjacent write locations that TOS may
    use without opening a visible macOS save sheet.
    """
    ordered: list[Path] = []
    seen: set[str] = set()
    for candidate in (primary_dir, *EXPORT_SCAN_FALLBACK_DIRS):
        key = str(candidate.expanduser())
        if key in seen:
            continue
        seen.add(key)
        ordered.append(candidate.expanduser())
    return ordered


def path_within(path: Path, parent: Path) -> bool:
    """Return whether `path` resolves inside `parent`."""
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def recent_artifact_markers(source_dirs: list[Path]) -> set[tuple[str, int, int]]:
    """Capture a lightweight fingerprint set for recent export-style artifacts."""
    markers: set[tuple[str, int, int]] = set()
    for source_dir in source_dirs:
        if not source_dir.exists():
            continue
        strict_keyword_mode = path_within(source_dir, Path.home() / "thinkorswim") or path_within(
            source_dir, Path.home() / ".thinkorswim"
        )
        for path in source_dir.rglob("*"):
            if path.name.startswith(".") or not path.is_file():
                continue
            if path_within(path, WORKSPACE_ROOT):
                continue
            if path.suffix.lower() not in EXPORT_SCAN_SUFFIXES:
                continue
            if strict_keyword_mode:
                lowered_path = str(path).lower()
                if not any(keyword in lowered_path for keyword in HIDDEN_EXPORT_KEYWORDS):
                    continue
            stat = path.stat()
            markers.add((str(path), stat.st_size, stat.st_mtime_ns))
    return markers


def summarize_new_artifacts(
    before_markers: set[tuple[str, int, int]],
    after_markers: set[tuple[str, int, int]],
) -> list[dict[str, Any]]:
    """Summarize newly detected export artifacts after a trigger fires."""
    new_markers = sorted(after_markers - before_markers, key=lambda item: item[0])
    return [
        {
            "path": path,
            "name": Path(path).name,
            "sizeBytes": size,
            "source": "file",
        }
        for path, size, _mtime in new_markers
    ]


def text(value: Any) -> str:
    """Normalize arbitrary values into trimmed text."""
    return str(value or "").strip()


def read_clipboard_text() -> str:
    """Read the plain-text clipboard safely.

    We only request text because that is enough to detect whether `Dump Account`
    copied a statement payload instead of writing a file. If the pasteboard does
    not currently contain text, we fail closed to an empty string.
    """
    result = subprocess.run(["pbpaste"], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return ""
    return result.stdout.replace("\r\n", "\n").replace("\r", "\n")


def clipboard_snapshot(raw_text: str) -> dict[str, Any]:
    """Return a non-sensitive summary of the current clipboard contents."""
    normalized = raw_text.strip()
    lowered = normalized.lower()
    keyword_hits = [keyword for keyword in CLIPBOARD_EXPORT_KEYWORDS if keyword in lowered]
    return {
        "present": bool(normalized),
        "lengthChars": len(normalized),
        "sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else None,
        "keywordHits": keyword_hits,
        "looksLikeAccountStatement": bool(keyword_hits),
    }


def persist_clipboard_export(raw_text: str, generated_at: datetime) -> Path:
    """Persist a clipboard-backed account statement dump into local ignored data.

    The export stays local inside the gitignored `data/` tree so the automation
    loop can ingest it later without relying on a fragile macOS save dialog.
    """
    EXPORT_CLIPBOARD_DIR.mkdir(parents=True, exist_ok=True)
    target = EXPORT_CLIPBOARD_DIR / f"account_statement_export_{generated_at.strftime('%Y%m%d-%H%M%S')}.txt"
    target.write_text(raw_text, encoding="utf-8")
    return target


def parse_shortcut(shortcut: str) -> tuple[str, list[str]]:
    """Parse a simple shortcut string like `command+shift+e`."""
    pieces = [piece.strip().lower() for piece in shortcut.split("+") if piece.strip()]
    if not pieces:
        raise ValueError("shortcut is empty")
    key = pieces[-1]
    modifiers = [MODIFIER_MAP[piece] for piece in pieces[:-1] if piece in MODIFIER_MAP]
    unknown = [piece for piece in pieces[:-1] if piece not in MODIFIER_MAP]
    if unknown:
        raise ValueError(f"unsupported shortcut modifiers: {', '.join(unknown)}")
    return key, modifiers


def applescript_keystroke(shortcut: str) -> str:
    """Render the keystroke portion of the AppleScript bridge."""
    key, modifiers = parse_shortcut(shortcut)
    modifier_clause = f" using {{{', '.join(modifiers)}}}" if modifiers else ""
    if key in SPECIAL_KEY_MAP:
        return f"key code {SPECIAL_KEY_MAP[key]}{modifier_clause}"
    if len(key) == 1:
        return f'keystroke "{key}"{modifier_clause}'
    raise ValueError(f"unsupported shortcut key: {key}")


def build_applescript(app_path: Path, shortcut: str, pre_delay: float, post_delay: float) -> str:
    """Build the guarded AppleScript that activates thinkorswim and fires the export shortcut."""
    allowed_processes = "{" + ", ".join(f'"{candidate}"' for candidate in TOS_PROCESS_CANDIDATES) + "}"
    keystroke_line = applescript_keystroke(shortcut)
    return "\n".join(
        [
            f'tell application "{app_path}" to activate',
            f"delay {pre_delay}",
            'tell application "System Events"',
            f"  set allowedFrontApps to {allowed_processes}",
            '  set frontApp to name of first application process whose frontmost is true',
            '  if allowedFrontApps does not contain frontApp then error "frontmost app is " & frontApp',
            '  try',
            '    set frontWindowName to name of window 1 of application process frontApp',
            f'    if frontWindowName is not "" and frontWindowName does not contain "{TOS_MAIN_WINDOW_TOKEN}" then error "front window is " & frontWindowName',
            '  end try',
            f"  {keystroke_line}",
            "end tell",
            f"delay {post_delay}",
        ]
    )


def build_dump_account_applescript(
    app_path: Path,
    process_name: str,
    split_group_index: int,
    monitor_group_index: int,
    button_index: int,
    post_delay: float,
) -> str:
    """Build a direct Account Statement export click for the visible TOS window.

    This path is safer than an unlabeled shortcut because it only fires when the
    probe has already verified the current session is sitting inside
    `Monitor > Account Statement` and has surfaced the explicit `Dump Account`
    control from the accessibility tree.
    """
    return "\n".join(
        [
            f'tell application "{app_path}" to activate',
            'tell application "System Events"',
            f'  tell application process "{process_name}"',
            f"    click UI element {button_index} of UI element {monitor_group_index} of UI element {split_group_index} of window 1",
            "  end tell",
            "end tell",
            f"delay {post_delay}",
        ]
    )


def run_applescript(script: str) -> subprocess.CompletedProcess[str]:
    """Execute AppleScript and return the completed process."""
    return subprocess.run(["osascript", "-e", script], text=True, capture_output=True, check=False)


def load_prior_export_report() -> dict[str, Any]:
    """Load the previous export report when it exists."""
    if not EXPORT_BRIDGE_FILE.exists():
        return {}
    try:
        payload = json.loads(EXPORT_BRIDGE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_generated_at(value: Any) -> datetime | None:
    """Parse a saved ISO timestamp into a datetime when possible."""
    raw = text(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def cooldown_remaining_seconds(prior_report: dict[str, Any], now: datetime) -> int:
    """Return remaining export cooldown seconds from the prior trigger."""
    if text(prior_report.get("status")) != "triggered":
        return 0
    generated_at = parse_generated_at(prior_report.get("generatedAt"))
    if not generated_at:
        return 0
    elapsed = (now - generated_at).total_seconds()
    remaining = TOS_EXPORT_COOLDOWN_SECONDS - int(elapsed)
    return max(0, remaining)


def run_export_bridge(dry_run: bool = False) -> dict[str, Any]:
    """Trigger the thinkorswim export shortcut when enabled."""
    ensure_dirs()
    app_path = TOS_APP_PATH
    enabled = TOS_EXPORT_AUTOMATION_ENABLED
    now = local_now()
    scan_roots = export_scan_roots(DOWNLOADS_SCAN_DIR)
    prior_report = load_prior_export_report()
    report = {
        "generatedAt": now.isoformat(),
        "enabled": enabled,
        "dryRun": dry_run,
        "appPath": str(app_path),
        "shortcut": TOS_EXPORT_SHORTCUT,
        "processCandidates": list(TOS_PROCESS_CANDIDATES),
        "preDelaySeconds": TOS_EXPORT_PRE_DELAY_SECONDS,
        "postDelaySeconds": TOS_EXPORT_POST_DELAY_SECONDS,
        "cooldownSeconds": TOS_EXPORT_COOLDOWN_SECONDS,
        "downloadsScanDir": str(DOWNLOADS_SCAN_DIR),
        "artifactScanRoots": [str(path) for path in scan_roots],
        "ok": False,
        "status": "blocked",
        "message": None,
    }
    if not app_path.exists():
        report["message"] = f"thinkorswim app not found at {app_path}"
        save_export_report(report)
        return report
    if not enabled:
        report["status"] = "dry-run-disabled" if dry_run else "disabled"
        report["message"] = "TOS export automation is disabled by config"
        if dry_run:
            report["ok"] = True
        save_export_report(report)
        return report
    script = build_applescript(app_path, TOS_EXPORT_SHORTCUT, TOS_EXPORT_PRE_DELAY_SECONDS, TOS_EXPORT_POST_DELAY_SECONDS)
    report["scriptPreview"] = script if dry_run else None
    if dry_run:
        route_report = route_to_account_statement(dry_run=True, allow_recovery=False)
        report["uiRoute"] = {
            "ok": route_report.get("ok"),
            "status": route_report.get("status"),
            "message": route_report.get("message"),
        }
        report["ok"] = True
        report["status"] = "dry-run"
        report["message"] = "dry-run only; no UI automation executed"
        save_export_report(report)
        return report

    cooldown_remaining = cooldown_remaining_seconds(prior_report, now)
    if cooldown_remaining > 0:
        report["ok"] = True
        report["status"] = "cooldown-skipped"
        report["cooldownRemainingSeconds"] = cooldown_remaining
        report["message"] = f"export trigger skipped; cooldown active for {cooldown_remaining}s"
        save_export_report(report)
        return report

    before_markers = recent_artifact_markers(scan_roots)
    clipboard_before_text = read_clipboard_text()
    report["clipboardBefore"] = clipboard_snapshot(clipboard_before_text)

    route_report = route_to_account_statement(dry_run=False, allow_recovery=False)
    report["uiRoute"] = {
        "ok": route_report.get("ok"),
        "status": route_report.get("status"),
        "message": route_report.get("message"),
        "finalSession": route_report.get("finalSession"),
    }
    if not route_report.get("ok"):
        report["status"] = "route-blocked"
        report["message"] = route_report.get("message") or "failed to route thinkorswim into Account Statement"
        save_export_report(report)
        return report

    trigger_session = probe_tos_session()
    report["triggerSession"] = {
        "summary": trigger_session.get("summary"),
        "matchedProcessName": trigger_session.get("matchedProcessName"),
        "currentPanel": trigger_session.get("currentPanel"),
        "monitorSubpanel": trigger_session.get("monitorSubpanel"),
        "splitGroupIndex": trigger_session.get("splitGroupIndex"),
        "monitorGroupIndex": trigger_session.get("monitorGroupIndex"),
    }
    trigger_method = "shortcut"
    trigger_script = script
    dump_button = next(
        (
            item
            for item in (trigger_session.get("labeledButtons") or [])
            if text(item.get("label")).strip().lower() == "dump account"
        ),
        None,
    )
    split_group_index = trigger_session.get("splitGroupIndex")
    monitor_group_index = trigger_session.get("monitorGroupIndex")
    if (
        trigger_session.get("monitorSubpanel") == "Account Statement"
        and trigger_session.get("matchedProcessName")
        and split_group_index
        and monitor_group_index
        and dump_button
        and dump_button.get("index")
    ):
        trigger_method = "dump-account-button"
        trigger_script = build_dump_account_applescript(
            app_path,
            str(trigger_session.get("matchedProcessName")),
            int(split_group_index),
            int(monitor_group_index),
            int(dump_button.get("index")),
            TOS_EXPORT_POST_DELAY_SECONDS,
        )
    report["triggerMethod"] = trigger_method
    result = run_applescript(trigger_script)
    report["stdout"] = text(result.stdout)
    report["stderr"] = text(result.stderr)
    report["returncode"] = result.returncode
    if result.returncode == 0:
        after_markers = recent_artifact_markers(scan_roots)
        new_files = summarize_new_artifacts(before_markers, after_markers)
        clipboard_after_text = read_clipboard_text()
        report["clipboardAfter"] = clipboard_snapshot(clipboard_after_text)
        report["clipboardChanged"] = report["clipboardBefore"].get("sha256") != report["clipboardAfter"].get("sha256")
        if report["clipboardChanged"] and report["clipboardAfter"].get("looksLikeAccountStatement"):
            clipboard_export_path = persist_clipboard_export(clipboard_after_text, now)
            report["clipboardArtifactPath"] = str(clipboard_export_path)
            new_files.append(
                {
                    "path": str(clipboard_export_path),
                    "name": clipboard_export_path.name,
                    "sizeBytes": clipboard_export_path.stat().st_size,
                    "source": "clipboard",
                }
            )
        scraper_report = None
        if not new_files:
            scraper_report = scrape_account_statement(route_if_needed=False)
            report["statementScrape"] = {
                "ok": scraper_report.get("ok"),
                "message": scraper_report.get("message"),
                "positions": len(scraper_report.get("positions") or []),
                "accountMode": scraper_report.get("accountMode"),
                "netLiquidatingValue": scraper_report.get("netLiquidatingValue"),
            }
            if scraper_report.get("ok"):
                for artifact_path in (ACCOUNT_STATEMENT_FILE, ACCOUNT_STATEMENT_TEXT_FILE):
                    if artifact_path.exists():
                        new_files.append(
                            {
                                "path": str(artifact_path),
                                "name": artifact_path.name,
                                "sizeBytes": artifact_path.stat().st_size,
                                "source": "statement-scrape",
                            }
                        )
        report["artifactDetected"] = bool(new_files)
        report["newArtifacts"] = new_files
        report["ok"] = True
        report["status"] = "triggered" if new_files else "triggered-no-artifact"
        trigger_phrase = "Dump Account trigger" if trigger_method == "dump-account-button" else "export shortcut"
        report["message"] = (
            f"{trigger_phrase} fired and a new export artifact was detected"
            if new_files
            else f"{trigger_phrase} fired, but no new export artifact appeared in the watched roots or clipboard"
        )
    else:
        report["status"] = "failed"
        report["message"] = text(result.stderr) or "osascript export trigger failed"
    save_export_report(report)
    return report


def export_report_text(report: dict[str, Any]) -> str:
    """Render the latest export bridge report."""
    lines = [
        "Inferno thinkorswim Export Bridge",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Enabled: {report.get('enabled')}",
        f"Dry run: {report.get('dryRun')}",
        f"Status: {report.get('status')}",
        f"App: {report.get('appPath')}",
        f"Shortcut: {report.get('shortcut')}",
        f"Cooldown: {report.get('cooldownSeconds')}s",
        f"Trigger method: {report.get('triggerMethod')}",
        f"Message: {report.get('message')}",
    ]
    if report.get("artifactScanRoots"):
        lines.append("Artifact scan roots:")
        for path in report.get("artifactScanRoots") or []:
            lines.append(f"- {path}")
    if report.get("artifactDetected") is not None:
        lines.append(f"Artifact detected: {report.get('artifactDetected')}")
    for artifact in report.get("newArtifacts") or []:
        lines.append(
            f"New artifact: {artifact.get('name')} | {artifact.get('sizeBytes')} bytes | {artifact.get('source')} | {artifact.get('path')}"
        )
    if report.get("clipboardArtifactPath"):
        lines.append(f"Clipboard artifact: {report.get('clipboardArtifactPath')}")
    clipboard_after = report.get("clipboardAfter") or {}
    if clipboard_after:
        lines.append(
            "Clipboard after: "
            f"present={clipboard_after.get('present')} | "
            f"len={clipboard_after.get('lengthChars')} | "
            f"keywords={', '.join(clipboard_after.get('keywordHits') or []) or '-'} | "
            f"statement={clipboard_after.get('looksLikeAccountStatement')}"
        )
    if report.get("clipboardChanged") is not None:
        lines.append(f"Clipboard changed: {report.get('clipboardChanged')}")
    statement_scrape = report.get("statementScrape") or {}
    if statement_scrape:
        lines.append(
            "Statement scrape: "
            f"ok={statement_scrape.get('ok')} | "
            f"positions={statement_scrape.get('positions')} | "
            f"account={statement_scrape.get('accountMode')} | "
            f"netLiq={statement_scrape.get('netLiquidatingValue') or '-'}"
        )
        if statement_scrape.get("message"):
            lines.append(f"Statement scrape message: {statement_scrape.get('message')}")
    if report.get("cooldownRemainingSeconds") is not None:
        lines.append(f"Cooldown remaining: {report.get('cooldownRemainingSeconds')}s")
    if report.get("stderr"):
        lines.append(f"stderr: {report.get('stderr')}")
    return "\n".join(lines).rstrip() + "\n"


def save_export_report(report: dict[str, Any]) -> None:
    """Persist the latest export bridge JSON and text reports."""
    ensure_dirs()
    EXPORT_BRIDGE_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    EXPORT_BRIDGE_TEXT_FILE.write_text(export_report_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse CLI args for the export bridge."""
    parser = argparse.ArgumentParser(description="Trigger the experimental thinkorswim export shortcut.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--dry-run", action="store_true", help="Validate config and render the script without executing UI automation")
    return parser.parse_args()


def main() -> int:
    """Run or show the latest export bridge report."""
    args = parse_args()
    if args.command == "status" and EXPORT_BRIDGE_TEXT_FILE.exists():
        print(EXPORT_BRIDGE_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = run_export_bridge(dry_run=args.dry_run)
    print(export_report_text(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
