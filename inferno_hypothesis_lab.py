from __future__ import annotations

"""Hypothesis lab: generate testable theories from the desk's evidence and
backtest each one with statistical confidence.

The theme synthesizer cubes the evidence and shows which cells have edges and
which don't. The hypothesis lab takes that one step further: it phrases each
finding as a testable hypothesis, immediately backtests it on the relevant
subset of evidence, and ranks the hypotheses by statistical confidence.

The five hypothesis templates this version implements:

1. **dimension-edge**     — "Setup X in regime Y wins above the win-rate
                            floor across N samples; tighten the filter to X+Y."
2. **dimension-anti-edge** — "Setup X in regime Y loses with statistical
                            significance; exclude that combination."
3. **pending-match-edge** — "Pending ticker T's profile matches a positive
                            cell; approving T pulls from a working pocket."
4. **pending-mismatch**    — "Pending ticker T's profile matches an anti-edge
                            cell; reject or shrink to a smaller cell."
5. **insufficient-but-trending** — "Cell C is below MIN_CELL_SAMPLES but its
                            current trend looks worth running."

Each hypothesis carries: a claim, a citation set (which records support it),
its statistical block (Wilson bounds, expectancy CI, profit factor), and a
`testConfidence` heuristic (0..1) so the operator can prioritise.

Read-only. Cannot promote authority, cannot modify shadow, cannot mutate the
approval queue.
"""

import argparse
import json
from typing import Any, Iterable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_theme_synthesizer import (
    DEFAULT_DIMENSIONS,
    MIN_CELL_SAMPLES,
    bootstrap_mean_ci,
    build_cube,
    normalize_record,
    rank_edges,
    wilson_interval,
    _load_shadow_records,
)
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


HYPOTHESIS_LAB_FILE = DATA_DIR / "inferno_hypothesis_lab.json"
HYPOTHESIS_LAB_TEXT_FILE = REPORTS_DIR / "hypothesis_lab_latest.txt"
HYPOTHESIS_LAB_STAGE = "hypothesis-lab-research-only"

# How many hypotheses to surface across all templates. The lab generates more
# internally; the cap is on what we present per cycle so the report stays
# readable.
DEFAULT_TOP_N_HYPOTHESES = 7

# Win-rate floor we test edges against (matches the production lab gate).
WIN_RATE_FLOOR = 0.42

# Statistical-confidence weight breakdown for the testConfidence score.
TEST_CONFIDENCE_WEIGHTS = {
    "wilson_lower": 0.45,
    "sample_size": 0.30,
    "expectancy_lower": 0.25,
}

# Sample-size saturation point for the testConfidence weight. Cells with this
# many or more samples earn the full weight; smaller cells earn proportionally
# less.
SAMPLE_SIZE_SATURATION = 12


def _statistical_block(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute Wilson + expectancy + profit-factor block for a record subset."""
    from inferno_theme_synthesizer import _r_units  # local import to keep top tidy

    samples: list[float] = []
    for record in records:
        r = _r_units(record)
        if r is not None:
            samples.append(r)
    sample_count = len(samples)
    wins = sum(1 for value in samples if value > 0)
    wr = (wins / sample_count) if sample_count else 0.0
    wr_lower, wr_upper = wilson_interval(wins, sample_count)
    gross_win = sum(value for value in samples if value > 0)
    gross_loss = -sum(value for value in samples if value < 0)
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None
    mean, lower, upper = bootstrap_mean_ci(samples)
    return {
        "sampleSize": sample_count,
        "wins": wins,
        "winRate": round(wr, 4),
        "winRateLower": round(wr_lower, 4),
        "winRateUpper": round(wr_upper, 4),
        "expectancyMean": round(mean, 4),
        "expectancyLower": round(lower, 4),
        "expectancyUpper": round(upper, 4),
        "profitFactor": round(profit_factor, 4) if profit_factor is not None else None,
    }


def _test_confidence(stats: dict[str, Any]) -> float:
    """Score a hypothesis 0..1 based on its statistical block."""
    wilson_lower = stats.get("winRateLower", 0.0) or 0.0
    sample_size = stats.get("sampleSize", 0) or 0
    expectancy_lower = stats.get("expectancyLower", 0.0) or 0.0

    sample_weight = min(1.0, sample_size / SAMPLE_SIZE_SATURATION)
    expectancy_component = max(0.0, min(1.0, (expectancy_lower + 1.0) / 2.0))
    # wilson_lower is naturally in 0..1.

    return round(
        TEST_CONFIDENCE_WEIGHTS["wilson_lower"] * wilson_lower
        + TEST_CONFIDENCE_WEIGHTS["sample_size"] * sample_weight
        + TEST_CONFIDENCE_WEIGHTS["expectancy_lower"] * expectancy_component,
        4,
    )


def _hypothesis_id(template: str, key: str) -> str:
    """Deterministic id so the ledger can dedupe across runs."""
    return f"{template}:{key}"


def _cell_to_key(cell: dict[str, Any]) -> str:
    return cell.get("key") or "|".join(
        str(value or "unknown") for value in (cell.get("cell") or {}).values()
    )


def _edge_hypotheses(
    edges: list[dict[str, Any]], anti_edges: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Phrase the top edges and anti-edges from the cube as hypotheses."""
    hypotheses: list[dict[str, Any]] = []
    for edge in edges:
        stats_block = {k: edge.get(k) for k in (
            "sampleSize", "wins", "winRate", "winRateLower", "winRateUpper",
            "expectancyMean", "expectancyLower", "expectancyUpper", "profitFactor",
        )}
        hypothesis = {
            "id": _hypothesis_id("dimension-edge", edge["key"]),
            "template": "dimension-edge",
            "claim": (
                f"Cell {edge['key']} shows a positive edge "
                f"(Wilson lower {edge['winRateLower']} over N={edge['sampleSize']}); "
                "approve names that match this cell more aggressively."
            ),
            "cell": edge.get("cell"),
            "stats": stats_block,
            "testConfidence": _test_confidence(stats_block),
            "supportingTickers": edge.get("tickerSample") or [],
            "suggestedAction": "tighten-filter-to-cell",
        }
        hypotheses.append(hypothesis)

    for cell in anti_edges:
        stats_block = {k: cell.get(k) for k in (
            "sampleSize", "wins", "winRate", "winRateLower", "winRateUpper",
            "expectancyMean", "expectancyLower", "expectancyUpper", "profitFactor",
        )}
        hypothesis = {
            "id": _hypothesis_id("dimension-anti-edge", cell["key"]),
            "template": "dimension-anti-edge",
            "claim": (
                f"Cell {cell['key']} shows an anti-edge "
                f"(Wilson upper {cell['winRateUpper']}, mean expectancy "
                f"{cell['expectancyMean']} R over N={cell['sampleSize']}); "
                "exclude names that match this cell or shrink them."
            ),
            "cell": cell.get("cell"),
            "stats": stats_block,
            "testConfidence": _test_confidence(stats_block),
            "supportingTickers": cell.get("tickerSample") or [],
            "suggestedAction": "exclude-cell",
        }
        hypotheses.append(hypothesis)
    return hypotheses


def _pending_match_hypotheses(
    pending_records: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    anti_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """For each pending ticket, see whether it matches an edge or anti-edge cell."""
    hypotheses: list[dict[str, Any]] = []
    edge_keys = {edge["key"]: edge for edge in edges}
    anti_keys = {cell["key"]: cell for cell in anti_edges}
    for pending in pending_records:
        normalized = normalize_record(pending)
        key = "|".join(
            str(normalized.get(dim) or "unknown") for dim in DEFAULT_DIMENSIONS
        )
        if key in edge_keys:
            edge = edge_keys[key]
            stats_block = {k: edge.get(k) for k in (
                "sampleSize", "wins", "winRate", "winRateLower", "winRateUpper",
                "expectancyMean", "expectancyLower", "expectancyUpper", "profitFactor",
            )}
            hypotheses.append({
                "id": _hypothesis_id(
                    "pending-match-edge", f"{normalized.get('ticker')}|{key}"
                ),
                "template": "pending-match-edge",
                "claim": (
                    f"Pending {normalized.get('ticker')} matches edge cell {key}; "
                    "approving pulls from a positive pocket."
                ),
                "cell": edge.get("cell"),
                "stats": stats_block,
                "testConfidence": _test_confidence(stats_block),
                "supportingTickers": edge.get("tickerSample") or [],
                "suggestedAction": "approve-with-priority",
            })
        elif key in anti_keys:
            cell = anti_keys[key]
            stats_block = {k: cell.get(k) for k in (
                "sampleSize", "wins", "winRate", "winRateLower", "winRateUpper",
                "expectancyMean", "expectancyLower", "expectancyUpper", "profitFactor",
            )}
            hypotheses.append({
                "id": _hypothesis_id(
                    "pending-mismatch", f"{normalized.get('ticker')}|{key}"
                ),
                "template": "pending-mismatch",
                "claim": (
                    f"Pending {normalized.get('ticker')} matches anti-edge cell {key}; "
                    "reject or shrink to a smaller risk slice."
                ),
                "cell": cell.get("cell"),
                "stats": stats_block,
                "testConfidence": _test_confidence(stats_block),
                "supportingTickers": cell.get("tickerSample") or [],
                "suggestedAction": "reject-or-shrink",
            })
    return hypotheses


def _trending_insufficient_hypotheses(
    cube: dict[tuple[str, ...], dict[str, Any]], dimensions: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Highlight cells just below MIN_CELL_SAMPLES that look promising.

    A cell qualifies when its sample size is in ``[1, MIN_CELL_SAMPLES)`` and
    its current win rate is at or above the win-rate floor.
    """
    hypotheses: list[dict[str, Any]] = []
    for key, metrics in cube.items():
        if metrics["sufficient"]:
            continue
        if metrics["sampleSize"] < 1:
            continue
        if metrics["winRate"] < WIN_RATE_FLOOR:
            continue
        cell_dict = {dim: value for dim, value in zip(dimensions, key)}
        stats_block = {k: metrics.get(k) for k in (
            "sampleSize", "wins", "winRate", "winRateLower", "winRateUpper",
            "expectancyMean", "expectancyLower", "expectancyUpper", "profitFactor",
        )}
        hypotheses.append({
            "id": _hypothesis_id("insufficient-but-trending", "|".join(key)),
            "template": "insufficient-but-trending",
            "claim": (
                f"Cell {'|'.join(key)} is below the {MIN_CELL_SAMPLES}-sample floor "
                f"but its current win rate is {metrics['winRate']}; "
                "worth queuing additional paper trades to grow N."
            ),
            "cell": cell_dict,
            "stats": stats_block,
            "testConfidence": _test_confidence(stats_block),
            "supportingTickers": metrics.get("tickerSample") or [],
            "suggestedAction": "grow-sample-size",
        })
    hypotheses.sort(key=lambda h: h["testConfidence"], reverse=True)
    return hypotheses


def build_hypothesis_lab(
    shadow_records: Iterable[dict[str, Any]] | None = None,
    pending_records: Iterable[dict[str, Any]] | None = None,
    *,
    dimensions: tuple[str, ...] = DEFAULT_DIMENSIONS,
    top_n: int = DEFAULT_TOP_N_HYPOTHESES,
    top_n_edges: int = 10,
) -> dict[str, Any]:
    """Build the full hypothesis lab report.

    Records are injectable for tests. When omitted, the shadow ledger is loaded
    lazily (same pattern as the theme synthesizer).
    """
    if shadow_records is None:
        shadow_records = _load_shadow_records()
    shadow_list = list(shadow_records)
    pending_list = list(pending_records or [])

    cube = build_cube(shadow_list, dimensions=dimensions)
    edges, anti_edges = rank_edges(cube, dimensions=dimensions, top_n=top_n_edges)

    hypotheses: list[dict[str, Any]] = []
    hypotheses.extend(_edge_hypotheses(edges, anti_edges))
    hypotheses.extend(
        _pending_match_hypotheses(pending_list, edges, anti_edges)
    )
    hypotheses.extend(_trending_insufficient_hypotheses(cube, dimensions))

    hypotheses.sort(key=lambda h: h["testConfidence"], reverse=True)
    top_hypotheses = hypotheses[:top_n]

    template_counts: dict[str, int] = {}
    for hypothesis in hypotheses:
        template_counts[hypothesis["template"]] = (
            template_counts.get(hypothesis["template"], 0) + 1
        )

    return {
        "generatedAt": local_now().isoformat(),
        "stage": HYPOTHESIS_LAB_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "shadowRecordCount": len(shadow_list),
        "pendingRecordCount": len(pending_list),
        "totalHypotheses": len(hypotheses),
        "topHypotheses": top_hypotheses,
        "allHypotheses": hypotheses,
        "templateCounts": template_counts,
        "edgeCount": len(edges),
        "antiEdgeCount": len(anti_edges),
        "winRateFloor": WIN_RATE_FLOOR,
        "reminders": [
            "research-only; cannot change desk state",
            "testConfidence is a heuristic, not a probability",
            "small sample sizes; treat all claims as exploratory until N >= 30",
        ],
    }


def hypothesis_lab_text(payload: dict[str, Any]) -> str:
    """Render the lab report into an operator memo."""
    lines = [
        "Inferno Hypothesis Lab (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Shadow records: {payload.get('shadowRecordCount')} | "
        f"pending records: {payload.get('pendingRecordCount')}",
        f"Hypotheses: {payload.get('totalHypotheses')} "
        f"(edges {payload.get('edgeCount')} | anti-edges {payload.get('antiEdgeCount')})",
        f"Win-rate floor: {payload.get('winRateFloor')}",
        "",
        "Top hypotheses (ranked by testConfidence):",
    ]
    for hypothesis in payload.get("topHypotheses") or []:
        stats = hypothesis.get("stats") or {}
        lines.append(
            f"- [{hypothesis.get('template'):<24}] "
            f"conf={hypothesis.get('testConfidence')} "
            f"N={stats.get('sampleSize')} "
            f"WR={stats.get('winRate')} [{stats.get('winRateLower')}-{stats.get('winRateUpper')}] "
            f"E={stats.get('expectancyMean')} [{stats.get('expectancyLower')}-{stats.get('expectancyUpper')}]"
        )
        lines.append(f"    claim: {hypothesis.get('claim')}")
        lines.append(f"    action: {hypothesis.get('suggestedAction')}")
        if hypothesis.get("supportingTickers"):
            lines.append(
                "    tickers: " + ", ".join(hypothesis.get("supportingTickers") or [])
            )
    lines.extend([
        "",
        "Template counts:",
    ])
    for template, count in (payload.get("templateCounts") or {}).items():
        lines.append(f"- {template}: {count}")
    lines.extend([
        "",
        "Reminders:",
    ])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_hypothesis_lab(payload: dict[str, Any]) -> None:
    """Persist the hypothesis lab JSON and text artifacts."""
    ensure_dirs()
    atomic_write_json(HYPOTHESIS_LAB_FILE, payload)
    atomic_write_text(HYPOTHESIS_LAB_TEXT_FILE, hypothesis_lab_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate testable hypotheses from desk evidence and backtest each "
            "one with confidence intervals. Research-only."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N_HYPOTHESES)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and HYPOTHESIS_LAB_TEXT_FILE.exists():
        print(HYPOTHESIS_LAB_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_hypothesis_lab(top_n=args.top_n)
    save_hypothesis_lab(payload)
    print(hypothesis_lab_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
