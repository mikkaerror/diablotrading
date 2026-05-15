from __future__ import annotations

"""Inferno Bayesian Win Rate — beta-binomial posterior over win probability.

What it does:
    The frequentist complement of Wilson lower bound. For every strategy
    with closed shadow records, we set a weak Beta(2, 2) prior on the
    win probability and update with observed wins / losses to get a
    posterior Beta(α, β). We report:

    - posterior mean (the Bayesian point estimate)
    - posterior 95% credible interval (the Bayesian counterpart of CI)
    - P(p > 0.5) — the probability the strategy is better than coinflip
    - "edge probability" P(p > 0.55) — a stricter operator-set threshold

What it does NOT do:
    - Anything live. Anything that promotes authority.

Strict contract: research-only, diagnostic-only, never promotable.

## The math

Beta-binomial conjugate update. Start with prior ``Beta(α₀, β₀)``;
observe ``w`` wins and ``ℓ`` losses; the posterior is ``Beta(α₀+w, β₀+ℓ)``.

We use a *weak conservative* prior ``α₀ = β₀ = 2``. This has:

- mean = 0.5 (no opinion about edge direction)
- variance = 1/20 (gentle pull toward 0.5 when sample is tiny)
- effective sample size = α₀ + β₀ = 4

So with 0 samples, posterior is Beta(2, 2) and posterior mean = 0.5. With
3 wins and 7 losses, posterior is Beta(5, 9) and posterior mean = 5/14 ≈
0.357 — pulled toward 0.5 vs the raw 0.3 sample rate.

Quantiles of Beta are computed by Monte Carlo (``random.betavariate``,
which is stdlib). 4000 draws give 95% CI bounds stable to ~0.01.

## Why ship Bayesian *and* Wilson

Wilson is the gold standard frequentist interval; Bayesian gives us
something Wilson doesn't: ``P(p > threshold)``. The desk needs both.
When the two agree, we're confident. When they disagree, the prior is
doing work and the sample is small — exactly when we should be
conservative.

## Verdict ladder

| Posterior P(p > 0.55) | Sample size | Verdict        |
|-----------------------|-------------|----------------|
| n < MIN_SAMPLES       |             | insufficient   |
| < 0.20                | n ≥ MIN     | edge-rejected  |
| < 0.50                | n ≥ MIN     | edge-uncertain |
| < 0.80                | n ≥ MIN     | edge-likely    |
| ≥ 0.80                | n ≥ MIN     | edge-strong    |

CLI::

    python3 inferno_bayesian_winrate.py             # run + persist
    python3 inferno_bayesian_winrate.py status      # show last memo
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


BAYESIAN_WINRATE_FILE = DATA_DIR / "inferno_bayesian_winrate.json"
BAYESIAN_WINRATE_TEXT_FILE = REPORTS_DIR / "bayesian_winrate_latest.txt"
BAYESIAN_WINRATE_STAGE = "bayesian-winrate-research-only"

PRIOR_ALPHA = float(os.environ.get("INFERNO_BAYES_PRIOR_ALPHA", "2.0"))
PRIOR_BETA = float(os.environ.get("INFERNO_BAYES_PRIOR_BETA", "2.0"))
EDGE_THRESHOLD = float(os.environ.get("INFERNO_BAYES_EDGE_THRESHOLD", "0.55"))
MIN_BAYES_SAMPLES = int(os.environ.get("INFERNO_BAYES_MIN_SAMPLES", "8"))
POSTERIOR_DRAWS = int(os.environ.get("INFERNO_BAYES_DRAWS", "4000"))
BAYES_SEED = int(os.environ.get("INFERNO_BAYES_SEED", "20260516"))
STRONG_PROBABILITY = 0.80
LIKELY_PROBABILITY = 0.50
REJECTED_PROBABILITY = 0.20


# ---------------------------------------------------------------------------
# Pure math.
# ---------------------------------------------------------------------------


def posterior_parameters(
    wins: int,
    losses: int,
    *,
    prior_alpha: float = PRIOR_ALPHA,
    prior_beta: float = PRIOR_BETA,
) -> tuple[float, float]:
    """Return the posterior ``(α, β)`` after observing ``wins, losses``."""
    if wins < 0 or losses < 0:
        raise ValueError("wins and losses must both be non-negative")
    return prior_alpha + wins, prior_beta + losses


def posterior_mean(alpha: float, beta: float) -> float:
    """Mean of a Beta(α, β) distribution."""
    total = alpha + beta
    if total <= 0:
        return 0.5
    return alpha / total


def posterior_credible_interval(
    alpha: float,
    beta: float,
    *,
    draws: int = POSTERIOR_DRAWS,
    seed: int = BAYES_SEED,
    alpha_level: float = 0.05,
) -> tuple[float, float]:
    """Monte-Carlo 95% credible interval for Beta(α, β).

    Uses ``random.betavariate`` (stdlib). For very tight CIs at extreme
    parameter values, increase ``draws``.
    """
    if alpha <= 0 or beta <= 0:
        return 0.0, 1.0
    rng = random.Random(seed)
    samples = [rng.betavariate(alpha, beta) for _ in range(draws)]
    samples.sort()
    lo_idx = max(0, int((alpha_level / 2.0) * draws))
    hi_idx = min(draws - 1, int((1.0 - alpha_level / 2.0) * draws))
    return float(samples[lo_idx]), float(samples[hi_idx])


def posterior_probability_above(
    alpha: float,
    beta: float,
    threshold: float,
    *,
    draws: int = POSTERIOR_DRAWS,
    seed: int = BAYES_SEED,
) -> float:
    """``P(p > threshold)`` under Beta(α, β) by Monte Carlo.

    For threshold=0.5, this is the probability the strategy beats coinflip.
    For threshold=0.55, the probability of a "real" edge by our convention.
    """
    if alpha <= 0 or beta <= 0:
        return 0.0
    if not (0.0 <= threshold <= 1.0):
        raise ValueError(f"threshold must be in [0, 1], got {threshold}")
    rng = random.Random(seed)
    hits = sum(1 for _ in range(draws) if rng.betavariate(alpha, beta) > threshold)
    return hits / draws


def classify_strategy(
    *,
    sample_size: int,
    probability_above_edge: float,
) -> str:
    if sample_size < MIN_BAYES_SAMPLES:
        return "insufficient"
    if probability_above_edge >= STRONG_PROBABILITY:
        return "edge-strong"
    if probability_above_edge >= LIKELY_PROBABILITY:
        return "edge-likely"
    if probability_above_edge >= REJECTED_PROBABILITY:
        return "edge-uncertain"
    return "edge-rejected"


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


def count_wins_losses_by_strategy(
    records: list[dict[str, Any]],
) -> dict[str, tuple[int, int]]:
    """Per-strategy ``(wins, losses)`` over closed outcomes."""
    out: dict[str, tuple[int, int]] = {}
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
        w, ell = out.get(strategy, (0, 0))
        if r > 0:
            w += 1
        else:
            ell += 1
        out[strategy] = (w, ell)
    return out


# ---------------------------------------------------------------------------
# Pure builder.
# ---------------------------------------------------------------------------


def build_bayesian_winrate(
    *,
    shadow_loader: Callable[[], list[dict[str, Any]]] | None = None,
    edge_threshold: float = EDGE_THRESHOLD,
    draws: int = POSTERIOR_DRAWS,
    seed: int = BAYES_SEED,
) -> dict[str, Any]:
    """Compute the Bayesian win-rate posterior for every strategy."""
    records = (shadow_loader or _default_shadow_loader)()
    by_strategy = count_wins_losses_by_strategy(records)

    rows: list[dict[str, Any]] = []
    for strategy, (wins, losses) in by_strategy.items():
        n = wins + losses
        alpha, beta = posterior_parameters(wins, losses)
        mean = posterior_mean(alpha, beta)
        lo, hi = posterior_credible_interval(alpha, beta, draws=draws, seed=seed)
        prob_above_coin = posterior_probability_above(alpha, beta, 0.5, draws=draws, seed=seed)
        prob_above_edge = posterior_probability_above(alpha, beta, edge_threshold, draws=draws, seed=seed)
        verdict = classify_strategy(
            sample_size=n,
            probability_above_edge=prob_above_edge,
        )
        rows.append({
            "strategy": strategy,
            "wins": wins,
            "losses": losses,
            "sampleSize": n,
            "posteriorAlpha": round(alpha, 4),
            "posteriorBeta": round(beta, 4),
            "posteriorMean": round(mean, 4),
            "credibleLower": round(lo, 4),
            "credibleUpper": round(hi, 4),
            "probabilityAboveCoin": round(prob_above_coin, 4),
            "probabilityAboveEdge": round(prob_above_edge, 4),
            "edgeThreshold": edge_threshold,
            "verdict": verdict,
        })

    rows.sort(key=lambda r: (-r["probabilityAboveEdge"], -r["sampleSize"], r["strategy"]))

    strong = [r for r in rows if r["verdict"] == "edge-strong"]
    likely = [r for r in rows if r["verdict"] == "edge-likely"]
    uncertain = [r for r in rows if r["verdict"] == "edge-uncertain"]
    rejected = [r for r in rows if r["verdict"] == "edge-rejected"]
    insufficient = [r for r in rows if r["verdict"] == "insufficient"]

    if not rows:
        verdict = "no-evidence"
        narrative = (
            "No closed shadow records — Bayesian posterior is the prior alone. "
            "Keep building paper evidence."
        )
    elif strong:
        verdict = "strong-edges-detected"
        narrative = (
            f"{len(strong)} strategy/strategies have posterior P(win > "
            f"{edge_threshold}) ≥ {STRONG_PROBABILITY}. "
            f"{len(likely)} likely, {len(uncertain)} uncertain, "
            f"{len(rejected)} rejected, {len(insufficient)} insufficient."
        )
    elif likely:
        verdict = "likely-edges"
        narrative = (
            f"{len(likely)} strategy/strategies in the likely-edge band "
            f"({LIKELY_PROBABILITY}–{STRONG_PROBABILITY}); none strong yet. "
            f"{len(rejected)} rejected; {len(insufficient)} insufficient."
        )
    elif uncertain:
        verdict = "uncertain"
        narrative = (
            f"Every strategy with sample is in the uncertain band; the Bayesian "
            f"posterior cannot yet separate signal from noise above the "
            f"{edge_threshold} threshold."
        )
    elif rejected:
        verdict = "edges-rejected"
        narrative = (
            f"{len(rejected)} strategy/strategies have posterior P(win > "
            f"{edge_threshold}) < {REJECTED_PROBABILITY}. The Bayesian view "
            "is unfavorable; reconcile against frequentist Wilson before any change."
        )
    else:
        verdict = "all-insufficient"
        narrative = (
            f"No strategy has reached {MIN_BAYES_SAMPLES} samples. "
            "Posterior is dominated by the prior."
        )

    return {
        "generatedAt": local_now().isoformat(),
        "stage": BAYESIAN_WINRATE_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "method": "beta-binomial-monte-carlo",
        "priorAlpha": PRIOR_ALPHA,
        "priorBeta": PRIOR_BETA,
        "edgeThreshold": edge_threshold,
        "minSamples": MIN_BAYES_SAMPLES,
        "monteCarloDraws": draws,
        "strategyCount": len(rows),
        "strongCount": len(strong),
        "likelyCount": len(likely),
        "uncertainCount": len(uncertain),
        "rejectedCount": len(rejected),
        "insufficientCount": len(insufficient),
        "rows": rows,
        "reminders": [
            "Bayesian posterior pairs with Wilson lower bound; both must agree before promotion",
            "weak conservative prior Beta(2, 2) pulls toward 0.5 when sample is tiny",
            "P(p > 0.55) is the operator-set 'edge' probability; widen via INFERNO_BAYES_EDGE_THRESHOLD",
        ],
    }


def bayesian_text(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno Bayesian Win Rate (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Method: {payload.get('method')}  draws={payload.get('monteCarloDraws')}  "
        f"prior=Beta({payload.get('priorAlpha')},{payload.get('priorBeta')})",
        f"Verdict: {payload.get('verdict')}  edge-threshold={payload.get('edgeThreshold')}",
        f"Strategies: {payload.get('strategyCount')}  "
        f"strong={payload.get('strongCount')}  "
        f"likely={payload.get('likelyCount')}  "
        f"uncertain={payload.get('uncertainCount')}  "
        f"rejected={payload.get('rejectedCount')}  "
        f"insufficient={payload.get('insufficientCount')}",
        "",
        f"Narrative: {payload.get('narrative')}",
    ]
    rows = payload.get("rows") or []
    if rows:
        lines.extend(["", "Per-strategy posterior:"])
        lines.append(
            f"{'Strategy':<22} {'N':>4} {'mean':>6} "
            f"{'lo95':>6} {'hi95':>6} {'P>0.5':>7} {'P>edge':>7} {'Verdict'}"
        )
        for row in rows:
            lines.append(
                f"{str(row['strategy'])[:22]:<22} "
                f"{row['sampleSize']:>4} "
                f"{row['posteriorMean']:>6.3f} "
                f"{row['credibleLower']:>6.3f} "
                f"{row['credibleUpper']:>6.3f} "
                f"{row['probabilityAboveCoin']:>7.3f} "
                f"{row['probabilityAboveEdge']:>7.3f} "
                f"{row['verdict']}"
            )
    lines.extend(["", "Thresholds:"])
    lines.append(f"- minSamples: n >= {payload.get('minSamples')}")
    lines.append(f"- edge-strong:   P(p > edge) >= {STRONG_PROBABILITY}")
    lines.append(f"- edge-likely:   P(p > edge) >= {LIKELY_PROBABILITY}")
    lines.append(f"- edge-rejected: P(p > edge) <  {REJECTED_PROBABILITY}")
    lines.extend(["", "Reminders:"])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_bayesian_winrate(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(BAYESIAN_WINRATE_FILE, payload)
    atomic_write_text(BAYESIAN_WINRATE_TEXT_FILE, bayesian_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compute the Beta-binomial posterior win rate for every strategy. "
            "Research-only; never promotable."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and BAYESIAN_WINRATE_TEXT_FILE.exists():
        print(BAYESIAN_WINRATE_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_bayesian_winrate()
    save_bayesian_winrate(payload)
    print(bayesian_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
