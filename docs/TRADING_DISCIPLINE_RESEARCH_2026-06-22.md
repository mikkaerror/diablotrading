# Trading Discipline Research - 2026-06-22

**Stage:** research-only
**Promotable:** false
**Authority change:** none
**Live trading allowed:** false

This memo converts primary-source research into operating rules and testable
hypotheses for the Diablo/Inferno desk. It covers strategy choice, sizing,
positioning, exits, turnover, and emotional discipline.

The central conclusion is less exciting than a magic setup and more useful:
the desk should optimize decision quality and evidence production before it
optimizes trade count. Faster trading without measured net expectancy is an
activity target, not an edge.

## Current desk evidence

The local artifacts matter more than generic internet strategy claims:

- Schwab account truth is stale pending OAuth renewal.
- Current account snapshot: about $1,599 NLV, $600 cash, 62.5% shares.
- Evidence-adjusted target: 50% shares, 0% live options, 50% cash.
- Strategy promotion evidence: 1 scored outcome of 30 required.
- Long-vol expected-move ledger: 96 closed observations, 31.25% move-hurdle
  beat rate, and -11.45 percentage points mean realized-minus-implied move.
- Live options max loss remains $0.

Those facts imply a narrow operating posture: refresh broker truth, close and
score paper evidence, reduce long-vol concentration, and keep live authority
locked.

## 1. Strategy selection

### Use a structure only when its edge source is explicit

Every candidate should name the source of expected return:

1. **Direction:** the underlying should move up or down farther or sooner than
   the market implies.
2. **Volatility:** realized movement or implied-volatility change should beat
   the premium hurdle.
3. **Carry:** time decay or another risk premium is expected to compensate for
   tail and assignment risk.
4. **Relative value:** one structure is mispriced versus another after
   liquidity and financing.
5. **Portfolio function:** the trade reduces a measured portfolio risk.

If none applies, cash is the correct structure.

### Structure map

| Evidence state | Structure worth testing | Main failure mode |
|---|---|---|
| Long-term bullish, timing weak, contract too large | Shares or no trade | Concentration and drawdown |
| Directional edge, defined horizon, moderate premium | Debit spread | Wrong direction, decay, capped upside |
| Realized move forecast exceeds premium hurdle | Long straddle/strangle | Theta and IV compression |
| Premium rich versus forecast movement, defined range | Defined-risk credit spread/condor | Gap and short-gamma loss |
| Desired share acquisition and enough cash for 100 shares | Cash-secured put, shadow first | Large downside and capital lock |
| No measurable edge or bad liquidity | Cash | Opportunity cost |

### Long-vol conclusion

The Options Industry Council notes that long options can lose even when the
underlying moves in the expected direction if implied volatility falls enough.
Its long-straddle material also identifies time decay as a strongly negative
exposure.

The desk's own 96-observation expected-move ledger is the stronger reason to
restrict long vol. Long vol should not be retired categorically, but it should
be admitted only when a written forecast explains why realized movement or IV
expansion can exceed:

- the implied move,
- theta through the planned holding period,
- bid/ask and modeled slippage,
- and the alternative defined-risk structures.

The next five-slot paper cohort should retain the existing cap of at most two
long-vol positions.

### Premium-selling conclusion

Research on variance risk premia supports the existence of compensation for
bearing volatility risk at broad-market level. It does not prove that every
single-name credit spread, earnings condor, or wheel trade has positive
expectancy.

Premium-selling candidates therefore need:

- defined maximum loss,
- sufficient spread liquidity,
- an explicit gap/event scenario,
- net Greek exposure across all legs,
- and comparison with shares or a debit spread.

## 2. Sizing and positioning

### Binding rules now

- Live options max loss stays at $0 until promotion evidence clears.
- Paper reference sizing stays at $25 per ticket and $75 per day.
- Use total NLV, not available cash alone, as the allocation denominator.
- Measure incremental portfolio heat by theme and correlation, not ticker
  count.
- Do not add to the existing AI/compute/miner theme while its equity sleeve is
  above the evidence-adjusted target.

### Kelly sizing

Kelly sizing maximizes long-run log growth only when the estimated
probabilities and payoffs are credible. Its suggested wagers can be aggressive,
and estimation error can make full-Kelly sizing dangerous.

The desk should not activate Kelly from one scored outcome. After a credible
strategy-family sample exists, fractional Kelly can be tested as a ceiling
inside stricter portfolio and contract-size caps.

### Drawdown response

A two-loss streak is not proof that the edge disappeared. Avoid building a
streak-based rule that mechanically chases recent outcomes.

The better control is:

- predefine account and strategy-family drawdown limits,
- reduce size when a limit is breached,
- stop immediately after an unplanned trade, ignored exit, or sizing breach,
- resume only after a written review and a fresh risk calculation.

This separates process failure from ordinary variance.

## 3. Taking profits and losses

OIC states there is no universal percentage at which a winning options trade
should be closed. It supports defining both profit and maximum-loss exits
before entry.

That means the desk's current ladders are hypotheses to test, not market laws.

### Required decision-card fields

- strategy and edge source,
- entry trigger,
- maximum loss in dollars and percent of NLV,
- thesis invalidation,
- profit objective or ladder,
- time stop and event stop,
- net Delta, Gamma, Theta, and Vega,
- bid/ask spread and modeled slippage,
- assignment and dividend exposure,
- no-trade reason.

### Exit decision test

At each review, ask:

> Would we initiate this exact remaining exposure now, at this price, with
> this time left and this portfolio?

If the answer is no, holding requires a written reason. The original entry
price is not a reason.

### DTE policy

Theta and gamma behavior becomes more acute near expiration, but a universal
21-DTE force-close is not established across every strategy, underlying, and
regime.

Treat 21 DTE as a review trigger and run matched cohorts:

- entry DTE,
- exit DTE,
- strategy family,
- IV and event regime,
- profit target,
- stop policy,
- net R after friction,
- drawdown and tail loss.

Adopt the rule that wins on desk evidence.

## 4. Moving on quickly without overtrading

Barber and Odean found that the most active households in their brokerage
sample materially underperformed the market and less-active households after
trading costs. Odean separately documented the disposition effect: investors
were more likely to realize winners than losers, and subsequent performance
did not justify the behavior.

The right interpretation is not "trade slowly." It is:

- do not use trade count as a performance goal,
- price spread and slippage before entry,
- close when the thesis or exit rule says close,
- do not preserve a loser merely to avoid realizing it,
- do not re-enter the same ticker without a new decision card,
- compare net expectancy per unit of attention and capital.

### Metrics to add

- trades and decisions per session,
- turnover as a percent of NLV,
- gross and net R,
- spread/slippage by strategy family,
- winner versus loser holding time,
- exit-rule exceptions,
- same-ticker re-entry interval,
- opportunity cost of capital tied up in stagnant trades.

## 5. Trading without emotions

The system should make emotional state observable without pretending emotion
can be eliminated.

### Precommitment controls

- Write the decision card before entry.
- Display R and rule status before raw dollar P/L.
- No averaging down in an options trade.
- A later share purchase is a separate portfolio decision with fresh sizing.
- After an unplanned entry, size breach, or ignored exit, stop new entries for
  the session.
- After a large win, do not raise size unless the normal sizing model permits
  it.
- Journal confidence and disconfirming evidence before the result is known.

### Process score

Score each closed trade separately on:

1. thesis quality,
2. structure fit,
3. sizing compliance,
4. execution quality,
5. exit compliance,
6. result in net R.

A losing trade can have a strong process score. A profitable rule violation
must still receive a poor process score.

## 6. Claims corrected or downgraded

Earlier draft research contained several attractive but overconfident claims.
They should not become code as written:

- **IV rank thresholds:** useful context, not an automatic debit/credit gate.
  Direction, skew, term structure, realized-vol forecast, and event risk also
  matter.
- **21-DTE force-close:** a cohort hypothesis, not a universal mandate.
- **Wheel as the best small-account edge:** unsupported. It requires
  100-share capital, retains substantial downside, caps upside in the covered
  call phase, and currently conflicts with the desk's equity overweight.
- **1-3% monthly wheel return:** not a planning assumption.
- **Two losses means halve risk:** two outcomes alone do not identify a regime
  change. Use predefined drawdown and process controls.
- **Checklist improves profit factor by a fixed percentage:** unsupported as a
  universal claim. Use the checklist as a process-control experiment.
- **45 DTE is unanimously optimal:** false across all products and strategies.
  Test DTE cohorts locally.

## 7. Action order

1. Restore fresh Schwab account, option-chain, and price-history truth.
2. Close and score due paper simulations before replacing them.
3. Add the long-vol premium-hurdle fields.
4. Add the precommitted decision card.
5. Normalize every outcome in net R after friction.
6. Add turnover and disposition-effect audits.
7. Test DTE and exit policies as cohorts.
8. Keep wheel research shadow-only until capital and sleeve fit improve.

The structured version of this queue is generated by:

```bash
./run_inferno_market_mastery_plan.sh
```

It writes:

- `data/inferno_market_mastery_plan.json`
- `reports/market_mastery_next_actions_latest.txt`

## 8. Implemented evidence controls

The research is now operationalized:

- Approval and strike candidates preserve IV rank, ATR, volatility context,
  and net Greeks without using one IV threshold as an automatic strategy gate.
- Every new paper ledger entry freezes a decision card.
- Long straddles and strangles remain shadow-only unless a forecasted realized
  move exceeds the implied move plus additional modeled friction.
- Desk evidence guards keep long vol shadow-only above a 20% implied move,
  above a 30% ATM spread, or inside seven days to earnings when the implied
  move is outside the ledger's 10-20% research cohort. These are conservative
  desk policies, not universal market laws.
- A long-vol structure above 25% of NLV remains inadmissible when fresh account
  NLV is available to the decision card.
- Process breaches can pause new paper entries; ordinary losing streaks cannot.
- Schwab option-chain age now blocks paper admission after 36 hours; a fresh
  strike-plan timestamp cannot make an old broker quote fresh.
- Trade management surfaces 21 DTE as a review trigger.
- DTE, expectancy, and behavior reports separate paper from shadow evidence.
- Expectancy separates risk-passed from risk-failed structures.
- Portfolio heat combines live share value and open paper maximum loss by
  economic theme.
- Wheel analysis checks 100-share lot size, assignment cash, downside stress,
  Schwab options freshness, open interest, and bid/ask width before showing a
  shadow candidate.
- Turnover counts only staged paper tickets and opened shadow scenarios, not
  blocked or rejected construction attempts.

Current generated evidence:

- 146 closed option observations: 1 paper and 145 shadow.
- The only risk-passed paper outcome is one losing vertical debit trade, so
  promotion remains 1/30.
- The 96 long-straddle shadow outcomes are all risk-failed constructions. Their
  confidence interval crosses zero and they cannot establish tradable edge.
- DELL and HPE contribute nearly all positive historical long-vol R. Removing
  those two leaves 79 records at about -0.42R mean, while the newest 24 records
  have a 0% implied-move beat rate.
- Six records report positive R despite missing the implied-move hurdle, and
  repeated scenario fingerprints remain in the ledger. The diagnostics expose
  both issues rather than silently deduplicating or reconciling them.
- Risk-failed vertical-debit shadow outcomes have negative expectancy.
- Winner holding time averages about 20.4 days versus 24.1 days for losers;
  this is not yet large enough for the audit's disposition-effect flag.
- Three shadow days exceeded 100% of available NLV in summed hypothetical max
  loss, demonstrating why faster scenario generation must stay separate from
  capital deployment.
- The live digital-infrastructure/miner cluster is about 39.1% of NLV.
- Wheel quotes are currently stale. Even on the stale tape, none of the four
  holdings has 100 shares; only HIVE's put assignment cash fits current cash.

Canonical commands:

```bash
./run_inferno_expectancy_ledger.sh
./run_inferno_dte_policy_analysis.sh
./run_inferno_trading_behavior_audit.sh
./run_inferno_process_compliance.sh
./run_inferno_portfolio_heat.sh
./run_inferno_wheel_shadow.sh
```

## Primary sources

- Options Industry Council, May Office Hours:
  https://www.optionseducation.org/news/may-office-hours-faqs
- Options Industry Council, Long Straddle:
  https://www.optionseducation.org/strategies/all-strategies/long-straddle
- Options Industry Council, Theta:
  https://www.optionseducation.org/advancedconcepts/theta
- Options Industry Council, Cash-Secured Put:
  https://www.optionseducation.org/strategies/all-strategies/cash-secured-put
- FINRA, Concentration Risk:
  https://www.finra.org/investors/insights/concentration-risk
- FINRA, Risk Tolerance:
  https://www.finra.org/investors/insights/know-your-risk-tolerance
- Barber and Odean, Trading Is Hazardous to Your Wealth:
  https://faculty.haas.berkeley.edu/odean/papers%20current%20versions/individual_investor_performance_final.pdf
- Odean, Are Investors Reluctant to Realize Their Losses?:
  https://faculty.haas.berkeley.edu/odean/papers%20current%20versions/areinvestorsreluctant.pdf
- Aldous and Ziemba, Good and Bad Properties of the Kelly Criterion:
  https://www.stat.berkeley.edu/~aldous/157/Papers/Good_Bad_Kelly.pdf
- Federal Reserve, Expected Stock Returns and Variance Risk Premia:
  https://www.federalreserve.gov/pubs/feds/2007/200711/200711pap.pdf
- Cboe Strategy Benchmark Indices:
  https://www.cboe.com/us/indices/benchmark_indices/
