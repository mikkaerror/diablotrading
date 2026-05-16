from __future__ import annotations

"""Inferno Counterfactual Replay — what would have happened under policy X?

The hypothesis lab tells the operator what *forward* claims look testable.
The counterfactual answers the *backward* question: given the closed shadow
outcomes we already have, which decision policy would have produced the
best realised expectancy?

The replay is policy-level rather than threshold-level on purpose. Threshold
sweeps require historical aggregate states the desk doesn't have many of
yet; a small set of named policies only needs (a) the closed shadow items
and (b) a pure function that classifies whether each item would have been
approved under that policy.

For each policy we compute:

- ``approvedCount`` / ``rejectedCount``
- ``winRate`` with Wilson 95 percent CI on the approved subset
- ``meanR`` with percentile-bootstrap 95 percent CI
- ``profitFactor`` (gross R wins / gross R losses)
- ``maxDrawdownR`` (worst observed loss in R units)

Then we rank the policies and surface the best by each of four orderings.
Disagreement between rankings is itself the headline finding — with small
N, every metric has overlapping CIs and operators need to know that.

Strict contract:

- read-only; never modifies the approval queue, shadow ledger, or any
  authority state
- ``researchOnly=True`` / ``promotable=False`` are hard-pinned in the payload
- safe to run on the daily-loop schedule
"""

import argparse
import json
import random
from typing import Any, Callable, Iterable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_theme_synthesizer import (
    DEFAULT_DIMENSIONS,
    EDGE_WIN_RATE_FLOOR,
    _load_shadow_records,
    _r_units,
    bootstrap_mean_ci,
    build_cube,
    normalize_record,
    rank_edges,
    wilson_interval,
)
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


COUNTERFACTUAL_FILE = DATA_DIR / "inferno_counterfactual.json"
COUNTERFACTUAL_TEXT_FILE = REPORTS_DIR / "counterfactual_latest.txt"
COUNTERFACTUAL_STAGE = "counterfactual-replay-research-only"

# Thresholds that define each policy. Centralised so the operator can read
# them off the report without grepping the code.
CATALYST_DTE_MAX_DAYS = 14.0
IV_CHEAP_RANK_MAX = 30.0

# Bootstrap settings. Same defaults as the theme synthesizer so CIs across
# the desk are comparable.
BOOTSTRAP_RESAMPLES = 400
BOOTSTRAP_SEED = 4242


PolicyFn = Callable[[dict[str, Any], dict[str, Any]], bool]


def _is_edge_cell(record: dict[str, Any], context: dict[str, Any]) -> bool:
    """Return True when the record matches one of the cube's edge cells."""
    edge_keys: set[str] = context.get("edgeKeys") or set()
    if not edge_keys:
        return False
    key = "|".join(str(record.get(dim) or "unknown") for dim in DEFAULT_DIMENSIONS)
    return key in edge_keys


def _is_anti_edge_cell(record: dict[str, Any], context: dict[str, Any]) -> bool:
    """Return True when the record matches one of the cube's anti-edge cells."""
    anti_keys: set[str] = context.get("antiEdgeKeys") or set()
    if not anti_keys:
        return False
    key = "|".join(str(record.get(dim) or "unknown") for dim in DEFAULT_DIMENSIONS)
    return key in anti_keys


def _is_catalyst_window(record: dict[str, Any]) -> bool:
    """Return True when the record's earnings catalyst is within the window."""
    raw = record.get("daysToEarnings")
    if raw is None:
        return False
    try:
        days = float(raw)
    except (TypeError, ValueError):
        return False
    return -10.0 <= days <= CATALYST_DTE_MAX_DAYS


def _is_iv_cheap(record: dict[str, Any]) -> bool:
    """Return True when the record's IV rank suggests cheap vol."""
    raw = record.get("ivRank")
    if raw is None:
        return False
    try:
        iv = float(raw)
    except (TypeError, ValueError):
        return False
    return iv < IV_CHEAP_RANK_MAX


def policy_all_approved(record: dict[str, Any], context: dict[str, Any]) -> bool:
    """Baseline: approve everything. Equivalent to the desk's current loose stance."""
    return True


def policy_edge_only(record: dict[str, Any], context: dict[str, Any]) -> bool:
    """Approve only records whose cell is a positive edge in the current cube."""
    return _is_edge_cell(record, context)


def policy_anti_edge_rejected(record: dict[str, Any], context: dict[str, Any]) -> bool:
    """Approve everything except records matching an anti-edge cell."""
    return not _is_anti_edge_cell(record, context)


def policy_catalyst_only(record: dict[str, Any], context: dict[str, Any]) -> bool:
    """Approve only records with an earnings catalyst within the window."""
    return _is_catalyst_window(record)


def policy_iv_cheap(record: dict[str, Any], context: dict[str, Any]) -> bool:
    """Approve only records with cheap implied volatility."""
    return _is_iv_cheap(record)


def policy_conservative(record: dict[str, Any], context: dict[str, Any]) -> bool:
    """Intersection of edge-only, catalyst-only, and iv-cheap."""
    return (
        policy_edge_only(record, context)
        and _is_catalyst_window(record)
        and _is_iv_cheap(record)
    )


DEFAULT_POLICIES: tuple[tuple[str, PolicyFn, str], ...] = (
    ("all-approved", policy_all_approved, "Baseline: approve everything."),
    (
        "edge-only",
        policy_edge_only,
        "Approve only if the record's cell is a positive edge in the theme cube.",
    ),
    (
        "anti-edge-rejected",
        policy_anti_edge_rejected,
        "Approve everything except items in anti-edge cells.",
    ),
    (
        "catalyst-only",
        policy_catalyst_only,
        f"Approve only items with daysToEarnings within ±{CATALYST_DTE_MAX_DAYS:g} days.",
    ),
    (
        "iv-cheap",
        policy_iv_cheap,
        f"Approve only items with ivRank < {IV_CHEAP_RANK_MAX:g}.",
    ),
    (
        "conservative",
        policy_conservative,
        "Intersection of edge-only, catalyst-only, and iv-cheap.",
    ),
)


def _statistical_block(samples: list[float]) -> dict[str, Any]:
    """Build the same statistical block the theme synthesizer uses.

    Encapsulated here so the counterfactual stays self-contained even if
    the theme synthesizer's signature drifts.
    """
    sample_count = len(samples)
    wins = sum(1 for value in samples if value > 0)
    losses = sample_count - wins
    win_rate = wins / sample_count if sample_count else 0.0
    wr_lower, wr_upper = wilson_interval(wins, sample_count)
    gross_win = sum(value for value in samples if value > 0)
    gross_loss = -sum(value for value in samples if value < 0)
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None
    mean, lower, upper = bootstrap_mean_ci(
        samples, resamples=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED
    )
    return {
        "sampleSize": sample_count,
        "wins": wins,
        "losses": losses,
        "winRate": round(win_rate, 4),
        "winRateLower": round(wr_lower, 4),
        "winRateUpper": round(wr_upper, 4),
        "totalR": round(sum(samples), 4),
        "meanR": round(mean, 4),
        "meanRLower": round(lower, 4),
        "meanRUpper": round(upper, 4),
        "profitFactor": round(profit_factor, 4) if profit_factor is not None else None,
        "maxDrawdownR": round(min(samples), 4) if samples else 0.0,
    }


def _build_cube_context(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the edge / anti-edge cell keys used by the policies."""
    cube = build_cube(records, dimensions=DEFAULT_DIMENSIONS)
    edges, anti_edges = rank_edges(cube, DEFAULT_DIMENSIONS, top_n=100)
    return {
        "edgeKeys": {edge["key"] for edge in edges},
        "antiEdgeKeys": {cell["key"] for cell in anti_edges},
        "edgeCount": len(edges),
        "antiEdgeCount": len(anti_edges),
    }


def _replay_policy(
    name: str,
    description: str,
    policy_fn: PolicyFn,
    normalized: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Run a single policy across all normalized records."""
    approved_samples: list[float] = []
    approved_tickers: list[str] = []
    approved_count = 0
    rejected_count = 0
    for record in normalized:
        if record.get("outcomeStatus") != "closed":
            # Counterfactual only operates over closed shadow outcomes.
            continue
        if policy_fn(record, context):
            approved_count += 1
            r_units = _r_units(record)
            if r_units is not None:
                approved_samples.append(r_units)
                if record.get("ticker"):
                    approved_tickers.append(str(record.get("ticker")))
        else:
            rejected_count += 1

    block = _statistical_block(approved_samples)
    verdict = (
        "insufficient-data"
        if block["sampleSize"] < 3
        else "researched"
    )
    return {
        "name": name,
        "description": description,
        "approvedCount": approved_count,
        "rejectedCount": rejected_count,
        "approvedTickers": sorted(set(approved_tickers)),
        "verdict": verdict,
        **block,
    }


def _rank_policies(policies: list[dict[str, Any]]) -> dict[str, str | None]:
    """Return the best policy under each ranking criterion."""
    candidates = [p for p in policies if p["verdict"] == "researched"]
    if not candidates:
        return {
            "bestByMeanR": None,
            "bestByWilsonLower": None,
            "bestByProfitFactor": None,
            "bestByDrawdown": None,
        }
    by_mean = max(candidates, key=lambda p: p["meanR"])
    by_wilson = max(candidates, key=lambda p: p["winRateLower"])
    by_pf = max(
        candidates,
        key=lambda p: (p["profitFactor"] is not None, p["profitFactor"] or float("-inf")),
    )
    by_dd = max(candidates, key=lambda p: p["maxDrawdownR"])
    return {
        "bestByMeanR": by_mean["name"],
        "bestByWilsonLower": by_wilson["name"],
        "bestByProfitFactor": by_pf["name"],
        "bestByDrawdown": by_dd["name"],
    }


def build_counterfactual(
    shadow_records: Iterable[dict[str, Any]] | None = None,
    *,
    policies: Iterable[tuple[str, PolicyFn, str]] | None = None,
) -> dict[str, Any]:
    """Build the full counterfactual report.

    Records and policies are injectable so tests can pass deterministic
    fixtures.
    """
    if shadow_records is None:
        shadow_records = _load_shadow_records()
    shadow_list = list(shadow_records)
    normalized = [normalize_record(record) for record in shadow_list]
    closed = [record for record in normalized if record.get("outcomeStatus") == "closed"]

    context = _build_cube_context(normalized)

    policy_specs = list(policies) if policies is not None else list(DEFAULT_POLICIES)
    policy_reports = [
        _replay_policy(name, description, fn, normalized, context)
        for name, fn, description in policy_specs
    ]

    rankings = _rank_policies(policy_reports)

    if not closed:
        verdict = "insufficient-data"
        narrative = (
            "The shadow ledger has zero closed outcomes; every policy reports "
            "an empty replay set. Run paper trades through the funnel to "
            "produce closed outcomes before this diagnostic can rank policies."
        )
    elif rankings["bestByMeanR"] is None:
        verdict = "insufficient-data"
        narrative = (
            "Closed shadow outcomes exist but no policy produced a sample of "
            "at least 3 approvals. Either the closed set is too small or the "
            "stricter policies rejected all of it."
        )
    else:
        verdict = "ranked"
        narrative = (
            "Best policy by mean R: "
            f"{rankings['bestByMeanR']}. "
            "Best by Wilson lower bound on win rate: "
            f"{rankings['bestByWilsonLower']}. "
            "Best by profit factor: "
            f"{rankings['bestByProfitFactor']}. "
            "Best by worst-drawdown (least bad single trade): "
            f"{rankings['bestByDrawdown']}. "
            "Disagreement between these rankings is expected with small N; "
            "treat all conclusions as exploratory until the closed sample "
            "size clears 30."
        )

    return {
        "generatedAt": local_now().isoformat(),
        "stage": COUNTERFACTUAL_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "shadowRecordCount": len(shadow_list),
        "closedRecordCount": len(closed),
        "edgeCellCount": context["edgeCount"],
        "antiEdgeCellCount": context["antiEdgeCount"],
        "verdict": verdict,
        "narrative": narrative,
        "policies": policy_reports,
        "rankings": rankings,
        "thresholds": {
            "catalystMaxDays": CATALYST_DTE_MAX_DAYS,
            "ivCheapMax": IV_CHEAP_RANK_MAX,
            "edgeWinRateFloor": EDGE_WIN_RATE_FLOOR,
            "bootstrapResamples": BOOTSTRAP_RESAMPLES,
            "bootstrapSeed": BOOTSTRAP_SEED,
        },
        "reminders": [
            "research-only; cannot promote authority or alter the approval queue",
            "policies are stateless and side-effect-free pure functions",
            "small sample size: rankings will disagree and that is informative",
        ],
    }


def counterfactual_text(payload: dict[str, Any]) -> str:
    """Render the counterfactual into an operator-readable memo."""
    lines = [
        "Inferno Counterfactual Replay (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Verdict: {payload.get('verdict')}",
        f"Shadow records: {payload.get('shadowRecordCount')} | closed: {payload.get('closedRecordCount')}",
        f"Edge cells: {payload.get('edgeCellCount')} | anti-edge cells: {payload.get('antiEdgeCellCount')}",
        "",
        f"Narrative: {payload.get('narrative')}",
        "",
        "Rankings:",
    ]
    rankings = payload.get("rankings") or {}
    for label, value in rankings.items():
        lines.append(f"- {label}: {value}")
    lines.append("")
    lines.append("Per-policy results:")
    for policy in payload.get("policies") or []:
        lines.append(
            f"- {policy.get('name'):<22} "
            f"approved={policy.get('approvedCount')} | "
            f"rejected={policy.get('rejectedCount')} | "
            f"N={policy.get('sampleSize')} | "
            f"WR={policy.get('winRate')} [{policy.get('winRateLower')}-{policy.get('winRateUpper')}] | "
            f"meanR={policy.get('meanR')} [{policy.get('meanRLower')}-{policy.get('meanRUpper')}] | "
            f"PF={policy.get('profitFactor')} | DD={policy.get('maxDrawdownR')}"
        )
        if policy.get("description"):
            lines.append(f"    {policy.get('description')}")
    lines.append("")
    lines.append("Thresholds:")
    for key, value in (payload.get("thresholds") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("Reminders:")
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_counterfactual(payload: dict[str, Any]) -> None:
    """Persist the counterfactual JSON and text artifacts."""
    ensure_dirs()
    atomic_write_json(COUNTERFACTUAL_FILE, payload)
    atomic_write_text(COUNTERFACTUAL_TEXT_FILE, counterfactual_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Counterfactual replay over closed shadow outcomes under a small set "
            "of named decision policies. Research-only."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and COUNTERFACTUAL_TEXT_FILE.exists():
        print(COUNTERFACTUAL_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_counterfactual()
    save_counterfactual(payload)
    print(counterfactual_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
