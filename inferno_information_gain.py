from __future__ import annotations

"""Inferno Information Gain — mutual information between features and outcome.

What it does:
    For every candidate feature (IV bucket, DTE bucket, ATR%-Z bucket,
    sector, strategy), compute the mutual information ``I(F; Y)`` between
    the feature and the win/loss outcome over the shadow ledger, in bits.
    Normalise by the outcome entropy ``H(Y)`` to express the result as a
    fraction of outcome uncertainty resolved by knowing the feature.

    The output is a ranked feature table — the desk's signal-to-noise
    inventory. A feature with high normalised MI carries real signal; a
    feature with near-zero MI is noise dressed up as a column.

What it does NOT do:
    - Trade. Modify authority. Touch the paper ledger.

Strict contract: research-only, diagnostic-only, never promotable.

## The math

Shannon mutual information for discrete random variables:

```
I(F; Y) = Σ_f Σ_y p(f, y) · log₂( p(f, y) / (p(f) · p(y)) )
```

In bits (log base 2). Equivalently:

```
I(F; Y) = H(Y) - H(Y | F)
```

The conditional-entropy form is the one that matters intuitively:
*how many bits of outcome uncertainty does observing F resolve?*

Normalised MI:

```
NMI = I(F; Y) / H(Y)         (if H(Y) > 0, else 0)
```

``NMI ∈ [0, 1]``. 1 means knowing the feature fully determines the
outcome; 0 means the feature is independent of the outcome.

We also compute a *permutation* significance check: shuffle the outcome
labels ``B`` times (default 1000) and count how often the shuffled MI
matches or exceeds the observed MI. The fraction is a non-parametric
p-value for ``H0: F and Y are independent``.

## Feature buckets

By default we discretise continuous features:

- IV rank → low/mid/high at 33/66 boundaries
- days to earnings → 0-7 / 8-21 / 22-60 / 60+
- ATR % z-score → < -1 / -1 to 1 / > 1

Categorical features (sector, strategy) are used as-is.

## Verdict ladder

Per feature:

| NMI band       | sample size | verdict        |
|----------------|-------------|----------------|
| `< 0.01`       | n ≥ MIN     | noise          |
| `< 0.05`       | n ≥ MIN     | faint          |
| `< 0.15`       | n ≥ MIN     | meaningful     |
| `≥ 0.15`       | n ≥ MIN     | strong         |
| any            | n < MIN     | insufficient   |

Combined with the permutation p-value, the operator gets both magnitude
(NMI) and statistical significance (p) — both must align for action.

CLI::

    python3 inferno_information_gain.py             # run + persist
    python3 inferno_information_gain.py status      # show last memo

References:
    Cover & Thomas (2006), *Elements of Information Theory*, Ch. 2.
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
from inferno_theme_synthesizer import _r_units
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


INFORMATION_GAIN_FILE = DATA_DIR / "inferno_information_gain.json"
INFORMATION_GAIN_TEXT_FILE = REPORTS_DIR / "information_gain_latest.txt"
INFORMATION_GAIN_STAGE = "information-gain-research-only"

MIN_MI_SAMPLES = int(os.environ.get("INFERNO_MI_MIN_SAMPLES", "20"))
PERMUTATION_RESAMPLES = int(os.environ.get("INFERNO_MI_PERMUTATIONS", "1000"))
PERMUTATION_SEED = int(os.environ.get("INFERNO_MI_SEED", "20260517"))

STRONG_NMI = 0.15
MEANINGFUL_NMI = 0.05
FAINT_NMI = 0.01


# ---------------------------------------------------------------------------
# Pure math.
# ---------------------------------------------------------------------------


def entropy(probabilities: list[float]) -> float:
    """Shannon entropy in bits."""
    total = 0.0
    for p in probabilities:
        if p <= 0:
            continue
        total -= p * math.log2(p)
    return total


def mutual_information(
    feature_values: list[Any],
    outcomes: list[bool],
) -> float:
    """Mutual information ``I(F; Y)`` in bits between a discrete feature
    and a Bernoulli outcome.

    Both lists must be the same length. Returns 0 for empty inputs and
    for trivial cases where either marginal has support 1.
    """
    n = len(feature_values)
    if n != len(outcomes):
        raise ValueError("feature and outcome lists must be the same length")
    if n == 0:
        return 0.0
    # Marginal p(y).
    wins = sum(1 for y in outcomes if y)
    losses = n - wins
    if wins == 0 or losses == 0:
        return 0.0  # outcome is constant — MI is identically 0
    py_win = wins / n
    py_loss = losses / n

    # Joint p(f, y) and marginal p(f).
    joint: dict[tuple[Any, bool], int] = {}
    marginal_f: dict[Any, int] = {}
    for f, y in zip(feature_values, outcomes):
        joint[(f, y)] = joint.get((f, y), 0) + 1
        marginal_f[f] = marginal_f.get(f, 0) + 1

    if len(marginal_f) <= 1:
        return 0.0  # feature is constant — MI is identically 0

    mi = 0.0
    for (f, y), count in joint.items():
        p_joint = count / n
        p_f = marginal_f[f] / n
        p_y = py_win if y else py_loss
        if p_joint <= 0 or p_f <= 0 or p_y <= 0:
            continue
        mi += p_joint * math.log2(p_joint / (p_f * p_y))
    return max(mi, 0.0)


def outcome_entropy(outcomes: list[bool]) -> float:
    """Bernoulli entropy ``H(Y)`` over the outcome stream."""
    n = len(outcomes)
    if n == 0:
        return 0.0
    wins = sum(1 for y in outcomes if y)
    if wins == 0 or wins == n:
        return 0.0
    p = wins / n
    return entropy([p, 1.0 - p])


def normalised_mi(mi_value: float, h_y: float) -> float:
    """``NMI = I(F;Y) / H(Y)`` clamped to ``[0, 1]``."""
    if h_y <= 0:
        return 0.0
    return max(0.0, min(1.0, mi_value / h_y))


def permutation_p_value(
    feature_values: list[Any],
    outcomes: list[bool],
    *,
    observed_mi: float,
    resamples: int = PERMUTATION_RESAMPLES,
    seed: int = PERMUTATION_SEED,
) -> float:
    """Permutation p-value for ``H0: F ⊥ Y``.

    Shuffle the outcome labels independently of the feature ``B`` times;
    count permutations whose MI matches or exceeds the observed. Apply
    the Phipson–Smyth ``(1 + k) / (B + 1)`` correction.
    """
    n = len(outcomes)
    if n < 2 or observed_mi <= 0:
        return 1.0
    rng = random.Random(seed)
    shuffled = list(outcomes)
    at_or_above = 0
    for _ in range(resamples):
        rng.shuffle(shuffled)
        mi_shuffled = mutual_information(feature_values, shuffled)
        if mi_shuffled >= observed_mi:
            at_or_above += 1
    return (1 + at_or_above) / (resamples + 1)


def classify_feature(*, sample_size: int, nmi: float) -> str:
    if sample_size < MIN_MI_SAMPLES:
        return "insufficient"
    if nmi >= STRONG_NMI:
        return "strong"
    if nmi >= MEANINGFUL_NMI:
        return "meaningful"
    if nmi >= FAINT_NMI:
        return "faint"
    return "noise"


# ---------------------------------------------------------------------------
# Feature bucketers.
# ---------------------------------------------------------------------------


def _iv_bucket(record: dict[str, Any]) -> str:
    iv = record.get("ivRank")
    if iv is None:
        ctx = record.get("marketContext") or record.get("context") or {}
        if isinstance(ctx, dict):
            iv = ctx.get("ivRank")
    if iv is None:
        return "unknown"
    try:
        value = float(iv)
    except (TypeError, ValueError):
        return "unknown"
    if value < 33:
        return "low"
    if value < 66:
        return "mid"
    return "high"


def _dte_bucket(record: dict[str, Any]) -> str:
    dte = record.get("daysToEarnings")
    if dte is None:
        ctx = record.get("marketContext") or record.get("context") or {}
        if isinstance(ctx, dict):
            dte = ctx.get("daysToEarnings")
    if dte is None:
        return "unknown"
    try:
        value = float(dte)
    except (TypeError, ValueError):
        return "unknown"
    if value <= 7:
        return "0-7"
    if value <= 21:
        return "8-21"
    if value <= 60:
        return "22-60"
    return "60+"


def _atr_z_bucket(record: dict[str, Any]) -> str:
    z = record.get("atrPctZScore")
    if z is None:
        ctx = record.get("marketContext") or record.get("context") or {}
        if isinstance(ctx, dict):
            z = ctx.get("atrPctZScore")
    if z is None:
        return "unknown"
    try:
        value = float(z)
    except (TypeError, ValueError):
        return "unknown"
    if value < -1:
        return "compressed"
    if value > 1:
        return "expanded"
    return "neutral"


def _sector(record: dict[str, Any]) -> str:
    sector = record.get("sector") or record.get("Sector")
    if not sector:
        fundamentals = record.get("fundamentals") or {}
        if isinstance(fundamentals, dict):
            sector = fundamentals.get("sector")
    return str(sector or "unknown")


def _strategy(record: dict[str, Any]) -> str:
    return str(record.get("strategy") or "Unknown")


FEATURE_EXTRACTORS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "ivBucket": _iv_bucket,
    "dteBucket": _dte_bucket,
    "atrZBucket": _atr_z_bucket,
    "sector": _sector,
    "strategy": _strategy,
}


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


def collect_features_outcomes(
    records: list[dict[str, Any]],
) -> tuple[dict[str, list[Any]], list[bool]]:
    """Walk closed records once; return per-feature value lists + outcome list."""
    features: dict[str, list[Any]] = {key: [] for key in FEATURE_EXTRACTORS}
    outcomes: list[bool] = []
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
        outcomes.append(r > 0)
        for name, extractor in FEATURE_EXTRACTORS.items():
            features[name].append(extractor(record))
    return features, outcomes


# ---------------------------------------------------------------------------
# Pure builder.
# ---------------------------------------------------------------------------


def build_information_gain(
    *,
    shadow_loader: Callable[[], list[dict[str, Any]]] | None = None,
    feature_extractors: dict[str, Callable[[dict[str, Any]], Any]] | None = None,
    permutation_resamples: int = PERMUTATION_RESAMPLES,
    seed: int = PERMUTATION_SEED,
) -> dict[str, Any]:
    """Compute per-feature MI / NMI / p-value over the shadow ledger."""
    records = (shadow_loader or _default_shadow_loader)()
    extractors = feature_extractors or FEATURE_EXTRACTORS

    # Use the configured extractors regardless of whether they overlap with
    # the default — supports tests that pass a custom subset.
    features: dict[str, list[Any]] = {key: [] for key in extractors}
    outcomes: list[bool] = []
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
        outcomes.append(r > 0)
        for name, extractor in extractors.items():
            features[name].append(extractor(record))

    h_y = outcome_entropy(outcomes)
    n = len(outcomes)
    wins = sum(1 for y in outcomes if y)

    rows: list[dict[str, Any]] = []
    for feature_name, values in features.items():
        mi = mutual_information(values, outcomes)
        nmi = normalised_mi(mi, h_y)
        p_value = permutation_p_value(
            values, outcomes,
            observed_mi=mi,
            resamples=permutation_resamples,
            seed=seed,
        )
        verdict = classify_feature(sample_size=n, nmi=nmi)
        # Custom feature extractors may return mixed comparable types
        # (for example int buckets plus "unknown"). Sort by repr so support
        # counting stays deterministic instead of crashing on Python 3.
        unique_values = sorted(set(values), key=repr)
        rows.append({
            "feature": feature_name,
            "miBits": round(mi, 4),
            "normalisedMI": round(nmi, 4),
            "permutationPValue": round(p_value, 4),
            "supportSize": len(unique_values),
            "sampleSize": n,
            "verdict": verdict,
        })

    rows.sort(key=lambda r: (-r["normalisedMI"], r["permutationPValue"], r["feature"]))

    strong = [r for r in rows if r["verdict"] == "strong"]
    meaningful = [r for r in rows if r["verdict"] == "meaningful"]
    faint = [r for r in rows if r["verdict"] == "faint"]
    noise = [r for r in rows if r["verdict"] == "noise"]
    insufficient = [r for r in rows if r["verdict"] == "insufficient"]

    if n == 0:
        verdict = "no-evidence"
        narrative = "No closed shadow records — information gain cannot be computed."
    elif n < MIN_MI_SAMPLES:
        verdict = "insufficient"
        narrative = (
            f"Only {n} closed records ({MIN_MI_SAMPLES} required). All features "
            "carry 'insufficient' verdict regardless of NMI."
        )
    elif strong:
        verdict = "signal-detected"
        names = ", ".join(r["feature"] for r in strong)
        narrative = (
            f"Strong signal in: {names} (NMI ≥ {STRONG_NMI}). These features "
            "deserve a place in the gating logic."
        )
    elif meaningful:
        verdict = "meaningful-signal"
        names = ", ".join(r["feature"] for r in meaningful)
        narrative = (
            f"Meaningful signal in: {names}. Worth tracking but not yet "
            "strong enough to gate alone."
        )
    elif faint:
        verdict = "faint-signal"
        narrative = "Every feature is at most a faint carrier of signal."
    else:
        verdict = "no-signal"
        narrative = "Every feature carries < 1% normalised MI. The outcome is noise from the desk's POV."

    return {
        "generatedAt": local_now().isoformat(),
        "stage": INFORMATION_GAIN_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "method": "shannon-mi-with-permutation-significance",
        "permutationResamples": permutation_resamples,
        "minSamples": MIN_MI_SAMPLES,
        "totalClosed": n,
        "totalWins": wins,
        "totalLosses": n - wins,
        "outcomeEntropyBits": round(h_y, 4),
        "strongCount": len(strong),
        "meaningfulCount": len(meaningful),
        "faintCount": len(faint),
        "noiseCount": len(noise),
        "insufficientCount": len(insufficient),
        "rows": rows,
        "reminders": [
            "NMI is fraction of outcome uncertainty resolved by the feature",
            "p-value < 0.05 is the standard significance threshold",
            "high NMI + low p-value = the feature deserves gating attention",
        ],
    }


def information_gain_text(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno Information Gain (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Method: {payload.get('method')}  perms={payload.get('permutationResamples')}",
        f"Verdict: {payload.get('verdict')}",
        f"Closed: {payload.get('totalClosed')}  wins={payload.get('totalWins')}  "
        f"losses={payload.get('totalLosses')}  H(Y)={payload.get('outcomeEntropyBits')} bits",
        f"Counts: strong={payload.get('strongCount')}  "
        f"meaningful={payload.get('meaningfulCount')}  "
        f"faint={payload.get('faintCount')}  "
        f"noise={payload.get('noiseCount')}  "
        f"insufficient={payload.get('insufficientCount')}",
        "",
        f"Narrative: {payload.get('narrative')}",
    ]
    rows = payload.get("rows") or []
    if rows:
        lines.extend(["", "Per-feature MI:"])
        lines.append(
            f"{'Feature':<14} {'MI (bits)':>10} {'NMI':>6} {'p-value':>9} {'support':>8} {'Verdict'}"
        )
        for row in rows:
            lines.append(
                f"{str(row['feature'])[:14]:<14} "
                f"{row['miBits']:>10.4f} "
                f"{row['normalisedMI']:>6.3f} "
                f"{row['permutationPValue']:>9.4f} "
                f"{row['supportSize']:>8} "
                f"{row['verdict']}"
            )
    lines.extend(["", "Thresholds:"])
    lines.append(f"- strong:     NMI >= {STRONG_NMI}")
    lines.append(f"- meaningful: NMI >= {MEANINGFUL_NMI}")
    lines.append(f"- faint:      NMI >= {FAINT_NMI}")
    lines.append(f"- minSamples: n >= {payload.get('minSamples')}")
    lines.extend(["", "Reminders:"])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_information_gain(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(INFORMATION_GAIN_FILE, payload)
    atomic_write_text(INFORMATION_GAIN_TEXT_FILE, information_gain_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compute mutual information between candidate features and the "
            "win/loss outcome across the shadow ledger. Research-only."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and INFORMATION_GAIN_TEXT_FILE.exists():
        print(INFORMATION_GAIN_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_information_gain()
    save_information_gain(payload)
    print(information_gain_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
