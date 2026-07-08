from __future__ import annotations

"""Inferno Kelly Sizing — fractional Kelly with conservative confidence bounds.

What it does:
    For every strategy with closed paper outcomes, compute the Kelly
    fraction ``f* = μ / σ²`` from bootstrap-stabilised mean R-units and
    sample variance. Then compute a *conservative* Kelly using the lower
    confidence bound on the mean and the upper confidence bound on the
    variance, cap the result at quarter-Kelly, and aggregate across
    strategies with the desk's existing risk-unit ceiling.

What it does NOT do:
    - Place trades. Open broker windows. Touch the authority manifest.
    - Override the operator's existing sizing policy. The output is a
      *recommendation* the capital allocator may consume.

Strict contract: research-only, diagnostic-only, never promotable.

## The math

For a strategy with closed-outcome R-units ``X = (x_1, ..., x_n)``:

1. Bootstrap the mean and variance::

       μ̂_lo, μ̂_hi  ← 95% percentile-bootstrap CI on mean(X)
       σ̂²_lo, σ̂²_hi ← 95% percentile-bootstrap CI on var(X)  (ddof=1)

2. Point-estimate Kelly fraction::

       f_point = mean(X) / var(X)             if var(X) > 0
       f_point = 0                            otherwise

3. Conservative Kelly fraction (the one we report) uses the **lower**
   bound on the mean and the **upper** bound on the variance::

       f_conservative = μ̂_lo / σ̂²_hi          if μ̂_lo > 0 and σ̂²_hi > 0
       f_conservative = 0                     otherwise

   This is the version that survives a 95% adversarial scenario on both
   moments simultaneously. It is meaningfully smaller than the point
   estimate when sample size is small — exactly when we want to be
   smaller.

4. Cap at quarter-Kelly::

       f_capped = min(f_conservative, MAX_KELLY_FRACTION)

   Default ``MAX_KELLY_FRACTION = 0.25``. Quarter-Kelly is the standard
   practitioner's hedge against estimation error (Thorp 2006).

5. Per-strategy verdict::

       mean(X) <= 0                 → no-position
       var(X) == 0                  → degenerate (single-point distribution)
       f_conservative <= 0          → marginal
       f_capped >= MAX_KELLY        → cap-limited (we wanted more risk than we'll allow)
       else                         → sized

6. Portfolio aggregation::

       total_recommended_units = min(Σ f_capped, MAX_DAILY_RISK_UNITS)

   So even if every strategy clears its Kelly gate, the total exposure
   stays under the global ceiling.

## Why bootstrap-conservative Kelly

Naive Kelly applied to noisy μ̂ overshoots dramatically. A point estimate
of `mean=0.4R, var=1.0R²` gives `f*=0.4` — 40% of bankroll. But the 95%
lower bound on a small sample might be `mean_lo=0.1R` and the upper bound
on variance might be `var_hi=1.6R²`, giving `f_conservative=0.062` —
about a sixth as much risk. That's the right asymmetry: under-bet when
the data is thin.

CLI::

    python3 inferno_kelly_sizing.py             # run + persist
    python3 inferno_kelly_sizing.py status      # show last memo
"""

import argparse
import json
import os
import random
from pathlib import Path
from typing import Any, Callable

from inferno_config import local_now
from inferno_math_config import (
    MAX_DAILY_RISK_UNITS as DEFAULT_MAX_DAILY_RISK_UNITS,
    MAX_KELLY_FRACTION as DEFAULT_MAX_KELLY_FRACTION,
)
from inferno_io import atomic_write_json, atomic_write_text
from inferno_theme_synthesizer import _r_units
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


KELLY_SIZING_FILE = DATA_DIR / "inferno_kelly_sizing.json"
KELLY_SIZING_TEXT_FILE = REPORTS_DIR / "kelly_sizing_latest.txt"
KELLY_SIZING_STAGE = "kelly-sizing-research-only"

MIN_KELLY_SAMPLES = int(os.environ.get("INFERNO_KELLY_MIN_SAMPLES", "8"))
MAX_KELLY_FRACTION = float(os.environ.get("INFERNO_KELLY_MAX_FRACTION", str(DEFAULT_MAX_KELLY_FRACTION)))
MAX_DAILY_RISK_UNITS = float(os.environ.get("INFERNO_KELLY_MAX_DAILY_RISK_UNITS", str(DEFAULT_MAX_DAILY_RISK_UNITS)))
KELLY_BOOTSTRAP_RESAMPLES = int(os.environ.get("INFERNO_KELLY_BOOTSTRAP", "2000"))
KELLY_BOOTSTRAP_SEED = int(os.environ.get("INFERNO_KELLY_SEED", "20260514"))


# ---------------------------------------------------------------------------
# Pure math.
# ---------------------------------------------------------------------------


def sample_variance(samples: list[float]) -> float:
    """Unbiased sample variance (ddof=1). Returns 0 for n < 2."""
    n = len(samples)
    if n < 2:
        return 0.0
    mean = sum(samples) / n
    return sum((value - mean) ** 2 for value in samples) / (n - 1)


def bootstrap_moment_ci(
    samples: list[float],
    moment: Callable[[list[float]], float],
    *,
    resamples: int = KELLY_BOOTSTRAP_RESAMPLES,
    seed: int = KELLY_BOOTSTRAP_SEED,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """Percentile-bootstrap CI on an arbitrary moment functional.

    Returns ``(point, lower, upper)``. For n < 2 the bounds collapse to
    the point estimate to keep callers from dividing by zero on
    pathological inputs.
    """
    n = len(samples)
    if n == 0:
        return 0.0, 0.0, 0.0
    point = moment(samples)
    if n == 1:
        return point, point, point
    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(resamples):
        sample = [samples[rng.randrange(n)] for _ in range(n)]
        draws.append(moment(sample))
    draws.sort()
    lower_idx = max(0, int((alpha / 2.0) * resamples))
    upper_idx = min(resamples - 1, int((1.0 - alpha / 2.0) * resamples))
    return point, draws[lower_idx], draws[upper_idx]


def kelly_fraction(mean: float, variance: float) -> float:
    """Point-estimate Kelly fraction. Returns 0 when math doesn't apply."""
    if variance <= 0 or mean <= 0:
        return 0.0
    return mean / variance


def conservative_kelly(
    mean_lower: float,
    variance_upper: float,
) -> float:
    """Conservative Kelly using lower-bound mean / upper-bound variance.

    Returns 0 when either bound makes the fraction non-positive. This is
    the asymmetric-bound version that survives a 95% adversarial scenario
    on both moments simultaneously.
    """
    if mean_lower <= 0 or variance_upper <= 0:
        return 0.0
    return mean_lower / variance_upper


def classify_strategy(
    *,
    sample_size: int,
    mean: float,
    variance: float,
    f_conservative: float,
    f_capped: float,
) -> str:
    if sample_size < MIN_KELLY_SAMPLES:
        return "insufficient"
    if mean <= 0:
        return "no-position"
    if variance <= 0:
        return "degenerate"
    if f_conservative <= 0:
        return "marginal"
    if f_capped >= MAX_KELLY_FRACTION:
        return "cap-limited"
    return "sized"


# ---------------------------------------------------------------------------
# Shadow loader (replaceable in tests).
# ---------------------------------------------------------------------------


def _default_shadow_loader() -> list[dict[str, Any]]:
    """Best-effort load of the shadow evidence records."""
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


def group_closed_by_strategy(records: list[dict[str, Any]]) -> dict[str, list[float]]:
    """Partition closed shadow records into per-strategy R-unit lists."""
    out: dict[str, list[float]] = {}
    for record in records:
        outcome = (record.get("outcome") or {})
        status = str(outcome.get("status") or record.get("outcomeStatus") or "").lower()
        if status != "closed":
            continue
        r = _r_units(record)
        if r is None:
            r = _r_units(outcome)
        if r is None:
            continue
        strategy = str(record.get("strategy") or "Unknown")
        out.setdefault(strategy, []).append(float(r))
    return out


# ---------------------------------------------------------------------------
# Pure builder.
# ---------------------------------------------------------------------------


def build_kelly_sizing(
    *,
    shadow_loader: Callable[[], list[dict[str, Any]]] | None = None,
    resamples: int = KELLY_BOOTSTRAP_RESAMPLES,
    seed: int = KELLY_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Compute Kelly recommendations across every strategy."""
    records = (shadow_loader or _default_shadow_loader)()
    by_strategy = group_closed_by_strategy(records)

    rows: list[dict[str, Any]] = []
    for strategy, samples in by_strategy.items():
        n = len(samples)
        mean_point, mean_lo, mean_hi = bootstrap_moment_ci(
            samples,
            lambda x: sum(x) / len(x),
            resamples=resamples,
            seed=seed,
        )
        var_point, var_lo, var_hi = bootstrap_moment_ci(
            samples,
            sample_variance,
            resamples=resamples,
            seed=seed,
        )
        f_point = kelly_fraction(mean_point, var_point)
        f_conservative = conservative_kelly(mean_lo, var_hi)
        f_capped = min(f_conservative, MAX_KELLY_FRACTION)
        verdict = classify_strategy(
            sample_size=n,
            mean=mean_point,
            variance=var_point,
            f_conservative=f_conservative,
            f_capped=f_capped,
        )
        rows.append({
            "strategy": strategy,
            "sampleSize": n,
            "meanR": round(mean_point, 4),
            "meanLower": round(mean_lo, 4),
            "meanUpper": round(mean_hi, 4),
            "varianceR": round(var_point, 4),
            "varianceLower": round(var_lo, 4),
            "varianceUpper": round(var_hi, 4),
            "kellyFractionPoint": round(f_point, 4),
            "kellyFractionConservative": round(f_conservative, 4),
            "kellyFractionCapped": round(f_capped, 4),
            "verdict": verdict,
        })

    rows.sort(key=lambda r: (-r["kellyFractionCapped"], -r["sampleSize"], r["strategy"]))

    # Aggregate sized + cap-limited strategies under the global risk ceiling.
    sized_sum = sum(
        r["kellyFractionCapped"]
        for r in rows
        if r["verdict"] in {"sized", "cap-limited"}
    )
    total_recommended = min(sized_sum, MAX_DAILY_RISK_UNITS)
    over_ceiling = sized_sum > MAX_DAILY_RISK_UNITS

    sized = [r for r in rows if r["verdict"] == "sized"]
    cap_limited = [r for r in rows if r["verdict"] == "cap-limited"]
    marginal = [r for r in rows if r["verdict"] == "marginal"]
    insufficient = [r for r in rows if r["verdict"] == "insufficient"]

    if not rows:
        verdict = "no-evidence"
        narrative = (
            "No closed shadow records yet — Kelly sizing has nothing to size. "
            "Keep building paper evidence."
        )
    elif over_ceiling:
        verdict = "ceiling-binding"
        narrative = (
            f"Σ Kelly = {sized_sum:.2f} risk units exceeds the global ceiling of "
            f"{MAX_DAILY_RISK_UNITS:.2f}. Total recommended is clipped to the ceiling. "
            f"{len(sized) + len(cap_limited)} strategy/strategies sized; "
            f"{len(marginal)} marginal."
        )
    elif sized:
        verdict = "sizing-available"
        narrative = (
            f"{len(sized)} strategy/strategies cleared conservative Kelly; "
            f"{len(cap_limited)} hit the {MAX_KELLY_FRACTION} cap; "
            f"total recommended = {total_recommended:.2f} risk units."
        )
    elif cap_limited:
        verdict = "cap-only"
        narrative = (
            f"Every Kelly-positive strategy hit the {MAX_KELLY_FRACTION} cap. "
            f"Total recommended = {total_recommended:.2f} risk units."
        )
    else:
        verdict = "no-positions"
        narrative = (
            f"No strategy cleared conservative Kelly. Likely causes: mean R-units "
            f"non-positive, lower bound non-positive, or sample size below "
            f"{MIN_KELLY_SAMPLES}. {len(marginal)} marginal, "
            f"{len(insufficient)} insufficient."
        )

    return {
        "generatedAt": local_now().isoformat(),
        "stage": KELLY_SIZING_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "method": "bootstrap-conservative-quarter-kelly",
        "bootstrapResamples": resamples,
        "minSamples": MIN_KELLY_SAMPLES,
        "maxKellyFraction": MAX_KELLY_FRACTION,
        "maxDailyRiskUnits": MAX_DAILY_RISK_UNITS,
        "strategyCount": len(rows),
        "sizedCount": len(sized),
        "capLimitedCount": len(cap_limited),
        "marginalCount": len(marginal),
        "insufficientCount": len(insufficient),
        "sumKellyCapped": round(sized_sum, 4),
        "totalRecommendedRiskUnits": round(total_recommended, 4),
        "ceilingBinding": over_ceiling,
        "rows": rows,
        "reminders": [
            "conservative Kelly uses 95% lower-mean / upper-variance bounds",
            "global risk ceiling clips total exposure regardless of Kelly sum",
            "outputs are recommendations; the capital allocator is the gate",
        ],
    }


def kelly_text(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno Kelly Sizing (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Method: {payload.get('method')}  resamples={payload.get('bootstrapResamples')}",
        f"Verdict: {payload.get('verdict')}",
        f"Strategies: {payload.get('strategyCount')}  "
        f"sized={payload.get('sizedCount')}  "
        f"cap-limited={payload.get('capLimitedCount')}  "
        f"marginal={payload.get('marginalCount')}  "
        f"insufficient={payload.get('insufficientCount')}",
        f"Sum capped Kelly: {payload.get('sumKellyCapped')}  "
        f"ceiling: {payload.get('maxDailyRiskUnits')}  "
        f"binding: {payload.get('ceilingBinding')}",
        f"Total recommended risk units: {payload.get('totalRecommendedRiskUnits')}",
        "",
        f"Narrative: {payload.get('narrative')}",
    ]
    rows = payload.get("rows") or []
    if rows:
        lines.extend(["", "Per-strategy Kelly:"])
        lines.append(
            f"{'Strategy':<22} {'N':>4} {'meanR':>8} "
            f"{'mLo':>8} {'varR':>8} {'varHi':>8} "
            f"{'f_pt':>7} {'f_con':>7} {'f_cap':>7} {'Verdict'}"
        )
        for row in rows:
            lines.append(
                f"{str(row['strategy'])[:22]:<22} "
                f"{row['sampleSize']:>4} "
                f"{row['meanR']:>+8.3f} "
                f"{row['meanLower']:>+8.3f} "
                f"{row['varianceR']:>8.3f} "
                f"{row['varianceUpper']:>8.3f} "
                f"{row['kellyFractionPoint']:>7.3f} "
                f"{row['kellyFractionConservative']:>7.3f} "
                f"{row['kellyFractionCapped']:>7.3f} "
                f"{row['verdict']}"
            )
    lines.extend(["", "Thresholds:"])
    lines.append(f"- minSamples:        n >= {payload.get('minSamples')}")
    lines.append(f"- maxKellyFraction:  capped at {payload.get('maxKellyFraction')}")
    lines.append(f"- maxDailyRiskUnits: portfolio sum capped at {payload.get('maxDailyRiskUnits')}")
    lines.extend(["", "Reminders:"])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_kelly_sizing(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(KELLY_SIZING_FILE, payload)
    atomic_write_text(KELLY_SIZING_TEXT_FILE, kelly_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compute conservative quarter-Kelly fractional sizing across every "
            "strategy with closed paper outcomes. Research-only; never promotable."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and KELLY_SIZING_TEXT_FILE.exists():
        print(KELLY_SIZING_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_kelly_sizing()
    save_kelly_sizing(payload)
    print(kelly_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
