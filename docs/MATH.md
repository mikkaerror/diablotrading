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
    readyScore   >= 72,
    confidence   >= 2,
    daysToEarnings <= 21,
    setupRec     not in {"Avoid"},
    bool(signalTrigger),
])
```

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

The slate normalizer solves a practical scale bug: if an upstream tracker
producer emits `Ready Score` on a 0-10 scale while the historical gate
expects 0-100, absolute thresholds can fail every name forever. The
normalizer adds a research-only, cross-sectional layer that asks:
"which names are strongest *relative to today's slate*?"

For a vector of non-null values `x_1, ..., x_n`, percentile rank is:

```
rank(x_i) = 100 * (count_below + 0.5 * count_equal) / n
```

This averaged-rank convention is stable under ties and invariant to
linear scaling. A score of `2.1` on a 0-10 axis and `21` on a 0-100 axis
rank identically if the cross-sectional ordering is unchanged.

Ranked fields:

| Field | Rank output |
|---|---|
| `readyScore` | `readyRank` |
| `valueScore` | `valueRank` |
| `momentumScore` | `momentumRank` |
| `squeezeScore` | `squeezeRank` |
| `ivRank` | `ivPercentileRank` |

`compositeRank` is the geometric mean of available component ranks, so
one weak pillar drags the whole candidate down. This mirrors the
evidence-strength philosophy: the weakest part of the thesis matters.

Strict contract: `researchOnly=true`, `diagnosticOnly=true`,
`promotable=false`. The normalizer is review context only. It does not
override the five live gates, touch authority, or make a trade eligible.

**Module:** `inferno_slate_normalizer`.

## 19. Cross-sectional percentile rank (the absolute-threshold fix)

The conviction gate `readyScore ≥ 72` is brittle: if the upstream score
formula changes scale (or breaks), the gate either lets everything in or
nothing. The empirical finding on the live 143-name slate was that
*every* name produced a Ready Score under 10 — the gate had been
pinned to a 100-scale while the formula produced 0–10.

Percentile rank is **scale-invariant**. For a column ``x_1, ..., x_n``,
the rank of value ``x_i`` is:

```
rank(x_i) = 100 · (count_below + 0.5 · count_equal) / n
```

This is the *averaged* percentile-rank convention — robust to ties,
well-defined on any scale. Multiplying every value by 10× leaves ranks
unchanged. Adding a constant leaves ranks unchanged. The gate becomes
"top N percent of slate" instead of "above threshold X."

Composite rank across multiple score columns uses the geometric mean
(same asymmetry as `inferno_evidence_strength` — the weakest component
caps the composite):

```
composite_rank = exp( (1/k) · Σ ln(rank_i) )      over k active components
```

The default gate is `top 20%` (readyRank ≥ 80). Picky operator modes:

| Gate | Meaning |
|------|---------|
| ≥ 80 | top 20% (default) |
| ≥ 90 | top 10% (Ackman-strict) |
| ≥ 95 | top 5% (Buffett-strict) |
| ≥ 99 | top 1% (Simons-strict, bell-cow only) |

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

## Where to add a new metric

When the desk adds a new probability or statistical primitive:

1. Add the math to a module — never inline it across multiple modules.
2. Document the formula and edge cases here.
3. Add at least three adversarial tests: empty input, single-sample
   degenerate case, clear positive/negative signal.
4. Add an invariant check in `inferno_math_verify` so the new metric
   can never silently drift.
5. If the metric gates promotion, add its threshold to the table in §10.
