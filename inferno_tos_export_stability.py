from __future__ import annotations

"""Hardening layer on top of the thinkorswim export verifier.

The verifier already classifies the export bridge into a `verdict` and a list of
`checks`, but it does so in a single shot. On a real Mac the accessibility tree
sometimes blinks for a second when thinkorswim repaints, when the Spaces switch
animation finishes, or when the user just unlocked the screen. A one-shot probe
can come back as `manual-check` for transient reasons even though the export
path is healthy two seconds later.

This module exists to make the export bridge feel "stable" in the
agentic / living-and-breathing sense: it runs the verifier `attempts` times
with backoff, classifies the failures it sees into a small fixed taxonomy,
and emits a narrative paragraph that says *what is wrong* and *what to do
about it* in plain English. It changes no state. It places no trades. It does
not call `route_to_account_statement` with anything other than `dry_run=True`.
It does not flip recovery flags. It never invokes the actual export shortcut.

Outputs:
- ``data/inferno_tos_export_stability.json`` — the chained report.
- ``reports/tos_export_stability_latest.txt`` — operator-facing memo.
"""

import argparse
import json
import time
from typing import Any, Callable

from inferno_config import (
    TOS_BACKGROUND_EXPORT_ALLOWED,
    TOS_EXPORT_AUTOMATION_ENABLED,
    approved_account_scope,
    local_now,
)
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


STABILITY_ARTIFACT_FILE = DATA_DIR / "inferno_tos_export_stability.json"
STABILITY_TEXT_FILE = REPORTS_DIR / "tos_export_stability_latest.txt"
STABILITY_STAGE = "tos-export-stability-observation-only"

# Fail-mode taxonomy. Every observed verifier result lands in exactly one of
# these buckets. Order matters: earlier entries are checked first when more
# than one symptom is present, so the most actionable diagnosis wins.
FAIL_MODES: tuple[str, ...] = (
    "ok-ready-live-readonly",
    "ok-ready-paper",
    "inactive-by-config",
    "tos-closed-low-power",
    "tos-not-running",
    "accessibility-blocked",
    "window-missing",
    "panel-unsafe",
    "account-not-authorized",
    "ui-route-dry-run-failed",
    "shortcut-invalid",
    "app-path-missing",
    "transient-blocked",
    "unknown",
)

# What to do if a given fail mode dominates. Strings are operator-facing.
REMEDIATION: dict[str, str] = {
    "ok-ready-live-readonly": (
        "verifier ready-live-readonly; no action required"
    ),
    "ok-ready-paper": (
        "verifier ready (paperMoney); no action required"
    ),
    "inactive-by-config": (
        "TOS_EXPORT_AUTOMATION_ENABLED is False — this is intentional; flip it "
        "only when the operator is at the keyboard"
    ),
    "tos-closed-low-power": (
        "thinkorswim is closed by operator choice. Keep it closed for math, "
        "tracker, brief, and paper-evidence runs; open it only for supervised "
        "export or manual order staging"
    ),
    "tos-not-running": (
        "thinkorswim is not running on this Mac. Launch it, wait for the main "
        "window to appear, then re-run the verifier"
    ),
    "accessibility-blocked": (
        "macOS is not granting System Events automation to Terminal/Claude. "
        "Open System Settings → Privacy & Security → Accessibility and "
        "Automation, grant the running shell, then re-run the verifier"
    ),
    "window-missing": (
        "thinkorswim is running but the main trading window is not visible. "
        "Bring it to the foreground (Cmd-Tab) or click its dock icon, then "
        "re-run the verifier"
    ),
    "panel-unsafe": (
        "thinkorswim is on a panel flagged as unsafe for automation. Navigate "
        "to Monitor → Account Statement before the next run"
    ),
    "account-not-authorized": (
        "the visible account is not the allowed suffix or not paperMoney. "
        f"Switch to the allowed live read-only {approved_account_scope()} or to "
        "paperMoney before relying on the export"
    ),
    "ui-route-dry-run-failed": (
        "the UI route dry-run came back not-ok. Confirm Monitor and Account "
        "Statement coordinates have not drifted; check the tos_ui_route "
        "report"
    ),
    "shortcut-invalid": (
        "the configured export shortcut failed to parse. Set "
        "TOS_EXPORT_SHORTCUT to a supported format (e.g. command+shift+e)"
    ),
    "app-path-missing": (
        "TOS_APP_PATH does not point at a real thinkorswim.app. Reinstall or "
        "update the path"
    ),
    "transient-blocked": (
        "the verifier blocked once but recovered on a later attempt. No "
        "operator action needed; the stability runner already absorbed it"
    ),
    "unknown": (
        "verifier returned a verdict the stability runner does not recognise. "
        "Read the raw report and update FAIL_MODES if a new symptom emerged"
    ),
}


def classify_attempt(attempt: dict[str, Any]) -> str:
    """Return the fail-mode bucket for a single verifier attempt.

    Inputs are the dict shape returned by ``verify_export_bridge``. We look at
    ``verdict`` first because the verifier already does most of the
    classification work; we only refine when the verdict is ambiguous.
    """
    verdict = str(attempt.get("verdict") or "").strip()
    message = str(attempt.get("message") or "").lower()

    if verdict == "ready-live-readonly":
        return "ok-ready-live-readonly"
    if verdict == "ready":
        return "ok-ready-paper"
    if verdict == "inactive-safe":
        return "inactive-by-config"

    if not attempt.get("appPathExists", True):
        return "app-path-missing"
    if not attempt.get("shortcutValid", True):
        return "shortcut-invalid"
    if not attempt.get("systemEventsOk", True):
        return "accessibility-blocked"
    if not attempt.get("appRunning", True):
        return "tos-not-running"

    session_probe = attempt.get("sessionProbe") or {}
    if not session_probe.get("mainWindowPresent"):
        return "window-missing"

    panel_safety = str(session_probe.get("currentPanelSafety") or "").lower()
    if panel_safety == "unsafe":
        return "panel-unsafe"

    ui_route = attempt.get("uiRoute") or {}
    if ui_route and ui_route.get("ok") is False:
        return "ui-route-dry-run-failed"

    account_mode = str(session_probe.get("accountMode") or "").lower()
    if account_mode and account_mode not in {"paper"}:
        # The verifier still gives ready-live-readonly when the suffix matches,
        # so reaching here means it explicitly refused on account grounds.
        return "account-not-authorized"

    if "is not provably paper" in message or "not authorized" in message:
        return "account-not-authorized"

    if verdict in {"blocked", "manual-check"}:
        # Catch-all: the verifier wants the human, but no specific symptom hit.
        return "transient-blocked"

    return "unknown"


def _is_ok_mode(mode: str) -> bool:
    return mode.startswith("ok-")


def _is_low_power_closed_mode(attempt_records: list[dict[str, Any]]) -> bool:
    """Return True when TOS absence is expected, not a broken automation lane.

    The normal desk posture is intentionally conservative: export automation is
    disabled and background agents are not allowed to foreground thinkorswim.
    In that mode, a closed/missing broker window should read as ``inactive-safe``
    so the morning loop can keep running on a lightweight Mac without burning
    memory on TOS.
    """
    if TOS_EXPORT_AUTOMATION_ENABLED or TOS_BACKGROUND_EXPORT_ALLOWED:
        return False
    if not attempt_records:
        return False
    tolerated_modes = {"tos-not-running", "window-missing"}
    return all(record.get("failMode") in tolerated_modes for record in attempt_records)


def build_stability_report(
    attempts: int = 3,
    backoff_seconds: float = 1.5,
    *,
    sleep: Callable[[float], None] = time.sleep,
    verifier: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the verifier ``attempts`` times with backoff and classify each.

    ``verifier`` is injected for tests. By default we lazy-import
    ``verify_export_bridge`` so unit tests can stub the module without paying
    the cost of pulling the real bridge dependencies.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    if backoff_seconds < 0:
        raise ValueError("backoff_seconds must be >= 0")

    if verifier is None:
        # Local import keeps the test surface narrow.
        from inferno_tos_export_verifier import verify_export_bridge as _verify

        verifier = _verify

    attempt_records: list[dict[str, Any]] = []
    classification_counts: dict[str, int] = {mode: 0 for mode in FAIL_MODES}

    for index in range(attempts):
        if index > 0 and backoff_seconds > 0:
            sleep(backoff_seconds)
        try:
            raw_attempt = verifier(require_enabled=False, allow_recovery=False)
        except Exception as exc:  # noqa: BLE001
            attempt_records.append(
                {
                    "index": index,
                    "ok": False,
                    "verdict": "exception",
                    "message": f"{type(exc).__name__}: {exc}",
                    "failMode": "unknown",
                }
            )
            classification_counts["unknown"] += 1
            continue

        mode = classify_attempt(raw_attempt)
        if mode not in classification_counts:
            classification_counts[mode] = 0
        classification_counts[mode] += 1
        attempt_records.append(
            {
                "index": index,
                "ok": _is_ok_mode(mode),
                "verdict": raw_attempt.get("verdict"),
                "message": raw_attempt.get("message"),
                "failMode": mode,
                "appRunning": raw_attempt.get("appRunning"),
                "systemEventsOk": raw_attempt.get("systemEventsOk"),
                "sessionProbeOk": (raw_attempt.get("sessionProbe") or {}).get("ok"),
                "currentPanel": (raw_attempt.get("sessionProbe") or {}).get("currentPanel"),
                "currentPanelSafety": (raw_attempt.get("sessionProbe") or {}).get(
                    "currentPanelSafety"
                ),
                "accountMode": (raw_attempt.get("sessionProbe") or {}).get("accountMode"),
                "uiRouteOk": (raw_attempt.get("uiRoute") or {}).get("ok"),
            }
        )

    return finalize_stability_report(attempts, attempt_records, classification_counts)


def finalize_stability_report(
    attempts: int,
    attempt_records: list[dict[str, Any]],
    classification_counts: dict[str, int],
) -> dict[str, Any]:
    """Combine per-attempt records into a single stability verdict + narrative.

    Verdict ladder:
    - ``stable-ready``        : every attempt landed in an ok mode.
    - ``transient-recovered`` : at least one ok mode, but also at least one
                                 non-ok mode — the path works but is jittery.
    - ``blocked``             : zero ok modes, dominant mode is actionable.
    - ``inactive-safe``       : every attempt landed in ``inactive-by-config``.
    """
    ok_attempts = sum(1 for record in attempt_records if record["ok"])
    inactive_attempts = sum(
        1 for record in attempt_records if record["failMode"] == "inactive-by-config"
    )

    # Pick the dominant non-ok bucket for narrative purposes; if everything is
    # ok we report the ok bucket instead.
    non_ok = {
        mode: count
        for mode, count in classification_counts.items()
        if not _is_ok_mode(mode) and count > 0
    }
    if ok_attempts == attempts:
        ok_only = {
            mode: count
            for mode, count in classification_counts.items()
            if _is_ok_mode(mode) and count > 0
        }
        dominant_mode = max(ok_only, key=lambda m: ok_only[m]) if ok_only else "unknown"
    elif non_ok:
        dominant_mode = max(non_ok, key=lambda m: non_ok[m])
    else:
        dominant_mode = "unknown"

    if attempts > 0 and inactive_attempts == attempts:
        verdict = "inactive-safe"
        narrative = (
            "Export automation is disabled by config and the verifier confirmed "
            "that on every probe. This is the safe-default desk posture."
        )
    elif _is_low_power_closed_mode(attempt_records):
        verdict = "inactive-safe"
        dominant_mode = "tos-closed-low-power"
        narrative = (
            "TOS is closed or not visible while background export automation is "
            "disabled. That is the intended low-performance mode: keep the broker "
            "closed for math, tracker, brief, and paper-evidence work; open it only "
            "for supervised export or manual order staging."
        )
    elif ok_attempts == attempts:
        verdict = "stable-ready"
        narrative = (
            "Every probe landed in an ok verdict. The native TOS export path is "
            "stable from this Mac right now."
        )
    elif ok_attempts > 0:
        verdict = "transient-recovered"
        narrative = (
            f"The path recovered: {ok_attempts}/{attempts} probes landed in an ok "
            "verdict and the rest fell into a transient bucket. No operator "
            "action required, but the verifier is sensitive to the current UI "
            "state, so consider rerunning if you actually need to export."
        )
    else:
        verdict = "blocked"
        narrative = (
            f"All {attempts} probes blocked. Dominant symptom: "
            f"{dominant_mode}. {REMEDIATION.get(dominant_mode, '')}"
        ).strip()

    return {
        "generatedAt": local_now().isoformat(),
        "stage": STABILITY_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "attempts": attempts,
        "okCount": ok_attempts,
        "verdict": verdict,
        "dominantFailMode": dominant_mode,
        "remediation": REMEDIATION.get(dominant_mode, ""),
        "narrative": narrative,
        "classificationCounts": classification_counts,
        "attemptRecords": attempt_records,
        "reminders": [
            "observation-only; this module never invokes the export shortcut",
            "no recovery actions are issued; allow_recovery is hard-pinned False",
            "cannot promote broker submission authority",
        ],
    }


def stability_text(payload: dict[str, Any]) -> str:
    """Render the stability report into an operator-facing memo."""
    lines = [
        "Inferno TOS Export Stability (observation-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Attempts: {payload.get('attempts')}",
        f"Ok count: {payload.get('okCount')}/{payload.get('attempts')}",
        f"Verdict: {payload.get('verdict')}",
        f"Dominant fail mode: {payload.get('dominantFailMode')}",
        "",
        f"Narrative: {payload.get('narrative')}",
        f"Remediation: {payload.get('remediation')}",
        "",
        "Fail-mode distribution:",
    ]
    counts = payload.get("classificationCounts") or {}
    for mode, count in counts.items():
        if count > 0:
            lines.append(f"- {mode}: {count}")
    lines.append("")
    lines.append("Per-attempt details:")
    for record in payload.get("attemptRecords") or []:
        lines.append(
            f"- #{record.get('index')} "
            f"verdict={record.get('verdict')} | "
            f"failMode={record.get('failMode')} | "
            f"appRunning={record.get('appRunning')} | "
            f"panel={record.get('currentPanel')} | "
            f"safety={record.get('currentPanelSafety')} | "
            f"account={record.get('accountMode')}"
        )
        if record.get("message"):
            lines.append(f"    message: {record.get('message')}")
    lines.extend([
        "",
        "Reminders:",
    ])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_stability_report(payload: dict[str, Any]) -> None:
    """Persist the stability JSON and text artifacts via the retry-safe writer."""
    ensure_dirs()
    atomic_write_json(STABILITY_ARTIFACT_FILE, payload)
    atomic_write_text(STABILITY_TEXT_FILE, stability_text(payload))


def parse_args() -> argparse.Namespace:
    """CLI: stability run [--attempts N] [--backoff-seconds F] | status."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the TOS export verifier multiple times with backoff and "
            "produce a stability verdict + narrative. Observation-only."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--backoff-seconds", type=float, default=1.5)
    return parser.parse_args()


def main() -> int:
    """Entry point: print the latest stability memo."""
    args = parse_args()
    if args.command == "status" and STABILITY_TEXT_FILE.exists():
        print(STABILITY_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_stability_report(
        attempts=args.attempts,
        backoff_seconds=args.backoff_seconds,
    )
    save_stability_report(payload)
    print(stability_text(payload))
    # Exit 0 for stable-ready, transient-recovered, inactive-safe; 1 for blocked.
    return 0 if payload.get("verdict") != "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
