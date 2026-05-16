from __future__ import annotations

"""Inferno Night Prep — confirm the desk is ready for tomorrow morning.

The operator wants to walk away from the keyboard tonight and have the
morning chain pick up cleanly. This diagnostic is the *bedside check*:
walk every layer of the chain, validate it's positioned for the 06:00
dawn cycle + 06:30 daily-loop fires, and emit a single PASS / WARN /
FAIL verdict.

Checks (each maps to one fixed name so the artifact stays stable):

- ``dawn_cycle_agent``        — LaunchAgent for the dawn cycle is loaded
- ``daily_loop_agent``        — LaunchAgent for the daily loop is loaded
- ``watchdog_agent``          — Watchdog LaunchAgent is loaded
- ``ops_maintenance_agent``   — Ops maintenance LaunchAgent is loaded
- ``recent_doctor``           — Doctor artifact is fresh and healthy
- ``recent_ops_maintenance``  — Ops maintenance artifact is fresh
- ``recent_daily_loop``       — Daily loop artifact is fresh
- ``authority_pinned``        — Authority manifest still paper-evidence-only
- ``tos_chain_known``         — TOS export chain artifact exists
- ``cycle_journal_healthy``   — Cycle journal has at least one entry
- ``watchlist_slot_ready``    — Input slot for tomorrow's tickers exists or is creatable
- ``narration_log_healthy``   — Brain narration log exists and has rows

Each check carries a PASS / WARN / FAIL status with a ``detail`` string
and a ``remediation`` string. The top-line ``readyForMorning`` boolean is
TRUE when no check is FAIL.

Strict contract:

- read-only; this module never writes desk state
- writes only to ``data/inferno_night_prep.json`` and
  ``reports/night_prep_latest.txt`` via ``inferno_io`` retry primitives
- ``researchOnly`` / ``promotable=False`` are pinned in the payload
- safe to run any time of day; it's just a snapshot
"""

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


NIGHT_PREP_ARTIFACT_FILE = DATA_DIR / "inferno_night_prep.json"
NIGHT_PREP_TEXT_FILE = REPORTS_DIR / "night_prep_latest.txt"
NIGHT_PREP_STAGE = "night-prep-observation-only"

# Watchlist input slot tomorrow's ingest reads from. Created lazily, so the
# absence of this file is a WARN (we can create it), not a FAIL.
WATCHLIST_INPUT_FILE = DATA_DIR / "inferno_watchlist_input.json"

# Artifact freshness window — anything older than this is flagged stale.
ARTIFACT_STALE_HOURS = 26.0

# LaunchAgent labels we expect to be loaded for tomorrow morning's fires.
EXPECTED_LAUNCH_AGENTS = (
    ("dawn_cycle_agent", "io.diablotrading.inferno-dawn-cycle"),
    ("daily_loop_agent", "io.diablotrading.inferno-daily-loop"),
    ("watchdog_agent", "io.diablotrading.inferno-watchdog"),
    ("ops_maintenance_agent", "io.diablotrading.inferno-ops-maintenance"),
)

# Artifacts we expect to be fresh (i.e. produced within ARTIFACT_STALE_HOURS).
EXPECTED_FRESH_ARTIFACTS = (
    ("recent_doctor", DATA_DIR / "inferno_doctor.json"),
    ("recent_ops_maintenance", DATA_DIR / "inferno_ops_maintenance.json"),
    ("recent_daily_loop", DATA_DIR / "inferno_daily_loop.json"),
)


def _pass(name: str, detail: str = "") -> dict[str, Any]:
    return {"name": name, "status": "pass", "detail": detail, "remediation": ""}


def _warn(name: str, detail: str, remediation: str = "") -> dict[str, Any]:
    return {"name": name, "status": "warn", "detail": detail, "remediation": remediation}


def _fail(name: str, detail: str, remediation: str = "") -> dict[str, Any]:
    return {"name": name, "status": "fail", "detail": detail, "remediation": remediation}


def _launchctl_print(label: str) -> tuple[bool, str]:
    """Return whether the given LaunchAgent is loaded for the current user.

    Wrapped so tests can stub the subprocess without a real launchctl.
    """
    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"launchctl unavailable: {exc}"
    if result.returncode != 0:
        return False, "agent not loaded"
    return True, "agent loaded"


def _launch_agent_check(
    name: str, label: str, launchctl: Callable[[str], tuple[bool, str]]
) -> dict[str, Any]:
    """Single-agent check using the injected launchctl probe."""
    loaded, detail = launchctl(label)
    if loaded:
        return _pass(name, f"{label}: {detail}")
    return _fail(
        name,
        f"{label}: {detail}",
        remediation=(
            f"Reinstall the agent: python3 install_inferno_<service>_service.py install"
        ),
    )


def _artifact_age_hours(path: Path, now: datetime) -> float | None:
    """Return artifact age in hours, or ``None`` when the file is missing."""
    if not path.exists():
        return None
    try:
        mtime_seconds = path.stat().st_mtime
    except OSError:
        return None
    mtime = datetime.fromtimestamp(mtime_seconds, tz=now.tzinfo)
    if mtime.tzinfo and not now.tzinfo:
        mtime = mtime.replace(tzinfo=None)
    elif now.tzinfo and not mtime.tzinfo:
        mtime = mtime.replace(tzinfo=now.tzinfo)
    return (now - mtime).total_seconds() / 3600.0


def _artifact_fresh_check(
    name: str, path: Path, now: datetime
) -> dict[str, Any]:
    """Pass if the artifact exists and is younger than ARTIFACT_STALE_HOURS."""
    age = _artifact_age_hours(path, now)
    if age is None:
        return _fail(
            name,
            f"{path.name} is missing",
            remediation=f"Run the producing module to create {path.name}.",
        )
    if age > ARTIFACT_STALE_HOURS:
        return _warn(
            name,
            f"{path.name} is {age:.1f} hours old",
            remediation="Re-run the producing module if you want a fresher snapshot.",
        )
    return _pass(name, f"{path.name} is {age:.1f} hours old")


def _authority_check(now: datetime) -> dict[str, Any]:
    """Confirm authority manifest still pins paper-evidence-only."""
    path = DATA_DIR / "inferno_authority_manifest.json"
    if not path.exists():
        return _fail(
            "authority_pinned",
            "authority manifest missing",
            remediation="Run python3 inferno_authority_controller.py to materialise it.",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return _fail("authority_pinned", f"manifest unreadable: {exc}")
    decision = payload.get("decision") or {}
    level = decision.get("authorityLevel") or "unknown"
    broker = decision.get("brokerSubmitAllowed")
    live = decision.get("liveTradingAllowed")
    if level != "paper-evidence-only" or broker is True or live is True:
        return _fail(
            "authority_pinned",
            f"unexpected posture: level={level} broker={broker} live={live}",
            remediation=(
                "Authority drifted. Inspect data/inferno_authority_manifest.json "
                "and run the authority controller to restore paper-evidence-only."
            ),
        )
    return _pass(
        "authority_pinned",
        f"level={level} brokerSubmit={broker} liveTrading={live}",
    )


def _tos_chain_known_check(now: datetime) -> dict[str, Any]:
    """Confirm the TOS export chain artifact exists and has a verdict."""
    path = DATA_DIR / "inferno_tos_export_chain.json"
    if not path.exists():
        return _warn(
            "tos_chain_known",
            "tos_export_chain artifact missing",
            remediation="Run python3 inferno_tos_export_chain.py to materialise it.",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return _warn("tos_chain_known", f"chain artifact unreadable: {exc}")
    verdict = payload.get("verdict")
    first_failure = payload.get("firstFailure")
    if verdict == "ready":
        return _pass("tos_chain_known", "chain verdict ready")
    return _warn(
        "tos_chain_known",
        f"chain verdict {verdict} (first failure: {first_failure or 'none'})",
        remediation=(
            "TOS export chain is blocked. The morning ingest doesn't need this "
            "to be ready, but a healthy chain is required when an actual export "
            "fires later."
        ),
    )


def _cycle_journal_check(now: datetime) -> dict[str, Any]:
    """Confirm the cycle journal has at least one historical entry."""
    cycles_root = DATA_DIR / "cycles"
    if not cycles_root.exists():
        return _warn(
            "cycle_journal_healthy",
            "data/cycles/ does not exist yet",
            remediation="Run the daily loop once to create the first journal entry.",
        )
    entries = [path for path in cycles_root.iterdir() if path.is_dir()]
    if not entries:
        return _warn(
            "cycle_journal_healthy",
            "data/cycles/ has no cycle directories yet",
            remediation="Run the daily loop once.",
        )
    return _pass(
        "cycle_journal_healthy",
        f"{len(entries)} cycle(s) on disk",
    )


def _watchlist_slot_check(now: datetime) -> dict[str, Any]:
    """Confirm the watchlist input slot exists or can be created."""
    if WATCHLIST_INPUT_FILE.exists():
        try:
            payload = json.loads(WATCHLIST_INPUT_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return _warn(
                "watchlist_slot_ready",
                f"input slot exists but is unreadable: {exc}",
                remediation=(
                    "Rewrite the file with valid JSON: "
                    '{"tickers": ["..."], "source": "manual"}'
                ),
            )
        count = len(payload.get("tickers") or [])
        return _pass(
            "watchlist_slot_ready",
            f"input slot present with {count} ticker(s)",
        )
    parent = WATCHLIST_INPUT_FILE.parent
    if not parent.exists():
        return _warn(
            "watchlist_slot_ready",
            f"parent directory {parent} does not exist",
            remediation="Create the data/ directory.",
        )
    if not os.access(parent, os.W_OK):
        return _fail(
            "watchlist_slot_ready",
            f"parent directory {parent} is not writable",
            remediation="Fix permissions on the data directory.",
        )
    return _warn(
        "watchlist_slot_ready",
        "input slot does not exist yet (will be created tomorrow)",
        remediation=(
            "Tomorrow morning, run: "
            "echo '{\"tickers\": [...]}' > data/inferno_watchlist_input.json"
        ),
    )


def _narration_log_check(now: datetime) -> dict[str, Any]:
    """Confirm the brain narration log exists and has at least one row."""
    path = DATA_DIR / "inferno_brain_narrations.jsonl"
    if not path.exists():
        return _warn(
            "narration_log_healthy",
            "narration log missing",
            remediation="Run the daily loop once to produce the first row.",
        )
    try:
        line_count = sum(1 for _ in path.read_text(encoding="utf-8").splitlines() if _.strip())
    except OSError as exc:
        return _warn("narration_log_healthy", f"unreadable: {exc}")
    if line_count == 0:
        return _warn(
            "narration_log_healthy",
            "narration log exists but is empty",
            remediation="Run the daily loop once.",
        )
    return _pass(
        "narration_log_healthy",
        f"{line_count} narration row(s) on disk",
    )


def build_night_prep(
    *,
    now: datetime | None = None,
    launchctl: Callable[[str], tuple[bool, str]] | None = None,
) -> dict[str, Any]:
    """Run every check and assemble the night-prep payload.

    ``launchctl`` is injectable so tests can stub the subprocess call.
    """
    now = now or local_now()
    launchctl = launchctl or _launchctl_print

    checks: list[dict[str, Any]] = []

    for name, label in EXPECTED_LAUNCH_AGENTS:
        checks.append(_launch_agent_check(name, label, launchctl))

    for name, path in EXPECTED_FRESH_ARTIFACTS:
        checks.append(_artifact_fresh_check(name, path, now))

    checks.append(_authority_check(now))
    checks.append(_tos_chain_known_check(now))
    checks.append(_cycle_journal_check(now))
    checks.append(_watchlist_slot_check(now))
    checks.append(_narration_log_check(now))

    pass_count = sum(1 for check in checks if check["status"] == "pass")
    warn_count = sum(1 for check in checks if check["status"] == "warn")
    fail_count = sum(1 for check in checks if check["status"] == "fail")

    ready_for_morning = fail_count == 0
    if fail_count > 0:
        verdict = "blocked"
        narrative = (
            f"{fail_count} hard failure(s) block tomorrow morning. "
            "Resolve them tonight; do not assume the morning fire will recover."
        )
    elif warn_count > 0:
        verdict = "warming"
        narrative = (
            f"All required layers pass, but {warn_count} warning(s) are worth "
            "noting. Morning fires should still succeed."
        )
    else:
        verdict = "ready"
        narrative = (
            "Every overnight layer is ready. Tomorrow morning is a "
            "one-command operation: drop tickers into "
            "data/inferno_watchlist_input.json and run the ingest."
        )

    return {
        "generatedAt": now.isoformat(),
        "stage": NIGHT_PREP_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "readyForMorning": ready_for_morning,
        "passCount": pass_count,
        "warnCount": warn_count,
        "failCount": fail_count,
        "checkCount": len(checks),
        "checks": checks,
        "watchlistInputFile": str(WATCHLIST_INPUT_FILE),
        "staleAfterHours": ARTIFACT_STALE_HOURS,
        "reminders": [
            "observation-only; this diagnostic never writes desk state",
            "rerun any time of day; it's a fresh snapshot each call",
            "operator should clear FAILs tonight, WARNs are advisory",
        ],
    }


def night_prep_text(payload: dict[str, Any]) -> str:
    """Render the night-prep payload into an operator memo."""
    lines = [
        "Inferno Night Prep (observation-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Verdict: {payload.get('verdict')}",
        f"Ready for morning: {payload.get('readyForMorning')}",
        f"Pass / warn / fail: "
        f"{payload.get('passCount')} / "
        f"{payload.get('warnCount')} / "
        f"{payload.get('failCount')} "
        f"(total {payload.get('checkCount')})",
        "",
        f"Narrative: {payload.get('narrative')}",
        "",
        f"Watchlist input slot: {payload.get('watchlistInputFile')}",
        f"Stale-after threshold: {payload.get('staleAfterHours')}h",
        "",
        "Checks:",
    ]
    for check in payload.get("checks") or []:
        marker = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}.get(
            check.get("status"), "?"
        )
        lines.append(f"- [{marker}] {check.get('name'):<24} {check.get('detail') or ''}")
        if check.get("status") in {"warn", "fail"} and check.get("remediation"):
            lines.append(f"    remediation: {check.get('remediation')}")
    lines.extend([
        "",
        "Reminders:",
    ])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_night_prep(payload: dict[str, Any]) -> None:
    """Persist the night-prep JSON and text artifacts."""
    ensure_dirs()
    atomic_write_json(NIGHT_PREP_ARTIFACT_FILE, payload)
    atomic_write_text(NIGHT_PREP_TEXT_FILE, night_prep_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Confirm every overnight layer is ready for tomorrow morning. "
            "Observation-only; never writes desk state."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and NIGHT_PREP_TEXT_FILE.exists():
        print(NIGHT_PREP_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_night_prep()
    save_night_prep(payload)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(night_prep_text(payload))
    # Exit 0 unless we're FAIL — WARN is informational and shouldn't fail the
    # verify script.
    return 0 if payload.get("readyForMorning") else 1


if __name__ == "__main__":
    raise SystemExit(main())
