from __future__ import annotations

"""Append-only ledger of every hypothesis the lab has ever proposed.

This is the desk's "thinking memory." The hypothesis lab regenerates a fresh
batch of hypotheses every cycle, but without persistence the desk forgets
yesterday's theories. The ledger fixes that: each cycle, we record every
hypothesis with its current statistical state, and we compare against the
previous appearance to compute a *trajectory*:

- **strengthening** : Wilson lower bound increased materially.
- **weakening**     : Wilson lower bound decreased materially.
- **stable**        : Wilson lower bound within the noise band.
- **new**           : first time we've seen this hypothesis id.
- **abandoned**     : present in a prior cycle but absent today.

Each hypothesis carries a ``reproductionCount`` (how many cycles it's been
spotted) and a ``firstSeenAt`` / ``lastSeenAt`` timestamp pair.

Read-only. Cannot promote authority, cannot change desk state.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


LEDGER_ARTIFACT_FILE = DATA_DIR / "inferno_hypothesis_ledger.json"
LEDGER_TEXT_FILE = REPORTS_DIR / "hypothesis_ledger_latest.txt"
LEDGER_STAGE = "hypothesis-ledger-research-only"

# Cap on records per hypothesis id (most recent N kept). 64 cycles ≈ a month
# of weekday firings without unbounded growth.
MAX_HISTORY_PER_ID = 64

# Minimum delta on Wilson lower bound to be called a real move. Below this
# we consider the hypothesis stable.
STRENGTH_NOISE_BAND = 0.04


def _load_existing_ledger() -> dict[str, Any]:
    """Load the ledger, tolerating a missing, corrupt, or contended file.

    Also catches ``OSError`` so transient errno-35 deadlocks on macOS during
    a concurrent write don't crash the read; we just fall back to "empty"
    and the next cycle re-populates the trajectory.
    """
    if not LEDGER_ARTIFACT_FILE.exists():
        return {"hypotheses": {}}
    try:
        payload = json.loads(LEDGER_ARTIFACT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"hypotheses": {}}
    if not isinstance(payload, dict):
        return {"hypotheses": {}}
    if not isinstance(payload.get("hypotheses"), dict):
        return {"hypotheses": {}}
    return payload


def _classify_trajectory(
    previous_wl: float | None, current_wl: float | None
) -> str:
    """Return one of strengthening / weakening / stable / new."""
    if previous_wl is None:
        return "new"
    if current_wl is None:
        return "stable"
    delta = current_wl - previous_wl
    if delta > STRENGTH_NOISE_BAND:
        return "strengthening"
    if delta < -STRENGTH_NOISE_BAND:
        return "weakening"
    return "stable"


def _hypothesis_signature(hypothesis: dict[str, Any]) -> dict[str, Any]:
    """Pull a small subset out of a hypothesis for the ledger row."""
    stats = hypothesis.get("stats") or {}
    return {
        "claim": hypothesis.get("claim"),
        "template": hypothesis.get("template"),
        "cell": hypothesis.get("cell"),
        "suggestedAction": hypothesis.get("suggestedAction"),
        "testConfidence": hypothesis.get("testConfidence"),
        "stats": {
            "sampleSize": stats.get("sampleSize"),
            "winRate": stats.get("winRate"),
            "winRateLower": stats.get("winRateLower"),
            "winRateUpper": stats.get("winRateUpper"),
            "expectancyMean": stats.get("expectancyMean"),
            "expectancyLower": stats.get("expectancyLower"),
            "profitFactor": stats.get("profitFactor"),
        },
    }


def update_ledger(
    new_hypotheses: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update the ledger with this cycle's hypotheses.

    Returns the full new ledger payload. Pass ``existing`` to inject state for
    tests; otherwise the on-disk ledger is loaded.
    """
    payload = existing if existing is not None else _load_existing_ledger()
    hypotheses: dict[str, Any] = dict(payload.get("hypotheses") or {})
    timestamp = (now or local_now()).isoformat()

    seen_ids: set[str] = set()
    trajectory_summary = {
        "new": 0,
        "strengthening": 0,
        "weakening": 0,
        "stable": 0,
    }

    for hypothesis in new_hypotheses:
        hid = hypothesis.get("id")
        if not hid:
            continue
        seen_ids.add(hid)
        signature = _hypothesis_signature(hypothesis)
        previous = hypotheses.get(hid)
        previous_wl = None
        reproduction_count = 0
        first_seen_at = timestamp
        history: list[dict[str, Any]] = []
        if previous:
            history = list(previous.get("history") or [])
            reproduction_count = int(previous.get("reproductionCount") or 0)
            first_seen_at = previous.get("firstSeenAt") or timestamp
            last_stats = previous.get("currentStats") or {}
            previous_wl = last_stats.get("winRateLower")

        current_wl = (signature.get("stats") or {}).get("winRateLower")
        trajectory = _classify_trajectory(previous_wl, current_wl)
        trajectory_summary[trajectory] = trajectory_summary.get(trajectory, 0) + 1

        history.append({
            "at": timestamp,
            "stats": signature.get("stats"),
            "testConfidence": hypothesis.get("testConfidence"),
            "trajectory": trajectory,
        })
        history = history[-MAX_HISTORY_PER_ID:]

        hypotheses[hid] = {
            "id": hid,
            "template": signature.get("template"),
            "claim": signature.get("claim"),
            "cell": signature.get("cell"),
            "suggestedAction": signature.get("suggestedAction"),
            "currentStats": signature.get("stats"),
            "currentTestConfidence": hypothesis.get("testConfidence"),
            "firstSeenAt": first_seen_at,
            "lastSeenAt": timestamp,
            "reproductionCount": reproduction_count + 1,
            "currentTrajectory": trajectory,
            "history": history,
        }

    # Hypotheses present last cycle but absent today get marked abandoned.
    abandoned_ids: list[str] = []
    for hid, record in hypotheses.items():
        if hid in seen_ids:
            continue
        if record.get("currentTrajectory") == "abandoned":
            continue
        history = list(record.get("history") or [])
        history.append({
            "at": timestamp,
            "stats": record.get("currentStats"),
            "testConfidence": record.get("currentTestConfidence"),
            "trajectory": "abandoned",
        })
        record["history"] = history[-MAX_HISTORY_PER_ID:]
        record["currentTrajectory"] = "abandoned"
        record["lastSeenAt"] = timestamp
        abandoned_ids.append(hid)
    trajectory_summary["abandoned"] = len(abandoned_ids)

    payload = {
        "updatedAt": timestamp,
        "stage": LEDGER_STAGE,
        "hypotheses": hypotheses,
    }
    # Retry-safe writer absorbs transient errno-35 deadlocks on macOS so
    # a concurrent writer never drops the ledger update silently.
    atomic_write_json(LEDGER_ARTIFACT_FILE, payload)
    payload["trajectorySummary"] = trajectory_summary
    return payload


def build_ledger_report(
    *,
    now: datetime | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarise the ledger for the operator memo.

    Highlights:
    - hypotheses strengthening the most
    - hypotheses weakening the most
    - hypotheses with the highest reproduction count (consistently shown)
    """
    ledger = payload if payload is not None else _load_existing_ledger()
    hypotheses = list((ledger.get("hypotheses") or {}).values())

    by_strengthening = sorted(
        [h for h in hypotheses if h.get("currentTrajectory") == "strengthening"],
        key=lambda h: (h.get("currentStats") or {}).get("winRateLower") or 0.0,
        reverse=True,
    )[:5]
    by_weakening = sorted(
        [h for h in hypotheses if h.get("currentTrajectory") == "weakening"],
        key=lambda h: (h.get("currentStats") or {}).get("winRateLower") or 0.0,
    )[:5]
    by_reproductions = sorted(
        hypotheses,
        key=lambda h: int(h.get("reproductionCount") or 0),
        reverse=True,
    )[:5]
    abandoned = [
        h for h in hypotheses if h.get("currentTrajectory") == "abandoned"
    ][:5]

    trajectory_counts: dict[str, int] = {
        "new": 0,
        "strengthening": 0,
        "weakening": 0,
        "stable": 0,
        "abandoned": 0,
    }
    for hypothesis in hypotheses:
        traj = str(hypothesis.get("currentTrajectory") or "stable")
        trajectory_counts[traj] = trajectory_counts.get(traj, 0) + 1

    return {
        "generatedAt": (now or local_now()).isoformat(),
        "stage": LEDGER_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "totalHypotheses": len(hypotheses),
        "trajectoryCounts": trajectory_counts,
        "strengthening": by_strengthening,
        "weakening": by_weakening,
        "byReproductionCount": by_reproductions,
        "abandoned": abandoned,
        "noiseBand": STRENGTH_NOISE_BAND,
        "reminders": [
            "research-only; the ledger does not promote anything",
            "trajectory uses Wilson lower bound deltas across cycles",
            "reproductionCount is the number of cycles a hypothesis has appeared",
        ],
    }


def ledger_text(payload: dict[str, Any]) -> str:
    """Render the ledger summary."""
    lines = [
        "Inferno Hypothesis Ledger (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Total tracked hypotheses: {payload.get('totalHypotheses')}",
        f"Noise band on Wilson lower: {payload.get('noiseBand')}",
    ]
    counts = payload.get("trajectoryCounts") or {}
    lines.append(
        "Trajectory counts: "
        + " | ".join(f"{key} {value}" for key, value in counts.items())
    )

    def _section(title: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        lines.append("")
        lines.append(f"{title}:")
        for row in rows:
            stats = row.get("currentStats") or {}
            lines.append(
                f"- [{row.get('currentTrajectory'):<14}] "
                f"reps={row.get('reproductionCount')} "
                f"conf={row.get('currentTestConfidence')} "
                f"WR={stats.get('winRate')} "
                f"[{stats.get('winRateLower')}-{stats.get('winRateUpper')}]"
            )
            lines.append(f"    claim: {row.get('claim')}")

    _section("Strengthening", payload.get("strengthening") or [])
    _section("Weakening", payload.get("weakening") or [])
    _section("Most reproduced", payload.get("byReproductionCount") or [])
    _section("Recently abandoned", payload.get("abandoned") or [])

    lines.extend([
        "",
        "Reminders:",
    ])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_ledger_report(payload: dict[str, Any]) -> None:
    """Persist the ledger summary text artifact (the JSON ledger writes itself)."""
    ensure_dirs()
    atomic_write_text(LEDGER_TEXT_FILE, ledger_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Manage and summarise the hypothesis ledger. Research-only; cannot "
            "change desk state."
        )
    )
    parser.add_argument("command", nargs="?", default="summary", choices=["summary", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and LEDGER_TEXT_FILE.exists():
        print(LEDGER_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_ledger_report()
    save_ledger_report(payload)
    print(ledger_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
