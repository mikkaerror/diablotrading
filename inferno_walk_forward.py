from __future__ import annotations

"""Inferno Walk-Forward — does the train-half edge survive out-of-sample?

What it does:
    Splits each strategy's chronologically-ordered R-unit stream into a
    *training half* and a *testing half*. Computes Wilson lower bound and
    bootstrap mean CI on each half independently, then reports whether the
    training-half edge survives in the testing half. Survival is the only
    honest sign of a real edge; everything else is in-sample illusion.

What it does NOT do:
    - Anything live. Anything that promotes authority.
    - Mix train and test data in any computation.

Strict contract: research-only, diagnostic-only, never promotable. This
module's job is to *demote* claims, not to promote them.

## The math

Per strategy with chronologically-ordered closed R-units ``x_1, ..., x_n``:

1. Sort by timestamp (ascending). The first ``⌊n/2⌋`` samples are the
   training set ``T``; the remaining samples are the validation set ``V``.

2. Compute on each half independently:

```
μ̂_T, μ̂_T_lo  ← bootstrap mean CI on T
w_T_lo        ← Wilson lower bound on T's win rate
μ̂_V, μ̂_V_lo  ← bootstrap mean CI on V
w_V_lo        ← Wilson lower bound on V's win rate
```

3. Classify the survival outcome:

| Condition                                                  | Verdict        |
|------------------------------------------------------------|----------------|
| ``n < MIN_WF_SAMPLES``                                     | insufficient   |
| ``μ̂_T > 0`` and ``μ̂_V > 0`` and ``|μ̂_V - μ̂_T| ≤ 0.5 σ̂``  | survives       |
| ``μ̂_T > 0`` but ``μ̂_V ≤ 0``                               | reverses       |
| ``μ̂_T > 0`` and ``μ̂_V > 0`` but ``μ̂_V < μ̂_T - 0.5σ̂``     | decays         |
| ``μ̂_T ≤ 0`` and ``μ̂_V ≤ 0``                               | no-edge        |
| ``μ̂_T ≤ 0`` but ``μ̂_V > 0``                               | emerged        |

The 0.5σ̂ band is the practitioner's tolerance for sampling noise. A strict
econometrician would use a paired t-test or Chow test; we prefer the
band-and-CI approach because it's more transparent and the desk operates
on small sample sizes where assumptions of normality are unsafe.

## Why this matters for an options desk

Edge claims that come from a single backtest are nearly always overfit.
The only way to know if an edge is real is to set aside data the
strategy has not seen and check whether it still wins. Walk-forward is
the cheapest, hardest-to-fool version of that check. If a strategy can't
survive a single chronological split, it certainly can't survive the
market.

CLI::

    python3 inferno_walk_forward.py             # run + persist
    python3 inferno_walk_forward.py status      # show last memo
"""

import argparse
import json
import math
import os
import random
from pathlib import Path
from typing import Any, Callable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_theme_synthesizer import _r_units, wilson_interval, bootstrap_mean_ci
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


WALK_FORWARD_FILE = DATA_DIR / "inferno_walk_forward.json"
WALK_FORWARD_TEXT_FILE = REPORTS_DIR / "walk_forward_latest.txt"
WALK_FORWARD_STAGE = "walk-forward-research-only"

MIN_WF_SAMPLES = int(os.environ.get("INFERNO_WF_MIN_SAMPLES", "16"))
DECAY_TOLERANCE_SIGMA = float(os.environ.get("INFERNO_WF_DECAY_SIGMA", "0.5"))
WF_BOOTSTRAP = int(os.environ.get("INFERNO_WF_BOOTSTRAP", "1500"))
WF_SEED = int(os.environ.get("INFERNO_WF_SEED", "20260518"))


# ---------------------------------------------------------------------------
# Pure math.
# ---------------------------------------------------------------------------


def split_chronologically(samples: list[float]) -> tuple[list[float], list[float]]:
    """Return ``(train, validate)`` halves; train is the first ⌊n/2⌋."""
    n = len(samples)
    if n < 2:
        return list(samples), []
    cut = n // 2
    return samples[:cut], samples[cut:]


def _sample_std(samples: list[float]) -> float:
    """Sample standard deviation (ddof=1); 1.0 when n < 2 to avoid div-by-zero."""
    n = len(samples)
    if n < 2:
        return 1.0
    mean = sum(samples) / n
    var = sum((value - mean) ** 2 for value in samples) / (n - 1)
    return math.sqrt(var) if var > 0 else 1.0


def half_stats(samples: list[float]) -> dict[str, Any]:
    """Wilson + bootstrap CI on one half of the stream."""
    n = len(samples)
    if n == 0:
        return {
            "sampleSize": 0,
            "wins": 0,
            "losses": 0,
            "winRate": 0.0,
            "winRateLower": 0.0,
            "winRateUpper": 1.0,
            "meanR": 0.0,
            "meanLower": 0.0,
            "meanUpper": 0.0,
            "std": 1.0,
        }
    wins = sum(1 for value in samples if value > 0)
    losses = n - wins
    win_rate = wins / n
    wr_lo, wr_hi = wilson_interval(wins, n)
    mean, mean_lo, mean_hi = bootstrap_mean_ci(samples, resamples=WF_BOOTSTRAP, seed=WF_SEED)
    return {
        "sampleSize": n,
        "wins": wins,
        "losses": losses,
        "winRate": round(win_rate, 4),
        "winRateLower": round(wr_lo, 4),
        "winRateUpper": round(wr_hi, 4),
        "meanR": round(mean, 4),
        "meanLower": round(mean_lo, 4),
        "meanUpper": round(mean_hi, 4),
        "std": round(_sample_std(samples), 4),
    }


def classify_walk_forward(
    *,
    sample_size: int,
    train_mean: float,
    valid_mean: float,
    pooled_std: float,
    tolerance_sigma: float = DECAY_TOLERANCE_SIGMA,
) -> str:
    """Six-state classification of how the train edge survives the test."""
    if sample_size < MIN_WF_SAMPLES:
        return "insufficient"
    band = tolerance_sigma * pooled_std
    if train_mean > 0 and valid_mean > 0:
        if abs(valid_mean - train_mean) <= band:
            return "survives"
        if valid_mean < train_mean - band:
            return "decays"
        return "survives"  # validation exceeds train (still survives, just stronger)
    if train_mean > 0 and valid_mean <= 0:
        return "reverses"
    if train_mean <= 0 and valid_mean > 0:
        return "emerged"
    return "no-edge"


# ---------------------------------------------------------------------------
# Loader (replaceable in tests).
# ---------------------------------------------------------------------------


def _default_shadow_loader() -> list[dict[str, Any]]:
    path = DATA_DIR / "inferno_shadow_evidence.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows: list[Any] = []
    if isinstance(payload, dict):
        rows = payload.get("records") or payload.get("entries") or payload.get("rows") or []
    elif isinstance(payload, list):
        rows = payload
    return [r for r in rows if isinstance(r, dict)]


def chronologically_ordered_by_strategy(
    records: list[dict[str, Any]],
) -> dict[str, list[float]]:
    """Per-strategy R-unit list, ordered by ``closedAt``/``settledAt``."""
    pairs: dict[str, list[tuple[Any, float]]] = {}
    for record in records:
        outcome = record.get("outcome") or {}
        status = str(outcome.get("status") or record.get("outcomeStatus") or "").lower()
        if status != "closed":
            continue
        r = _r_units(record)
        if r is None:
            r = _r_units(outcome)
        if r is None:
            continue
        ts = (
            outcome.get("closedAt")
            or outcome.get("settledAt")
            or record.get("closedAt")
            or record.get("timestamp")
            or record.get("createdAt")
        )
        strategy = str(record.get("strategy") or "Unknown")
        pairs.setdefault(strategy, []).append((ts or "", float(r)))
    out: dict[str, list[float]] = {}
    for strategy, ps in pairs.items():
        ps.sort(key=lambda p: str(p[0]))
        out[strategy] = [r for _, r in ps]
    return out


# ---------------------------------------------------------------------------
# Pure builder.
# ---------------------------------------------------------------------------


def build_walk_forward(
    *,
    shadow_loader: Callable[[], list[dict[str, Any]]] | None = None,
    tolerance_sigma: float = DECAY_TOLERANCE_SIGMA,
) -> dict[str, Any]:
    """Run walk-forward on every strategy."""
    records = (shadow_loader or _default_shadow_loader)()
    streams = chronologically_ordered_by_strategy(records)

    rows: list[dict[str, Any]] = []
    for strategy, samples in streams.items():
        n = len(samples)
        train, validate = split_chronologically(samples)
        train_stats = half_stats(train)
        valid_stats = half_stats(validate)
        # Pooled standard deviation across both halves (used by the
        # tolerance band).
        pooled_std = _sample_std(samples)
        verdict = classify_walk_forward(
            sample_size=n,
            train_mean=train_stats["meanR"],
            valid_mean=valid_stats["meanR"],
            pooled_std=pooled_std,
            tolerance_sigma=tolerance_sigma,
        )
        rows.append({
            "strategy": strategy,
            "sampleSize": n,
            "trainSize": train_stats["sampleSize"],
            "validateSize": valid_stats["sampleSize"],
            "trainMeanR": train_stats["meanR"],
            "trainMeanLower": train_stats["meanLower"],
            "trainWinRate": train_stats["winRate"],
            "trainWilsonLower": train_stats["winRateLower"],
            "validateMeanR": valid_stats["meanR"],
            "validateMeanLower": valid_stats["meanLower"],
            "validateWinRate": valid_stats["winRate"],
            "validateWilsonLower": valid_stats["winRateLower"],
            "pooledStd": round(pooled_std, 4),
            "toleranceBand": round(tolerance_sigma * pooled_std, 4),
            "edgeShift": round(valid_stats["meanR"] - train_stats["meanR"], 4),
            "verdict": verdict,
        })

    rows.sort(
        key=lambda r: (
            # Reverses → decays → survives → emerged → no-edge → insufficient.
            {"reverses": 0, "decays": 1, "survives": 2, "emerged": 3, "no-edge": 4, "insufficient": 5}.get(r["verdict"], 6),
            -r["sampleSize"], r["strategy"],
        )
    )

    survives = [r for r in rows if r["verdict"] == "survives"]
    decays = [r for r in rows if r["verdict"] == "decays"]
    reverses = [r for r in rows if r["verdict"] == "reverses"]
    emerged = [r for r in rows if r["verdict"] == "emerged"]
    no_edge = [r for r in rows if r["verdict"] == "no-edge"]
    insufficient = [r for r in rows if r["verdict"] == "insufficient"]

    if not rows:
        verdict = "no-evidence"
        narrative = "No closed shadow records — walk-forward cannot run."
    elif reverses:
        verdict = "edge-reversal"
        names = ", ".join(r["strategy"] for r in reverses[:3])
        narrative = (
            f"{len(reverses)} strategy/strategies have positive train mean but "
            f"non-positive validate mean: {names}. Authority must hold."
        )
    elif decays:
        verdict = "edge-decay"
        narrative = (
            f"{len(decays)} strategy/strategies show validate mean below the "
            f"train mean − {tolerance_sigma}σ̂ band. Decay suspected; investigate."
        )
    elif survives:
        verdict = "edge-survives"
        narrative = (
            f"{len(survives)} strategy/strategies survive walk-forward within "
            f"the {tolerance_sigma}σ̂ tolerance. {len(emerged)} emerged in validate; "
            f"{len(no_edge)} are no-edge in both halves."
        )
    elif emerged:
        verdict = "emerging"
        narrative = (
            f"{len(emerged)} strategy/strategies only show edge in the validate "
            "half. Could be real or could be noise — wait for more data."
        )
    elif no_edge:
        verdict = "no-edge-detected"
        narrative = (
            f"All {len(no_edge)} strategy/strategies are no-edge in both halves. "
            "The paper loop has not yet produced a candidate."
        )
    else:
        verdict = "insufficient-overall"
        narrative = (
            f"Every strategy is below {MIN_WF_SAMPLES} samples. Need more closed "
            "outcomes before walk-forward becomes meaningful."
        )

    return {
        "generatedAt": local_now().isoformat(),
        "stage": WALK_FORWARD_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "method": "chronological-split-with-bootstrap-CI",
        "minSamples": MIN_WF_SAMPLES,
        "toleranceSigma": tolerance_sigma,
        "bootstrapResamples": WF_BOOTSTRAP,
        "strategyCount": len(rows),
        "survivesCount": len(survives),
        "decaysCount": len(decays),
        "reversesCount": len(reverses),
        "emergedCount": len(emerged),
        "noEdgeCount": len(no_edge),
        "insufficientCount": len(insufficient),
        "rows": rows,
        "reminders": [
            "walk-forward never mixes train and validate data",
            "tolerance band is ±0.5σ̂ by default; lower σ̂ multiple is stricter",
            "reverses + decays both veto promotion regardless of point estimates",
        ],
    }


def walk_forward_text(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno Walk-Forward (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Method: {payload.get('method')}  tolerance={payload.get('toleranceSigma')}σ̂",
        f"Verdict: {payload.get('verdict')}",
        f"Strategies: {payload.get('strategyCount')}  "
        f"survives={payload.get('survivesCount')}  "
        f"decays={payload.get('decaysCount')}  "
        f"reverses={payload.get('reversesCount')}  "
        f"emerged={payload.get('emergedCount')}  "
        f"no-edge={payload.get('noEdgeCount')}  "
        f"insufficient={payload.get('insufficientCount')}",
        "",
        f"Narrative: {payload.get('narrative')}",
    ]
    rows = payload.get("rows") or []
    if rows:
        lines.extend(["", "Per-strategy walk-forward:"])
        lines.append(
            f"{'Strategy':<22} {'N':>4} {'nT':>4} {'nV':>4} "
            f"{'μT':>7} {'μV':>7} {'Δμ':>7} {'wrT':>5} {'wrV':>5} {'Verdict'}"
        )
        for row in rows:
            lines.append(
                f"{str(row['strategy'])[:22]:<22} "
                f"{row['sampleSize']:>4} "
                f"{row['trainSize']:>4} "
                f"{row['validateSize']:>4} "
                f"{row['trainMeanR']:>+7.3f} "
                f"{row['validateMeanR']:>+7.3f} "
                f"{row['edgeShift']:>+7.3f} "
                f"{row['trainWinRate']:>5.2f} "
                f"{row['validateWinRate']:>5.2f} "
                f"{row['verdict']}"
            )
    lines.extend(["", "Thresholds:"])
    lines.append(f"- minSamples:        n >= {payload.get('minSamples')}")
    lines.append(f"- tolerance band:    ±{payload.get('toleranceSigma')} σ̂")
    lines.extend(["", "Reminders:"])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_walk_forward(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(WALK_FORWARD_FILE, payload)
    atomic_write_text(WALK_FORWARD_TEXT_FILE, walk_forward_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Chronological walk-forward validation across every strategy's "
            "R-unit stream. Research-only; never promotable."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and WALK_FORWARD_TEXT_FILE.exists():
        print(WALK_FORWARD_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_walk_forward()
    save_walk_forward(payload)
    print(walk_forward_text(payload))
    if payload.get("verdict") in {"edge-reversal", "edge-decay"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
