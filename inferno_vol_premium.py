from __future__ import annotations

"""Inferno Vol Premium — IV-bucket volatility risk premium discriminator.

What it does:
    Bucketise closed paper outcomes by ``(strategyVolDirection × ivBucket)``
    and measure whether the desk's edge on short-vol strategies is
    concentrated in high-IV setups (the textbook VRP signature) and whether
    long-vol edge concentrates in low-IV setups (the mirror image).

    The "discriminator" is the difference in mean R-units across two
    buckets. We bootstrap a 95% CI on the discriminator. If the CI excludes
    zero, the desk has statistically meaningful evidence that vol-bucket
    selection is itself an edge.

What it does NOT do:
    - Trade. Touch authority. Modify paper ledger. Open broker windows.

Strict contract: research-only, diagnostic-only, never promotable.

## The math

For each closed record ``r`` we extract:

- ``r_units(r)``      — outcome in R-multiples of max loss
- ``iv_rank(r)``      — pre-trade implied-volatility rank, 0..100
- ``strategy(r)``     — short-vol / long-vol / vega-neutral

IV buckets::

    low  = ivRank in [0, 33)
    mid  = ivRank in [33, 66)
    high = ivRank in [66, 100]

Strategy vol direction is inferred from the strategy name. The mapping is
configurable via ``INFERNO_VRP_VOL_TAGS`` env var.

For each direction (short-vol, long-vol) we compute::

    high_mean = mean R in (direction, high IV)
    low_mean  = mean R in (direction, low IV)
    discriminator = high_mean - low_mean    (short-vol)
    discriminator = low_mean - high_mean    (long-vol, mirror)

Bootstrap discriminator CI by paired-bucket resampling. If the 95% lower
bound is positive, the bucket effect is statistically real at that
confidence level. Verdict ladder::

    discriminator_lo >  0         → vrp-real
    discriminator_lo <= 0 < hi    → vrp-uncertain
    discriminator_hi <= 0         → vrp-absent
    sample size below minimum     → insufficient

The desk does not place short-vol bets just because VRP is real — that's
the lab's job. This module's output is *one factor* the lab and the Kelly
sizer may consider.

CLI::

    python3 inferno_vol_premium.py             # run + persist
    python3 inferno_vol_premium.py status      # show last memo
"""

import argparse
import json
import os
import random
from pathlib import Path
from typing import Any, Callable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_theme_synthesizer import _r_units
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


VOL_PREMIUM_FILE = DATA_DIR / "inferno_vol_premium.json"
VOL_PREMIUM_TEXT_FILE = REPORTS_DIR / "vol_premium_latest.txt"
VOL_PREMIUM_STAGE = "vol-premium-research-only"

MIN_BUCKET_SAMPLES = int(os.environ.get("INFERNO_VRP_MIN_BUCKET_SAMPLES", "5"))
BOOTSTRAP_RESAMPLES = int(os.environ.get("INFERNO_VRP_BOOTSTRAP", "2000"))
BOOTSTRAP_SEED = int(os.environ.get("INFERNO_VRP_SEED", "20260515"))

IV_LOW_CEIL = 33.0
IV_MID_CEIL = 66.0


# Strategy → vol direction. The defaults cover the desk's current playbook;
# operators may override via ``INFERNO_VRP_VOL_TAGS=Strategy:direction;...``.
DEFAULT_VOL_DIRECTION_MAP: dict[str, str] = {
    "iron condor": "short-vol",
    "credit spread": "short-vol",
    "put credit spread": "short-vol",
    "call credit spread": "short-vol",
    "short straddle": "short-vol",
    "short strangle": "short-vol",
    "covered call": "short-vol",
    "cash secured put": "short-vol",
    "vertical call": "long-vol",
    "vertical put": "long-vol",
    "debit spread": "long-vol",
    "long call": "long-vol",
    "long put": "long-vol",
    "long straddle": "long-vol",
    "long strangle": "long-vol",
    "straddle": "long-vol",  # default to long if direction unspecified
    "calendar": "vega-neutral",
    "diagonal": "vega-neutral",
}


def _load_vol_direction_overrides() -> dict[str, str]:
    raw = os.environ.get("INFERNO_VRP_VOL_TAGS", "").strip()
    if not raw:
        return {}
    overrides: dict[str, str] = {}
    for chunk in raw.split(";"):
        if ":" not in chunk:
            continue
        name, direction = chunk.split(":", 1)
        name = name.strip().lower()
        direction = direction.strip().lower()
        if name and direction in {"short-vol", "long-vol", "vega-neutral"}:
            overrides[name] = direction
    return overrides


def classify_vol_direction(strategy: str) -> str:
    """Map a strategy name to short-vol / long-vol / vega-neutral / unknown."""
    if not strategy:
        return "unknown"
    name = strategy.strip().lower()
    overrides = _load_vol_direction_overrides()
    merged = {**DEFAULT_VOL_DIRECTION_MAP, **overrides}
    if name in merged:
        return merged[name]
    # Substring fallback so "Bull Put Credit Spread" still maps.
    for key, direction in merged.items():
        if key in name:
            return direction
    return "unknown"


def classify_iv_bucket(iv_rank: float | None) -> str:
    if iv_rank is None:
        return "unknown"
    try:
        value = float(iv_rank)
    except (TypeError, ValueError):
        return "unknown"
    if value < 0:
        return "unknown"
    if value < IV_LOW_CEIL:
        return "low"
    if value < IV_MID_CEIL:
        return "mid"
    return "high"


# ---------------------------------------------------------------------------
# Pure math.
# ---------------------------------------------------------------------------


def bootstrap_mean_diff(
    a: list[float],
    b: list[float],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """Independent two-sample bootstrap on ``mean(a) - mean(b)``.

    Returns ``(point, lower, upper)``. The two samples are resampled
    independently with replacement; the difference of resample means
    builds the bootstrap distribution.

    Edge cases:
    - either sample empty: returns ``(0.0, 0.0, 0.0)``.
    - either sample size 1: returns the point difference with collapsed
      bounds (no resampling buys us anything with n=1).
    """
    if not a or not b:
        return 0.0, 0.0, 0.0
    point = (sum(a) / len(a)) - (sum(b) / len(b))
    if len(a) == 1 and len(b) == 1:
        return float(point), float(point), float(point)
    rng = random.Random(seed)
    na, nb = len(a), len(b)
    draws: list[float] = []
    for _ in range(resamples):
        ra = sum(a[rng.randrange(na)] for _ in range(na)) / na
        rb = sum(b[rng.randrange(nb)] for _ in range(nb)) / nb
        draws.append(ra - rb)
    draws.sort()
    lo_idx = max(0, int((alpha / 2.0) * resamples))
    hi_idx = min(resamples - 1, int((1.0 - alpha / 2.0) * resamples))
    return float(point), float(draws[lo_idx]), float(draws[hi_idx])


def classify_discriminator(
    *,
    sample_count_high: int,
    sample_count_low: int,
    lower: float,
    upper: float,
) -> str:
    if sample_count_high < MIN_BUCKET_SAMPLES or sample_count_low < MIN_BUCKET_SAMPLES:
        return "insufficient"
    if lower > 0:
        return "vrp-real"
    if upper <= 0:
        return "vrp-absent"
    return "vrp-uncertain"


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


def normalise_closed(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten the closed records into ``{r, direction, ivBucket, strategy}``."""
    out: list[dict[str, Any]] = []
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
        strategy = str(record.get("strategy") or "Unknown")
        iv_rank = record.get("ivRank")
        if iv_rank is None:
            context = record.get("marketContext") or record.get("context") or {}
            if isinstance(context, dict):
                iv_rank = context.get("ivRank")
        out.append({
            "r": float(r),
            "direction": classify_vol_direction(strategy),
            "ivBucket": classify_iv_bucket(iv_rank),
            "strategy": strategy,
            "ivRank": iv_rank,
        })
    return out


# ---------------------------------------------------------------------------
# Pure builder.
# ---------------------------------------------------------------------------


def _cell_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate mean R, sample size, and lift over zero."""
    samples = [r["r"] for r in rows]
    n = len(samples)
    mean = sum(samples) / n if n else 0.0
    wins = sum(1 for value in samples if value > 0)
    return {
        "sampleSize": n,
        "wins": wins,
        "losses": n - wins,
        "meanR": round(mean, 4),
        "tickers": sorted({r.get("strategy") for r in rows}),
    }


def build_vol_premium(
    *,
    shadow_loader: Callable[[], list[dict[str, Any]]] | None = None,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Compute the per-direction VRP discriminator with bootstrap CIs."""
    records = (shadow_loader or _default_shadow_loader)()
    rows = normalise_closed(records)

    cube: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in rows:
        cube.setdefault(row["direction"], {}).setdefault(row["ivBucket"], []).append(row)

    discriminators: list[dict[str, Any]] = []

    def add_discriminator(direction: str, hi_bucket: str, lo_bucket: str) -> None:
        hi_rows = cube.get(direction, {}).get(hi_bucket, [])
        lo_rows = cube.get(direction, {}).get(lo_bucket, [])
        hi_samples = [r["r"] for r in hi_rows]
        lo_samples = [r["r"] for r in lo_rows]
        point, lower, upper = bootstrap_mean_diff(
            hi_samples, lo_samples, resamples=resamples, seed=seed,
        )
        verdict = classify_discriminator(
            sample_count_high=len(hi_samples),
            sample_count_low=len(lo_samples),
            lower=lower,
            upper=upper,
        )
        discriminators.append({
            "direction": direction,
            "highBucket": hi_bucket,
            "lowBucket": lo_bucket,
            "discriminator": round(point, 4),
            "lower": round(lower, 4),
            "upper": round(upper, 4),
            "sampleHigh": len(hi_samples),
            "sampleLow": len(lo_samples),
            "verdict": verdict,
        })

    # Short-vol: edge expected to be larger in HIGH IV than LOW IV (sell rich).
    add_discriminator("short-vol", "high", "low")
    # Long-vol: edge expected to be larger in LOW IV than HIGH IV (buy cheap).
    add_discriminator("long-vol", "low", "high")

    cube_summary: dict[str, dict[str, dict[str, Any]]] = {}
    for direction, buckets in cube.items():
        cube_summary[direction] = {bucket: _cell_stats(b_rows) for bucket, b_rows in buckets.items()}

    real = [d for d in discriminators if d["verdict"] == "vrp-real"]
    absent = [d for d in discriminators if d["verdict"] == "vrp-absent"]
    uncertain = [d for d in discriminators if d["verdict"] == "vrp-uncertain"]
    insufficient = [d for d in discriminators if d["verdict"] == "insufficient"]

    if not rows:
        verdict = "no-evidence"
        narrative = "No closed shadow records — vol premium cannot be tested."
    elif real:
        verdict = "vrp-detected"
        directions = ", ".join(d["direction"] for d in real)
        narrative = (
            f"VRP edge detected for: {directions}. The IV-bucket discriminator's "
            f"95% lower bound is positive — bucket selection is statistically real."
        )
    elif absent:
        verdict = "vrp-rejected"
        narrative = (
            "Every tested direction has discriminator upper-bound at or below zero — "
            "no statistically real bucket edge. Vol selection is not yet an edge."
        )
    elif uncertain:
        verdict = "vrp-uncertain"
        narrative = (
            "Bucket discriminator CIs include zero. Need more samples per "
            f"(direction, IV bucket) cell — minimum is {MIN_BUCKET_SAMPLES} per side."
        )
    else:
        verdict = "insufficient"
        narrative = (
            f"Every (direction, IV bucket) intersection is below {MIN_BUCKET_SAMPLES} "
            "samples. Falsification path cannot test the discriminator yet."
        )

    return {
        "generatedAt": local_now().isoformat(),
        "stage": VOL_PREMIUM_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "method": "two-sample-bootstrap-mean-diff",
        "bootstrapResamples": resamples,
        "minBucketSamples": MIN_BUCKET_SAMPLES,
        "ivBucketCeilings": {"low": IV_LOW_CEIL, "mid": IV_MID_CEIL},
        "discriminators": discriminators,
        "cube": cube_summary,
        "realCount": len(real),
        "uncertainCount": len(uncertain),
        "absentCount": len(absent),
        "insufficientCount": len(insufficient),
        "totalClosed": len(rows),
        "reminders": [
            "VRP verdict is one factor — it does not promote authority on its own",
            "low/mid/high buckets cut at 33 / 66 ivRank by default",
            "strategy → vol direction map is configurable via INFERNO_VRP_VOL_TAGS",
        ],
    }


def vol_premium_text(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno Vol Premium (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Method: {payload.get('method')}  resamples={payload.get('bootstrapResamples')}",
        f"Verdict: {payload.get('verdict')}",
        f"Closed records: {payload.get('totalClosed')}  "
        f"real={payload.get('realCount')}  "
        f"uncertain={payload.get('uncertainCount')}  "
        f"absent={payload.get('absentCount')}  "
        f"insufficient={payload.get('insufficientCount')}",
        "",
        f"Narrative: {payload.get('narrative')}",
    ]
    discriminators = payload.get("discriminators") or []
    if discriminators:
        lines.extend(["", "Discriminators (high - low, 95% bootstrap CI):"])
        lines.append(
            f"{'Direction':<12} {'High':<6} {'Low':<6} "
            f"{'N_hi':>5} {'N_lo':>5} {'Δmean':>8} {'Lo':>8} {'Hi':>8} {'Verdict'}"
        )
        for row in discriminators:
            lines.append(
                f"{str(row['direction'])[:12]:<12} "
                f"{str(row['highBucket']):<6} "
                f"{str(row['lowBucket']):<6} "
                f"{row['sampleHigh']:>5} "
                f"{row['sampleLow']:>5} "
                f"{row['discriminator']:>+8.3f} "
                f"{row['lower']:>+8.3f} "
                f"{row['upper']:>+8.3f} "
                f"{row['verdict']}"
            )
    cube = payload.get("cube") or {}
    if cube:
        lines.extend(["", "Cube (direction × IV bucket):"])
        for direction in sorted(cube.keys()):
            buckets = cube[direction]
            for bucket in ("low", "mid", "high", "unknown"):
                if bucket not in buckets:
                    continue
                stats = buckets[bucket]
                lines.append(
                    f"- {direction:<14} {bucket:<8} "
                    f"N={stats.get('sampleSize'):>3} "
                    f"wins={stats.get('wins'):>3} "
                    f"meanR={stats.get('meanR'):+.3f}"
                )
    lines.extend(["", "Thresholds:"])
    lines.append(f"- minBucketSamples: each cell n >= {payload.get('minBucketSamples')}")
    ceilings = payload.get("ivBucketCeilings") or {}
    lines.append(f"- IV buckets: low<{ceilings.get('low')} | mid<{ceilings.get('mid')} | high>=")
    lines.extend(["", "Reminders:"])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_vol_premium(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(VOL_PREMIUM_FILE, payload)
    atomic_write_text(VOL_PREMIUM_TEXT_FILE, vol_premium_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compute the IV-bucket vol-premium discriminator across short-vol "
            "and long-vol strategies. Research-only; never promotable."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and VOL_PREMIUM_TEXT_FILE.exists():
        print(VOL_PREMIUM_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_vol_premium()
    save_vol_premium(payload)
    print(vol_premium_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
