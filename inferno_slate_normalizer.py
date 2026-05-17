from __future__ import annotations

"""Inferno Slate Normalizer — scale-invariant percentile ranks.

What it does:
    Reads the current slate snapshot and adds *percentile rank* columns
    alongside the raw scores. Percentile rank is scale-invariant: a score
    of 2.19 on a 0–10 axis maps to the same percentile as 21.9 on a 0–100
    axis. This lets the conviction gates be expressed as "top N percent
    of the slate" instead of "above absolute threshold X" — which is how
    every real quant desk actually does cross-sectional ranking.

What this fixes:
    The diagnostic on the live 143-name slate revealed Ready Score values
    in the 0–10 range while the conviction gate was set at ≥ 72. Result:
    every name fails the gate forever. Rather than chase the broken
    multiplier upstream (it lives in the Backtest project), normalize at
    the consumer. Top 10% of the slate is the top 10% regardless of
    whether the producer ever gets its scale right.

What it does NOT do:
    - Modify the source snapshot or the sheet. Reads only.
    - Promote authority. The output is a normalized snapshot file that
      downstream gates may consume; nothing changes about the manifest.

Strict contract: research-only, diagnostic-only, never promotable.

## The math (percentile rank — Cover & Thomas appendix style)

For a column of values ``x_1, ..., x_n``, the percentile rank of value
``x_i`` is::

    rank(x_i) = 100 · (count_below + 0.5 · count_equal) / n

where ``count_below`` is the number of values strictly less than ``x_i``
and ``count_equal`` is the number tied with it (including ``x_i``
itself). This is the *average* of competition rank and dense rank —
robust to ties, well-defined on any scale.

Null values are excluded from the ranking and receive ``rank = None``.

We rank: ``readyScore``, ``valueScore``, ``momentumScore``,
``squeezeScore``, plus IV Rank. We then compose a single
``compositeRank`` via the geometric mean of the components that are
present, mirroring `inferno_evidence_strength` — the weakest component
caps the composite (a useful asymmetry when scoring trade quality).

## Gate translation

The five live conviction gates expressed in percentile-rank terms:

| Live gate                         | Percentile-rank equivalent |
|-----------------------------------|----------------------------|
| readyScore ≥ 72 (absolute)        | readyRank ≥ percentile     |
| confidence ≥ 2 of 3               | unchanged (categorical)    |
| daysUntilEarnings ≤ 21            | unchanged (intent: catalyst window) |
| setupRec not in {Avoid}           | unchanged (categorical)    |
| signalTrigger present             | unchanged (categorical)    |

The default ``GATE_PERCENTILE`` threshold is **80** (top 20% of slate).
For Buffett/Ackman-style picky entry, raise to **90** (top 10%) or
**95** (top 5%).

CLI::

    python3 inferno_slate_normalizer.py             # run + persist
    python3 inferno_slate_normalizer.py status      # show last memo
    python3 inferno_slate_normalizer.py --percentile 90   # show top-10% summary
"""

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any, Callable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


SLATE_NORMALIZED_FILE = DATA_DIR / "inferno_slate_normalized.json"
SLATE_NORMALIZED_TEXT_FILE = REPORTS_DIR / "slate_normalized_latest.txt"
SLATE_NORMALIZER_STAGE = "slate-normalizer-research-only"

# Default percentile threshold for the "Ready" gate. 80 ≡ top 20%.
# Raise for stricter selection: 90 ≡ top 10%, 95 ≡ top 5%.
GATE_PERCENTILE = float(os.environ.get("INFERNO_GATE_PERCENTILE", "80"))

# Score fields we percentile-rank, in the order they should appear.
RANKABLE_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("readyScore",    ("readyScore", "Ready Score")),
    ("valueScore",    ("valueScore", "Value Score")),
    ("momentumScore", ("momentumScore", "Momentum Score")),
    ("squeezeScore",  ("squeezeScore", "Squeeze Score")),
    ("ivRank",        ("ivRank", "IV Rank")),
)


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _extract(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key in row:
            return _coerce_float(row[key])
    return None


# ---------------------------------------------------------------------------
# Pure math.
# ---------------------------------------------------------------------------


def percentile_ranks(values: list[float | None]) -> list[float | None]:
    """Return percentile rank for each value, preserving None.

    Uses the *averaged* percentile-rank convention:

        rank(x) = 100 · (#below + 0.5 · #equal) / n

    where ``n`` is the count of non-null values. Tied values get
    identical ranks (the midpoint of their tie group).
    """
    non_null = [v for v in values if v is not None]
    n = len(non_null)
    if n == 0:
        return [None] * len(values)

    sorted_values = sorted(non_null)
    out: list[float | None] = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        # Binary-search-equivalent in stdlib via list ops.
        below = sum(1 for x in sorted_values if x < v)
        equal = sum(1 for x in sorted_values if x == v)
        rank = 100.0 * (below + 0.5 * equal) / n
        out.append(round(rank, 2))
    return out


def composite_rank(component_ranks: list[float | None]) -> float | None:
    """Geometric mean of active (non-None) component ranks, on the
    standard 0–100 scale. Mirrors `inferno_evidence_strength`: the
    weakest component caps the composite.
    """
    active = [r for r in component_ranks if r is not None and r > 0]
    if not active:
        return None
    log_sum = sum(math.log(r) for r in active)
    return round(math.exp(log_sum / len(active)), 2)


# ---------------------------------------------------------------------------
# Slate I/O.
# ---------------------------------------------------------------------------


def _load_snapshot() -> dict[str, Any]:
    path = DATA_DIR / "latest_snapshot.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _candidate_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("rows", "scoredRows", "items", "tickers"):
        value = snapshot.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


# ---------------------------------------------------------------------------
# Pure builder.
# ---------------------------------------------------------------------------


def build_normalized(
    *,
    snapshot_loader: Callable[[], dict[str, Any]] | None = None,
    gate_percentile: float = GATE_PERCENTILE,
) -> dict[str, Any]:
    """Rank every score column cross-sectionally and emit a normalized snapshot."""
    snapshot = (snapshot_loader or _load_snapshot)()
    rows = _candidate_rows(snapshot)
    if not rows:
        return {
            "generatedAt": local_now().isoformat(),
            "stage": SLATE_NORMALIZER_STAGE,
            "diagnosticOnly": True,
            "researchOnly": True,
            "promotable": False,
            "verdict": "no-evidence",
            "narrative": "No slate snapshot to normalize.",
            "slateSize": 0,
            "gatePercentile": gate_percentile,
            "rows": [],
            "passingRanked": [],
        }

    # Extract each rankable column and compute ranks.
    column_values: dict[str, list[float | None]] = {}
    for canonical_name, alias_keys in RANKABLE_FIELDS:
        column_values[canonical_name] = [_extract(r, alias_keys) for r in rows]

    column_ranks: dict[str, list[float | None]] = {
        name: percentile_ranks(values) for name, values in column_values.items()
    }

    normalized_rows: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        ticker = str(
            row.get("ticker") or row.get("Ticker") or row.get("symbol") or "?"
        ).strip()
        component_ranks = [
            column_ranks["readyScore"][i],
            column_ranks["valueScore"][i],
            column_ranks["momentumScore"][i],
            column_ranks["squeezeScore"][i],
        ]
        composite = composite_rank(component_ranks)
        normalized_rows.append({
            "ticker": ticker,
            "readyScoreRaw": column_values["readyScore"][i],
            "readyRank": column_ranks["readyScore"][i],
            "valueRank": column_ranks["valueScore"][i],
            "momentumRank": column_ranks["momentumScore"][i],
            "squeezeRank": column_ranks["squeezeScore"][i],
            "ivRankRaw": column_values["ivRank"][i],
            "ivPercentileRank": column_ranks["ivRank"][i],
            "compositeRank": composite,
            "passesReadyPercentileGate": (
                column_ranks["readyScore"][i] is not None
                and column_ranks["readyScore"][i] >= gate_percentile
            ),
        })

    # Stable sort by composite rank descending, then by readyRank desc.
    normalized_rows.sort(
        key=lambda r: (
            -(r.get("compositeRank") or 0.0),
            -(r.get("readyRank") or 0.0),
            r["ticker"],
        )
    )
    passing = [r for r in normalized_rows if r["passesReadyPercentileGate"]]

    if not passing:
        verdict = "no-passers"
        narrative = (
            f"No name in {len(rows)}-ticker slate cleared the top "
            f"{100 - gate_percentile:.0f}% by Ready percentile rank. "
            "Either the gate is too strict or the slate is genuinely thin."
        )
    elif len(passing) <= 3:
        verdict = "tight-shortlist"
        narrative = (
            f"{len(passing)} name(s) cleared the top {100 - gate_percentile:.0f}% "
            "by Ready percentile rank. Tight shortlist — review each one carefully."
        )
    else:
        verdict = "ranked"
        narrative = (
            f"{len(passing)} of {len(rows)} names rank in the top "
            f"{100 - gate_percentile:.0f}% by Ready. Top of the list is the "
            "strongest *relative* candidate regardless of absolute scale."
        )

    return {
        "generatedAt": local_now().isoformat(),
        "stage": SLATE_NORMALIZER_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "method": "averaged-percentile-rank-cross-sectional",
        "slateSize": len(rows),
        "gatePercentile": gate_percentile,
        "rows": normalized_rows,
        "passingRanked": [r["ticker"] for r in passing[:20]],
        "passingCount": len(passing),
        "reminders": [
            "percentile rank is scale-invariant; works regardless of raw scale",
            "top N% gate is a relative filter — there's always a top-N% even on bad days",
            "compositeRank is the geometric mean of available component ranks",
        ],
    }


def normalized_text(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno Slate Normalizer (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Method: {payload.get('method')}",
        f"Verdict: {payload.get('verdict')}",
        f"Slate size: {payload.get('slateSize')}  "
        f"gate: top {100 - payload.get('gatePercentile', 80):.0f}% "
        f"(readyRank >= {payload.get('gatePercentile')})  "
        f"passing: {payload.get('passingCount', 0)}",
        "",
        f"Narrative: {payload.get('narrative')}",
        "",
    ]
    rows = payload.get("rows") or []
    if rows:
        # Show the top 20 by composite rank.
        lines.append("Top 20 by composite rank:")
        lines.append(
            f"{'Ticker':<8} {'Comp':>6} {'ReadyR':>7} {'ValueR':>7} "
            f"{'MomR':>6} {'SqzR':>6} {'IVR':>6} {'ReadyRaw':>10} {'Gate'}"
        )
        for r in rows[:20]:
            comp = r.get("compositeRank")
            ready_r = r.get("readyRank")
            value_r = r.get("valueRank")
            mom_r = r.get("momentumRank")
            sqz_r = r.get("squeezeRank")
            iv_r = r.get("ivPercentileRank")
            ready_raw = r.get("readyScoreRaw")
            lines.append(
                f"{str(r.get('ticker'))[:8]:<8} "
                f"{comp if comp is not None else '-':>6} "
                f"{ready_r if ready_r is not None else '-':>7} "
                f"{value_r if value_r is not None else '-':>7} "
                f"{mom_r if mom_r is not None else '-':>6} "
                f"{sqz_r if sqz_r is not None else '-':>6} "
                f"{iv_r if iv_r is not None else '-':>6} "
                f"{ready_raw if ready_raw is not None else '-':>10} "
                f"{'PASS' if r.get('passesReadyPercentileGate') else '-'}"
            )
        lines.append("")
    lines.extend([
        "Thresholds:",
        f"  - readyRank gate: >= {payload.get('gatePercentile')} (top "
        f"{100 - payload.get('gatePercentile', 80):.0f}% of slate)",
        "  - compositeRank: geometric mean of available component ranks",
        "",
        "Reminders:",
    ])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_normalized(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(SLATE_NORMALIZED_FILE, payload)
    atomic_write_text(SLATE_NORMALIZED_TEXT_FILE, normalized_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compute scale-invariant percentile ranks over the slate so the "
            "conviction gates work regardless of the upstream score scale."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument(
        "--percentile", type=float, default=GATE_PERCENTILE,
        help=f"Ready-rank gate percentile (default {GATE_PERCENTILE}; "
             "80 = top 20%%, 90 = top 10%%, 95 = top 5%%).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and SLATE_NORMALIZED_TEXT_FILE.exists():
        print(SLATE_NORMALIZED_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    if not (0 <= args.percentile <= 100):
        print(f"--percentile must be in [0, 100], got {args.percentile}")
        return 2
    payload = build_normalized(gate_percentile=args.percentile)
    save_normalized(payload)
    print(normalized_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
