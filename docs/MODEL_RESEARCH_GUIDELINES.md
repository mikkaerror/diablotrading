# Model Research Guidelines

Revised September 10, 2026 at the operator's request. These are research and
review instructions. Existing runtime scoring, thresholds, risk constants,
eligible universe, and authority remain unchanged.

## Purpose

Investigate substantial upside in the AI infrastructure cycle and test whether
the desk improves decisions after costs. Illustrative contribution forecasts
are not the strategy's return target. Industry knowledge should supply specific
hypotheses about demand, capacity, pricing and suppliers, supported by public
sources. Neither conviction nor willingness to lose capital establishes edge.

An existing guideline is a hypothesis about useful behavior. Correct it when
its units, inputs, assumptions or purpose are wrong. Compare alternatives when
its predictive value is uncertain. Do not preserve a discovery rule merely
because it is conservative, familiar, or already implemented.

## Keep four questions separate

| Question | Research measurements | Required distinction |
|---|---|---|
| Which businesses benefit over quarters? | Funded demand, backlog conversion, capacity delivery, pricing power, revenue acceleration, margins, cash generation, financing and dilution | Industry membership is context; revenue is not profit or cash |
| Which stocks offer opportunity over weeks or months? | Timestamped earnings expectations and revisions, valuation scenarios, relative strength versus relevant peers, market breadth | A growing business can already be fully priced |
| Which trade expresses the thesis? | Explicit catalyst and holding period; shares, calls and spreads where permitted; premium, liquidity, expiration, payoff bounds and exit mechanics | Stock direction, event movement and net option profit are different targets |
| Did the method improve outcomes? | Net return, net R for options with verified risk basis, benchmark-relative stock return, downside, concentration and missed opportunities | Research, paper and live results remain separate |

Every experiment declares its own holding period before evaluation. A 21-day
earnings window can define the earnings lane; it must not silently exclude a
multi-quarter thesis from research. Comparisons use the existing eligible
universe. A new research lane does not make a name or instrument trade-eligible.

## Measurement rules

1. Distinguish source freshness from observation freshness and preserve the
   prediction-time snapshot. A regenerated report cannot make old facts current.
2. Identify units, denominator, lookback, session completeness and option tenor.
   Do not describe partial-day volume versus full-day averages as verified weak
   participation. Use completed-session comparisons or a separately validated
   same-time-of-day baseline; do not invent an intraday adjustment.
3. Preserve missingness and valid zero values. A fallback or clipped value must
   be visible. Unknown quality is not demonstrated poor quality.
4. Document which inputs each score reuses. Agreement between scores sharing
   readiness, trend or confidence is not independent corroboration.
5. Treat fixed weights, category bonuses, growth caps and technical thresholds
   as unvalidated until later outcomes support them. Preserve raw features when
   evaluating an alternative transformation; extreme growth also needs source
   checks and a robustness comparison, not automatically unlimited score credit.
6. Arithmetic tests verify calculations. They do not establish predictive
   accuracy. Empty regression or walk-forward reports are missing evidence.
7. Match live option legs by underlying, expiration, strikes, direction and
   quantity before interpreting a spread. A per-leg warning is not by itself a
   verified spread-level risk assessment. Preserve the warning while reconciling
   the complete position; do not bypass the existing gate.

## Evaluate guidelines before replacing runtime rules

For each proposed change, record the existing rule and its source, intended
purpose, observed failure, affected population, proposed alternative and
falsifier. Distinguish a calculation defect from an unproven modeling choice.

Freeze the current baseline, challenger definition, target, costs, universe,
holding period, evaluation window and practical success criterion before
viewing evaluation results. Keep evaluator code outside unattended modification.
Use chronological evaluation with all observations and variants of the same
event grouped together; training outcomes must have been knowable at entry.

Retain selected and rejected observations. Report coverage, missingness,
independent event counts, uncertainty, net payoff and downside. Define a
"missed winner" before observing its return, and report the losses admitted by
the looser rule alongside any recovered winners. Do not optimize recall alone.
If costs or benchmark history are absent, state which comparison is unavailable.

Compare against simple baselines: the current method, a fixed sector-momentum
rule, and a fundamental/valuation challenger. Compare strategy choices on the
same opportunities and capital assumptions. Benchmarks are evaluation sources,
not additions to the eligible trading universe. A single profitable trade, more
rows, or reaching 30 events alone does not validate a model.

## Initial review queue

These are proposed experiments, not implemented changes or new thresholds.

| Priority | Existing behavior to investigate | Bounded next step | Evidence needed for adoption |
|---|---|---|---|
| 1 | Daily RVOL used as intraday confirmation | Trace each consuming field and bar timestamp; distinguish completed and partial sessions | Reproduced misclassification and verified session-aware input semantics |
| 2 | Missing values and valid zeros share fallbacks | Audit feature transformations with explicit null/zero examples | Correct units and missingness propagation without replacing facts with assumptions |
| 3 | Core quality clips revenue growth at 50%; theme credit is category-based | Preserve raw growth and compare a robust continuous transform with the frozen baseline | Later improvement after controlling for sector and concentration; no tuning on holdout |
| 4 | Earnings timing dominates discovery; multiple scores reuse inputs | Evaluate a separate longer-horizon research rank and remove redundant features in isolated comparisons | Incremental net value and downside evidence versus simple baselines |
| 5 | Priced variants can remain absent from the operator queue | Trace source, economics, route requirements and explicit block reasons end to end | Correct reporting and an operator-owned path that preserves every applicable gate |

## Authority and completion

Correcting documentation and running isolated research comparisons do not need
a paper-promotion sample. Runtime discovery changes still require a concrete
review of their effect on downstream eligibility. Risk constants and eligible
universe remain operator-owned. No agent may approve, reject, close or promote
an operator paper ticket or enable live trading/broker submission.

Independent operator live trades are broker facts, not automatic validation of
the model, paper sample credit or permission for the agent to place orders.
Guideline adoption, software implementation, empirical validation and trading
authority are separate statuses and must be reported separately.

Record accepted research progress as a reproducible finding or completed
predeclared comparison. Record software progress as a verified repair. Record
paper progress only from qualified outcomes. Do not keep rerunning an unchanged
comparison; resume when new evidence or a corrected input can change the result.

## Evidence behind this revision

- [Score implementation](../inferno_edge_research.py): fixed component weights,
  category thesis score and revenue-growth clipping.
- [Conviction implementation](../inferno_conviction_research.py): shared score
  inputs and null/zero fallback behavior requiring review.
- [Volume formulas](../inferno_tos_formula_math.py): daily volume comparisons
  without time-of-day normalization.
- [Calibration review](MODEL_CALIBRATION_REVIEW_2026-09-06.md) and current
  `reports/score_calibration_latest.txt`: historical provenance limitations.
- [[../knowledge/agent-loop/Historical Model Comparison and Event Date Quality]]:
  fixed retrospective comparison, uncertain gain and an event-date conflict.
- [[../knowledge/agent-loop/Model Guidelines Must Earn Their Place]]: revision
  outcome, remaining work and falsifiers.
