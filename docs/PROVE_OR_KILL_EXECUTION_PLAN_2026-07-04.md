# Inferno Prove-or-Kill Execution Plan

- Date: 2026-07-04
- Stage: research-only planning
- Authority: `liveTradingAllowed=false`, `brokerSubmitAllowed=false`
- Scope: cleanup, instrumentation, and evidence design for the 7-14 DTE pre-earnings long-vol hypothesis

## Current read

The desk should stop treating "more paper trades" as the goal. The goal is now
to collect clean evidence on the one narrow shadow edge that survived the DTE
audit:

- `Long Straddle`, 7-14 DTE before earnings, liquid large-caps.
- Current shadow cohort: n=39, win 58.97%, mean net-R +0.8714.
- Caveats: all risk-failed, friction not realized, no cross-cycle proof, and the
  full straddle is often too expensive for the current account size.

The broader long-vol lane is not healthy enough to trust blindly:

- Closed long-vol observations: 100.
- Move beat rate: 34.0%.
- Mean realized-minus-implied move edge: -10.62%.
- Excluding the two biggest contributors, mean R falls to -0.3605.

Conclusion: prove or kill the narrow 7-14 DTE setup with real friction. Do not
generalize the finding to all earnings options or all long-vol structures.

## External research guardrails

These outside references support the way the desk should test, not a live-trade
decision:

- Options Industry Council long-straddle guidance: the structure needs a sharp
  move or implied-volatility increase, has limited max loss equal to premiums
  paid, and suffers materially from time decay.
- FINRA concentration-risk guidance: different tickers can still be one
  correlated exposure when they sit in the same sector, market segment, or
  security type.
- FINRA risk-tolerance guidance: willingness to take risk and ability to absorb
  loss are different constraints.
- Barber and Odean, "Trading Is Hazardous to Your Wealth": higher retail trading
  activity carried a large net performance penalty after costs in the studied
  sample.
- MacLean, Thorp, and Ziemba on Kelly: full Kelly can imply very large wagers and
  can be risky over finite paths; fractional sizing is the relevant future
  research lane only after a credible edge sample exists.
- Cboe benchmark indices: compare each strategy family to an appropriate
  strategy benchmark, not to long stock by default.

## Cleanup decisions

1. Keep generated/private state out of Git. Do not commit `data/`, `reports/`,
   broker exports, credentials, logs, or local screenshots.
2. Keep the current dirty worktree split into coherent bundles:
   - control surface and dashboard,
   - capital and cash attribution,
   - paper/live drawdown decouple,
   - priority-slate Schwab chain coverage,
   - prove-or-kill campaign docs.
3. Do not stage all files together. The priority-slate chain-pull patch is a
   coherent small commit candidate by itself.
4. Leave the stray capital-scaling ack as a data-state issue, not a code commit.
   If it is still present, clear it with the explicit revoke command rather than
   manually editing generated state.

## Implementation sequence

### P0 - Campaign instrumentation

Add a hypothesis register entry type for the 7-14 DTE campaign. Every staged or
shadow row should preserve:

- strategy family and structure variant,
- entry DTE and earnings date,
- whether friction is realized or modeled,
- entry bid/ask/mid for both legs,
- exit bid/ask/mid for both legs,
- net debit, total spread cost, net R, and payoff hurdle,
- entry score fields: readiness, scenario score, priority, RVOL, momentum,
  ATR%, strength, and support/resistance status,
- exit variant: hold-to-expiration versus day-after-earnings exit,
- regime key: earnings cycle / calendar window.

Done when the desk can answer: "Was this exact trade rule good after real
spreads, or only good in shadow marks?"

### P0 - Real-friction fill model

For paper outcomes, model entry and exit with executable-looking bid/ask marks.
Mid-only marks are allowed only as a separate diagnostic field, never as the
promotion score.

Minimum acceptance fields:

- entry cost at ask for long legs,
- exit value at bid for long legs,
- spread cost in dollars and R,
- liquidity score and ATM spread status at entry,
- `frictionRealized=true` only when executable bid/ask marks exist.

### P0 - Exit-variant A/B test

Track both exits for each admitted candidate:

- hold through expiration, matching the shadow cohort assumption;
- close the session after earnings, to test whether the IV-ramp capture works
  before post-event drift and theta dominate.

The variants share the same entry but score independently.

### P1 - Affordable proxy lane

Because full large-cap straddles can exceed account constraints, add a proxy
cohort that attempts to preserve the same mechanism with smaller defined risk.
Acceptable proxy candidates should be compared, not promoted:

- narrower long strangle,
- call/put debit-spread pair,
- lower-priced liquid large-cap straddle,
- other defined-risk structure only if it keeps the same event-vol thesis.

Reject any proxy that changes the thesis into a directional bet without labeling
it separately.

### P1 - Bad-cohort suppression

Do not keep generating 22-35 DTE long straddles or generic vertical debits as
priority candidates unless a future matched cohort overturns the current
evidence. They can remain in shadow/backtest reports, but they should not consume
scarce campaign paper slots.

### P1 - Score preservation

Closed option outcomes currently lack enough score fields to calibrate whether
the desk's scores predict option R. Preserve scores at entry before future
outcomes close. Until then, use scores only for ranking and discovery, not for
sizing or authority.

### P2 - Sizing research only

No Kelly sizing, no live pilot, and no authority escalation until the campaign
has at least 30 scored real-friction outcomes across multiple earnings cycles.
Even after a positive Gate C, the first live sizing model should be minimum-size,
fixed-fraction, and capped by portfolio heat.

## Decision gates

- Gate A: The loop actually stages or shadows 7-14 DTE liquid-name candidates
  with the required fields.
- Gate B: Around 15 real-friction outcomes, stop early if net-R is clearly
  negative or the payoff-adjusted win rate collapses.
- Gate C: At 30+ outcomes across 2-3 earnings cycles, require positive
  lower-bound expectancy, profit factor >= 1.25, controlled drawdown, and
  consistency across cycles before even discussing a tiny live pilot.

If Gate C fails, kill the strategy. The cleanup win is knowing that quickly.

## Source links

- OIC long straddle: https://www.optionseducation.org/strategies/all-strategies/long-straddle
- FINRA concentration risk: https://www.finra.org/investors/insights/concentration-risk
- FINRA risk tolerance: https://www.finra.org/investors/insights/know-your-risk-tolerance
- Barber/Odean active trading paper: https://faculty.haas.berkeley.edu/odean/papers%20current%20versions/individual_investor_performance_final.pdf
- Kelly criterion paper: https://www.stat.berkeley.edu/~aldous/157/Papers/Good_Bad_Kelly.pdf
- Cboe strategy benchmark indices: https://www.cboe.com/us/indices/benchmark_indices/
