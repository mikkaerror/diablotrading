from __future__ import annotations

"""Inferno Factor Regression — logistic regression over feature buckets.

What it does:
    Fits a multi-feature logistic regression ``P(win | x) = σ(β·x + b)``
    over one-hot-encoded feature buckets from the shadow ledger. Returns
    per-coefficient point estimates and bootstrap 95% confidence
    intervals. A coefficient whose CI excludes zero is a feature the
    desk has statistical evidence is moving the win probability.

    This is the multi-factor signal combiner — the Renaissance-style
    aggregator that turns N weak signals into one calibrated probability.

What it does NOT do:
    - Use external ML libraries. Hand-rolled gradient descent only;
      stdlib `math` and `random`.
    - Promote authority. Never. The regression's job is to *characterise*
      signal, not authorise positions.

Strict contract: research-only, diagnostic-only, never promotable. The
output is advisory: ``inferno_information_gain`` answers "which features
might carry signal"; this module answers "given a model that fits them
all jointly, which features are individually significant?"

## The math

For each closed shadow record we extract a feature vector by one-hot
encoding the bucketed features (IV bucket, DTE bucket, ATR%-Z bucket,
sector when small enough). The outcome is Bernoulli ``y ∈ {0, 1}``.

Standard logistic regression maximises the log-likelihood:

```
L(β, b) = Σ_i [ y_i (β·x_i + b) - log(1 + exp(β·x_i + b)) ]
```

We optimise via batch gradient ascent with L2 regularisation::

```
∂L/∂β_j = Σ_i (y_i - σ(β·x_i + b)) · x_ij  - λ β_j
∂L/∂b   = Σ_i (y_i - σ(β·x_i + b))
```

with ``λ = 0.1`` by default. Learning rate ``η = 0.1``; max iterations
500; tolerance ``10⁻⁶`` on the L2-norm of the gradient.

## Confidence intervals

We bootstrap the coefficient distribution by resampling records with
replacement ``B`` times (default 500) and refitting. The 95% percentile
interval is the empirical 2.5%–97.5% range of each coefficient's
bootstrap draws.

A coefficient is "significant" if its 95% CI excludes zero on the
appropriate side (positive coefficients need ``lower > 0``; negative
need ``upper < 0``).

## Verdict ladder

Per coefficient:

| Condition                  | Verdict        |
|----------------------------|----------------|
| sample size below MIN      | insufficient   |
| 95% CI excludes zero, β>0  | positive-edge  |
| 95% CI excludes zero, β<0  | negative-edge  |
| else                       | inconclusive   |

CLI::

    python3 inferno_factor_regression.py             # run + persist
    python3 inferno_factor_regression.py status      # show last memo

References:
    Hosmer, Lemeshow & Sturdivant (2013), *Applied Logistic Regression*,
    Wiley.
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
from inferno_information_gain import (
    _iv_bucket,
    _dte_bucket,
    _atr_z_bucket,
    _sector,
)
from inferno_theme_synthesizer import _r_units
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


FACTOR_REGRESSION_FILE = DATA_DIR / "inferno_factor_regression.json"
FACTOR_REGRESSION_TEXT_FILE = REPORTS_DIR / "factor_regression_latest.txt"
FACTOR_REGRESSION_STAGE = "factor-regression-research-only"

MIN_REGRESSION_SAMPLES = int(os.environ.get("INFERNO_FR_MIN_SAMPLES", "30"))
LEARNING_RATE = float(os.environ.get("INFERNO_FR_LR", "0.1"))
MAX_ITERATIONS = int(os.environ.get("INFERNO_FR_MAX_ITER", "500"))
L2_LAMBDA = float(os.environ.get("INFERNO_FR_L2", "0.1"))
GRADIENT_TOLERANCE = float(os.environ.get("INFERNO_FR_TOL", "1e-6"))
BOOTSTRAP_DRAWS = int(os.environ.get("INFERNO_FR_BOOTSTRAP", "500"))
REGRESSION_SEED = int(os.environ.get("INFERNO_FR_SEED", "20260519"))

# We exclude `strategy` from features — it's a label, not a factor. We
# also exclude `sector` from the default extractor list unless the desk
# has fewer than this many sectors (one-hot blows up otherwise).
MAX_SECTOR_BUCKETS = int(os.environ.get("INFERNO_FR_MAX_SECTORS", "8"))


# ---------------------------------------------------------------------------
# Pure math.
# ---------------------------------------------------------------------------


def sigmoid(z: float) -> float:
    """Numerically stable logistic sigmoid."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _dot(weights: list[float], features: list[float]) -> float:
    return sum(w * x for w, x in zip(weights, features))


def fit_logistic(
    feature_matrix: list[list[float]],
    outcomes: list[int],
    *,
    learning_rate: float = LEARNING_RATE,
    l2_lambda: float = L2_LAMBDA,
    max_iterations: int = MAX_ITERATIONS,
    tolerance: float = GRADIENT_TOLERANCE,
) -> tuple[list[float], float, int]:
    """Fit a logistic regression by batch gradient ascent.

    Returns ``(weights, bias, iterations_used)``.

    Edge cases:
    - empty input: returns ``([], 0.0, 0)``.
    - constant outcome: returns zero weights and a bias matching the
      class proportion's logit (or ±10 if proportion is 0/1).
    """
    n = len(feature_matrix)
    if n == 0:
        return [], 0.0, 0
    if len(outcomes) != n:
        raise ValueError("feature_matrix and outcomes must align")
    d = len(feature_matrix[0]) if n > 0 else 0
    if d == 0:
        return [], 0.0, 0

    positive_count = sum(1 for y in outcomes if y)
    if positive_count == 0 or positive_count == n:
        # A one-class target has no learnable factor relationship. Return a
        # saturated intercept so downstream code sees the base rate, without
        # pretending any feature earned a coefficient.
        saturated_bias = 10.0 if positive_count == n else -10.0
        return [0.0] * d, saturated_bias, 0

    # Initialise at zero (a sensible neutral start for logistic).
    weights = [0.0] * d
    bias = 0.0

    for iteration in range(max_iterations):
        grad_w = [0.0] * d
        grad_b = 0.0
        for x, y in zip(feature_matrix, outcomes):
            p = sigmoid(_dot(weights, x) + bias)
            residual = y - p
            for j in range(d):
                grad_w[j] += residual * x[j]
            grad_b += residual
        # L2 regularisation on weights only (not bias).
        for j in range(d):
            grad_w[j] -= l2_lambda * weights[j]
        # Check convergence on the same average-gradient scale used by the
        # update step; otherwise larger ledgers look falsely "unconverged".
        norm = math.sqrt(sum((g / n) * (g / n) for g in grad_w) + (grad_b / n) * (grad_b / n))
        if norm < tolerance:
            return weights, bias, iteration + 1
        # Update.
        for j in range(d):
            weights[j] += learning_rate * grad_w[j] / n
        bias += learning_rate * grad_b / n
    return weights, bias, max_iterations


def bootstrap_logistic_coefficients(
    feature_matrix: list[list[float]],
    outcomes: list[int],
    *,
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = REGRESSION_SEED,
    learning_rate: float = LEARNING_RATE,
    l2_lambda: float = L2_LAMBDA,
    max_iterations: int = MAX_ITERATIONS,
) -> tuple[list[list[float]], list[float]]:
    """Bootstrap-resample the dataset and refit; collect coefficient draws.

    Returns ``(weight_draws, bias_draws)``. ``weight_draws[j]`` is the
    list of bootstrap draws for coefficient ``j``.
    """
    n = len(feature_matrix)
    if n == 0:
        return [], []
    d = len(feature_matrix[0])
    rng = random.Random(seed)
    weight_draws: list[list[float]] = [[] for _ in range(d)]
    bias_draws: list[float] = []
    for _ in range(draws):
        idx = [rng.randrange(n) for _ in range(n)]
        boot_X = [feature_matrix[i] for i in idx]
        boot_y = [outcomes[i] for i in idx]
        # Use fewer iterations per bootstrap fit to keep runtime sane;
        # the dataset is small enough that convergence is fast.
        weights, bias, _ = fit_logistic(
            boot_X, boot_y,
            learning_rate=learning_rate,
            l2_lambda=l2_lambda,
            max_iterations=max(50, max_iterations // 4),
            tolerance=GRADIENT_TOLERANCE * 10,
        )
        for j in range(d):
            weight_draws[j].append(weights[j])
        bias_draws.append(bias)
    return weight_draws, bias_draws


def percentile_ci(draws: list[float], alpha: float = 0.05) -> tuple[float, float]:
    """95% percentile CI from a list of bootstrap draws."""
    if not draws:
        return 0.0, 0.0
    sorted_draws = sorted(draws)
    n = len(sorted_draws)
    lo_idx = max(0, int((alpha / 2.0) * n))
    hi_idx = min(n - 1, int((1.0 - alpha / 2.0) * n))
    return sorted_draws[lo_idx], sorted_draws[hi_idx]


def classify_coefficient(*, sample_size: int, lower: float, upper: float) -> str:
    if sample_size < MIN_REGRESSION_SAMPLES:
        return "insufficient"
    if lower > 0:
        return "positive-edge"
    if upper < 0:
        return "negative-edge"
    return "inconclusive"


# ---------------------------------------------------------------------------
# Feature encoding.
# ---------------------------------------------------------------------------


def _record_feature_values(record: dict[str, Any]) -> dict[str, str]:
    """Extract the bucketed feature dict for one record."""
    return {
        "ivBucket": _iv_bucket(record),
        "dteBucket": _dte_bucket(record),
        "atrZBucket": _atr_z_bucket(record),
        "sector": _sector(record),
    }


def _one_hot(values: list[str], levels: list[str]) -> list[list[float]]:
    """One-hot encode a list of categorical values against a fixed level set.

    The first level is dropped to avoid the dummy-variable trap (this is
    the convention for unregularised regression; with L2 regularisation
    we technically don't need it but the interpretation is cleaner).
    """
    if len(levels) <= 1:
        return [[0.0] for _ in values]
    out: list[list[float]] = []
    levels_after_first = levels[1:]
    for value in values:
        row = [1.0 if value == level else 0.0 for level in levels_after_first]
        out.append(row)
    return out


def build_design_matrix(
    records: list[dict[str, Any]],
) -> tuple[list[list[float]], list[int], list[str]]:
    """Assemble the design matrix, outcome vector, and column names."""
    closed: list[tuple[dict[str, str], int]] = []
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
        closed.append((_record_feature_values(record), 1 if r > 0 else 0))
    if not closed:
        return [], [], []

    # Collect levels per feature.
    feature_levels: dict[str, list[str]] = {}
    for feature_name in ("ivBucket", "dteBucket", "atrZBucket", "sector"):
        levels = sorted({features[feature_name] for features, _ in closed})
        # Drop the sector feature entirely if it's too sparse.
        if feature_name == "sector" and len(levels) > MAX_SECTOR_BUCKETS:
            continue
        feature_levels[feature_name] = levels

    column_names: list[str] = []
    feature_matrix: list[list[float]] = [[] for _ in closed]
    for feature_name, levels in feature_levels.items():
        if len(levels) <= 1:
            continue  # constant feature — would be a zero column
        values = [features[feature_name] for features, _ in closed]
        block = _one_hot(values, levels)
        for level in levels[1:]:
            column_names.append(f"{feature_name}={level}")
        for i, row in enumerate(block):
            feature_matrix[i].extend(row)
    outcomes = [y for _, y in closed]
    return feature_matrix, outcomes, column_names


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


# ---------------------------------------------------------------------------
# Pure builder.
# ---------------------------------------------------------------------------


def build_factor_regression(
    *,
    shadow_loader: Callable[[], list[dict[str, Any]]] | None = None,
    learning_rate: float = LEARNING_RATE,
    l2_lambda: float = L2_LAMBDA,
    max_iterations: int = MAX_ITERATIONS,
    bootstrap_draws: int = BOOTSTRAP_DRAWS,
    seed: int = REGRESSION_SEED,
) -> dict[str, Any]:
    """Fit the logistic regression and bootstrap the coefficient CIs."""
    records = (shadow_loader or _default_shadow_loader)()
    feature_matrix, outcomes, column_names = build_design_matrix(records)
    n = len(outcomes)

    if n == 0:
        return {
            "generatedAt": local_now().isoformat(),
            "stage": FACTOR_REGRESSION_STAGE,
            "diagnosticOnly": True,
            "researchOnly": True,
            "promotable": False,
            "verdict": "no-evidence",
            "narrative": "No closed shadow records — regression cannot fit.",
            "method": "hand-rolled-logistic-l2",
            "learningRate": learning_rate,
            "l2Lambda": l2_lambda,
            "maxIterations": max_iterations,
            "iterationsUsed": 0,
            "bootstrapDraws": bootstrap_draws,
            "minSamples": MIN_REGRESSION_SAMPLES,
            "sampleSize": 0,
            "featureCount": 0,
            "bias": 0.0,
            "biasLower": 0.0,
            "biasUpper": 0.0,
            "positiveEdgeCount": 0,
            "negativeEdgeCount": 0,
            "inconclusiveCount": 0,
            "insufficientCount": 0,
            "coefficients": [],
            "reminders": ["regression is research-only; never promotes authority"],
        }

    weights, bias, iterations_used = fit_logistic(
        feature_matrix, outcomes,
        learning_rate=learning_rate,
        l2_lambda=l2_lambda,
        max_iterations=max_iterations,
    )

    # Bootstrap CIs only when sample size justifies it; otherwise return
    # zero-width CIs (the point estimate is the only thing we can claim).
    if n >= MIN_REGRESSION_SAMPLES and column_names:
        weight_draws, bias_draws = bootstrap_logistic_coefficients(
            feature_matrix, outcomes,
            draws=bootstrap_draws,
            seed=seed,
            learning_rate=learning_rate,
            l2_lambda=l2_lambda,
            max_iterations=max_iterations,
        )
    else:
        weight_draws = [[w] for w in weights]
        bias_draws = [bias]

    coefficients: list[dict[str, Any]] = []
    for j, name in enumerate(column_names):
        lo, hi = percentile_ci(weight_draws[j])
        verdict = classify_coefficient(sample_size=n, lower=lo, upper=hi)
        coefficients.append({
            "feature": name,
            "coefficient": round(weights[j], 4),
            "lower95": round(lo, 4),
            "upper95": round(hi, 4),
            "verdict": verdict,
        })

    bias_lo, bias_hi = percentile_ci(bias_draws) if bias_draws else (bias, bias)

    coefficients.sort(key=lambda c: (-abs(c["coefficient"]), c["feature"]))

    positive = [c for c in coefficients if c["verdict"] == "positive-edge"]
    negative = [c for c in coefficients if c["verdict"] == "negative-edge"]
    inconclusive = [c for c in coefficients if c["verdict"] == "inconclusive"]
    insufficient = [c for c in coefficients if c["verdict"] == "insufficient"]

    if not coefficients:
        verdict = "no-features"
        narrative = (
            f"{n} closed records but no usable features (all constant). "
            "Add variety to the paper test set."
        )
    elif n < MIN_REGRESSION_SAMPLES:
        verdict = "insufficient"
        narrative = (
            f"{n} closed records (need {MIN_REGRESSION_SAMPLES}). Point "
            "estimates only — no CIs."
        )
    elif positive and negative:
        verdict = "edges-mixed"
        narrative = (
            f"{len(positive)} feature(s) significantly increase P(win); "
            f"{len(negative)} significantly decrease it. {len(inconclusive)} inconclusive."
        )
    elif positive:
        verdict = "positive-edges"
        names = ", ".join(c["feature"] for c in positive[:5])
        narrative = (
            f"{len(positive)} feature(s) carry significant positive coefficient: {names}."
        )
    elif negative:
        verdict = "negative-edges"
        names = ", ".join(c["feature"] for c in negative[:5])
        narrative = (
            f"{len(negative)} feature(s) carry significant negative coefficient: {names}. "
            "Avoiding these buckets is itself an edge."
        )
    else:
        verdict = "no-significant-features"
        narrative = (
            "No feature's 95% CI excludes zero. Either the regression isn't "
            "powerful enough yet, or the features genuinely carry no signal."
        )

    return {
        "generatedAt": local_now().isoformat(),
        "stage": FACTOR_REGRESSION_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "method": "hand-rolled-logistic-l2",
        "learningRate": learning_rate,
        "l2Lambda": l2_lambda,
        "maxIterations": max_iterations,
        "iterationsUsed": iterations_used,
        "bootstrapDraws": bootstrap_draws,
        "minSamples": MIN_REGRESSION_SAMPLES,
        "sampleSize": n,
        "featureCount": len(column_names),
        "bias": round(bias, 4),
        "biasLower": round(bias_lo, 4),
        "biasUpper": round(bias_hi, 4),
        "positiveEdgeCount": len(positive),
        "negativeEdgeCount": len(negative),
        "inconclusiveCount": len(inconclusive),
        "insufficientCount": len(insufficient),
        "coefficients": coefficients,
        "reminders": [
            "coefficients are log-odds; positive means feature increases P(win)",
            "L2 regularisation shrinks coefficients toward zero",
            "regression is advisory — pair with information-gain for confirmation",
        ],
    }


def factor_regression_text(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno Factor Regression (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Method: {payload.get('method')}  λ={payload.get('l2Lambda')}  "
        f"η={payload.get('learningRate')}  iters={payload.get('iterationsUsed')}/{payload.get('maxIterations')}",
        f"Verdict: {payload.get('verdict')}",
        f"Samples: {payload.get('sampleSize')}  features: {payload.get('featureCount')}  "
        f"bias: {payload.get('bias')} [{payload.get('biasLower')}, {payload.get('biasUpper')}]",
        f"Counts: positive={payload.get('positiveEdgeCount')}  "
        f"negative={payload.get('negativeEdgeCount')}  "
        f"inconclusive={payload.get('inconclusiveCount')}  "
        f"insufficient={payload.get('insufficientCount')}",
        "",
        f"Narrative: {payload.get('narrative')}",
    ]
    coefficients = payload.get("coefficients") or []
    if coefficients:
        lines.extend(["", "Coefficients (sorted by |β|):"])
        lines.append(
            f"{'Feature':<30} {'β':>8} {'lo95':>8} {'hi95':>8} {'Verdict'}"
        )
        for coef in coefficients:
            lines.append(
                f"{str(coef['feature'])[:30]:<30} "
                f"{coef['coefficient']:>+8.3f} "
                f"{coef['lower95']:>+8.3f} "
                f"{coef['upper95']:>+8.3f} "
                f"{coef['verdict']}"
            )
    lines.extend(["", "Thresholds:"])
    lines.append(f"- minSamples: n >= {payload.get('minSamples')}")
    lines.append(f"- positive-edge: 95% CI lower bound > 0")
    lines.append(f"- negative-edge: 95% CI upper bound < 0")
    lines.extend(["", "Reminders:"])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_factor_regression(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(FACTOR_REGRESSION_FILE, payload)
    atomic_write_text(FACTOR_REGRESSION_TEXT_FILE, factor_regression_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fit a multi-factor logistic regression on the shadow ledger and "
            "bootstrap the coefficient CIs. Research-only; never promotable."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and FACTOR_REGRESSION_TEXT_FILE.exists():
        print(FACTOR_REGRESSION_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_factor_regression()
    save_factor_regression(payload)
    print(factor_regression_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
