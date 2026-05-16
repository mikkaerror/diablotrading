from __future__ import annotations

"""Statistical theme cube over closed shadow evidence.

The shadow ledger has dozens of closed outcomes (10 as of 2026-05-10). Looking
at them in aggregate produces one verdict, but the desk has many axes that
plausibly affect outcomes:

- **Setup** (Straddle, Call Debit Spread, Iron Condor, Vertical Call, ...)
- **Market regime** (bullish-normal, bullish-strong, bearish, sideways)
- **Sector** (Technology, Industrials, Utilities, ...)
- **IV-rank bucket** (low / mid / high)
- **Days-to-earnings bucket** (imminent / near / mid / far / none)
- **Edge-research lane** (Catalyst, Ignore-For-Theme, ...)

The theme synthesizer builds a multi-axis cube and reports the per-cell metrics
that matter for an edge: sample size, win rate with Wilson lower bound,
expectancy with bootstrap CI, profit factor, max drawdown. It then ranks the
strongest *edges* (cells with positive Wilson lower) and strongest *anti-edges*
(cells with Wilson upper below 0.5 and negative expectancy).

This is purely an analysis layer. It changes no state, cannot promote
authority, and never modifies the shadow ledger.

Outputs:
- ``data/inferno_theme_synthesizer.json``
- ``reports/theme_synthesizer_latest.txt``
"""

import argparse
import json
import math
import random
from typing import Any, Iterable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


THEME_ARTIFACT_FILE = DATA_DIR / "inferno_theme_synthesizer.json"
THEME_TEXT_FILE = REPORTS_DIR / "theme_synthesizer_latest.txt"
THEME_STAGE = "theme-synthesizer-research-only"

# Minimum cell sample size for a metric to be reportable. Below this we still
# count the cell but flag it as ``insufficient-data``.
MIN_CELL_SAMPLES = 3

# Win-rate floor used by the production strategy lab. The theme synthesizer
# aligns to the same number so an "edge" here means the same thing as the
# rest of the desk: Wilson lower bound above the lab's win-rate floor with
# 95 percent confidence.
EDGE_WIN_RATE_FLOOR = 0.42

# Bootstrap settings for expectancy CI. We use a small B by default because the
# evidence set is also small; tests pass a seed for determinism.
BOOTSTRAP_RESAMPLES = 400
BOOTSTRAP_SEED = 4242

# IV-rank bucket boundaries (lower-inclusive).
IV_BUCKETS = (("low", 0.0, 20.0), ("mid", 20.0, 50.0), ("high", 50.0, 1000.0))

# Days-to-earnings bucket boundaries (lower-inclusive).
DTE_BUCKETS = (
    ("imminent", -10, 3),
    ("near", 3, 14),
    ("mid", 14, 45),
    ("far", 45, 10_000),
)

# Dimensions we cube over. Order matters for the per-cell label string.
DEFAULT_DIMENSIONS: tuple[str, ...] = (
    "strategy",
    "regime",
    "sector",
    "ivBucket",
    "dteBucket",
)


def _bucket_for(value: float | None, buckets: Iterable[tuple[str, float, float]]) -> str:
    """Return the bucket label for ``value`` or ``unknown`` when missing."""
    if value is None:
        return "unknown"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "unknown"
    for label, lower, upper in buckets:
        if lower <= numeric < upper:
            return label
    return "unknown"


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    """Flatten a shadow record into the fields the cube actually needs.

    Inputs come from ``inferno_shadow_evidence``-style dicts. Tests pass
    pre-flattened records so this function is permissive about shape.
    """
    outcome = record.get("outcome") or {}
    risk = record.get("riskVerdict") or {}
    context = record.get("marketContext") or record.get("context") or {}
    fundamentals = record.get("fundamentals") or {}
    iv_raw = record.get("ivRank")
    if iv_raw is None:
        iv_raw = context.get("ivRank")
    dte_raw = record.get("daysToEarnings")
    if dte_raw is None:
        dte_raw = context.get("daysToEarnings")
    return {
        "ticker": record.get("ticker"),
        "strategy": record.get("strategy") or "Unknown",
        "status": record.get("status"),
        "outcomeStatus": (outcome.get("status") or "open").lower(),
        "estimatedPnl": outcome.get("estimatedPnl"),
        "maxLossDollars": (risk.get("metrics") or {}).get("maxLossDollars")
        or record.get("maxLossDollars"),
        "regime": record.get("regime") or context.get("regime") or "unknown",
        "sector": record.get("sector") or fundamentals.get("sector") or "unknown",
        # Raw values are preserved so downstream policies (e.g. the
        # counterfactual replay) can filter on them, while the bucket
        # labels are kept for the cube indexing.
        "ivRank": iv_raw,
        "daysToEarnings": dte_raw,
        "ivBucket": _bucket_for(iv_raw, IV_BUCKETS),
        "dteBucket": _bucket_for(dte_raw, DTE_BUCKETS),
    }


def _r_units(record: dict[str, Any]) -> float | None:
    """Return PnL normalised to R units (multiples of max loss)."""
    pnl = record.get("estimatedPnl")
    max_loss = record.get("maxLossDollars")
    if pnl is None or not max_loss:
        return None
    try:
        max_loss_f = float(max_loss)
    except (TypeError, ValueError):
        return None
    if max_loss_f <= 0:
        return None
    return float(pnl) / max_loss_f


def wilson_interval(wins: int, total: int, *, z: float = 1.96) -> tuple[float, float]:
    """Compute the symmetric Wilson confidence interval for a proportion.

    Returns ``(lower, upper)``. For ``total == 0`` returns ``(0.0, 1.0)``.
    """
    if total <= 0:
        return 0.0, 1.0
    p = wins / total
    denominator = 1.0 + (z * z) / total
    centre = (p + (z * z) / (2.0 * total)) / denominator
    spread = z * math.sqrt(p * (1.0 - p) / total + (z * z) / (4.0 * total * total))
    spread /= denominator
    return max(0.0, centre - spread), min(1.0, centre + spread)


def bootstrap_mean_ci(
    samples: list[float],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """Bootstrap a mean CI. Returns ``(mean, lower, upper)``.

    For small samples we use percentile bootstrap on resampled means. The seed
    makes this deterministic for tests.
    """
    if not samples:
        return 0.0, 0.0, 0.0
    mean = sum(samples) / len(samples)
    if len(samples) == 1:
        return mean, mean, mean
    rng = random.Random(seed)
    means: list[float] = []
    n = len(samples)
    for _ in range(resamples):
        draw = [samples[rng.randrange(n)] for _ in range(n)]
        means.append(sum(draw) / n)
    means.sort()
    lower_idx = max(0, int((alpha / 2.0) * resamples))
    upper_idx = min(resamples - 1, int((1.0 - alpha / 2.0) * resamples))
    return mean, means[lower_idx], means[upper_idx]


def cell_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the per-cell metric block for a list of normalized records."""
    closed = [r for r in records if r.get("outcomeStatus") == "closed"]
    samples = []
    for record in closed:
        r_units = _r_units(record)
        if r_units is not None:
            samples.append(r_units)

    sample_count = len(samples)
    wins = sum(1 for value in samples if value > 0)
    losses = sum(1 for value in samples if value <= 0)
    wr_lower, wr_upper = wilson_interval(wins, sample_count)
    win_rate = (wins / sample_count) if sample_count else 0.0

    gross_win = sum(value for value in samples if value > 0)
    gross_loss = -sum(value for value in samples if value < 0)
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None

    mean, lower, upper = bootstrap_mean_ci(samples)
    max_dd = min(samples) if samples else 0.0

    sufficient = sample_count >= MIN_CELL_SAMPLES

    return {
        "sampleSize": sample_count,
        "wins": wins,
        "losses": losses,
        "winRate": round(win_rate, 4),
        "winRateLower": round(wr_lower, 4),
        "winRateUpper": round(wr_upper, 4),
        "expectancyMean": round(mean, 4),
        "expectancyLower": round(lower, 4),
        "expectancyUpper": round(upper, 4),
        "profitFactor": round(profit_factor, 4) if profit_factor is not None else None,
        "maxDrawdownR": round(max_dd, 4),
        "sufficient": sufficient,
        "tickerSample": sorted({r.get("ticker") for r in records if r.get("ticker")}),
    }


def _cell_key(record: dict[str, Any], dimensions: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(record.get(dim) or "unknown") for dim in dimensions)


def build_cube(
    records: Iterable[dict[str, Any]],
    *,
    dimensions: tuple[str, ...] = DEFAULT_DIMENSIONS,
) -> dict[tuple[str, ...], dict[str, Any]]:
    """Build the per-cell metric cube. Returns ``{cell_key: metric_block}``."""
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for raw in records:
        normalized = normalize_record(raw)
        key = _cell_key(normalized, dimensions)
        grouped.setdefault(key, []).append(normalized)
    return {key: cell_metrics(items) for key, items in grouped.items()}


def rank_edges(
    cube: dict[tuple[str, ...], dict[str, Any]],
    dimensions: tuple[str, ...],
    *,
    top_n: int = 10,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rank cells into edges and anti-edges.

    An *edge* is a cell with sufficient data, positive expectancy lower, and
    Wilson-lower > 0.5. An *anti-edge* is sufficient data, negative expectancy
    mean, Wilson-upper < 0.5.
    """
    edges: list[dict[str, Any]] = []
    anti_edges: list[dict[str, Any]] = []
    for key, metrics in cube.items():
        if not metrics["sufficient"]:
            continue
        cell = {
            "cell": {dimension: value for dimension, value in zip(dimensions, key)},
            "key": "|".join(key),
            **metrics,
        }
        if metrics["winRateLower"] > EDGE_WIN_RATE_FLOOR and metrics["expectancyLower"] > 0:
            edges.append(cell)
        elif metrics["winRateUpper"] < EDGE_WIN_RATE_FLOOR and metrics["expectancyMean"] < 0:
            anti_edges.append(cell)
    edges.sort(key=lambda c: (c["winRateLower"], c["sampleSize"]), reverse=True)
    anti_edges.sort(key=lambda c: (c["winRateUpper"], -c["sampleSize"]))
    return edges[:top_n], anti_edges[:top_n]


def build_theme_report(
    records: Iterable[dict[str, Any]] | None = None,
    *,
    dimensions: tuple[str, ...] = DEFAULT_DIMENSIONS,
    top_n: int = 10,
) -> dict[str, Any]:
    """Build the full theme report.

    Records can be injected for tests. When omitted we load the shadow ledger
    lazily so importers that don't have yfinance/etc don't pay for it.
    """
    if records is None:
        records = _load_shadow_records()
    record_list = list(records)
    cube = build_cube(record_list, dimensions=dimensions)
    edges, anti_edges = rank_edges(cube, dimensions=dimensions, top_n=top_n)

    sufficient_cells = [
        {
            "cell": {dim: value for dim, value in zip(dimensions, key)},
            "key": "|".join(key),
            **metrics,
        }
        for key, metrics in cube.items()
        if metrics["sufficient"]
    ]

    return {
        "generatedAt": local_now().isoformat(),
        "stage": THEME_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "minCellSamples": MIN_CELL_SAMPLES,
        "dimensions": list(dimensions),
        "totalCells": len(cube),
        "sufficientCells": len(sufficient_cells),
        "edges": edges,
        "antiEdges": anti_edges,
        "sufficientCellsDetail": sufficient_cells[:50],
        "reminders": [
            "research-only; cannot change desk state or thresholds",
            "small samples; treat Wilson bounds as exploratory",
            "cells with N < MIN_CELL_SAMPLES are omitted from rankings",
        ],
    }


def _load_shadow_records() -> list[dict[str, Any]]:
    """Lazy-load shadow records so the module is testable without yfinance."""
    try:
        from inferno_shadow_evidence import SHADOW_EVIDENCE_FILE
    except Exception:
        return []
    if not SHADOW_EVIDENCE_FILE.exists():
        return []
    try:
        payload = json.loads(SHADOW_EVIDENCE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(payload, dict):
        return list(payload.get("items") or payload.get("records") or [])
    if isinstance(payload, list):
        return payload
    return []


def theme_text(payload: dict[str, Any]) -> str:
    """Render the theme report into an operator memo."""
    lines = [
        "Inferno Theme Synthesizer (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Dimensions: {', '.join(payload.get('dimensions') or [])}",
        f"Cells (total / sufficient): {payload.get('totalCells')} / {payload.get('sufficientCells')}",
        f"Min cell samples: {payload.get('minCellSamples')}",
        "",
        "Top edges (positive Wilson lower):",
    ]
    edges = payload.get("edges") or []
    if not edges:
        lines.append("- none with the current sample size")
    for edge in edges:
        lines.append(
            f"- {edge.get('key'):<60} N={edge.get('sampleSize')} "
            f"WR={edge.get('winRate')} [{edge.get('winRateLower')}-{edge.get('winRateUpper')}] "
            f"E={edge.get('expectancyMean')} [{edge.get('expectancyLower')}-{edge.get('expectancyUpper')}] "
            f"PF={edge.get('profitFactor')}"
        )
    lines.extend(["", "Top anti-edges (negative expectancy):"])
    anti = payload.get("antiEdges") or []
    if not anti:
        lines.append("- none with the current sample size")
    for cell in anti:
        lines.append(
            f"- {cell.get('key'):<60} N={cell.get('sampleSize')} "
            f"WR={cell.get('winRate')} [{cell.get('winRateLower')}-{cell.get('winRateUpper')}] "
            f"E={cell.get('expectancyMean')} [{cell.get('expectancyLower')}-{cell.get('expectancyUpper')}] "
            f"PF={cell.get('profitFactor')}"
        )
    lines.extend([
        "",
        "Reminders:",
    ])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_theme_report(payload: dict[str, Any]) -> None:
    """Persist the theme JSON and text artifacts.

    Uses ``inferno_io.atomic_write_*`` so concurrent local writers can't
    drop the artifact under macOS errno-35 deadlocks.
    """
    ensure_dirs()
    atomic_write_json(THEME_ARTIFACT_FILE, payload)
    atomic_write_text(THEME_TEXT_FILE, theme_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a multi-axis evidence cube over closed shadow outcomes and "
            "rank cells into edges and anti-edges. Research-only."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--top-n", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and THEME_TEXT_FILE.exists():
        print(THEME_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_theme_report(top_n=args.top_n)
    save_theme_report(payload)
    print(theme_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
