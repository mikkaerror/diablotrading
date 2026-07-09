# Math Reference

Every probability and statistical primitive the desk uses. One source of
truth, with formulas, edge-case behavior, and a worked example for each.

If a module's math contradicts this doc, the doc wins.

## 1. Wilson interval (binomial confidence bound)

A confidence interval for the proportion ``p = w/n`` of wins to total
trials. Tighter than the naive normal-approximation interval, especially
when ``p`` is near 0 or 1 or when ``n`` is small.

**Formula** (95% CI, ``z = 1.96``):

```
denom  = 1 + z²/n
center = (p + z²/(2n)) / denom
half   = z · √( p(1-p)/n + z²/(4n²) ) / denom
[lower, upper] = center ± half
```

**Edge cases:**
- ``n == 0`` → returns ``(0.0, 1.0)`` (uninformative — every proportion possible).
- ``p == 0`` or ``p == 1`` → returns a strictly-narrow interval that never
  collapses to a point (unlike the normal approximation).

**Worked example.** 6 wins out of 10 trades:

```
p = 0.6, z = 1.96, n = 10
denom  = 1 + 3.8416/10        = 1.384
center = (0.6 + 0.192) / 1.384 = 0.5727
half   = 1.96 · √(0.24/10 + 0.0384) / 1.384 = 0.2593
lower  ≈ 0.3127
upper  ≈ 0.832
```

So 6-of-10 gives a 95% CI of roughly ``[0.31, 0.83]``. The desk's edge
gates use the *lower* bound, not the point estimate.

**Module:** `inferno_theme_synthesizer.wilson_interval`.

## 2. Percentile bootstrap CI on the mean

Non-parametric CI on the mean of a sample. Robust to non-normality, which
matters because R-unit distributions are fat-tailed.

**Algorithm:**

1. Compute observed mean ``μ̂ = mean(X)``.
2. Resample ``X`` with replacement ``B`` times (default 2000); compute the
   mean of each resample.
3. Sort the resampled means.
4. The 95% CI is ``[means[B·0.025], means[B·0.975]]``.

**Edge cases:**
- ``n == 0`` → returns ``(0, 0, 0)``.
- ``n == 1`` → returns ``(x, x, x)``; bootstrap can't extract info from a
  single point.

**Seed.** Every module that bootstraps fixes the RNG seed so test runs are
reproducible.

**Module:** `inferno_theme_synthesizer.bootstrap_mean_ci`.

## 3. Sign-flip bootstrap p-value (falsification)

Tests ``H0: mean(X) = 0`` under the assumption that, absent edge, the
distribution is approximately symmetric around zero. This is the canonical
non-parametric falsification of a claimed edge.

**Algorithm:**

1. Compute observed mean ``μ̂_obs``.
2. For each of ``B`` resamples (default 2000): flip each ``x_i``'s sign
   with probability 0.5; compute the resample mean ``μ̂_b``.
3. Count resamples with ``μ̂_b ≥ μ̂_obs``; call the count ``k``.
4. One-sided p-value with the Phipson–Smyth exact-test correction:

```
p = (1 + k) / (B + 1)
```

The ``+1`` numerator and denominator keep ``p`` strictly positive even
when no resample exceeds the observation. Without the correction, an
exact p of 0 underestimates the true rate of seeing the observation by
chance.

**Verdict ladder** (stricter than standard frequentist tests by design):

| p-value         | verdict          |
|----------------:|------------------|
| `p < 0.05`      | edge-holds       |
| `p < 0.20`      | edge-weakens     |
| `p ≥ 0.20`      | edge-falsified   |
| `n < 8`         | insufficient     |

**Module:** `inferno_devils_advocate.sign_flip_p_value`.

**Reference.** Phipson & Smyth (2010), *Permutation P-values Should Never
Be Zero*, Statistical Applications in Genetics and Molecular Biology.

## 4. Two-sample bootstrap on a mean difference

Tests whether two independent samples have different means.

**Algorithm:**

1. Compute observed difference ``Δ̂ = mean(A) - mean(B)``.
2. For each resample: draw ``|A|`` items from ``A`` with replacement and
   ``|B|`` items from ``B`` with replacement; compute the difference of
   resample means.
3. 95% CI is the empirical 2.5%–97.5% range of the resample differences.

**Verdict ladder** (used in the VRP discriminator):

| CI                   | verdict        |
|----------------------|----------------|
| `lower > 0`          | vrp-real       |
| `upper ≤ 0`          | vrp-absent     |
| `lower ≤ 0 ≤ upper`  | vrp-uncertain  |
| `min(|A|, |B|) < 5`  | insufficient   |

**Module:** `inferno_vol_premium.bootstrap_mean_diff`.

## 5. Geometric mean composite

The composite score in `inferno_evidence_strength` is the geometric mean
of its component scores. We choose geometric over arithmetic because the
geometric mean is *asymmetric in favor of the worst component*: if any
component is near zero, the composite is near zero too.

**Formula** (over ``k`` active components, each in ``[0, 1]``):

```
strength = ( ∏ s_i )^(1/k)
```

Equivalently, in log-space (which we use to avoid underflow):

```
strength = exp( (1/k) · Σ ln(max(s_i, ε)) )
```

with ``ε = 1e-12`` to guard against ``ln(0)``.

**Components currently composed:**

| Component        | Formula                                      |
|------------------|----------------------------------------------|
| Sample-size      | `min(1, n / 60)`                             |
| Wilson lower     | `max(0, (w_lo − 0.5) / 0.5)`                 |
| Expectancy lower | `clamp(m_lo / 0.40, 0, 1)`                   |
| Falsification    | `edges_holding / max(1, strategies_total)`   |

Missing components (e.g. devil's advocate hasn't run) are *dropped*, not
zeroed. Drop-vs-zero matters: dropping means we don't punish for absent
data, but the remaining components still must clear the gate.

**Module:** `inferno_evidence_strength.composite_strength`.

## 6. Conservative Kelly fraction

Classic Kelly is ``f* = μ / σ²``. The *conservative* version we ship
substitutes the 95% **lower** bound on μ and the 95% **upper** bound on
σ², then caps at quarter-Kelly. This is the version that survives an
adversarial 95% scenario on both moments simultaneously.

**Formula:**

```
f_conservative = max(0, μ̂_lo / σ̂²_hi)
f_capped       = min(f_conservative, 0.25)
```

Then aggregate:

```
total = min( Σ f_capped[strategy] , MAX_DAILY_RISK_UNITS )
```

**Why this asymmetry.** Point-estimate Kelly applied to noisy μ̂
overshoots dramatically. A point estimate of ``μ=0.4R, σ²=1.0R²`` gives
``f* = 0.4`` — 40% of bankroll. But on a small sample the lower-mean /
upper-variance bounds might be ``μ_lo=0.10, σ²_hi=1.6``, giving
``f_conservative = 0.0625`` — about a sixth of the point estimate. That's
exactly the right asymmetry: under-bet when the data is thin.

**Verdict ladder:**

| Condition                                | Verdict       |
|------------------------------------------|---------------|
| `n < 8`                                  | insufficient  |
| `mean(X) ≤ 0`                            | no-position   |
| `var(X) == 0`                            | degenerate    |
| `f_conservative ≤ 0`                     | marginal      |
| `f_capped ≥ MAX_KELLY_FRACTION`          | cap-limited   |
| else                                     | sized         |

**Module:** `inferno_kelly_sizing`.

**Reference.** Thorp (2006), *The Kelly Criterion in Blackjack, Sports
Betting, and the Stock Market*.

## 7. R-units (the desk's unit of risk)

Every trade outcome is expressed in *multiples of maximum loss at entry*.

```
R = pnl / |max_loss_at_entry|
```

- ``R = +1.0`` means the trade returned one unit of the risk taken.
- ``R = −1.0`` means the trade hit max loss.
- ``R > 0`` means win; ``R ≤ 0`` means loss.

This normalization is what lets us pool outcomes across strategies with
very different dollar sizes. Every module that does math on outcomes
operates on R-units, not dollar P&L.

**Module:** `inferno_theme_synthesizer._r_units`.

## 8. IV bucket boundaries

Implied volatility rank is bucketed at fixed boundaries for the VRP
discriminator:

| Bucket | ivRank range  |
|--------|---------------|
| low    | `[0, 33)`     |
| mid    | `[33, 66)`    |
| high   | `[66, 100]`   |

Records with missing ``ivRank`` go into the ``unknown`` bucket and are
excluded from VRP math (but counted in the cube summary).

**Module:** `inferno_vol_premium.classify_iv_bucket`.

## 9. Strategy → vol direction map

Strategies are categorised as ``short-vol``, ``long-vol``, or
``vega-neutral``. The default map in `inferno_vol_premium.DEFAULT_VOL_DIRECTION_MAP`
covers the desk's current playbook; operators may override via the
``INFERNO_VRP_VOL_TAGS`` env var (format: ``Name1:direction;Name2:...``).

Substring matching means "Bull Put Credit Spread" still maps to
``short-vol`` via the "credit spread" key.

## 10. Promotion gates summary

When a strategy might be promoted, every module's verdict must clear:

| Gate                                  | Required           |
|---------------------------------------|--------------------|
| Sample size (`inferno_strategy_lab`)  | typically ≥ 30     |
| Wilson lower bound                    | ≥ 0.42 (current)   |
| Expectancy lower bound                | > 0                |
| Devil's advocate                      | edge-holds         |
| Evidence strength composite           | ≥ 0.70             |
| Authority manifest                    | controller approves|

A failure on any single gate blocks promotion. No gate has authority to
override another.

## 11. Beta-binomial Bayesian posterior

The Bayesian complement to Wilson. Beta-binomial conjugate update with a
weak conservative prior ``Beta(α₀, β₀) = Beta(2, 2)``:

```
posterior = Beta(α₀ + wins, β₀ + losses)
mean      = (α₀ + wins) / (α₀ + β₀ + wins + losses)
```

95% credible interval is the empirical 2.5%–97.5% quantile of 4000
samples drawn via ``random.betavariate`` (stdlib, no deps). The
operator-relevant probabilities are:

```
P(p > 0.5)  — strategy beats coinflip
P(p > 0.55) — strategy clears the operator-set 'edge' threshold
```

**Verdict ladder** (per strategy):

| P(p > edge_threshold) | Verdict        |
|----------------------:|----------------|
| ≥ 0.80                | edge-strong    |
| ≥ 0.50                | edge-likely    |
| ≥ 0.20                | edge-uncertain |
| < 0.20                | edge-rejected  |
| n < 8                 | insufficient   |

**Why both Wilson and Bayesian.** Wilson gives a frequentist CI on the
proportion. Bayesian gives a posterior probability statement —
``P(p > t)`` — that Wilson can't. When the two agree, we trust. When
they disagree, the prior is doing work and the sample is small: be
conservative.

**Module:** `inferno_bayesian_winrate`.

## 12. Two-sided CUSUM change-point detection

Page (1954) cumulative-sum control chart. Per strategy, the in-control
baseline is the *first half* of the chronologically-ordered R-unit
stream; the second half is the period under test.

```
S⁺_t = max( 0 , S⁺_{t-1} + (x_t - μ̂ - k·σ̂) )
S⁻_t = min( 0 , S⁻_{t-1} + (x_t - μ̂ + k·σ̂) )
alarm when |S| > h · σ̂
```

with ``k = 0.5`` (allowance) and ``h = 5`` (alarm) by default.

**Verdict ladder** (per strategy):

| Condition                                | Verdict        |
|------------------------------------------|----------------|
| n < 12                                   | insufficient   |
| both alarms None                         | stable         |
| up-alarm in tested half only             | improving      |
| down-alarm in tested half only           | decaying       |
| both alarms in tested half               | unstable       |
| alarm in baseline half                   | baseline-noisy |

Decay is the silent killer that mean-CI tests don't catch: a strategy
with full-sample mean +0.3R might be +0.6R in the first half and 0.0R
in the second. CUSUM catches that.

**Module:** `inferno_regime_drift`.

**Reference.** Page (1954), *Continuous Inspection Schemes*, Biometrika 41(1).

## 13. Mutual information (information gain)

Shannon mutual information between a discrete feature ``F`` and the
Bernoulli outcome ``Y`` (win/loss), in bits:

```
I(F; Y) = Σ_f Σ_y p(f, y) · log₂( p(f, y) / (p(f) · p(y)) )
```

Equivalently ``I(F; Y) = H(Y) - H(Y | F)``: how many bits of outcome
uncertainty are resolved by observing F.

Normalised MI scales the result to ``[0, 1]``:

```
NMI = I(F; Y) / H(Y)
```

Statistical significance is computed by a permutation test: shuffle the
outcome labels ``B`` times (default 1000) and count permutations whose
MI matches or exceeds the observed. With Phipson–Smyth correction:

```
p = (1 + k) / (B + 1)
```

**Verdict ladder** (per feature):

| NMI band   | Verdict      |
|-----------:|--------------|
| ≥ 0.15     | strong       |
| ≥ 0.05     | meaningful   |
| ≥ 0.01     | faint        |
| < 0.01     | noise        |
| n < 20     | insufficient |

**Module:** `inferno_information_gain`.

**Reference.** Cover & Thomas (2006), *Elements of Information Theory*,
Ch. 2.

## 14. Black-Scholes options primitives

Standard Black-Scholes (1973) primitives, pure functions, no I/O:

```
d1 = ( ln(S/K) + (r + σ²/2) T ) / ( σ √T )
d2 = d1 - σ √T
```

Implied 1-σ move at the money:

```
move_1σ = S · σ · √T
```

Short-horizon expected absolute move approximation (also the ATM straddle
breakeven traders usually quote):

```
E[|S_T - S_0|]  ≈  S · σ · √T · √(2/π)  ≈  0.7979 · S · σ · √T
```

This is the normal/small-move approximation around spot, not an exact
closed-form lognormal absolute deviation. It is appropriate for the
short earnings horizons where the dashboard uses it as a sanity-check
breakeven proxy.

Call delta ``= N(d1)``; put delta ``= N(d1) - 1``. Put-call delta
parity ``Δ_call - Δ_put = 1`` is preserved across every input.

The IV-rank-to-annualised-IV converter linearly interpolates between
configurable floor (default 10%) and ceiling (default 120%):

```
σ_annual = iv_floor + (rank / 100) · (iv_ceiling - iv_floor)
```

**Module:** `inferno_options_math`.

**Reference.** Black & Scholes (1973), *The Pricing of Options and
Corporate Liabilities*, Journal of Political Economy 81(3).

## 15. Walk-forward validation

Per strategy, split the chronologically-ordered R-unit stream into a
training half ``T`` (first ⌊n/2⌋ samples) and a validation half ``V``
(remaining samples). Compute Wilson lower bound and bootstrap mean CI
on each half *independently*. Survival of edge requires:

```
μ̂_T > 0  and  μ̂_V > 0  and  |μ̂_V - μ̂_T| ≤ 0.5 · σ̂_pooled
```

Six-state verdict ladder (per strategy):

| Condition                                            | Verdict      |
|------------------------------------------------------|--------------|
| n < 16                                               | insufficient |
| Both means > 0 and within ±0.5σ̂ band                | survives     |
| Both > 0 but μ̂_V < μ̂_T − 0.5σ̂                       | decays       |
| μ̂_T > 0, μ̂_V ≤ 0                                    | reverses     |
| μ̂_T ≤ 0, μ̂_V > 0                                    | emerged      |
| Both ≤ 0                                             | no-edge      |

The desk treats *reverses* and *decays* as veto verdicts — they block
promotion regardless of point estimates from other modules. An edge
that doesn't survive a chronological split has not earned authority.

**Module:** `inferno_walk_forward`.

## 16. Logistic factor regression

Fit ``P(win | x) = σ(β·x + b)`` over one-hot-encoded feature buckets
(IV bucket, DTE bucket, ATR%-Z bucket, sector) from the shadow ledger.
Loss is the standard logistic negative log-likelihood with L2
regularisation:

```
∂L/∂β_j = Σ_i (y_i − σ(β·x_i + b)) · x_ij − λ β_j
∂L/∂b   = Σ_i (y_i − σ(β·x_i + b))
```

Batch gradient ascent, ``η = 0.1``, ``λ = 0.1``, max 500 iterations,
tolerance ``10⁻⁶`` on the L2-norm of the average gradient. Hand-rolled
(stdlib `math` only). If the outcome is constant, the module returns
zero feature coefficients and a saturated intercept instead of inventing
factor edge from a one-class sample.

Coefficient confidence intervals via bootstrap: resample records with
replacement ``B = 500`` times, refit each time, take percentile CI on
each coefficient.

**Per-coefficient verdict:**

| 95% CI                | Verdict        |
|-----------------------|----------------|
| lower > 0             | positive-edge  |
| upper < 0             | negative-edge  |
| straddles zero        | inconclusive   |
| n < 30                | insufficient   |

**Reference.** Hosmer, Lemeshow & Sturdivant (2013),
*Applied Logistic Regression*, Wiley.

**Module:** `inferno_factor_regression`.

## 17. Cross-module invariant verification

`inferno_math_verify` loads every math module's latest artifact and
asserts the invariants from this document hold. The invariants checked
include:

- Wilson lower < upper, both in `[0, 1]`
- Bootstrap point estimate sits inside its CI
- Geometric-mean composite ≤ each active component
- Kelly fraction capped at `MAX_KELLY_FRACTION`
- Sum of strategy-bucket counts equals declared total
- Probability fields in `[0, 1]`; p-values strictly in `(0, 1]`
- Bayesian credible-interval bounds in `[0, 1]` and ordered
- Bayesian monotonicity: `P(p > 0.5) ≥ P(p > 0.55)` when threshold ≥ 0.5
- VRP discriminator: `lower ≤ point ≤ upper`
- Information-gain rows sorted by NMI descending
- Walk-forward: `trainSize + validateSize == sampleSize`
- CUSUM alarm threshold equals `h · σ̂`; half index equals `n // 2`
- Factor regression: coefficient CI order, point-inside-CI,
  verdict/CI consistency, and coefficient count totals

Verdict ladder:

| Condition                                | Verdict             |
|------------------------------------------|---------------------|
| every artifact present, no violations    | clean               |
| at least one violation                   | violations-detected |
| missing artifacts but no violations      | artifacts-missing   |

Exit code is 1 when violations are detected. The verifier is the
last-line defense against silent math drift between modules.

**Module:** `inferno_math_verify`.

## 18. Paper bootstrap scoring

The bridge from Phase 1 to Phase 2. Phase 2 unlocks when the math has
~30 closed paper outcomes per active strategy, but the strict live
filter (all five conviction gates simultaneously) typically clears zero
names per day. Without paper data the promotion math has nothing to
learn from. The bootstrapper solves this by scoring each slate row on
*how many* of the five gates it clears:

```
score = sum([
    readiness    >= 72,            # 0-100 percent, computed via score_to_percent
    confidence   >= 2,
    daysToEarnings <= 21,
    setupRec     not in {"Avoid"},
    bool(signalTrigger),
])
```

The gate is evaluated against the row's computed ``readiness`` field
(0–100 percent, produced by ``morning_inferno_pipeline.score_to_percent``
from the raw ``readyScore`` column). Earlier revisions of this doc and of
``inferno_paper_bootstrap`` compared the raw 0–~4 sheet column directly
against the 0–100 threshold; that was the bug §19 below describes.
Hand-built fixtures and legacy rows without a ``readiness`` field still
fall back to treating ``readyScore`` as if it were already on a 0–100
axis (see ``_readiness_percent``), which preserves historical test
semantics.

Each predicate evaluates to 0 or 1, so `score ∈ [0, 5]`. The default
admit threshold is 3-of-5; the operator can raise it (stricter paper
seeding) or lower it (more seed data, lower quality).

Every proposal carries `paperBootstrap: true`, which the strategy lab
and authority controller respect — bootstrap outcomes feed the shadow
ledger but **never count toward live promotion math** until the operator
manually reclassifies them. The `liveQualityYet` flag is true *only*
when `score == 5`, i.e. the proposal would have cleared the live filter
on its own.

Sizing: each bootstrap paper ticket is `BOOTSTRAP_TICKET_DOLLARS = $50`
of paper notional. Total open bootstrap tickets capped at 10. These caps
are intentionally tiny — bootstrap seed data is not live capital.

Verdict ladder:

| Condition                                 | Verdict                  |
|-------------------------------------------|--------------------------|
| no slate                                  | no-evidence              |
| no row at or above threshold              | insufficient-relaxation  |
| fewer than 3 admitted                     | slate-too-thin           |
| ≥ 3 admitted, all live-quality            | live-quality-found       |
| ≥ 3 admitted, mixed                       | ready-to-seed            |

**Module:** `inferno_paper_bootstrap`.

## 19. Slate normalizer percentile ranks

The slate normalizer solves a practical scale bug — and provides a
permanent scale-invariant safety net so that fix can never silently
regress.

### The bug it was built for

The historical conviction gate ``readyScore ≥ 72`` was brittle: if the
upstream score formula changes scale (or breaks), the gate either lets
everything in or nothing. The empirical finding on the live 143-name
slate was that *every* name produced a raw Ready Score under 10 — the
gate had been pinned to a 100-scale while the formula (a Google Sheets
cell written by ``morning_inferno_pipeline.sync_score_formulas`` —
upstream of Inferno's daily refresh, not in the Backtest repo) produced
values in the 0–~4 range.

The downstream gate now compares ``readiness`` (a 0–100 percent
produced by ``score_to_percent(readyScore, ceiling=2.5)``) against the
72 threshold, in both ``inferno_operator_briefing`` and
``inferno_paper_bootstrap``. With that fix in place, the slate
normalizer's percentile ranks are belt-and-suspenders rather than
load-bearing.

### Percentile rank math

For a column ``x_1, ..., x_n``, the rank of value ``x_i`` is:

```
rank(x_i) = 100 · (count_below + 0.5 · count_equal) / n
```

This is the *averaged* percentile-rank convention — stable under ties,
well-defined on any scale. Multiplying every value by 10× leaves ranks
unchanged. Adding a constant leaves ranks unchanged. The gate becomes
"top N percent of slate" instead of "above threshold X."

### Ranked fields

| Field | Rank output |
|---|---|
| `readyScore` | `readyRank` |
| `valueScore` | `valueRank` |
| `momentumScore` | `momentumRank` |
| `squeezeScore` | `squeezeRank` |
| `ivRank` | `ivPercentileRank` |

``compositeRank`` is the geometric mean of available component ranks:

```
composite_rank = exp( (1/k) · Σ ln(rank_i) )      over k active components
```

One weak pillar drags the whole candidate down — the same asymmetry as
``inferno_evidence_strength``.

### Picky-operator gates

The default gate is ``top 20%`` (readyRank ≥ 80). Picky operator modes:

| Gate | Meaning |
|------|---------|
| ≥ 80 | top 20% (default) |
| ≥ 90 | top 10% (Ackman-strict) |
| ≥ 95 | top 5% (Buffett-strict) |
| ≥ 99 | top 1% (Simons-strict, bell-cow only) |

### Strict contract

``researchOnly=true``, ``diagnosticOnly=true``, ``promotable=false``.
The normalizer is review context only. It does not override the five
live gates, touch authority, or make a trade eligible.

**Module:** `inferno_slate_normalizer`.

## 20. Determinism and seed discipline (`inferno_math_config`)

Boring, repeatable, trustworthy math depends on one rule: **same inputs
always produce the same outputs**. The desk enforces this with a single
master seed and deterministic per-module derivation.

```
module_seed(name) = (MATH_SEED + BLAKE2b(name)) mod 2³¹
```

`MATH_SEED` is the only number that anchors every random stream on the
desk. Reproducing any historical run requires fixing only `MATH_SEED`
(via `INFERNO_MATH_SEED`).

### What lives in the central config

`inferno_math_config` is the auditor's one-screen target view of every
math knob. New math modules should import from it, and existing inline
constants should migrate toward it one module at a time:

- Master seed and per-module derivation
- Bootstrap / permutation / posterior resample counts
- Default `alpha` and `z`
- Promotion gates (Wilson floor, sample size minimum, devil's advocate
  thresholds, evidence strength bands)
- Risk caps (`MAX_KELLY_FRACTION`, `MAX_DAILY_RISK_UNITS`)
- Picky-operator levels: `default` / `ackman` / `buffett` / `simons`
  map to the readyRank gate percentile
- The complete verdict vocabulary (every word every math module can emit)

### The single picky-operator dial

The operator decides how picky the desk should be once, via
`INFERNO_OPERATOR_LEVEL`, and every threshold downstream shifts
consistently. Levels:

| Level | readyRank gate | Meaning |
|-------|---------------:|---------|
| `default` | 80 | Top 20% — production default |
| `ackman` | 90 | Top 10% — concentrated, willing to wait |
| `buffett` | 95 | Top 5% — bell-cow names only |
| `simons` | 99 | Top 1% — stat-arb tight |

### What this buys

- One file to inspect when calibrating the target threshold policy.
- One seed discipline to migrate toward when reproducing historical runs.
- One vocabulary to audit when reviewing every verdict the math emits.
- Future calibration changes touch one file and are unit-tested by
  `tests/test_inferno_math_config`.

**Module:** `inferno_math_config`.

## 21. Trade conviction audit (per-ticket math case)

Most numbers on the desk answer a binary question: *does the gate pass?*
The trade-conviction audit answers a richer question: *given the gate
passed, is the math case for the trade stronger than the math case
against it?*

The auditor is research-only. It cannot approve, reject, or size any
ticket. Its purpose is to keep the operator from confusing a gate pass
with conviction.

### Inputs

For each ready-to-execute ticket on `inferno_operator_briefing`:

- the briefing's chosen structure, allocation, readiness, confidence, DTE
- the matching `inferno_decision_brief` row (tracker, edge, exposure, live)
- `inferno_evidence_strength` (sample size and verdict)
- `inferno_devils_advocate` (falsification verdict)
- `inferno_vol_premium` (direction × IV bucket)
- `inferno_regime_drift` (CUSUM)

### Output

Per ticket, five lists and one conviction tag:

| Section | Rule |
|---|---|
| **bull** | every quantitative reason the gates passed, with explicit numbers and a citation tag |
| **bear** | the strongest available counter-argument; auditor must produce at least one bullet — if no rule fires, the state-of-evidence bullet (prior-only) is inserted automatically so the audit is *never* zero-bear |
| **disagreements** | layers that contradict each other (e.g. readiness ≥ 90 but edge category = Unclassified) |
| **falsification triggers** | pre-committed fold-if-X clauses; the operator commits to an exit *before* sizing |
| **state of evidence** | what the desk does and does not yet know (below `EVIDENCE_PRIOR_ONLY_SAMPLES` closed samples, every readiness number is labelled prior-only) |
| **convictionTag** | `supportable` / `mixed` / `weak`; downgrades when bear ≥ bull or any disagreement fires |

### Why a bear is mandatory

A trade-conviction audit that never produces a bear bullet is a
yes-man. To preserve adversarial rigor under refactors, the test suite
pins the no-yes-man invariant:

```python
def test_clean_ticket_still_gets_a_bear(self):
    # Even on a maximally clean ticket, auditor must produce a bear bullet.
```

### Disagreement detection

A disagreement is any pair of evidence layers that point in opposite
directions on conviction. The rule set is deterministic and small. Each
rule names the two layers, quotes their numbers, and links to where to
verify. Examples already shipping:

- readiness ≥ 90 AND edge.lane in {Unclassified, Ignore For Theme}
- ticker.sector == slate.largestSector AND largestSectorShare ≥ 0.50
- trend == Bullish AND chosen structure delta-neutral (straddle)
- IV rank ≥ 80 AND chosen structure is long-premium

When a disagreement fires, conviction is at least *mixed*. The audit
does not block the trade — that is the operator's call — but it
guarantees the operator made the call with the disagreement visible.

### Citations

Every theory tag in a bull or bear bullet resolves through
`docs/THEORY_REFERENCES.md` to a peer-reviewed paper. The bear case for
long straddles, for example, cites Bakshi & Kapadia (2003) on the
variance risk premium and Diavatopoulos et al. (2012) on post-earnings
IV crush. Heuristics that lack a citation are labelled honestly.

### Strict contract

``researchOnly=true``, ``diagnosticOnly=true``, ``promotable=false``.
The auditor never approves, rejects, or sizes. It cannot touch the
authority manifest, the broker, the queue, or any TOS surface.

**Module:** `inferno_trade_conviction_audit`.

## 22. Conviction research map (giants, sleepers, winners)

`inferno_conviction_research` is the desk's "trust your gut, but make it
survive cross-examination" layer. It is research-only: it cannot approve,
reject, size, stage, or submit a trade. It ranks the whole tracker universe
into four operator-readable groups:

| Group | Meaning |
|---|---|
| Behemoths / giants | Bell-cow AI, semis, cloud, and data-center names where theme relevance is already obvious |
| Sleepers | Less obvious power, cooling, networking, server, optical, test, or data-center operators that can still participate in the boom |
| Near-term winners | Names where readiness, trigger, DTE, and multi-pillar evidence line up now |
| Contradictions | Names that look exciting but carry explicit reasons to slow down |

### Pillars

Every scored row gets these 0-100 pillars:

| Pillar | Inputs |
|---|---|
| `theme` | category override, edge-research thesis, AI/data-center supply-chain mapping |
| `timing` | readiness, priority, confidence, trigger state, days until earnings |
| `options` | setup type, IV rank sweet spot, IV-rank impulse, ATR%-Z, ATR% |
| `structure` | trend, RVOL, ATR expansion, support distance, resistance headroom, alignment |
| `quality` | edge-research quality when available; otherwise value score + PE proxy |
| `valuation` | edge-research valuation-risk score when available; otherwise long-term score + PE proxy |
| `evidence` | source quality, edge-score agreement, confidence |
| `longTerm` | theme, quality, valuation, long-term score, and buy-zone discipline |

The near-term gut score is:

```
gutCheckScore =
    0.18 · theme
  + 0.20 · timing
  + 0.17 · options
  + 0.16 · structure
  + 0.13 · quality
  + 0.09 · valuation
  + 0.07 · evidence
```

The long-term accumulation score is:

```
longTermConvictionScore =
    0.22 · theme
  + 0.22 · quality
  + 0.22 · valuation
  + 0.22 · trackerLongTerm
  + 0.12 · buyZone
```

`buyZone = clamp(100 - distanceToSupportPct / 14 · 100)`, so a name
near support gets more long-term credit than a name already stretched.

### Balance and uncertainty overlay

The v2 conviction map adds a second score that asks a harder question:
*is this conviction broad and trustworthy, or is one loud pillar doing
all the work?*

First, the module measures breadth across the seven near-term pillars:

```
pillarBalanceScore = geometric_mean(pillars) / arithmetic_mean(pillars) · 100
```

If every pillar is equally strong, the ratio is close to 100. If theme
and timing are hot but evidence, valuation, or structure are weak, the
geometric mean collapses faster than the arithmetic mean. This is the
same geometric-mean instinct used in §5: the weakest component should
matter.

Then the module computes an uncertainty haircut:

```
uncertaintyPenalty =
    fallback_data
  + missing_edge_research
  + dead_trigger
  + weak_evidence
  + weak_structure
  + risk_flag_count
  + high_PE_addon
  + stretched_entry_addon
```

The adjusted score is:

```
convictionAdjustedScore =
    0.74 · gutCheckScore
  + 0.16 · pillarBalanceScore
  + 0.10 · evidence
  - uncertaintyPenalty
```

Finally the row receives an evidence grade:

| Grade | Meaning |
|---|---|
| A | high adjusted score, broad pillar balance, low uncertainty |
| B | good adjusted score with manageable uncertainty |
| C | useful research candidate, not clean enough for blind trust |
| D | shadow/watch only until evidence improves |

This overlay is intentionally conservative. It can demote exciting names
that are stretched, fallback-sourced, unclassified, or too dependent on a
single pillar.

### Options setup logic

The options pillar intentionally treats structures differently:

- Vertical calls prefer mid/cheaper IV, positive ATR pressure, and IV
  impulse without panic pricing.
- Straddles need expansion; IV impulse and ATR pressure carry more
  weight than raw IV rank because high IV alone can be a trap.
- Iron condors prefer calm structure; ATR expansion is penalised.

This is not a signal to buy/sell. It is a classification surface that
answers: "Does the proposed option structure match the environment?"

### Risk flags

The row is slowed down when any of these fire:

- market context fallback
- high PE
- near resistance
- far from support
- options setup thin
- theme edge weak
- trigger not live

Contradictions are deliberately not hidden. A hot name with flags can
still appear in the near-term list, but it also appears in the
contradictions section so the operator sees both the bull case and the
reason to hesitate.

### References

The layer explicitly cites momentum (Jegadeesh & Titman), PEAD
(Ball/Brown and Bernard/Thomas), Kelly sizing discipline (Kelly, Thorp,
Rotando/Thorp), VRP (Bakshi/Kapadia and Carr/Wu), and the AI/data-center
regime references in `docs/THEORY_REFERENCES.md`.

**Strict contract:** `researchOnly=true`, `promotable=false`.

**Module:** `inferno_conviction_research`.

## 23. Position sizing as ruin protection

Most of the math on this desk answers the question *what is the
edge?* This section answers a different, more important question:
*what bet size makes ruin acceptably rare even if the edge is real?*

The two answers are not the same. Edge tells you whether to take a
trade. Ruin math tells you whether you survive being *wrong* about
the edge.

### Risk of ruin — the closed-form intuition

For independent bets at even money with edge `e` (so win probability
`p = 0.5 + e/2`), starting bankroll `B`, and fixed bet size `b`:

```
P(ruin) ≈ ((1 - e) / (1 + e)) ^ (B / b)
```

Two consequences worth internalising:

1. Risk of ruin shrinks **exponentially** in `B/b`. Doubling the
   bankroll-to-bet ratio doesn't halve ruin; it *squares* the small
   ruin probability. The simplest robustness move is always: smaller
   `b` relative to `B`.
2. Risk of ruin shrinks only **linearly** in edge. Doubling the edge
   reduces ruin once; doubling the bankroll-to-bet ratio reduces it
   exponentially. Sizing dominates skill in the survival math.

### Asymmetric cost of over-betting Kelly

Full-Kelly betting maximises long-run compound growth under perfect
knowledge of edge and payoff. Two well-documented facts about
deviation from optimal:

- Betting *less* than Kelly: linear loss of growth, large reduction
  in drawdown.
- Betting *more* than Kelly: growth falls off **quadratically**;
  betting twice optimal Kelly yields **zero** long-run growth even
  with a real edge; betting more than that produces *negative*
  long-run growth.

So when win probability and R are estimated (always), the cost of
under-betting is small and bounded, the cost of over-betting is
unbounded. This asymmetry is why the desk caps at quarter-Kelly,
not half — under estimation error, the quarter-Kelly user has a
~1% risk-of-ruin profile, half-Kelly ~5%, full-Kelly ~13.5% (per
the practitioner benchmarks in the Kelly literature).

References: [`KEL56`](THEORY_REFERENCES.md), [`RT92`](THEORY_REFERENCES.md),
[`MTZ10`](THEORY_REFERENCES.md).

### The four constraints we actually enforce

The desk imposes four constraints, each tied to a specific blow-up
mode documented in [`BLOWUP_CASE_STUDIES.md`](BLOWUP_CASE_STUDIES.md):

| # | Constraint | What it prevents | Case |
|---|---|---|---|
| 1 | Every position has a defined maximum loss known at trade open | Margin spiral on undefined-loss positions | Niederhoffer, Cordier |
| 2 | Per-ticket dollar risk ≤ quarter-Kelly of bankroll | Over-betting under estimation error | Kelly literature |
| 3 | Daily-total risk ≤ configured fraction of bankroll | One-day book-ending loss | Hwang, Amaranth |
| 4 | Slate concentration caps on sector / setup / underlying | Correlated blow-up that ignores diversification claim | LTCM, Hwang |

These are *guardrails*, not advisories. A trade that violates any of
them is blocked at the briefing layer regardless of conviction.

### Bankroll discipline

Two stop-loss-style operator rules layered on top of the constraints:

- **Daily-drawdown circuit breaker.** If realised loss for the day
  exceeds a configured fraction of bankroll, no new tickets that
  day. Resets at the next session.
- **Consecutive-loss size tightening.** After N consecutive losing
  tickets, per-ticket size is halved until a winning ticket lands.
  This is the desk's mechanical answer to revenge-trading.

Both are deliberately *mechanical*. The disposition-effect
literature (`[SS85]`) is clear that humans staring at red P/L cannot
be trusted to set their own size; the desk does not give them the
chance.

### Why this is in MATH and not just OPS

Because the ruin math is one of the most important *quantitative*
results on the desk and is often skipped in favour of edge math.
The point of putting it here, alongside Wilson intervals and
percentile bootstraps, is to make clear that *survival* is the
math the desk is committed to first, *growth* second.

**Module:** `inferno_blowup_guardrails`.

## 24. Score calibration and expected-move discipline

Two new diagnostics tighten the bridge between *ranked conviction* and
*realised evidence* without changing trade authority.

### Score calibration

The desk's `readiness` and `scenarioScore` fields are ranking surfaces.
They are not posterior probabilities. A score of 80 means "ranked ahead
of lower-scored alternatives under the current model", not "80% chance
of profit".

`inferno_score_calibration` tests that ranking surface with closed
scenario observations:

```
favorable_rate(bucket) = favorable_observations / closed_observations
```

The module buckets scores into:

```
0-49, 50-59, 60-69, 70-79, 80-89, 90-100
```

For each bucket it reports favorable / neutral / unfavorable rates,
mean observation score, mean underlying return, mean absolute underlying
move, and a diagnostic gap:

```
gap = favorable_rate(bucket) - score_midpoint(bucket) / 100
```

That gap is not treated as a trading edge because the score midpoint is
not a true probability. It is a pressure test: if high-score buckets do
not beat low-score buckets over enough samples, the ranking surface is
not earning trust.

The module also reports adjacent monotonicity violations when a higher
score bucket has a lower favorable rate than the previous useful bucket.
Small buckets stay visibly small and cannot promote a strategy.

### Expected move ledger

Long straddles and strangles require movement, not just a correct story.
The expected-move ledger asks whether the realised absolute move cleared
the option structure's movement hurdle:

```
realized_abs_move_pct = abs(exit_underlying - entry_underlying) / entry_underlying
```

When breakevens are available, the required move is the smaller
two-sided breakeven distance:

```
required_move_pct = min(
  abs(entry_underlying - lower_breakeven),
  abs(upper_breakeven - entry_underlying)
) / entry_underlying
```

When breakevens are missing, the module uses the entry debit as a
conservative proxy:

```
debit_implied_move_pct = entry_debit / entry_underlying
```

The closed-record edge is:

```
move_edge_pct = realized_abs_move_pct - required_move_pct
```

A long-vol record "beats expected move" only when:

```
realized_abs_move_pct >= required_move_pct
```

This still excludes spread, fees, and Greek path risk unless those are
already reflected in the closed ticket's R outcome. That is why the
ledger reports both move edge and outcome R when available.

For current long-vol candidates, the desk adds a diagnostic premium
hurdle:

```
required_move_atr_multiple = required_move_pct / atr_percent
```

The candidate is then labelled:

| Label | ATR multiple | Diagnostic rank penalty |
|---|---:|---:|
| reasonable | `<= 1.25x` | `0` |
| stretch | `> 1.25x` and `<= 2.0x` | `6` |
| hard | `> 2.0x` and `<= 3.0x` | `12` |
| extreme | `> 3.0x` | `20` |

The adjusted score is:

```
rank_pressure_score = max(0, scenario_score - rank_penalty)
```

This is ranking pressure, not execution authority. It tells the desk
when long vol is asking for too much movement relative to the recent
range and should be compared against defined-risk alternatives.

### Defined-risk alternative scoring

When a current long-vol candidate is labelled `hard` or `extreme`,
`inferno_strategy_alternative_scorer` compares defined-risk structures:

- `CALL_DEBIT_SPREAD`: bullish defined-risk debit; expected Greek
  posture is positive delta, limited negative theta, limited positive
  vega.
- `PUT_CREDIT_SPREAD`: bullish defined-risk short premium; expected
  Greek posture is mild positive delta, positive theta, negative vega.
- `IRON_CONDOR`: neutral defined-risk short premium; expected Greek
  posture is near-neutral delta, positive theta, negative vega.
- `PUT_DEBIT_SPREAD`: bearish defined-risk debit; expected Greek
  posture is negative delta, limited negative theta, limited positive
  vega.

It also scores `STAND_ASIDE` as a valid zero-risk decision.

`inferno_strategy_alternative_pricing` uses the ticket-cap policy's construction
band for optimizer sizing and then separately records the central paper-risk
verdict. This allows shadow/pricing research under the current construction
band printed by `reports/ticket_cap_policy_latest.txt`. Paper verdicts use the
simulated paper budget from `inferno_config.py`; live verdicts still inherit the
drawdown-scaled capital cap and can remain `$0` while live capital is paused.

The main contextual ratios are:

```
support_atr_multiple = distance_to_support_pct / atr_percent
resistance_atr_multiple = distance_to_resistance_pct / atr_percent
range_atr_multiple = min(support_atr_multiple, resistance_atr_multiple)
```

The scorer rewards structures whose Greek posture fits the market
context and penalises them for poor option-chain quality:

```
alternative_score = raw_context_score - chain_quality_penalty
```

Unpriced alternatives are capped at `72` so an idea without current
chain pricing cannot outrank a priced, clean ticket with false
precision. The comparison to long vol is:

```
score_edge_vs_long_vol = alternative_score - rank_pressure_score
```

A defined-risk alternative is only marked `prefer-alternative-research`
when the score is at least `70` and clears the pressured long-vol score
by at least `5` points. This is a research ranking only; it still needs
strike-cycle pricing and risk-policy approval before any paper staging.

`inferno_strategy_alternative_pricing` then prices the top research
recommendations in isolation. It can price more than one ranked
strategy variant per ticker group, so a failed top idea can be compared
against the next-best defined-risk structure without changing any queue or
ledger. It uses the same strike-selector plan builders and the same
paper risk policy, but writes only its own artifact:

```
price -> expand ranked variants -> build candidate legs -> evaluate paper risk -> report pass/block
```

For `PUT_CREDIT_SPREAD`, the pricing pass now enumerates a ladder of
short/long put pairs instead of accepting the first conservative pair.
The short-put sample deliberately includes both near-price strikes and
support-safe strikes below the current support reference, so a blocked
result can distinguish high-premium/unsafe placement from low-premium
support-safe placement.

For `IRON_CONDOR`, the pricing pass similarly enumerates short-call /
short-put pairs plus wing widths. The short-call sample includes both
near-price calls and resistance-safe calls above the current resistance
reference; the short-put sample includes both near-price and
support-safe puts. A range-safe condor requires:

```
short_put_strike < support
short_call_strike > resistance
credit/risk >= floor
max_loss <= single_ticket_cap
net_theta > 0
net_vega < 0
```

Each row gets two gates:

```
optimizer_passed = credit/risk >= floor
                 and max_loss <= single_ticket_cap
                 and short_put_strike < support
                 and net_theta > 0
                 and net_vega < 0

combined_passed = optimizer_passed and paper_risk_passed
```

Rows sort by `combined_passed`, then paper-risk pass, optimizer pass,
optimizer score, credit/risk, and smaller max loss. The retained ladder
therefore answers a cleaner question: "Was put-credit bad, or was the
first sampled spread bad?"

The pricing pass does not mutate the execution queue, approval queue,
main strike plan, or paper ledger. A `priced-risk-blocked` verdict is
useful information: it means the idea beat long vol theoretically but
failed actual chain/risk math.

When a priced alternative clears both gates, `inferno_strategy_shadow_comparison`
copies the passing structure into a separate comparison register. That
register is not the shadow evidence ledger; it is a research snapshot for
tracking the same ticker across three hypotheses:

```
passing_defined_risk_structure
  vs blocked_put_credit_structure
  vs pressured_long_vol_hurdle
```

The register preserves the condor's credit, max loss, credit/risk,
breakevens, wings, and Greeks alongside the put-credit block reasons
and long-vol ATR hurdle. Its purpose is theory cleanup: after expiration
or manual outcome review, the desk can ask whether the range-safe
condor actually improved on both the original long-vol idea and the
put-credit spread that the optimizer rejected.

The same register also adds a deterministic expiration payoff grid for
the priced alternatives. For credit structures, entry credit is treated
as positive cash flow and intrinsic value is marked from the trader's
perspective:

```
put_credit_pnl = credit * 100
               - max(0, short_put - underlying) * 100
               + max(0, long_put - underlying) * 100

iron_condor_pnl = credit * 100
                - max(0, short_put - underlying) * 100
                + max(0, long_put - underlying) * 100
                - max(0, underlying - short_call) * 100
                + max(0, underlying - long_call) * 100
```

Rows are evaluated at current underlying, support, resistance, one ATR
down/up, and the condor breakevens when present. Each row reports both
dollar P/L and R multiple:

```
r_multiple = pnl / estimated_max_loss
```

This grid is still diagnostic-only. It makes the theory falsifiable
without creating a paper ticket or shadow-evidence outcome.

**Strict contract:** both modules are `researchOnly=true`,
`diagnosticOnly=true`, and `promotable=false`. They can criticize the
score model and long-vol premium assumptions, but they cannot create
orders, relax gates, or grant live authority.

**Modules:** `inferno_score_calibration`, `inferno_expected_move_ledger`,
`inferno_strategy_alternative_scorer`, `inferno_strategy_alternative_pricing`,
`inferno_strategy_shadow_comparison`.

## 31. Schwab account sync normalization

`inferno_schwab_account_sync.py` converts Schwab approved-account position rows
into the live-sync shape used by `inferno_live_position_review.py`.

For equities:

```
qty = long_quantity - short_quantity
mark = abs(market_value) / abs(qty)
cost_basis = abs(qty) * average_price
open_pl = market_value - cost_basis        # long positions
open_pl_pct = open_pl / cost_basis * 100
weight_pct = mark_value / net_liq * 100
```

For options, the same formula uses a 100 multiplier:

```
mark = abs(market_value) / (abs(qty) * 100)
cost_basis = abs(qty) * average_price * 100
```

When Schwab supplies explicit open P/L fields, the adapter uses Schwab's value
and derives the percent from cost basis. Day P/L is preserved separately as
`dayPl` and `dayPlPercent`; it does not replace open P/L for drawdown or
position-review logic.

The adapter stores balances and positions only for the configured approved
suffix. Other suffixes may appear as suffix-level candidates for guardrail
visibility, but their balances and holdings are intentionally dropped.

## 32. TOS-style formula mirror

`inferno_tos_formula_math.py` is the local mirror for tracker/TOS-style
context formulas. It keeps the math testable and lets automation use API
history instead of screen-only TOS columns.

RVOL excludes the latest bar from its own baseline:

```
rvol = volume_t / mean(volume_(t-1) ... volume_(t-n))
```

with `n = 20` and a minimum of 6 usable volume bars.

Trend uses close, SMA20, SMA50, and SMA20 slope:

```
Bullish if price >= sma20 >= sma50 and sma20 rising
Bearish if price <= sma20 <= sma50 and sma20 falling
Uptrend if price > sma20
Basing if price is within 3% of sma20
Neutral otherwise
```

Support and resistance use the trailing 20-bar high/low range:

```
support = min(low over trailing 20 bars)
resistance = max(high over trailing 20 bars)
```

The current tracker score formulas in columns U:Y are:

```
value_score = confidence * (iv_rank / 100) * (abs(atr_z_score) + 1)
momentum_score = max(0, iv_rank_change)
squeeze_score = max(0, -atr_z_score)
ready_score = value_score if signal_trigger and setup_rec != "Avoid" else 0
priority = value_score + momentum_score + squeeze_score + ready_score
```

This means the tracker `Momentum Score` is IV-rank momentum, not price
momentum. The price-momentum mirror is a separate research signal:

```
roc_n = close_t / close_(t-n) - 1
weighted_return_pct = roc5 * 0.25 + roc20 * 0.45 + roc60 * 0.30
acceleration_pct = roc5 - (roc20 * 5 / 20)
atr_multiple = weighted_return_pct / max(atr_percent, 1)
momentum_score = clamp(1.25 + atr_multiple * 0.18 + acceleration_pct * 0.035 + trend_bonus, 0, 2.5)
```

Strength is a `0` to `100` composite:

```
relative_strength_pct = symbol_weighted_return_pct - benchmark_weighted_return_pct
relative_score = clamp(50 + relative_strength_pct * 2, 0, 100)
strength = momentum_score_100 * 0.35
         + relative_score * 0.25
         + trend_score * 0.20
         + participation_score * 0.20
```

`inferno_tos_formula_audit.py` compares the latest snapshot against the
mirror and writes `reports/tos_formula_audit_latest.txt`. It is read-only:
no broker calls, no sheet writes, no queue mutation, and no staging.

`inferno_tos_custom_metrics.py` is the separate lane for user-authored
ThinkScript custom columns. It imports TOS-exported values by ticker or accepts
Schwab price-history recomputations for formulas that use only OHLCV. In both
cases, it stores values under `tosCustomMetrics`:

```
row.tosCustomMetrics[metric_key].raw
row.tosCustomMetrics[metric_key].value
row.tosCustomMetrics[metric_key].formulaStatus
row.marketContext.tosCustomMetricSourceStatus
row.marketContext.tosCustomSignalSummary
```

The currently recognized TOS headers from the watchlist screenshot are:
`RVOL`, `Pv52H`, `MOM`, `ATR%`, `Str...`, and `SUP/RES *`.

`tosCustomSignalSummary` is observed-only. It exposes bands such as
`rvolBand`, `momentumSign`, and `strengthBand` for research visibility, but
does not change readiness, sizing, or risk gates by itself.

The exact Python mirrors for the screenshot formulas live under
`marketContext.tosCustomFormulaMirror`:

```
tos_rvol = volume / Average(volume, 30)
tos_pv52h = close / Highest(high, 252) * 100
tos_momentum = close - Average(close, 10)
tos_atr_percent = Average(TrueRange(high, close, low), 14) / close * 100
tos_strength = (close - low) / (high - low) * 100
tos_support_resistance_state =
    "Near High" if close is within 2% of Highest(high, 10)
    "Near Low" if close is within 2% of Lowest(low, 10)
    "Neutral" otherwise
```

These mirrors are exact formula translations from the user screenshots and
the local TOS custom quote cache. They remain separate from legacy
market-context fields until outcome calibration says they should affect gates.

`inferno_schwab_tos_metrics_sync.py` now runs the same six mirrors on Schwab
daily candles and publishes the canonical custom-metrics artifact. That is the
preferred automation path for these metrics because it avoids a fragile TOS UI
or CSV dependency while still matching the user's ThinkScript formulas.

`inferno_tos_metric_theory_audit.py` is the anti-confirmation layer. It does
not change gates. It checks each visible metric against a more decision-useful
companion:

- RVOL gets a prior-30 denominator and 63-day volume percentile.
- Pv52H gets drawdown-from-high context.
- MOM gets percent and ATR-normalized momentum because raw dollars are not
  cross-ticker comparable.
- ATR% is classified as risk/sizing context, not directional evidence.
- Strength gets a 5-day close-location check.
- SUP/RES gets treated as tactical 10-day context only.

The audit writes explicit `supports`, `challenges`, `context`, and
`antiYesManCaveats` lists by ticker so formula evidence can clarify a thesis
instead of flattering it.

If `formulaStatus != captured` or `hasThinkScript = false`, the metric is
available as observed TOS evidence but is not yet a fully reproduced local
formula.

See [TOS_FORMULA_MIRROR.md](TOS_FORMULA_MIRROR.md) for the full crosswalk and
the placeholder table where exact ThinkScript formulas should be pasted.
See [TOS_CUSTOM_METRICS.md](TOS_CUSTOM_METRICS.md) for the exact-value import
and registry workflow.

## Where to add a new metric

When the desk adds a new probability or statistical primitive:

1. Add the math to a module — never inline it across multiple modules.
2. Document the formula and edge cases here.
3. Add at least three adversarial tests: empty input, single-sample
   degenerate case, clear positive/negative signal.
4. Add an invariant check in `inferno_math_verify` so the new metric
   can never silently drift.
5. If the metric gates promotion, add its threshold to the table in §10.
