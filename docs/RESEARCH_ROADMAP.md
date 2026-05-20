# Research Roadmap

Three-phase plan for evolving the desk from "rigorous pre-trade research" to a
full hedge-fund-grade learning system. Each phase is one long session.

This doc is the contract any session (Claude, Codex, future me) picks up. If
the phase status here disagrees with `coordination/active_missions.json`, the
mission file wins for ownership but this doc still defines what the deliverable
looks like.

Last updated: 2026-05-20.

## Why these three phases, in this order

The desk has built a credible pre-trade research stack. The bottleneck now is
not "is this idea good" — the auditor handles that. The bottleneck is:

1. **What did we actually learn from each closed outcome?** Without post-trade
   attribution, the desk produces opinions but never learns from results.
2. **Are our "diverse" strategies actually diverse?** Without a correlation
   matrix across families, we can have fifteen trades that are one bet.
3. **Are we taking the trade everyone else is in?** Without a crowdedness
   signal, we are exposed to reflexivity reversals we cannot see.

Build them in this order because:

- **A unlocks B.** Portfolio construction needs per-strategy expected return
  and risk numbers — those come out of the attribution pass.
- **B unlocks C.** Crowdedness has compounding effects only when you can
  measure correlation. A single crowded trade is fine; a portfolio of crowded
  trades is fragile.
- **C is the highest intellectual leverage and the lowest operational
  leverage** at the desk's current size. Earned last.

## Authority constraints (do not change)

Every phase below ships as research-only, diagnostic-only, promotable=False.
Broker submit stays OFF. Live authority does not expand. Promotion math
continues to wait for the 30-closed-scored-outcomes paper-evidence gate.

These constraints are not negotiable inside any phase.

## Phase A — Post-trade learning layer

Status: **in progress.**

### What this is

Close the loop. When a paper outcome closes, the desk should be able to
decompose the PnL, score which auditor bullets predicted the result, and
update an honest picture of per-rule edge over time. Without this layer,
closed paper outcomes are wasted signal.

### Research scope

Three literature pulls:

1. **Performance attribution.** Brinson decomposition (allocation effect vs
   selection effect, Brinson-Hood-Beebower 1986); risk-adjusted ratios
   (Sharpe 1966, Sortino 1980, Calmar / pain ratio, Ulcer Index — Martin
   1989); William Eckhardt's counter-intuition principle ("markets do not pay
   for what is hard"); per-trade decomposition frameworks.
2. **Edge half-life.** Renaissance-style discipline that every edge decays
   (Simons via Zuckerman); Grinold-Kahn alpha decay framework; Israel-Moskowitz
   on factor decay; Bayesian online change-point detection (Adams-MacKay 2007)
   as a step beyond CUSUM.
3. **Slippage and execution gap.** Almgren-Chriss optimal execution; effective
   vs quoted spread; market impact (Kyle 1985, Hasbrouck); paper-to-live
   adverse selection literature.

### Documentation deliverables

- `docs/PERFORMANCE_ATTRIBUTION.md` — long-form research note synthesizing
  attribution + edge half-life + slippage with primary citations.
- `docs/MATH.md` §24 — Attribution math + decay math (Wilson-style CIs for
  per-rule hit rates, half-life estimator, slippage adjustment formula).
- `docs/THEORY_REFERENCES.md` — new citation tags (Brinson-BHB86, Sharpe66,
  Sortino80, Martin89-Ulcer, Eckhardt-MW93, GrinoldKahn00, IsraelMoskowitz13,
  AdamsMacKay07-BOCP, AlmgrenChriss00, Kyle85, Hasbrouck91).

### Code deliverables

Three new modules, all research-only:

- `inferno_outcome_attribution.py` — for each closed paper outcome, decompose
  PnL into structure / underlying / timing / size / regime effects. Records
  which auditor bullets fired and whether they correctly predicted the
  outcome. Artifact: `reports/outcome_attribution_latest.txt`.
- `inferno_rule_edge_decay.py` — extends regime drift from per-strategy to
  per-bullet. For each auditor bullet, tracks hit rate over closed outcomes
  with a rolling half-life estimator. Surfaces decayed bullets to the auditor
  as candidates for retirement. Artifact: `reports/rule_edge_decay_latest.txt`.
- `inferno_slippage_estimator.py` — research-only paper-to-live gap estimator.
  Uses bid-ask spread (Schwab quote when available, vendor estimate
  otherwise) plus market impact heuristic per strategy family. Produces an
  adjusted expected PnL for the promotion math to consume. Artifact:
  `reports/slippage_estimator_latest.txt`.

### Wiring

- Add all three artifacts to the doctor's freshness check.
- Add to `inferno_model_command_center.py` REPORTING_MAP + recommendedReads.
- Add to `inferno_daily_loop.py` after the trade conviction audit step.
- Extend `inferno_math_verify.py` to cover the new artifacts.
- Update PROJECT_STATUS "Current state" table.

### Success criteria

- All three modules ship with tests freezing their contracts.
- Math verify reports zero violations including the new artifacts.
- The conviction auditor reads from rule edge decay and surfaces a
  retirement-candidate note if any bullet's hit rate drops below its
  half-life floor.
- Full coordination note dropped; commit shipped.

## Phase B — Portfolio-level layer

Status: **pending.**

### What this is

Move from per-ticket discipline to portfolio-level discipline. The desk
already enforces concentration caps per ticket; it does not measure how
correlated our strategy families are, what our drawdown protocol is, or what
the capacity limit per strategy is.

### Research scope

1. **Correlation structure.** Dalio's Holy Grail (Bridgewater Principles 2017):
   15 uncorrelated streams. Markowitz 1952 (modern portfolio theory). Roll
   1992 / equal risk contribution (Maillard et al 2010). Black-Litterman
   1992 framework.
2. **Drawdown protocol.** Calmar ratio; pain index; drawdown duration; PTJ /
   Druckenmiller / Steenbarger on drawdown psychology. Explicit drawdown
   protocols from operating manuals.
3. **Strategy capacity.** Sadka 2010; Korajczyk-Sadka 2004; capacity-adjusted
   alpha. When does a strategy stop working at size?

### Documentation deliverables

- `docs/PORTFOLIO_CONSTRUCTION.md` — Holy Grail synthesis, correlation math,
  why diversification by count is a lie without correlation control.
- `docs/DRAWDOWN_PROTOCOL.md` — explicit thresholds and behaviour at each
  drawdown level; drawdown-state-aware sizing.
- `docs/MATH.md` §25 — Correlation math, equal risk contribution.
- `docs/MATH.md` §26 — Drawdown math (max DD, duration, Calmar, ulcer).

### Code deliverables

- `inferno_strategy_correlation.py` — pairwise correlation matrix across
  strategy families using closed paper outcomes, with bootstrap CIs.
  Artifact: `reports/strategy_correlation_latest.txt`.
- `inferno_drawdown_protocol.py` — drawdown-state-aware behaviour modifier.
  Reads daily PnL from outcome attribution, computes current drawdown state,
  emits diagnostic recommendations (e.g. "below -5% — reduce size 50%",
  "below -10% — halt new tickets, audit existing"). Diagnostic-only; the
  operator decides whether to act.
- `inferno_capacity_estimator.py` (optional, depending on data volume).

### Wiring

- Drawdown protocol's verdict surfaces in the conviction auditor as a
  global modifier (e.g. SIT-OUT-style block at -10%).
- Correlation artifact threads into the conviction research map.
- Standard doctor + command center wiring.

### Success criteria

- Drawdown protocol fires correctly in synthetic drawdown tests.
- Correlation matrix produces stable results across the bootstrap.
- Math verify stays clean.
- The desk now refuses to "diversify by count" — every sizing decision
  considers correlation as well.

## Phase C — Consensus / crowdedness layer

Status: **pending.**

### What this is

Add the Soros / reflexivity overlay: are we taking a trade that is already
in everyone else's book? This is the highest intellectual leverage but the
lowest operational leverage today because we already filter conservatively.

### Research scope

1. **Reflexivity.** Soros 1987 (Alchemy of Finance) — expand the existing
   citation into a quantitative trigger.
2. **Positioning signals.** CFTC Commitments of Traders; short interest +
   days-to-cover; options open interest + put-call skew; institutional
   flow (13F change deltas); analyst dispersion.
3. **Crowded-trade research.** Stein 2009 on overcrowded long-short; recent
   academic work on factor crowding and reversal risk.
4. **Renaissance-style alt-data philosophy.** Find what nobody else sees
   (Zuckerman, Simons). Frame the desk's signal mix accordingly.

### Documentation deliverables

- `docs/CONSENSUS_RISK.md` — what makes a trade "crowded", how to measure
  it, when to fade.
- `docs/THEORY_REFERENCES.md` — new tags (CoT positioning, Stein09-crowded,
  Soros-reflexivity expansion).

### Code deliverables

- `inferno_crowdedness.py` — multi-signal consensus score. Inputs: short
  interest, options open interest (Schwab when available), put-call skew,
  institutional flow direction. Output: 0–1 crowdedness score with explicit
  driver list. Artifact: `reports/crowdedness_latest.txt`.
- Wire into the conviction auditor as a new bear bullet
  ("crowded-trade reflexivity risk") when the score crosses a configured
  threshold.

### Success criteria

- Crowdedness signal surfaces consistently for tickets with extreme
  positioning.
- Conviction auditor's new bear bullet fires only when threshold crossed.
- Soros reflexivity citation now appears with operational meaning, not
  just narrative.
- Math verify stays clean.

## How to run a phase

The shape is the same every time:

1. Read this doc, the SYSTEM_MAP, and PROJECT_STATUS.
2. Open a task list for this phase's tasks.
3. Research pass — WebSearch for primary sources, capture citations into
   THEORY_REFERENCES with full tags.
4. Write the long-form research note for that phase (PERFORMANCE_ATTRIBUTION,
   PORTFOLIO_CONSTRUCTION + DRAWDOWN_PROTOCOL, or CONSENSUS_RISK).
5. Pick the code seeds from the deliverables list; do not over-build.
6. Implement with tests freezing the contracts.
7. Wire into daily loop / command center / doctor.
8. Verify: math verify, conviction-audit tests, full test suite.
9. Update PROJECT_STATUS Current state row.
10. Drop coordination note. Commit.

## What to NOT do inside any phase

- Do not enable live submit.
- Do not change capital deployment authority.
- Do not let new modules write to live broker surfaces.
- Do not loosen the paper-evidence promotion gate.
- Do not delete existing rules — retire by adding a "retired" tag on the
  rule and let the edge-decay layer document why.
- Do not introduce dependencies on unverified vendor APIs without a
  fail-closed fallback.

## Anti-goals

These look attractive but are out of scope:

- **A live execution gateway.** The desk is intentionally paper-only.
- **A backtester for arbitrary historical periods.** The scenario backtest
  already serves this need and expanding it ahead of the learning layer is
  premature.
- **An ML model that predicts winners.** Without attribution honesty, an ML
  layer will overfit and we will not see it.

## Cross-phase shared work

These touch all three phases — do them once when they become natural:

- Extend `docs/MATH.md` chronologically — append, do not reorganise.
- Keep `docs/THEORY_REFERENCES.md` as the single source of truth for citation
  tags; every doc cites by tag.
- Keep `coordination/model_notes.jsonl` honest: one note per shipped piece.

## Where this lands in the system

After all three phases, the desk has:

- Layer 1 (idea generation): already shipped.
- Layer 2 (pre-trade discipline): already shipped + master traders.
- Layer 3 (execution): intentionally not shipped.
- Layer 4 (learning): A delivers attribution + decay + slippage; B delivers
  correlation + drawdown; C delivers consensus risk.

That is a complete hedge-fund-grade research desk minus the live execution
surface, with the execution surface intentionally held off.
