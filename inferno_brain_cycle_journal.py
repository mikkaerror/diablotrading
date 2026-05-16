from __future__ import annotations

"""Inferno Brain Cycle Journal — freeze every cycle's artifacts for replay.

The daily loop produces 13 reports per fire. Each report is overwritten the
next time the loop runs. That means yesterday's brain state is gone the
moment today's fires.

The cycle journal solves that by snapshotting every key artifact into a
timestamped directory at the end of each daily-loop run. After 90 cycles
the oldest are pruned automatically, so the journal stays bounded (~45
weekday days at twice-per-day cadence).

The result is a *time machine* for the brain. You can run:

::

    ls data/cycles/
    cat data/cycles/2026-05-11-0630/narrative.txt
    diff data/cycles/2026-05-10-1630/hypothesis_lab.json \\
         data/cycles/2026-05-11-0630/hypothesis_lab.json

and see exactly what the brain knew and thought at any point in the
recent past.

Strict contract:
- read-only with respect to the source artifacts; we *copy* them, we
  never modify them
- writes only into ``data/cycles/<cycle-id>/`` and ``reports/cycle_journal_latest.txt``
- pruning is delete-only on directories *inside* ``data/cycles/`` whose
  names match the ``YYYY-MM-DD-HHMM`` pattern; nothing else can be
  removed
- self-bounding: ``MAX_CYCLES`` rows on disk at any time
"""

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from inferno_config import local_now
from inferno_io import atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


CYCLES_ROOT = DATA_DIR / "cycles"
CYCLE_TEXT_FILE = REPORTS_DIR / "cycle_journal_latest.txt"
CYCLE_JOURNAL_STAGE = "brain-cycle-journal-research-only"

# Maximum number of cycle directories we keep. Older ones are pruned.
MAX_CYCLES = 90

# Files we snapshot from data/. Each entry is (source-name, target-name).
# Target names are deliberately shorter than the originals so the cycle
# directory listing reads cleanly.
SNAPSHOT_TARGETS: tuple[tuple[str, str], ...] = (
    ("inferno_daily_loop.json",           "daily_loop.json"),
    ("inferno_approval_cadence.json",     "approval_cadence.json"),
    ("inferno_decision_brief.json",       "decision_briefs.json"),
    ("inferno_promotion_gap.json",        "promotion_gap.json"),
    ("inferno_threshold_sensitivity.json","threshold_sensitivity.json"),
    ("inferno_strategy_replay.json",      "strategy_replay.json"),
    ("inferno_daily_success.json",        "daily_success.json"),
    ("inferno_tos_export_stability.json", "tos_export_stability.json"),
    ("inferno_skills_audit.json",         "skills_audit.json"),
    ("inferno_heartbeat.json",            "heartbeat.json"),
    ("inferno_theme_synthesizer.json",    "theme_synthesizer.json"),
    ("inferno_hypothesis_lab.json",       "hypothesis_lab.json"),
    ("inferno_hypothesis_ledger.json",    "hypothesis_ledger.json"),
    ("inferno_model_command_center.json", "command_center.json"),
)

# Anchored regex for the cycle-id directory format. Used both for naming
# new cycles and for pruning *only* directories created by this module.
CYCLE_ID_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{4}$")


def cycle_id_for(now: datetime) -> str:
    """Return the ``YYYY-MM-DD-HHMM`` directory name for the given timestamp."""
    return now.strftime("%Y-%m-%d-%H%M")


def _safe_copy(source: Path, target: Path) -> bool:
    """Copy ``source`` to ``target`` if source exists. Return True on success."""
    if not source.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, target)
    except OSError:
        return False
    return True


def _existing_cycle_dirs(root: Path) -> list[Path]:
    """Return the cycle directories sorted oldest first, ignoring strays."""
    if not root.exists():
        return []
    found: list[Path] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if not CYCLE_ID_PATTERN.match(entry.name):
            continue
        found.append(entry)
    found.sort(key=lambda p: p.name)
    return found


def _prune_old_cycles(root: Path, max_keep: int) -> list[str]:
    """Delete oldest cycle directories until at most ``max_keep`` remain."""
    cycles = _existing_cycle_dirs(root)
    if len(cycles) <= max_keep:
        return []
    to_remove = cycles[: len(cycles) - max_keep]
    pruned: list[str] = []
    for path in to_remove:
        try:
            shutil.rmtree(path)
            pruned.append(path.name)
        except OSError:
            # Best-effort prune; we'd rather skip a stuck directory than
            # crash the daily loop.
            continue
    return pruned


def snapshot_cycle(
    *,
    now: datetime | None = None,
    cycles_root: Path | None = None,
    targets: Iterable[tuple[str, str]] | None = None,
    source_dir: Path | None = None,
    narrative: str | None = None,
    max_cycles: int = MAX_CYCLES,
) -> dict[str, Any]:
    """Snapshot the current artifact set into a new cycle directory.

    All parameters are injectable for tests; the production call site uses
    the defaults from ``inferno_daily_loop.py``.
    """
    now = now or local_now()
    cycles_root = cycles_root or CYCLES_ROOT
    targets = list(targets) if targets is not None else list(SNAPSHOT_TARGETS)
    source_dir = source_dir or DATA_DIR

    cycle_dir = cycles_root / cycle_id_for(now)
    cycle_dir.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    missing: list[str] = []
    for source_name, target_name in targets:
        ok = _safe_copy(source_dir / source_name, cycle_dir / target_name)
        if ok:
            copied.append(target_name)
        else:
            missing.append(source_name)

    if narrative:
        atomic_write_text(cycle_dir / "narrative.txt", narrative + "\n")

    # Drop a small manifest into the cycle dir so an operator who finds it
    # later can identify its provenance.
    manifest = {
        "cycleId": cycle_id_for(now),
        "snapshotAt": now.isoformat(),
        "stage": CYCLE_JOURNAL_STAGE,
        "copied": copied,
        "missing": missing,
        "maxCycles": max_cycles,
    }
    atomic_write_text(cycle_dir / "manifest.json", json.dumps(manifest, indent=2))

    pruned = _prune_old_cycles(cycles_root, max_cycles)

    return {
        "generatedAt": now.isoformat(),
        "stage": CYCLE_JOURNAL_STAGE,
        "cycleId": cycle_id_for(now),
        "cycleDirectory": str(cycle_dir),
        "copied": copied,
        "missing": missing,
        "pruned": pruned,
        "totalCyclesOnDisk": len(_existing_cycle_dirs(cycles_root)),
        "maxCycles": max_cycles,
        "reminders": [
            "research-only; never mutates source artifacts",
            "older cycles are pruned automatically",
            "narrative.txt holds the operator-facing memo for the cycle",
        ],
    }


def journal_text(payload: dict[str, Any]) -> str:
    """Render a small operator memo summarising the latest snapshot."""
    lines = [
        "Inferno Brain Cycle Journal",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Cycle id: {payload.get('cycleId')}",
        f"Cycle dir: {payload.get('cycleDirectory')}",
        f"Snapshots copied: {len(payload.get('copied') or [])}",
        f"Sources missing: {len(payload.get('missing') or [])}",
        f"Cycles on disk: {payload.get('totalCyclesOnDisk')} / max {payload.get('maxCycles')}",
    ]
    pruned = payload.get("pruned") or []
    if pruned:
        lines.append(f"Pruned cycles: {', '.join(pruned)}")
    missing = payload.get("missing") or []
    if missing:
        lines.append("")
        lines.append("Missing source artifacts:")
        for name in missing:
            lines.append(f"- {name}")
    lines.extend([
        "",
        "Reminders:",
    ])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_journal_memo(payload: dict[str, Any]) -> None:
    """Persist the latest cycle-journal memo to reports/."""
    ensure_dirs()
    atomic_write_text(CYCLE_TEXT_FILE, journal_text(payload))


def list_cycles(*, cycles_root: Path | None = None) -> list[str]:
    """Return the cycle ids on disk, oldest first."""
    return [path.name for path in _existing_cycle_dirs(cycles_root or CYCLES_ROOT)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Snapshot the current brain artifacts into a per-cycle directory, "
            "or list / inspect existing cycles. Research-only."
        )
    )
    sub = parser.add_subparsers(dest="command", required=False)
    sub.add_parser("snapshot", help="Take a snapshot of the current artifacts")
    sub.add_parser("list", help="List cycle ids currently on disk")
    sub.add_parser("status", help="Print the last persisted journal memo")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command = args.command or "snapshot"
    if command == "list":
        for cycle_id in list_cycles():
            print(cycle_id)
        return 0
    if command == "status" and CYCLE_TEXT_FILE.exists():
        print(CYCLE_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = snapshot_cycle()
    save_journal_memo(payload)
    print(journal_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
