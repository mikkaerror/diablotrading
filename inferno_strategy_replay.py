from __future__ import annotations

"""Research-only replay of the strategy lab against shadow evidence.

Purpose
-------
The paper ledger has 0 closed scored tickets, so the strategy lab is stuck at
``insufficient-data``. The shadow ledger has ~10 closed hypothetical outcomes.
This module re-runs the *exact same* lab logic against those shadow outcomes
to answer the operator question: "If shadow evidence were promoted to scored
paper evidence, what would the lab say?"

Hard contract
-------------
- This is research-only. It never modifies the shadow ledger, paper ledger,
  or strategy lab artifact.
- The replay artifact is written to ``data/inferno_strategy_replay.json`` so
  it cannot be confused with the real lab output.
- Authority manifest never reads this file. It cannot promote anything.
"""

import argparse
import json
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_shadow_evidence import SHADOW_EVIDENCE_FILE
from inferno_strategy_lab import build_strategy_lab
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


REPLAY_ARTIFACT_FILE = DATA_DIR / "inferno_strategy_replay.json"
REPLAY_TEXT_FILE = REPORTS_DIR / "strategy_replay_latest.txt"
REPLAY_STAGE = "shadow-replay-research-only"


def normalize_shadow_item(item: dict[str, Any]) -> dict[str, Any]:
    """Reshape a shadow ledger item into the shape ``summarize_strategy`` expects.

    Specifically: the lab filters on ``outcome.status == "closed"`` and reads
    ``riskVerdict.metrics.maxLossDollars`` plus ``outcome.estimatedPnl`` to
    compute return-on-risk. Both fields are already present on shadow items,
    so this is a thin copy that re-tags the top-level ``status`` to a
    lab-compatible value without mutating the original.
    """
    copy = dict(item)
    # The lab uses status purely for funnel diagnostics (paper-blocked vs
    # paper-staged). We re-tag closed shadow items as 'paper-staged-replay'
    # so the false-positive math reflects accurately and so anyone reading
    # the artifact can tell these came from replay, not real paper fills.
    outcome = item.get("outcome") or {}
    if outcome.get("status") == "closed":
        copy["status"] = "paper-staged-replay"
    else:
        copy["status"] = "shadow-open-replay"
    return copy


def build_replay(shadow: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the strategy lab against normalized shadow evidence."""
    shadow = shadow if shadow is not None else (load_json_file(SHADOW_EVIDENCE_FILE) or {})
    items = shadow.get("items") or []
    normalized = [normalize_shadow_item(item) for item in items]
    pseudo_ledger = {
        "updatedAt": shadow.get("updatedAt"),
        "items": normalized,
    }
    lab = build_strategy_lab(pseudo_ledger)
    closed_count = sum(
        1 for item in normalized if (item.get("outcome") or {}).get("status") == "closed"
    )
    return {
        "generatedAt": local_now().isoformat(),
        "stage": REPLAY_STAGE,
        "researchOnly": True,
        "promotable": False,
        "sourceShadowUpdatedAt": shadow.get("updatedAt"),
        "shadowItemCount": len(items),
        "closedShadowCount": closed_count,
        "lab": lab,
        "deskVerdictReplay": (lab.get("deskVerdict") or {}),
        "promotionCandidatesReplay": list(lab.get("promotionCandidates") or []),
        "researchNotes": [
            "shadow-replay only; cannot promote broker authority",
            "informational read of strategy gates against hypothetical outcomes",
        ],
    }


def replay_text(replay: dict[str, Any]) -> str:
    """Render a short operator memo for the replay artifact."""
    lab = replay.get("lab") or {}
    overall = lab.get("overall") or {}
    desk = replay.get("deskVerdictReplay") or {}
    lines = [
        "Inferno Strategy Replay (research-only)",
        "",
        f"Generated: {replay.get('generatedAt')}",
        f"Stage: {replay.get('stage')}",
        f"Research only: {replay.get('researchOnly')}",
        f"Promotable from this artifact: {replay.get('promotable')}",
        "",
        f"Shadow items considered: {replay.get('shadowItemCount', 0)}",
        f"Shadow items closed: {replay.get('closedShadowCount', 0)}",
        f"Replay desk verdict: {desk.get('level')} | {desk.get('message')}",
        f"Replay promotion candidates: "
        + (", ".join(replay.get("promotionCandidatesReplay") or []) or "none"),
        "",
        "Replay overall metrics:",
        f"- scored: {overall.get('scoredCount', 0)}",
        f"- win rate: {overall.get('winRate')}",
        f"- win rate lower bound: {overall.get('winRateLowerBound')}",
        f"- profit factor: {overall.get('profitFactor')}",
        f"- expectancy confidence: {overall.get('expectancyPerRiskConfidence')}",
        f"- max drawdown (R units): {overall.get('maxDrawdownRiskUnits')}",
        "",
        "Per-strategy replay:",
    ]
    for strat in lab.get("strategies") or []:
        verdict = strat.get("verdict") or {}
        lines.append(
            f"- {strat.get('strategy')}: scored {strat.get('scoredCount', 0)} | "
            f"win {strat.get('winCount', 0)} | loss {strat.get('lossCount', 0)} | "
            f"verdict {verdict.get('level')}"
        )
    lines.extend(
        [
            "",
            "Reminders:",
            "- this file does not modify shadow, paper, or lab artifacts",
            "- this file cannot promote broker submission authority",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def save_replay(replay: dict[str, Any]) -> None:
    """Persist replay JSON and text artifacts."""
    ensure_dirs()
    atomic_write_json(REPLAY_ARTIFACT_FILE, replay)
    atomic_write_text(REPLAY_TEXT_FILE, replay_text(replay))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Research-only replay of the strategy lab against shadow evidence. "
            "Does not modify any other artifact."
        )
    )
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and REPLAY_TEXT_FILE.exists():
        print(REPLAY_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    replay = build_replay()
    save_replay(replay)
    print(replay_text(replay))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
