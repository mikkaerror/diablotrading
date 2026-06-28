from __future__ import annotations

"""Inferno Math Config — every math knob in one auditable file.

What it does:
    Centralises the target random seeds, resample counts, gate thresholds,
    and verdict-band boundaries for the desk's math layer. This is the
    audited source of truth future math modules should import from as the
    remaining inline constants are migrated.

Why this exists:
    Boring, repeatable, trustworthy math has *one* place where every
    knob lives. Before this module, the math layer had:
      - 7 different random seeds across 7 modules
      - 4 different bootstrap resample defaults
      - 5 different "verdict ladder" vocabularies
      - hyperparameters defined inline in business logic
    That made auditing the math impossible — you'd have to grep 15
    files to know what a change to a single threshold would touch.

    With this module:
      - One global seed (``MATH_SEED``) with deterministic per-module
        derivation so individual modules can still seed independently
        without colliding.
      - One bootstrap resample default (``DEFAULT_BOOTSTRAP_RESAMPLES``).
      - One vocabulary of verdict band names (see ``VERDICT_VOCAB``).
      - One CI alpha (``DEFAULT_ALPHA``).
      - One picky-operator level (``OPERATOR_LEVEL``) that maps to the
        target cross-sectional gate percentile.

What it does NOT do:
    - Hold any state. This module is constants only.
    - Read or write disk. Pure configuration.
    - Override module-specific env vars set explicitly by the operator
      (those still take precedence — the constants here are defaults).

Strict contract: read-only constants and pure derivation helpers. Tests
must be able to import this module without side effects.

## The single seed discipline

A boring math layer uses one seed and derives per-module seeds via a
deterministic hash. That way:

  - Reproducing any historical run requires fixing only ``MATH_SEED``.
  - Two modules' random streams never accidentally collide.
  - Code review is easy: one number to inspect.

The derivation is::

    module_seed(name) = (MATH_SEED + stable_hash(name)) mod 2^31

where ``stable_hash`` is a Python `hash()`-free deterministic hash so
the same name always derives the same seed across Python invocations.

## The picky-operator level

The operator decides how picky the desk should be once, and every
module's thresholds shift consistently. Levels::

    "default"  - sensible production defaults
    "ackman"   - top 10% picky (concentrated, willing to wait)
    "buffett"  - top 5% picky (only the bell-cow names)
    "simons"   - top 1% picky (statistical-arb tight)

Changing levels touches every module at once. No drift between modules.
"""

import hashlib
import os
from typing import Final


# ---------------------------------------------------------------------------
# Master seed and per-module derivation.
# ---------------------------------------------------------------------------

# One number that anchors every random stream on the desk. Override only
# when intentionally re-running a historical analysis.
MATH_SEED: Final[int] = int(os.environ.get("INFERNO_MATH_SEED", "20260520"))


def module_seed(module_name: str) -> int:
    """Derive a deterministic per-module seed from the master seed.

    Uses BLAKE2b (stdlib) instead of Python's ``hash()`` because the
    latter is randomized between interpreter starts when PYTHONHASHSEED
    is not set. We need cross-invocation stability.

    Returns an integer in ``[0, 2^31)`` suitable for ``random.Random``.
    """
    if not isinstance(module_name, str) or not module_name:
        raise ValueError("module_name must be a non-empty string")
    digest = hashlib.blake2b(module_name.encode("utf-8"), digest_size=4).digest()
    suffix = int.from_bytes(digest, "big") & 0x7FFFFFFF
    return (MATH_SEED + suffix) & 0x7FFFFFFF


# ---------------------------------------------------------------------------
# Resample counts.
# ---------------------------------------------------------------------------

DEFAULT_BOOTSTRAP_RESAMPLES: Final[int] = int(
    os.environ.get("INFERNO_BOOTSTRAP_RESAMPLES", "2000")
)
"""Default bootstrap resample count. Override per-module only when there's
a quantified reason (e.g. permutation tests can use fewer because each
permutation is cheaper to evaluate)."""

DEFAULT_PERMUTATION_RESAMPLES: Final[int] = int(
    os.environ.get("INFERNO_PERMUTATION_RESAMPLES", "1000")
)
"""Default permutation-test resample count for mutual information and
sign-flip falsification."""

DEFAULT_POSTERIOR_DRAWS: Final[int] = int(
    os.environ.get("INFERNO_POSTERIOR_DRAWS", "4000")
)
"""Default Monte Carlo draws for posterior credible intervals."""


# ---------------------------------------------------------------------------
# Confidence levels.
# ---------------------------------------------------------------------------

DEFAULT_ALPHA: Final[float] = float(os.environ.get("INFERNO_DEFAULT_ALPHA", "0.05"))
"""Default two-tailed alpha for every CI on the desk. 0.05 ≡ 95% CI."""

DEFAULT_Z: Final[float] = 1.96
"""Two-tailed z-score for 95% confidence. Frozen — change alpha instead."""


# ---------------------------------------------------------------------------
# Picky-operator levels — one knob shifts every threshold consistently.
# ---------------------------------------------------------------------------

OPERATOR_LEVEL: Final[str] = os.environ.get("INFERNO_OPERATOR_LEVEL", "default").lower()
"""Sets the picky level for cross-sectional gates. Values:

    default - top 20% by Ready percentile rank
    ackman  - top 10%
    buffett - top 5%
    simons  - top 1%
"""

OPERATOR_LEVEL_GATE_PERCENTILE: Final[dict[str, float]] = {
    "default": 80.0,
    "ackman":  90.0,
    "buffett": 95.0,
    "simons":  99.0,
}


def gate_percentile_for_level(level: str | None = None) -> float:
    """Return the readyRank gate percentile for the picky level."""
    chosen = (level or OPERATOR_LEVEL).lower()
    return OPERATOR_LEVEL_GATE_PERCENTILE.get(chosen, 80.0)


# ---------------------------------------------------------------------------
# Promotion gates (frozen — these are the desk's risk policy).
# ---------------------------------------------------------------------------

MIN_PAPER_SAMPLES_FOR_PROMOTION: Final[int] = 30
"""Strategy needs at least this many closed paper outcomes before any
promotion math can render a verdict that touches authority."""

MIN_WILSON_LOWER_FOR_EDGE: Final[float] = 0.42
"""Legacy fixed Wilson lower-bound fallback used only when a payoff-aware
strategy promotion target cannot be derived. The live strategy-lab gate uses
payoff-implied breakeven plus margin when payoff data exists."""

DEVILS_ADVOCATE_HOLD_P: Final[float] = 0.05
"""Sign-flip bootstrap one-sided p-value below which the falsification
verdict is ``edge-holds``."""

DEVILS_ADVOCATE_WEAKEN_P: Final[float] = 0.20
"""p-value below which the falsification verdict is ``edge-weakens``.
At or above this the verdict is ``edge-falsified``."""

EVIDENCE_STRENGTH_STRONG: Final[float] = 0.70
EVIDENCE_STRENGTH_MODERATE: Final[float] = 0.40
EVIDENCE_STRENGTH_WEAK: Final[float] = 0.20
"""Geometric-mean composite thresholds for the four-band verdict ladder
(strong, moderate, weak, insufficient)."""


# ---------------------------------------------------------------------------
# Risk caps (frozen — sourced from RISK_POLICY.md).
# ---------------------------------------------------------------------------

MAX_KELLY_FRACTION: Final[float] = 0.25
"""Quarter-Kelly cap on any single strategy's risk fraction."""

MAX_DAILY_RISK_UNITS: Final[float] = 3.0
"""Global daily ceiling on summed Kelly fractions across strategies."""


# ---------------------------------------------------------------------------
# The one vocabulary every verdict ladder draws from.
# ---------------------------------------------------------------------------

VERDICT_VOCAB: Final[frozenset[str]] = frozenset({
    # universal bands
    "strong", "moderate", "weak", "insufficient", "no-evidence",
    # falsification
    "edge-holds", "edge-weakens", "edge-falsified",
    # walk-forward
    "survives", "decays", "reverses", "emerged", "no-edge",
    # drift / CUSUM
    "stable", "improving", "unstable", "baseline-noisy",
    # bayesian
    "edge-strong", "edge-likely", "edge-uncertain", "edge-rejected",
    # kelly
    "sized", "cap-limited", "marginal", "no-position", "degenerate",
    # information gain
    "signal-detected", "meaningful-signal", "faint-signal", "no-signal",
    # math verify
    "clean", "violations-detected", "artifacts-missing",
    # operational
    "ready-to-execute", "no-candidates", "no-slate", "no-cash",
    # operator briefing convenience
    "ranked", "no-passers", "tight-shortlist", "live-quality-found",
    "ready-to-seed", "slate-too-thin", "insufficient-relaxation",
})
"""Every verdict string the math layer emits must come from this set.
New modules that need new verdicts add them here first so the audit
surface remains finite."""


# ---------------------------------------------------------------------------
# Convenience snapshot for auditors.
# ---------------------------------------------------------------------------


def snapshot() -> dict[str, object]:
    """Return a flat dict of every config knob — what an auditor inspects."""
    return {
        "mathSeed": MATH_SEED,
        "defaultBootstrapResamples": DEFAULT_BOOTSTRAP_RESAMPLES,
        "defaultPermutationResamples": DEFAULT_PERMUTATION_RESAMPLES,
        "defaultPosteriorDraws": DEFAULT_POSTERIOR_DRAWS,
        "defaultAlpha": DEFAULT_ALPHA,
        "defaultZ": DEFAULT_Z,
        "operatorLevel": OPERATOR_LEVEL,
        "gatePercentile": gate_percentile_for_level(),
        "minPaperSamplesForPromotion": MIN_PAPER_SAMPLES_FOR_PROMOTION,
        "minWilsonLowerForEdge": MIN_WILSON_LOWER_FOR_EDGE,
        "devilsAdvocateHoldP": DEVILS_ADVOCATE_HOLD_P,
        "devilsAdvocateWeakenP": DEVILS_ADVOCATE_WEAKEN_P,
        "evidenceStrengthStrong": EVIDENCE_STRENGTH_STRONG,
        "evidenceStrengthModerate": EVIDENCE_STRENGTH_MODERATE,
        "evidenceStrengthWeak": EVIDENCE_STRENGTH_WEAK,
        "maxKellyFraction": MAX_KELLY_FRACTION,
        "maxDailyRiskUnits": MAX_DAILY_RISK_UNITS,
        "verdictVocabSize": len(VERDICT_VOCAB),
    }
