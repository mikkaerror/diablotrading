from __future__ import annotations

"""Central liveness ledger for the Inferno desk.

Every scheduled subsystem (dawn cycle, ops maintenance, daily loop, watchdog,
TOS session probe) can call ``record_heartbeat(name, status, summary)`` to
write a tiny row into ``data/inferno_heartbeat.json``. The daily loop then
reads the ledger and reports which subsystems are still beating and which
have gone quiet.

Why a separate file instead of reusing the watchdog?

- The watchdog already exists, but it cares about *failures* and dispatches
  alerts. Heartbeat is the inverse: it cares about *presence* and produces a
  living-and-breathing view of the desk over time.
- A subsystem can be healthy in the watchdog sense and still be missing here
  if it never ran. That distinction matters for "did the LaunchAgent actually
  fire today?" questions.

Contract:
- read-only with respect to authority; cannot change desk state.
- atomic-ish writes via a temp file + rename, so a race between two writers
  cannot truncate the ledger.
- self-pruning: only the most recent ``MAX_RECORDS_PER_SOURCE`` rows per
  subsystem are kept, so the ledger does not grow unbounded.
"""

import argparse
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


HEARTBEAT_ARTIFACT_FILE = DATA_DIR / "inferno_heartbeat.json"
HEARTBEAT_TEXT_FILE = REPORTS_DIR / "heartbeat_latest.txt"
HEARTBEAT_STAGE = "heartbeat-liveness-ledger"

# Maximum number of records to keep per subsystem. Older rows are pruned so
# the JSON stays under a few KB even after months of operation.
MAX_RECORDS_PER_SOURCE: int = 50

# How long a subsystem can stay silent before we call it "stale". This is
# deliberately generous because some subsystems only fire once per weekday.
STALE_AFTER_HOURS: float = 36.0

# How long until we call a subsystem "silent" (probably forgotten or broken).
SILENT_AFTER_HOURS: float = 96.0

# Allowed status values. ``ok`` is the happy path. ``warn`` is degraded but
# alive. ``fail`` is broken. ``inactive`` is a deliberate not-running state
# (e.g. weekend, market closed). Anything else is coerced to ``unknown``.
ALLOWED_STATUSES = ("ok", "warn", "fail", "inactive", "unknown")


def _coerce_status(status: str | None) -> str:
    """Normalise an arbitrary status string into the allowed set."""
    raw = (status or "").strip().lower()
    return raw if raw in ALLOWED_STATUSES else "unknown"


def _load_existing_ledger() -> dict[str, Any]:
    """Read the existing ledger, tolerating a missing or corrupt file."""
    if not HEARTBEAT_ARTIFACT_FILE.exists():
        return {"records": []}
    try:
        payload = json.loads(HEARTBEAT_ARTIFACT_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"records": []}
    if not isinstance(payload, dict):
        return {"records": []}
    records = payload.get("records")
    if not isinstance(records, list):
        return {"records": []}
    return payload


def _prune_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the most recent ``MAX_RECORDS_PER_SOURCE`` rows per source."""
    by_source: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        source = str(record.get("source") or "unknown")
        by_source.setdefault(source, []).append(record)
    pruned: list[dict[str, Any]] = []
    for source, items in by_source.items():
        items.sort(key=lambda r: str(r.get("at") or ""))
        pruned.extend(items[-MAX_RECORDS_PER_SOURCE:])
    pruned.sort(key=lambda r: str(r.get("at") or ""))
    return pruned


def _atomic_write(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` via a temp file + rename.

    The temp file is created in the same directory so the rename stays inside
    a single filesystem and remains atomic on macOS.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    except Exception:
        # Best-effort cleanup; the rename never happened.
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def record_heartbeat(
    source: str,
    *,
    status: str = "ok",
    summary: str | None = None,
    detail: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Append a heartbeat row for ``source`` and return the persisted record."""
    if not source or not isinstance(source, str):
        raise ValueError("heartbeat source must be a non-empty string")

    ensure_dirs()
    payload = _load_existing_ledger()
    records: list[dict[str, Any]] = list(payload.get("records") or [])

    timestamp = now or local_now()
    record = {
        "source": source.strip(),
        "status": _coerce_status(status),
        "summary": (summary or "").strip() or None,
        "at": timestamp.isoformat(),
        "detail": detail or {},
    }
    records.append(record)
    pruned = _prune_records(records)

    out_payload = {
        "stage": HEARTBEAT_STAGE,
        "updatedAt": timestamp.isoformat(),
        "records": pruned,
    }
    atomic_write_json(HEARTBEAT_ARTIFACT_FILE, out_payload)
    return record


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _latest_per_source(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        source = str(record.get("source") or "unknown")
        candidate_at = _parse_iso(str(record.get("at") or ""))
        if candidate_at is None:
            continue
        current = latest.get(source)
        if current is None:
            latest[source] = record
            continue
        current_at = _parse_iso(str(current.get("at") or ""))
        if current_at is None or candidate_at > current_at:
            latest[source] = record
    return latest


def _classify_age(record: dict[str, Any], now: datetime) -> tuple[str, float | None]:
    """Return ``(freshness, hours_since)`` for a latest-per-source record."""
    at = _parse_iso(str(record.get("at") or ""))
    if at is None:
        return "unknown", None
    # If timestamps disagree on tz-awareness, force both to naive to compare.
    if at.tzinfo and not now.tzinfo:
        at = at.replace(tzinfo=None)
    elif now.tzinfo and not at.tzinfo:
        at = at.replace(tzinfo=now.tzinfo)
    delta = now - at
    hours = delta.total_seconds() / 3600.0
    if hours < 0:
        return "fresh", hours
    if hours < STALE_AFTER_HOURS:
        return "fresh", hours
    if hours < SILENT_AFTER_HOURS:
        return "stale", hours
    return "silent", hours


def build_heartbeat_report(
    expected_sources: Iterable[str] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Summarise the ledger into a desk-wide liveness verdict.

    ``expected_sources`` is the operator-curated list of subsystems we *expect*
    to be beating. A source missing from the ledger but present here lands in
    the ``missingExpected`` bucket — that's how we surface "the dawn cycle
    forgot to fire today" without the watchdog needing to know.
    """
    payload = _load_existing_ledger()
    records = list(payload.get("records") or [])
    now = now or local_now()

    latest = _latest_per_source(records)
    fresh: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    silent: list[dict[str, Any]] = []
    inactive: list[dict[str, Any]] = []

    for source, record in sorted(latest.items()):
        freshness, hours = _classify_age(record, now)
        row = {
            "source": source,
            "status": record.get("status"),
            "summary": record.get("summary"),
            "at": record.get("at"),
            "hoursSince": round(hours, 2) if hours is not None else None,
            "freshness": freshness,
        }
        if record.get("status") == "inactive":
            inactive.append(row)
            continue
        if freshness == "fresh":
            fresh.append(row)
        elif freshness == "stale":
            stale.append(row)
        else:
            silent.append(row)

    expected_list = sorted(set((source or "").strip() for source in (expected_sources or []) if source))
    missing_expected = [source for source in expected_list if source not in latest]

    if silent or missing_expected:
        verdict = "silent"
    elif stale:
        verdict = "stale"
    else:
        verdict = "alive"

    return {
        "generatedAt": now.isoformat(),
        "stage": HEARTBEAT_STAGE,
        "diagnosticOnly": True,
        "verdict": verdict,
        "totalSources": len(latest),
        "freshCount": len(fresh),
        "staleCount": len(stale),
        "silentCount": len(silent),
        "inactiveCount": len(inactive),
        "missingExpected": missing_expected,
        "expectedSources": expected_list,
        "fresh": fresh,
        "stale": stale,
        "silent": silent,
        "inactive": inactive,
        "staleAfterHours": STALE_AFTER_HOURS,
        "silentAfterHours": SILENT_AFTER_HOURS,
        "reminders": [
            "diagnostic only; cannot change desk state",
            "subsystems write their own heartbeat rows; this module only summarises",
        ],
    }


def heartbeat_text(payload: dict[str, Any]) -> str:
    """Render the heartbeat summary into an operator memo."""
    lines = [
        "Inferno Heartbeat (liveness ledger)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Total sources: {payload.get('totalSources')} "
        f"(fresh {payload.get('freshCount')} | "
        f"stale {payload.get('staleCount')} | "
        f"silent {payload.get('silentCount')} | "
        f"inactive {payload.get('inactiveCount')})",
        f"Thresholds: stale > {payload.get('staleAfterHours')}h | "
        f"silent > {payload.get('silentAfterHours')}h",
    ]
    missing = payload.get("missingExpected") or []
    if missing:
        lines.append(f"Missing expected sources: {', '.join(missing)}")

    def _section(title: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        lines.append("")
        lines.append(f"{title}:")
        for row in rows:
            lines.append(
                f"- {row.get('source'):<28} status={row.get('status')} | "
                f"freshness={row.get('freshness')} | "
                f"age={row.get('hoursSince')}h | "
                f"summary={row.get('summary') or '-'}"
            )

    _section("Fresh", payload.get("fresh") or [])
    _section("Stale", payload.get("stale") or [])
    _section("Silent", payload.get("silent") or [])
    _section("Inactive", payload.get("inactive") or [])
    lines.extend([
        "",
        "Reminders:",
    ])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_heartbeat_report(payload: dict[str, Any]) -> None:
    """Persist the rendered heartbeat memo (the JSON ledger writes itself)."""
    ensure_dirs()
    atomic_write_text(HEARTBEAT_TEXT_FILE, heartbeat_text(payload))


def _default_expected_sources() -> list[str]:
    """The operator-curated list of subsystems we expect to be beating."""
    return [
        "ops_maintenance",
        "daily_loop",
        "watchdog",
        "tos_session_probe",
    ]


def parse_args() -> argparse.Namespace:
    """CLI: heartbeat record | summary | status."""
    parser = argparse.ArgumentParser(
        description=(
            "Record a heartbeat or summarise the desk liveness ledger. "
            "Diagnostic only; cannot change desk state."
        )
    )
    sub = parser.add_subparsers(dest="command", required=False)

    record_p = sub.add_parser("record", help="Append a heartbeat row")
    record_p.add_argument("source")
    record_p.add_argument("--status", default="ok")
    record_p.add_argument("--summary", default=None)

    summary_p = sub.add_parser("summary", help="Render the ledger summary memo")
    summary_p.add_argument(
        "--expected",
        nargs="*",
        default=None,
        help="Override the default expected-sources list",
    )

    sub.add_parser("status", help="Print the last persisted summary memo")

    return parser.parse_args()


def main() -> int:
    """CLI entrypoint."""
    args = parse_args()
    command = args.command or "summary"
    if command == "record":
        record_heartbeat(args.source, status=args.status, summary=args.summary)
        print(f"Heartbeat recorded for {args.source} ({args.status}).")
        return 0
    if command == "status" and HEARTBEAT_TEXT_FILE.exists():
        print(HEARTBEAT_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    expected = getattr(args, "expected", None) or _default_expected_sources()
    payload = build_heartbeat_report(expected_sources=expected)
    save_heartbeat_report(payload)
    print(heartbeat_text(payload))
    return 0 if payload.get("verdict") != "silent" else 1


if __name__ == "__main__":
    raise SystemExit(main())
