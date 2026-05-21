from __future__ import annotations

"""Inferno TOS Export Chain — end-to-end diagnostic of the native export path.

The stability runner (``inferno_tos_export_stability``) repeats the verifier
with backoff and classifies the final verdict. That's the right tool when
the question is "is the path stable right now?"

The *chain* diagnostic answers a different question: "if I tried to export
right now, where exactly would I fail?" It walks every step the bridge
would take, in order, and attributes a PASS / FAIL / SKIPPED status to
each one. Each step carries a remediation string the operator can act on
without grepping AppleScript.

The chain is the natural debug tool when the verifier returns
``manual-check`` or ``blocked`` and you want to know which specific link
in the chain broke.

Steps walked (in execution order):

1. ``config-loaded``       — TOS_APP_PATH, shortcut, allowed suffixes parsed
2. ``app-installed``       — thinkorswim.app exists at the configured path
3. ``app-running``         — a matching process is alive on this Mac
4. ``accessibility-ok``    — System Events automation is granted
5. ``main-window-present`` — the trading window is visible
6. ``panel-safe``          — the current panel is on the safe-automation list
7. ``account-authorized``  — visible account matches paper OR allowed live suffix
8. ``ui-route-dry-run``    — the click route compiles and the dry-run passes
9. ``shortcut-valid``      — TOS_EXPORT_SHORTCUT parses to keystroke+modifiers
10. ``applescript-builds`` — the AppleScript compiles locally
11. ``ingest-ready``       — the downloads watch / paper fill ingest path exists

Strict contract:

- read-only; never invokes the export shortcut, never enables recovery
- ``researchOnly=True`` / ``promotable=False`` hard-pinned
- output goes only to ``data/inferno_tos_export_chain.json`` and
  ``reports/tos_export_chain_latest.txt``

CLI:

::

    python3 inferno_tos_export_chain.py        # run + print
    python3 inferno_tos_export_chain.py status # print last memo
    python3 inferno_tos_export_chain.py --json # structured output
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable

from inferno_config import (
    TOS_ALLOWED_ACCOUNT_SUFFIXES,
    TOS_ALLOW_LIVE_READONLY,
    TOS_APP_PATH,
    TOS_EXPORT_AUTOMATION_ENABLED,
    TOS_EXPORT_SHORTCUT,
    TOS_PROCESS_CANDIDATES,
    approved_account_scope,
    local_now,
)
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


CHAIN_ARTIFACT_FILE = DATA_DIR / "inferno_tos_export_chain.json"
CHAIN_TEXT_FILE = REPORTS_DIR / "tos_export_chain_latest.txt"
CHAIN_STAGE = "tos-export-chain-observation-only"

# The ordered step names. We pin this so the report's shape is stable and
# downstream tools (brain console, future dashboard) can rely on it.
CHAIN_STEPS: tuple[str, ...] = (
    "config-loaded",
    "app-installed",
    "app-running",
    "accessibility-ok",
    "main-window-present",
    "panel-safe",
    "account-authorized",
    "ui-route-dry-run",
    "shortcut-valid",
    "applescript-builds",
    "ingest-ready",
)

# Operator-facing remediation strings. Keyed by step name.
REMEDIATION: dict[str, str] = {
    "config-loaded": (
        "TOS config didn't parse. Check .env.inferno for TOS_APP_PATH, "
        "TOS_EXPORT_SHORTCUT, and TOS_ALLOWED_ACCOUNT_SUFFIXES."
    ),
    "app-installed": (
        "thinkorswim.app not found at the configured path. Reinstall or "
        "update TOS_APP_PATH."
    ),
    "app-running": (
        "Launch thinkorswim and let the main window finish loading."
    ),
    "accessibility-ok": (
        "Grant System Events automation permission to your terminal/Claude "
        "in System Settings → Privacy & Security → Automation."
    ),
    "main-window-present": (
        "Bring the thinkorswim window to the foreground (Cmd-Tab) so the "
        "accessibility tree exposes it."
    ),
    "panel-safe": (
        "Navigate thinkorswim to Monitor → Account Statement before the "
        "export fires. Other panels are flagged unsafe by policy."
    ),
    "account-authorized": (
        f"Switch to the allowed live read-only {approved_account_scope()} or to paperMoney. "
        "The bridge refuses unknown account modes."
    ),
    "ui-route-dry-run": (
        "The UI route coordinates may have drifted. Check the latest "
        "tos_ui_route_latest report. The route is attach-only and will not "
        "launch or reopen thinkorswim."
    ),
    "shortcut-valid": (
        "TOS_EXPORT_SHORTCUT didn't parse. Use a string like "
        "'command+shift+e'."
    ),
    "applescript-builds": (
        "AppleScript compile failed locally. Inspect TOS_EXPORT_SHORTCUT and "
        "the process candidate list."
    ),
    "ingest-ready": (
        "The downloads watch / paper fill ingest path isn't ready. Make sure "
        "the watch agent is loaded and DOWNLOADS_SCAN_DIR is writable."
    ),
}


def _ok(name: str, detail: str = "") -> dict[str, Any]:
    return {"name": name, "status": "pass", "detail": detail, "remediation": ""}


def _fail(name: str, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "fail",
        "detail": detail,
        "remediation": REMEDIATION.get(name, ""),
    }


def _skip(name: str, reason: str) -> dict[str, Any]:
    """Step not run because an earlier link in the chain failed."""
    return {
        "name": name,
        "status": "skipped",
        "detail": reason,
        "remediation": "",
    }


def _config_loaded_step() -> dict[str, Any]:
    """First-link sanity check: did inferno_config produce sane values?"""
    if not TOS_APP_PATH:
        return _fail("config-loaded", "TOS_APP_PATH is empty")
    if not TOS_EXPORT_SHORTCUT:
        return _fail("config-loaded", "TOS_EXPORT_SHORTCUT is empty")
    if not TOS_PROCESS_CANDIDATES:
        return _fail("config-loaded", "TOS_PROCESS_CANDIDATES is empty")
    return _ok(
        "config-loaded",
        f"app={TOS_APP_PATH} shortcut={TOS_EXPORT_SHORTCUT} "
        f"suffixes={','.join(TOS_ALLOWED_ACCOUNT_SUFFIXES) or '-'}",
    )


def _app_installed_step(app_path: Path | None = None) -> dict[str, Any]:
    path = app_path or TOS_APP_PATH
    if path.exists():
        return _ok("app-installed", str(path))
    return _fail("app-installed", f"missing at {path}")


def _evaluate_session_probe(
    probe_fn: Callable[[], dict[str, Any]] | None,
) -> dict[str, Any]:
    """Run the session probe once and return the raw dict.

    Wrapped so tests can inject a stub probe.
    """
    if probe_fn is None:
        from inferno_tos_session_probe import probe_tos_session as default_probe

        probe_fn = default_probe
    return probe_fn()


def _evaluate_ui_route(
    route_fn: Callable[..., dict[str, Any]] | None,
) -> dict[str, Any]:
    """Run the UI route dry-run once and return the raw dict.

    Wrapped so tests can inject a stub.
    """
    if route_fn is None:
        from inferno_tos_ui_route import route_to_account_statement as default_route

        route_fn = default_route
    return route_fn(dry_run=True, allow_recovery=False)


def _build_applescript_step(
    builder: Callable[..., str] | None,
) -> dict[str, Any]:
    """Compile the AppleScript locally to surface keystroke / shortcut errors."""
    try:
        if builder is None:
            from inferno_tos_export_bridge import build_applescript as default_builder

            builder = default_builder
        builder(TOS_APP_PATH, TOS_EXPORT_SHORTCUT, 0.5, 0.5)
        return _ok("applescript-builds", "AppleScript compiled locally")
    except Exception as exc:  # noqa: BLE001
        return _fail("applescript-builds", f"{type(exc).__name__}: {exc}")


def _shortcut_valid_step(
    parser: Callable[[str], tuple[str, list[str]]] | None,
) -> dict[str, Any]:
    """Parse TOS_EXPORT_SHORTCUT through the bridge's parser."""
    try:
        if parser is None:
            from inferno_tos_export_bridge import parse_shortcut as default_parser

            parser = default_parser
        key, modifiers = parser(TOS_EXPORT_SHORTCUT)
        return _ok(
            "shortcut-valid",
            f"key={key} modifiers={','.join(modifiers) or '-'}",
        )
    except Exception as exc:  # noqa: BLE001
        return _fail("shortcut-valid", f"{type(exc).__name__}: {exc}")


def _ingest_ready_step(downloads_scan_dir: Path | None = None) -> dict[str, Any]:
    """Check the post-export ingest path looks healthy.

    We don't trigger ingest; we just verify the directory exists and is
    writable so the watch agent / paper fill ingest can land artifacts.
    """
    if downloads_scan_dir is None:
        try:
            from inferno_config import DOWNLOADS_SCAN_DIR
        except Exception:
            return _fail("ingest-ready", "DOWNLOADS_SCAN_DIR not importable")
        downloads_scan_dir = DOWNLOADS_SCAN_DIR
    path = Path(downloads_scan_dir).expanduser()
    if not path.exists():
        return _fail("ingest-ready", f"{path} does not exist")
    if not os.access(path, os.W_OK):
        return _fail("ingest-ready", f"{path} is not writable")
    return _ok("ingest-ready", str(path))


def _account_authorized(session_probe: dict[str, Any]) -> tuple[bool, str]:
    """Decide whether the visible account satisfies the suffix allowlist."""
    account_mode = str(session_probe.get("accountMode") or "").lower()
    if account_mode == "paper":
        return True, "paperMoney sandbox visible"
    if not TOS_ALLOW_LIVE_READONLY:
        return False, f"account mode {account_mode}; live read-only disabled"
    suffix_candidates = [str(value) for value in
                         (session_probe.get("accountSuffixCandidates") or [])
                         if str(value)]
    for candidate in suffix_candidates:
        for allowed in TOS_ALLOWED_ACCOUNT_SUFFIXES:
            if candidate.endswith(allowed) or allowed.endswith(candidate):
                return True, f"live read-only suffix matched ({allowed})"
    return False, (
        f"account mode {account_mode} | suffixes {','.join(suffix_candidates) or '-'} "
        f"| allowed {','.join(TOS_ALLOWED_ACCOUNT_SUFFIXES) or '-'}"
    )


def build_chain_report(
    *,
    app_path: Path | None = None,
    process_check: Callable[[str], bool] | None = None,
    accessibility_check: Callable[[], tuple[bool, str]] | None = None,
    session_probe_fn: Callable[[], dict[str, Any]] | None = None,
    ui_route_fn: Callable[..., dict[str, Any]] | None = None,
    applescript_builder: Callable[..., str] | None = None,
    shortcut_parser: Callable[[str], tuple[str, list[str]]] | None = None,
    downloads_scan_dir: Path | None = None,
) -> dict[str, Any]:
    """Walk every link of the export chain. All callbacks injectable for tests.

    The callbacks default to the production functions when omitted. Tests
    inject stubs so each step can be exercised without spawning thinkorswim,
    osascript, or pgrep.
    """
    steps: list[dict[str, Any]] = []
    short_circuit = False

    # Step 1: config-loaded
    config_step = _config_loaded_step()
    steps.append(config_step)
    short_circuit = short_circuit or config_step["status"] == "fail"

    effective_app_path = app_path or TOS_APP_PATH

    # Step 2: app-installed
    if short_circuit:
        steps.append(_skip("app-installed", "config-loaded failed"))
    else:
        step = _app_installed_step(effective_app_path)
        steps.append(step)
        short_circuit = short_circuit or step["status"] == "fail"

    # Step 3: app-running
    if short_circuit:
        steps.append(_skip("app-running", "earlier link failed"))
    else:
        if process_check is None:
            from inferno_tos_export_verifier import app_running as default_check

            process_check = default_check
        running = bool(process_check(effective_app_path.stem))
        steps.append(
            _ok("app-running", f"{effective_app_path.stem} is running")
            if running
            else _fail("app-running", f"{effective_app_path.stem} not running")
        )
        short_circuit = short_circuit or not running

    # Step 4: accessibility-ok
    if short_circuit:
        steps.append(_skip("accessibility-ok", "earlier link failed"))
    else:
        if accessibility_check is None:
            from inferno_tos_export_verifier import frontmost_app_name as default_acc

            accessibility_check = default_acc
        ok, detail = accessibility_check()
        steps.append(_ok("accessibility-ok", detail) if ok
                     else _fail("accessibility-ok", detail))
        short_circuit = short_circuit or not ok

    # Step 5-7: session probe → main window, panel safety, account authorized
    session_probe: dict[str, Any] = {}
    if short_circuit:
        for step_name in ("main-window-present", "panel-safe", "account-authorized"):
            steps.append(_skip(step_name, "earlier link failed"))
    else:
        session_probe = _evaluate_session_probe(session_probe_fn)
        # main-window-present
        main_ok = bool(session_probe.get("mainWindowPresent"))
        steps.append(
            _ok("main-window-present",
                f"window: {','.join(session_probe.get('windowNames') or []) or 'none'}")
            if main_ok else _fail("main-window-present",
                                  session_probe.get("summary")
                                  or "no main window detected")
        )
        if not main_ok:
            short_circuit = True
            steps.append(_skip("panel-safe", "main window missing"))
            steps.append(_skip("account-authorized", "main window missing"))
        else:
            # panel-safe
            panel_safety = str(session_probe.get("currentPanelSafety") or "unknown")
            panel_name = str(session_probe.get("currentPanel") or "unknown")
            if panel_safety == "unsafe":
                steps.append(_fail("panel-safe", f"{panel_name} | safety unsafe"))
                short_circuit = True
            else:
                steps.append(_ok("panel-safe",
                                 f"{panel_name} | safety {panel_safety}"))
            # account-authorized — independent of panel safety
            account_ok, account_detail = _account_authorized(session_probe)
            steps.append(_ok("account-authorized", account_detail) if account_ok
                         else _fail("account-authorized", account_detail))
            if not account_ok:
                short_circuit = True

    # Step 8: ui-route-dry-run (only meaningful if we got past panel + account)
    if short_circuit:
        steps.append(_skip("ui-route-dry-run", "earlier link failed"))
    else:
        route = _evaluate_ui_route(ui_route_fn)
        ok = bool(route.get("ok"))
        message = route.get("message") or route.get("status") or "no message"
        steps.append(_ok("ui-route-dry-run", message) if ok
                     else _fail("ui-route-dry-run", message))
        if not ok:
            short_circuit = True

    # Step 9: shortcut-valid (does not require app running so we always run it)
    steps.append(_shortcut_valid_step(shortcut_parser))

    # Step 10: applescript-builds (depends on shortcut + config; we always run)
    steps.append(_build_applescript_step(applescript_builder))

    # Step 11: ingest-ready
    steps.append(_ingest_ready_step(downloads_scan_dir))

    pass_count = sum(1 for step in steps if step["status"] == "pass")
    fail_count = sum(1 for step in steps if step["status"] == "fail")
    skip_count = sum(1 for step in steps if step["status"] == "skipped")
    first_failure = next((step for step in steps if step["status"] == "fail"), None)

    if fail_count == 0 and skip_count == 0:
        verdict = "ready"
        narrative = (
            "Every link of the export chain is healthy. The path is ready to fire "
            "the moment authority is granted; nothing here would block it."
        )
    elif first_failure is None:
        verdict = "blocked"
        narrative = (
            "The chain has skipped steps but no explicit failure. Re-run with "
            "more recent artifacts."
        )
    else:
        verdict = "blocked"
        narrative = (
            f"First blocking link: {first_failure['name']}. "
            f"{first_failure.get('remediation') or first_failure.get('detail') or ''}"
        ).strip()

    return {
        "generatedAt": local_now().isoformat(),
        "stage": CHAIN_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "passCount": pass_count,
        "failCount": fail_count,
        "skipCount": skip_count,
        "stepCount": len(steps),
        "firstFailure": first_failure["name"] if first_failure else None,
        "automationEnabled": TOS_EXPORT_AUTOMATION_ENABLED,
        "allowedSuffixes": list(TOS_ALLOWED_ACCOUNT_SUFFIXES),
        "steps": steps,
        "reminders": [
            "observation-only; never invokes the export shortcut",
            "first-failure attribution lets operators fix one link at a time",
            "rerun after each remediation to walk the chain again",
        ],
    }


def chain_text(payload: dict[str, Any]) -> str:
    """Render the chain into an operator memo."""
    lines = [
        "Inferno TOS Export Chain (observation-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Verdict: {payload.get('verdict')}",
        f"Pass / fail / skipped: "
        f"{payload.get('passCount')} / "
        f"{payload.get('failCount')} / "
        f"{payload.get('skipCount')} "
        f"(total {payload.get('stepCount')})",
        f"First failure: {payload.get('firstFailure') or 'none'}",
        f"Automation enabled: {payload.get('automationEnabled')}",
        f"Allowed suffixes: {', '.join(payload.get('allowedSuffixes') or []) or '-'}",
        "",
        f"Narrative: {payload.get('narrative')}",
        "",
        "Steps:",
    ]
    for step in payload.get("steps") or []:
        marker = {"pass": "PASS", "fail": "FAIL", "skipped": "SKIP"}.get(
            step.get("status"), "?"
        )
        lines.append(f"- [{marker}] {step.get('name'):<22} {step.get('detail') or ''}")
        if step.get("status") == "fail" and step.get("remediation"):
            lines.append(f"    remediation: {step.get('remediation')}")
    lines.extend([
        "",
        "Reminders:",
    ])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_chain_report(payload: dict[str, Any]) -> None:
    """Persist the chain JSON and text artifacts via the retry-safe writer."""
    ensure_dirs()
    atomic_write_json(CHAIN_ARTIFACT_FILE, payload)
    atomic_write_text(CHAIN_TEXT_FILE, chain_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "End-to-end TOS export chain diagnostic. Observation-only; never "
            "invokes the export shortcut."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and CHAIN_TEXT_FILE.exists():
        print(CHAIN_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_chain_report()
    save_chain_report(payload)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(chain_text(payload))
    # Always exit 0 if the chain produced a report. "blocked" is a legitimate
    # result that the operator should see, not a runtime failure that should
    # fail the verify script. Use the artifact's verdict field for branching.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
