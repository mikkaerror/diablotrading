from __future__ import annotations

"""Shared reporting language for the Inferno desk.

This module keeps the morning brief, twice-daily action pulses, live sync, and
command center speaking from the same operating picture. It is intentionally
read-only: the helpers only inspect local artifacts and process state, then
return small dictionaries/strings for report renderers.

Safety contract:
- never opens thinkorswim
- never clicks, types, or submits broker actions
- never reads or prints secrets
- treats hidden TOS windows as an attach/visibility issue, not permission to
  launch a new broker instance
"""

import json
import subprocess
from datetime import datetime, time
from pathlib import Path
from typing import Any

from inferno_config import TOS_PROCESS_CANDIDATES, local_now
from server import DATA_DIR, LOG_FILE, REPORTS_DIR, SNAPSHOT_FILE


TRACKER_SNAPSHOT_FILE = SNAPSHOT_FILE
SCHWAB_OPTIONS_FILE = DATA_DIR / "inferno_schwab_options.json"
SCHWAB_DAILY_OPS_FILE = DATA_DIR / "inferno_schwab_daily_ops.json"
SCHWAB_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_schwab_account_sync.json"
LIVE_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_live_account_sync.json"
TOS_SESSION_PROBE_FILE = DATA_DIR / "inferno_tos_session_probe.json"
TOS_EXPORT_VERIFIER_FILE = DATA_DIR / "inferno_tos_export_verifier.json"
ACTION_PULSE_FILE = DATA_DIR / "inferno_action_pulse.json"
DOCTOR_TEXT_FILE = REPORTS_DIR / "doctor_latest.txt"
MORNING_BRIEF_TEXT_FILE = REPORTS_DIR / "morning_brief_latest.txt"

MARKET_OPEN_TAPE_READY_LOCAL = time(7, 35)
MARKET_OPEN_TAPE_MIN_TIMESTAMP_LOCAL = time(7, 30)


def text(value: Any, default: str = "") -> str:
    """Normalize loose artifact values into trimmed display text."""
    if value is None:
        return default
    rendered = str(value).strip()
    return rendered or default


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON artifact without raising on missing or malformed files."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - reports must fail soft
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_timestamp(raw: Any) -> datetime | None:
    """Parse the timestamp formats used across Inferno artifacts."""
    rendered = text(raw)
    if not rendered:
        return None
    try:
        return datetime.fromisoformat(rendered.replace("Z", "+00:00"))
    except ValueError:
        return None


def live_account_source_timestamp(payload: dict[str, Any]) -> str | None:
    """Return the timestamp of the broker data, not the wrapper rebuild."""
    source = text(payload.get("accountDataSource")).lower()
    keys = (
        ("schwabAccountGeneratedAt", "statementGeneratedAt", "generatedAt")
        if source == "schwab-account-api"
        else ("statementGeneratedAt", "generatedAt")
    )
    for key in keys:
        if text(payload.get(key)):
            return text(payload.get(key))
    return None


def artifact_generated_at(path: Path) -> str | None:
    """Return the best available timestamp for a JSON or text artifact."""
    payload = load_json(path)
    if path == LIVE_ACCOUNT_SYNC_FILE:
        source_timestamp = live_account_source_timestamp(payload)
        if source_timestamp:
            return source_timestamp
    for key in ("generatedAt", "checkedAt", "sentAt", "timestamp"):
        if text(payload.get(key)):
            return text(payload.get(key))
    if not path.exists():
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=local_now().tzinfo).isoformat()
    except OSError:
        return None


def age_hours(timestamp: str | None, *, now: datetime | None = None) -> float | None:
    """Return artifact age in hours, or None when the timestamp is unknown."""
    parsed = parse_timestamp(timestamp)
    if parsed is None:
        return None
    current = now or local_now()
    if parsed.tzinfo is None and current.tzinfo is not None:
        parsed = parsed.replace(tzinfo=current.tzinfo)
    return max((current - parsed).total_seconds() / 3600.0, 0.0)


def freshness_status(timestamp: str | None, *, max_age_hours: float, now: datetime | None = None) -> str:
    """Classify whether an artifact is fresh enough for operator reporting."""
    age = age_hours(timestamp, now=now)
    if age is None:
        return "missing"
    if age <= max_age_hours:
        return "fresh"
    return "stale"


def market_open_options_status(timestamp: str | None, *, now: datetime | None = None) -> str:
    """Require same-session Schwab options tape after the market-open refresh window."""
    current = now or local_now()
    if current.timetz().replace(tzinfo=None) < MARKET_OPEN_TAPE_READY_LOCAL:
        return freshness_status(timestamp, max_age_hours=18, now=current)
    parsed = parse_timestamp(timestamp)
    if parsed is None:
        return "missing"
    if parsed.tzinfo is None and current.tzinfo is not None:
        parsed = parsed.replace(tzinfo=current.tzinfo)
    elif parsed.tzinfo is not None and current.tzinfo is not None:
        parsed = parsed.astimezone(current.tzinfo)
    if parsed.date() != current.date():
        return "stale"
    if parsed.timetz().replace(tzinfo=None) < MARKET_OPEN_TAPE_MIN_TIMESTAMP_LOCAL:
        return "stale"
    if (age_hours(timestamp, now=current) or 0.0) > 2:
        return "stale"
    return "fresh"


def latest_morning_email_event(log_file: Path = LOG_FILE) -> dict[str, Any]:
    """Return the latest morning brief log row without exposing email secrets."""
    if not log_file.exists():
        return {}
    latest: dict[str, Any] = {}
    try:
        lines = log_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in lines[-80:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("job") != "morning_inferno_pipeline":
            continue
        latest = row
    return latest


def _freshness_entry(
    label: str,
    path: Path,
    *,
    max_age_hours: float,
    timestamp: str | None = None,
    now: datetime | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Build one compact freshness row for reports."""
    generated_at = timestamp or artifact_generated_at(path)
    age = age_hours(generated_at, now=now)
    return {
        "label": label,
        "path": str(path),
        "generatedAt": generated_at,
        "ageHours": round(age, 2) if age is not None else None,
        "status": status or freshness_status(generated_at, max_age_hours=max_age_hours, now=now),
    }


def build_freshness_panel(*, now: datetime | None = None) -> dict[str, Any]:
    """Build the shared freshness panel for command-center and email reports."""
    current = now or local_now()
    morning_event = latest_morning_email_event()
    schwab_options_timestamp = artifact_generated_at(SCHWAB_OPTIONS_FILE)
    schwab_daily_ops_timestamp = artifact_generated_at(SCHWAB_DAILY_OPS_FILE)
    rows = [
        _freshness_entry("tracker snapshot", TRACKER_SNAPSHOT_FILE, max_age_hours=18, now=current),
        _freshness_entry(
            "Schwab options tape",
            SCHWAB_OPTIONS_FILE,
            max_age_hours=18,
            timestamp=schwab_options_timestamp,
            now=current,
            status=market_open_options_status(schwab_options_timestamp, now=current),
        ),
        _freshness_entry(
            "Schwab daily ops",
            SCHWAB_DAILY_OPS_FILE,
            max_age_hours=18,
            timestamp=schwab_daily_ops_timestamp,
            now=current,
            status=market_open_options_status(schwab_daily_ops_timestamp, now=current),
        ),
        _freshness_entry("Schwab account sync", SCHWAB_ACCOUNT_SYNC_FILE, max_age_hours=8, now=current),
        _freshness_entry("live account sync", LIVE_ACCOUNT_SYNC_FILE, max_age_hours=8, now=current),
        _freshness_entry("doctor", DOCTOR_TEXT_FILE, max_age_hours=8, now=current),
        _freshness_entry(
            "morning email",
            MORNING_BRIEF_TEXT_FILE,
            max_age_hours=30,
            timestamp=text(morning_event.get("generatedAt")) or None,
            now=current,
        ),
        _freshness_entry("last TOS probe", TOS_SESSION_PROBE_FILE, max_age_hours=8, now=current),
        _freshness_entry("action pulse", ACTION_PULSE_FILE, max_age_hours=8, now=current),
    ]
    stale = [row for row in rows if row["status"] == "stale"]
    missing = [row for row in rows if row["status"] == "missing"]
    return {
        "generatedAt": current.isoformat(),
        "rows": rows,
        "staleCount": len(stale),
        "missingCount": len(missing),
        "ok": not stale and not missing,
        "latestMorningEmailSent": bool(morning_event.get("emailSent")),
        "latestMorningEmailAt": morning_event.get("generatedAt"),
    }


def render_freshness_lines(panel: dict[str, Any] | None = None) -> list[str]:
    """Render freshness rows into concise bullet lines."""
    payload = panel or build_freshness_panel()
    lines: list[str] = []
    for row in payload.get("rows") or []:
        age = row.get("ageHours")
        age_text = f"{age:.2f}h old" if isinstance(age, (int, float)) else "age unknown"
        lines.append(f"{row.get('label')}: {row.get('status')} | {row.get('generatedAt') or '-'} | {age_text}")
    return lines


def _process_running(candidates: list[str]) -> tuple[bool | None, str | None]:
    """Check whether a TOS process exists without launching or activating it."""
    for candidate in candidates:
        name = text(candidate)
        if not name:
            continue
        result = subprocess.run(
            ["pgrep", "-if", name],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0 and text(result.stdout):
            return True, name
    return False, None


def build_tos_visibility_summary() -> dict[str, Any]:
    """Summarize TOS process/window state using attach-only evidence."""
    probe = load_json(TOS_SESSION_PROBE_FILE)
    verifier = load_json(TOS_EXPORT_VERIFIER_FILE)
    process_running, matched_process = _process_running(list(TOS_PROCESS_CANDIDATES))
    if process_running is False and verifier.get("appRunning") is True:
        # Keep older verifier evidence if pgrep misses a wrapped Java process.
        process_running = True
    main_window_present = bool(probe.get("mainWindowPresent"))
    probe_message = text(probe.get("summary") or probe.get("message"))

    if main_window_present:
        level = "visible"
        message = "TOS existing window is visible to the attach-only probe."
    elif process_running:
        level = "running-not-visible"
        message = (
            "TOS is running, but no main window is visible to the attach-only probe; "
            "reveal the existing TOS window before any fresh broker scrape."
        )
    elif process_running is False:
        level = "not-running"
        message = "TOS is not running or not visible; open it manually only when broker capture is needed."
    else:
        level = "unknown"
        message = "TOS visibility is unknown; attach-only automation remains fail-closed."

    return {
        "level": level,
        "message": message,
        "appRunning": bool(process_running),
        "matchedProcessName": probe.get("matchedProcessName") or matched_process,
        "mainWindowPresent": main_window_present,
        "frontmostApp": probe.get("frontmostApp"),
        "probeSummary": probe_message,
        "generatedAt": local_now().isoformat(),
    }


def render_tos_visibility_line(summary: dict[str, Any] | None = None) -> str:
    """Render the TOS attach-only status as one report-safe sentence."""
    payload = summary or build_tos_visibility_summary()
    return text(payload.get("message"), "TOS visibility unknown; attach-only automation remains fail-closed.")


def normalize_tos_fallback_message(raw: Any, summary: dict[str, Any] | None = None) -> str:
    """Convert low-level TOS fallback strings into operator-safe language."""
    rendered = text(raw)
    tos_summary = summary or build_tos_visibility_summary()
    lowered = rendered.lower()
    if "not visible" in lowered or "no visible" in lowered or "window" in lowered:
        return render_tos_visibility_line(tos_summary)
    return rendered


def sanitize_tos_language(narrative: Any, summary: dict[str, Any] | None = None) -> str:
    """Replace stale closed-TOS wording with the current attach-only status."""
    rendered = text(narrative)
    if not rendered:
        return ""
    stale = (
        "TOS is intentionally closed for low-performance mode; open it only "
        "for supervised export or manual order staging."
    )
    if stale not in rendered:
        return rendered
    return rendered.replace(stale, render_tos_visibility_line(summary))
