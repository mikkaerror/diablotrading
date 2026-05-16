from __future__ import annotations

"""Stale-skill auditor for the Inferno desk.

The desk has accreted 40+ Python modules and shell wrappers. Some of them
fire daily, some weekly, some only when an operator pokes them. There is no
"are these still running?" radar. This module is that radar.

Approach:
1. Walk ``ROOT`` for ``inferno_*.py`` modules and ``run_inferno_*.sh``
   wrappers. Skip tests, backups, and the audit module itself.
2. For each candidate, find its newest related artifact in ``data/`` or
   ``reports/`` by matching prefix (e.g. ``inferno_doctor.py`` matches
   ``data/inferno_doctor.json`` and ``reports/doctor_latest.txt``).
3. Classify each skill by age:
   - ``fresh``  : the artifact is newer than ``STALE_AFTER_HOURS``
   - ``stale``  : older than ``STALE_AFTER_HOURS`` but newer than
                  ``RETIRE_AFTER_DAYS``
   - ``silent`` : older than ``RETIRE_AFTER_DAYS``
   - ``unknown``: no matching artifact found

Read-only. Cannot retire, run, or modify any skill. Output goes to
``data/inferno_skills_audit.json`` and ``reports/skills_audit_latest.txt``.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from inferno_config import ROOT, local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


SKILLS_AUDIT_ARTIFACT_FILE = DATA_DIR / "inferno_skills_audit.json"
SKILLS_AUDIT_TEXT_FILE = REPORTS_DIR / "skills_audit_latest.txt"
SKILLS_AUDIT_STAGE = "skills-audit-research-only"

# Freshness thresholds. These are deliberately loose because some skills are
# weekly (e.g. paper exit auditor) and we do not want to call them stale on
# the weekend.
STALE_AFTER_HOURS: float = 48.0
RETIRE_AFTER_DAYS: float = 14.0

# Files we never include in the audit. The audit module audits itself by name
# only when a real artifact exists, so adding it to the skip list keeps the
# bootstrap pass clean.
SKIP_NAMES: frozenset[str] = frozenset(
    {
        "inferno_config.py",
        "inferno_skills_audit.py",
        "inferno_heartbeat.py",  # heartbeat has its own liveness signal
    }
)


def _artifact_dirs() -> list[Path]:
    return [DATA_DIR, REPORTS_DIR]


# A few modules write artifacts whose filenames don't follow the default
# ``inferno_<stem>`` / ``<stem>_latest`` convention. The audit accepts these
# explicit aliases on top of the default heuristic so the long tail of
# mismatches doesn't get reported as ``unknown``. Keys are the module stem
# *without* the ``inferno_`` or ``run_inferno_`` prefix; values are extra
# substrings the audit should treat as matching.
SPECIFIC_ALIASES: dict[str, tuple[str, ...]] = {
    "deploy_preflight": ("deploy_preflight",),
    "doctor": ("doctor",),
    "tos_export_verifier": ("tos_export_verifier", "export_verifier"),
    "tos_export_bridge": ("tos_export_bridge", "export_bridge"),
    "tos_session_probe": ("tos_session_probe", "session_probe"),
    "tos_ui_route": ("tos_ui_route", "ui_route"),
    "tos_sandbox": ("tos_sandbox", "paper_money_sandbox"),
    "tos_account_statement_scraper": ("account_statement",),
    "ops_maintenance": ("ops_maintenance",),
    "approval_queue": ("approval_queue",),
    "authority_controller": ("authority_manifest", "authority_controller"),
    "strike_selector": ("strike_ledger", "strike_plan", "strike_selector"),
    "live_account_sync": ("live_account_sync", "live_account"),
    "live_position_review": ("live_position", "position_review"),
    "performance_analytics": ("performance_analytics",),
    "shadow_evidence": ("shadow_evidence",),
    "strategy_lab": ("strategy_lab",),
    "outcome_reviewer": ("outcome_reviewer", "outcome_review"),
    "exposure_analytics": ("exposure_analytics", "exposure"),
    "edge_research": ("edge_research", "edge_radar"),
    "model_command_center": ("model_command_center", "command_center"),
    "downloads_manager": ("downloads_manager", "downloads"),
    "broker_preview": ("broker_preview",),
    "paper_test_director": ("paper_test_director",),
    "paper_evidence_loop": ("paper_evidence_loop",),
    "paper_exit_auditor": ("paper_exit_auditor", "paper_exit"),
    "paper_fill_ingest": ("paper_fill",),
    "cloud_control_plane": ("cloud_control_plane",),
    "cloud_execution_audit": ("cloud_execution_audit",),
    "cloud_state": ("cloud_state",),
    "desktop_automation": ("desktop_automation",),
    "watchdog": ("watchdog",),
    "ticker_universe_audit": ("ticker_universe", "universe_audit"),
    "data_readiness_audit": ("data_readiness", "readiness_audit"),
    "morning_inferno_pipeline": ("morning_inferno", "morning_brief"),
    "dawn_cycle": ("dawn_cycle",),
    "central_command": ("central_command",),
    "approval_cadence": ("approval_cadence",),
    "decision_brief": ("decision_brief",),
    "promotion_gap": ("promotion_gap",),
    "threshold_sensitivity": ("threshold_sensitivity",),
    "strategy_replay": ("strategy_replay",),
    "daily_success": ("daily_success",),
    "daily_loop": ("daily_loop",),
    "theme_synthesizer": ("theme_synthesizer",),
    "hypothesis_lab": ("hypothesis_lab",),
    "hypothesis_ledger": ("hypothesis_ledger",),
    "tos_export_stability": ("tos_export_stability",),
    "brain_console": ("brain_console",),
    "brain_cycle_journal": ("cycle_journal", "brain_cycle_journal"),
}


def _prefix_aliases(stem: str) -> list[str]:
    """Generate plausible artifact name fragments for a module stem.

    A module called ``inferno_doctor`` produces artifacts that include
    ``inferno_doctor`` (its JSON) and ``doctor_latest`` (its text). We try
    both shapes so the audit catches most files without a per-module
    mapping table — and we union in the explicit ``SPECIFIC_ALIASES`` entries
    for modules whose filenames don't follow the default pattern.
    """
    aliases = [stem]
    short_stem = stem
    if stem.startswith("inferno_"):
        short_stem = stem[len("inferno_"):]
        aliases.append(short_stem)
    elif stem.startswith("run_inferno_"):
        short_stem = stem[len("run_inferno_"):]
        aliases.append(short_stem)
    extra = SPECIFIC_ALIASES.get(short_stem, ())
    for alias in extra:
        if alias and alias not in aliases:
            aliases.append(alias)
    return [alias for alias in aliases if alias]


def _candidate_modules() -> list[Path]:
    """Return all inferno_*.py modules and run_inferno_*.sh wrappers."""
    found: list[Path] = []
    for path in sorted(ROOT.glob("inferno_*.py")):
        if path.name in SKIP_NAMES:
            continue
        found.append(path)
    for path in sorted(ROOT.glob("run_inferno_*.sh")):
        if path.name in SKIP_NAMES:
            continue
        found.append(path)
    return found


def _latest_artifact(aliases: list[str], dirs: list[Path]) -> Path | None:
    """Return the newest artifact whose name contains any alias."""
    candidates: list[Path] = []
    for directory in dirs:
        if not directory.exists():
            continue
        for artifact in directory.iterdir():
            if not artifact.is_file():
                continue
            lowered = artifact.name.lower()
            if any(alias.lower() in lowered for alias in aliases):
                candidates.append(artifact)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _classify(latest: Path | None, now: datetime) -> tuple[str, float | None]:
    """Return ``(freshness, hours_since)`` for an artifact."""
    if latest is None:
        return "unknown", None
    mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=now.tzinfo)
    if mtime.tzinfo and not now.tzinfo:
        mtime = mtime.replace(tzinfo=None)
    elif now.tzinfo and not mtime.tzinfo:
        mtime = mtime.replace(tzinfo=now.tzinfo)
    hours = (now - mtime).total_seconds() / 3600.0
    if hours < 0:
        return "fresh", hours
    if hours < STALE_AFTER_HOURS:
        return "fresh", hours
    if hours < RETIRE_AFTER_DAYS * 24.0:
        return "stale", hours
    return "silent", hours


def build_skills_audit(
    *,
    now: datetime | None = None,
    modules: Iterable[Path] | None = None,
    artifact_dirs: Iterable[Path] | None = None,
) -> dict[str, Any]:
    """Run the audit and return the full report.

    ``modules`` and ``artifact_dirs`` are injectable for tests so the audit
    can run against a small fixture directory.
    """
    now = now or local_now()
    module_paths = list(modules) if modules is not None else _candidate_modules()
    dirs = list(artifact_dirs) if artifact_dirs is not None else _artifact_dirs()

    rows: list[dict[str, Any]] = []
    counts = {"fresh": 0, "stale": 0, "silent": 0, "unknown": 0}

    for module_path in module_paths:
        aliases = _prefix_aliases(module_path.stem)
        latest = _latest_artifact(aliases, dirs)
        freshness, hours = _classify(latest, now)
        counts[freshness] = counts.get(freshness, 0) + 1
        rows.append(
            {
                "module": module_path.name,
                "freshness": freshness,
                "hoursSinceArtifact": round(hours, 2) if hours is not None else None,
                "latestArtifact": str(latest) if latest else None,
                "aliases": aliases,
            }
        )

    rows.sort(
        key=lambda row: (
            {"silent": 0, "unknown": 1, "stale": 2, "fresh": 3}[row["freshness"]],
            row["module"],
        )
    )

    if counts["silent"] > 0:
        verdict = "needs-attention"
        narrative = (
            f"{counts['silent']} skill(s) have not produced an artifact in over "
            f"{RETIRE_AFTER_DAYS:.0f} days. Either run them, retire them, or "
            "wire them into a cadence."
        )
    elif counts["unknown"] > counts["fresh"]:
        verdict = "needs-attention"
        narrative = (
            f"{counts['unknown']} skill(s) have no detectable artifact. Either "
            "the audit's prefix heuristic is too narrow, or the skill has never "
            "actually run on this Mac."
        )
    elif counts["stale"] > 0:
        verdict = "warming"
        narrative = (
            f"{counts['stale']} skill(s) are stale (older than "
            f"{STALE_AFTER_HOURS:.0f}h but newer than {RETIRE_AFTER_DAYS:.0f}d). "
            "Likely fine; consider running them in the next cadence pass."
        )
    else:
        verdict = "healthy"
        narrative = "All audited skills produced fresh artifacts."

    return {
        "generatedAt": now.isoformat(),
        "stage": SKILLS_AUDIT_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "counts": counts,
        "staleAfterHours": STALE_AFTER_HOURS,
        "retireAfterDays": RETIRE_AFTER_DAYS,
        "totalSkills": len(rows),
        "rows": rows,
        "reminders": [
            "research-only; cannot retire or run any skill",
            "freshness uses artifact mtime in data/ or reports/",
            "missing artifacts may be a prefix-matching gap, not a real failure",
        ],
    }


def skills_audit_text(payload: dict[str, Any]) -> str:
    """Render the audit into an operator memo."""
    counts = payload.get("counts") or {}
    lines = [
        "Inferno Skills Audit (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Narrative: {payload.get('narrative')}",
        f"Total skills: {payload.get('totalSkills')}",
        f"Counts: fresh {counts.get('fresh', 0)} | "
        f"stale {counts.get('stale', 0)} | "
        f"silent {counts.get('silent', 0)} | "
        f"unknown {counts.get('unknown', 0)}",
        f"Thresholds: stale > {payload.get('staleAfterHours')}h | "
        f"silent > {payload.get('retireAfterDays')}d",
        "",
        "Per-skill detail:",
    ]
    for row in payload.get("rows") or []:
        lines.append(
            f"- [{row.get('freshness'):<7}] {row.get('module'):<42} "
            f"age={row.get('hoursSinceArtifact')}h "
            f"artifact={Path(row.get('latestArtifact')).name if row.get('latestArtifact') else '-'}"
        )
    lines.extend([
        "",
        "Reminders:",
    ])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_skills_audit(payload: dict[str, Any]) -> None:
    """Persist the audit JSON and text artifacts via the retry-safe writer."""
    ensure_dirs()
    atomic_write_json(SKILLS_AUDIT_ARTIFACT_FILE, payload)
    atomic_write_text(SKILLS_AUDIT_TEXT_FILE, skills_audit_text(payload))


def parse_args() -> argparse.Namespace:
    """CLI: audit run | status."""
    parser = argparse.ArgumentParser(
        description=(
            "Audit Inferno skills for staleness based on artifact mtime. "
            "Research-only; cannot retire or run any skill."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint."""
    args = parse_args()
    if args.command == "status" and SKILLS_AUDIT_TEXT_FILE.exists():
        print(SKILLS_AUDIT_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_skills_audit()
    save_skills_audit(payload)
    print(skills_audit_text(payload))
    return 0 if payload.get("verdict") != "needs-attention" else 1


if __name__ == "__main__":
    raise SystemExit(main())
