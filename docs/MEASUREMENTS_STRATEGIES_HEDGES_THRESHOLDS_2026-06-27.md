# Measurements, Strategies, Hedges, And Thresholds - 2026-06-27

Stage: research-only
Promotable: false
Authority change: none
Live trading allowed: false
Broker submit allowed: false

This memo is the desk inventory for what we are actually measuring, which
strategy families are live in research, what is functioning as a hedge, and
which thresholds are hard rails versus calibration hypotheses. It does not
approve trades, change risk constants, modify the universe, promote any
strategy, or widen authority.

## Bottom Line

The desk should keep optimizing measurement and evidence throughput, not loosen
gates. The current bottleneck is not a shortage of ideas. It is a shortage of
clean, priced, risk-passed, closed paper evidence.

Current generated state says:

| Area | Current read |
|---|---|
| Authority | `paper-evidence-only`; `liveTradingAllowed=false`; `brokerSubmitAllowed=false` |
| Account truth | Schwab suffix 8499 read-only account artifacts are canonical for NLV, cash, and positions |
| Promotion gap | 29 more scored paper outcomes required before promotion review |
| Long-vol evidence | 100 closed long-vol records; 34% beat rate; mean move edge -10.62 percentage points |
| Current long-vol slate | 7 candidates, all unpriced, so premium pressure cannot be judged yet |
| Defined-risk alternative pricing | 4 priced put-credit candidates; 1 combined pass, SMR 9/8 put credit spread, shadow-only |
| Capital posture | Manual review allowed with warnings; auto-live locked; edge-adjusted options max loss remains $0 |
| Risk cap tension | Config cap $500 versus current NLV formula recommendation $25; operator ack required for any formula adoption |

The useful operating rule is:

```text
Scores discover work.
Prices and liquidity qualify structure.
Paper outcomes promote strategy.
Authority gates decide what can touch the broker.
```

## Source Stack Used

Fresh generated artifacts outrank durable docs for current state. This memo
relies on:

- `reports/model_command_center_latest.txt`
- `reports/score_threshold_audit_latest.txt`
- `reports/expected_move_ledger_latest.txt`
- `reports/strategy_alternative_pricing_latest.txt`
- `reports/strategy_shadow_comparison_latest.txt`
- `reports/risk_gate_audit_latest.txt`
- `reports/capital_deployment_readiness_latest.txt`
- `reports/capital_scaling_latest.txt`
- `reports/expectancy_ledger_latest.txt`
- `reports/dte_policy_analysis_latest.txt`
- `reports/portfolio_heat_latest.txt`
- `docs/TRADING_DISCIPLINE_RESEARCH_2026-06-22.md`
- `docs/FUNNEL_STAGNATION_DIAGNOSIS_2026-06-25.md`
- `docs/RISK_POLICY.md`
- `docs/STRATEGY_REQUIREMENTS.md`
- `docs/THEORY_REFERENCES.md`

External reference checks:

- OCC options disclosure document:
  https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- FINRA options overview:
  https://www.finra.org/investors/investing/investment-products/options
- Schwab bid/ask spread explainer:
  https://www.schwab.com/learn/story/large-bidask-options-spreads-volatile-markets
- Options Industry Council implied-volatility metrics:
  https://www.optionseducation.org/videolibrary/implied-volatility-metrics
- Options Industry Council long straddle:
  https://www.optionseducation.org/strategies/all-strategies/long-straddle
- Options Industry Council bull put spread / credit put spread:
  https://www.optionseducation.org/strategies/all-strategies/bull-put-spread-credit-put-spread
- Options Industry Council protective put / married put:
  https://www.optionseducation.org/strategies/all-strategies/protective-put-married-put
- Options Industry Council collar / protective collar:
  https://www.optionseducation.org/strategies/all-strategies/collar-protective-collar
- Carr and Wu (2009), variance risk premium:
  https://academic.oup.com/rfs/article-abstract/22/3/1311/1599134
- Barber and Odean (2000), household trading underperformance:
  https://faculty.haas.berkeley.edu/odean/papers%20current%20versions/individual_investor_performance_final.pdf
- Kelly (1956), capital growth criterion:
  https://archive.org/details/bstj35-4-917

## Measurement Inventory

### 1. Account And Capital Measurements

These answer: "What money exists, what is already exposed, and what could be
reviewed manually?"

| Measurement | Meaning | Current use | Caveat |
|---|---|---|---|
| NLV | Schwab net liquidating value for approved account | Denominator for account risk, cap scaling, portfolio heat | Refresh Schwab before any current sizing claim |
| Cash | Schwab total cash | Manual deployment review | Cash deltas are not realized options profit |
| Deployable cash | Operator or readiness input | Splits manual review into options, starter, long-term, reserve guardrails | Budget, not authority |
| Reserve cash | Cash deliberately not deployed | Liquidity and drawdown hedge | Should not be treated as unused opportunity by default |
| Config ticket caps | $500 single, $1500 daily, 5 open paper tickets | Risk-policy containment | Current NLV formula recommends $25; changing constants is operator-owned |
| Capital scaling formula | 1% of NLV, $25 floor, $2000 ceiling, drawdown stepper | Research-only recommendation with ack file | Does not mutate config without explicit accept |
| Portfolio heat | Theme-level NLV concentration | Detects theme crowding | Current effective theme count is low because live shares cluster |
| Drawdown stepper | Peak-to-current NLV discipline | Halves or quarters new-ticket cap in drawdown | Current cap-scaling report shows step-1-half from live NLV history |

### 2. Candidate Measurements

These answer: "Which names deserve attention before we even price options?"

| Measurement | Meaning | Current use | Caveat |
|---|---|---|---|
| Readiness | 0-100 quality/timing composite | Discovery and paper-bootstrap gate | Rank surface, not probability |
| Confidence | 0-3 tracker conviction input | One of five candidate quality predicates | Ordinal, not calibrated |
| Days until earnings | Catalyst proximity | <=21 candidate timing predicate | 21 DTE is a review convention, not a proven optimum |
| Signal trigger | Whether the tracker says action is live | Setup gate | Cannot override price, quote, or risk gates |
| Scenario score | Scenario slate rank | Backtest/observation comparison | Current monotonicity is imperfect |
| Priority score | Queue/order-of-attention score | Paper and shadow context | Useful only if preserved at entry and closed outcome |
| Setup recommendation | Straddle, vertical, avoid, etc. | Initial structure hint | Current funnel has premium-buy monoculture bias |
| IV rank / IV context | Implied volatility regime proxy | Paper variant scanner and structure context | IV rank alone is not a debit/credit switch |

The score-threshold audit's important warning is that readiness >=72 currently
admits 53% of the 146-name universe, while the operator-level default intends
roughly top-20% selectivity. That is a calibration finding, not permission to
move the gate autonomously.

### 3. Option Quote And Structure Measurements

These answer: "Is the contract actually tradeable, and does the structure pay
enough for its risk?"

| Measurement | Current threshold or use | Notes |
|---|---|---|
| Schwab option-chain age | <=36 hours | Blocks stale read-only option evidence |
| Visible quote floor | bid/ask >= $0.10 per leg | Catches quote artifacts that are not real markets |
| Generic spread guard | spread <=35% of mid | Wide spreads are friction, not a cosmetic warning |
| ATM liquidity score | Composite of spread, OI, volume | Audit recommends risk policy eventually gate on this, not spread alone |
| Underlying source drift | <=5% tracker/chain price divergence | Prevents stale or mismatched price bases |
| Debit spread reward/risk | >=0.50 | Low payoff cannot be rescued by a high setup score |
| Credit spread credit/risk | >=0.20 | Current SMR pass is 0.5385 |
| Support cushion | Credit short put should sit below support | Current failed alternatives often have short put at or above support |
| Expected move hurdle | reasonable <=1.25 ATR; stretch <=2.0; hard <=3.0 | Long-vol demotion thresholding |
| Max loss | Must fit effective ticket cap | Cap is current bottleneck for many contracts |
| Greeks | Delta, theta, vega context by structure | Required for decision cards; not yet promotion evidence by itself |

OCC and FINRA both frame options as leveraged instruments with material risk.
Schwab's spread guidance is especially relevant here: wide bid/ask spreads are
an execution-cost problem and can worsen during volatile markets. That matches
the desk's own refusal to treat poor quote quality as a small warning.

### 4. Evidence And Outcome Measurements

These answer: "Did the rule cell work after friction?"

| Measurement | Promotion role | Current read |
|---|---|---|
| Scored paper outcomes | >=30 required before promotion review | 1 scored; gap 29 |
| Wilson lower win rate | Must clear payoff-implied breakeven + 0.03 margin, fallback 0.42 | Payoff-aware gate implemented; still not enough evidence |
| Expectancy lower bound | Must be >0 R | Current production does not promote |
| Profit factor | Must be >=1.25 | Current production does not promote |
| Max drawdown | Must be no worse than -6R | Shadow long-vol has path pain; paper sample too small |
| False-positive rate | Warning above 45% | Funnel quality metric |
| Expected move beat rate | Long-vol move proof | 34% beat rate across 100 closed long-vol records |
| Net R by family | Friction-adjusted evidence | Paper vertical debit n=1 loss; shadow vertical debit negative; shadow long straddle risk-failed |
| DTE cohort result | Observational timing evidence | 21-DTE policy has no closed >=21 DTE scored cohort |
| Score calibration monotonicity | Decides whether scores can become probabilities | Current scores rank, but do not size |

The promotion rule is deliberately multi-dimensional. A high win rate with poor
payoff, a good mean with ugly lower bound, or a pretty shadow replay without
paper evidence should not grant authority.

### 5. Portfolio And Process Measurements

These answer: "Are we accidentally running one big correlated bet, or breaking
discipline?"

| Measurement | Use | Current caveat |
|---|---|---|
| Theme heat | Flags concentration by economic theme | Digital-infrastructure-miners are watch-level heat |
| Effective theme count | Measures diversification quality | Current value is below 2 in latest heat report |
| Portfolio correlation | Effective bet count and co-movement | Research-only until more outcomes exist |
| Drawdown protocol | Sizing response to losses | Research-only for paper outcomes; cap-scaling uses NLV drawdown |
| Consensus/crowdedness | Identifies crowded/reflexive risk | Advisory unless risk policy consumes it |
| Process compliance | Stops new paper entries after process breaches | Protects evidence integrity |
| Trading behavior | Turnover, holding time, re-entry discipline | Prevents trade count becoming the goal |

Barber and Odean's household trading evidence supports the desk's own bias:
more activity is not automatically progress. A clean skipped trade can be a
better outcome than a forced, unpriced, low-liquidity test.

## Strategy Family Review

### Long Vol: Straddles, Strangles, Long Calls, Long Puts

Current stance: demoted unless priced premium, expected move, spread, and
alternative structures justify the debit.

Evidence:

- Closed long-vol records: 100.
- Beat rate: 34%.
- Mean implied move: 32.53%.
- Mean realized absolute move: 21.90%.
- Mean move edge: -10.62 percentage points.
- Recent cohort is worse than the full sample.
- Excluding the top two positive contributors, the long-vol evidence degrades
  materially.
- Current long-vol slate has 7 unpriced candidates, so it cannot pass premium
  pressure analysis yet.

Use when:

- The structure is priced.
- Realized move forecast can beat debit, spread, and decay.
- The trade sits inside the 10-20% implied-move sweet spot or has a written
  reason to depart from it.
- A defined-risk alternative has been compared and lost on expected net R.

Do not use when:

- The only reason is high readiness.
- The required move is unpriced or hard/extreme by ATR.
- The setup is riding the same premium-buy monoculture that has already
  stalled the funnel.

### Debit Spreads: Call Debit Spread, Put Debit Spread

Current stance: useful defined-risk directional expression, but not promoted.

Evidence:

- Risk policy requires debit reward/risk >=0.50.
- Net-R ledger shows risk-failed shadow vertical debit n=49 with negative net R
  and negative confidence interval.
- The only paper risk-passed vertical debit record is one closed loss.

Use when:

- Directional conviction is explicit.
- Max loss and max profit are bounded.
- Reward/risk clears 0.50 after quote quality.
- Spread, OI, and volume support a paper-quality entry.

Do not use when:

- The vertical exists only because the straddle was too expensive.
- Reward/risk is below floor.
- The DTE cohort is being treated as causal evidence.

### Defined-Risk Premium Selling: Put Credit Spreads And Condors

Current stance: the best current area for paper discovery, but still
shadow-only until evidence accumulates.

Evidence:

- Paper variant scanner created measurable paper chances.
- Strategy alternative pricing checked 4 put-credit candidates and found 1
  combined pass.
- SMR 2026-08-21 9/8 put credit spread: credit $0.35, max loss $65,
  credit/risk 0.5385, support cushion 1.333%, shadow comparison only.
- Other priced alternatives failed for support, quote width, cap, or low
  credit/risk.
- Iron-condor range-safe rows are currently 0.

Use when:

- Maximum loss is defined.
- Credit/risk clears 0.20.
- The short strike is support-safe.
- Quote width and liquidity are clean.
- Gap/event risk is named and sized.

Do not use when:

- The credit is high because the short strike is sitting at/above support.
- The spread is too wide or OI/volume are too thin.
- It is being used as a shortcut around evidence gates.

### Iron Condors And Range Trades

Current stance: infrastructure exists, but current tape is not producing
range-safe condor rows.

Use when:

- Range boundaries are explicit.
- Both wings price cleanly.
- Credit/risk is acceptable after slippage.
- Event gap risk is bounded.

Do not use when:

- It is just a "premium-selling sounds smart" wrapper.
- The chain has no range-safe rows.

### Wheel / Cash-Secured Put Proxy

Current stance: research-only shadow lane. Not capital-realistic at the current
account size unless assignment and downside stress fit.

Evidence:

- Variant scanner can surface wheel-proxy rows using price <30 and IV rank >30.
- Wheel shadow currently reports no-capital-realistic-wheel.

Use when:

- The account can absorb 100-share assignment under stress.
- The underlying is acceptable as a long-term hold.
- The downside scenario is written before entry.

Do not use when:

- It consumes the whole account.
- It is only a way to sell premium without owning the assignment consequence.

### Long-Term Shares

Current stance: separate from options authority. Shares can be manually reviewed
under capital readiness, but existing declared holds do not automatically
approve new additions.

Measurements:

- Thesis quality, support zone, concentration, theme heat, drawdown context,
  balance-sheet risk, and long-term score.

Do not mix:

- Live share gains are not evidence that options rules worked.
- Existing ownership is not permission to average up or add without the fresh
  candidate gate.

## Hedges

The desk's current hedges are mostly structural. They reduce the chance of a
bad decision reaching the broker rather than adding an offsetting option
position.

### Active Structural Hedges

| Hedge | How it protects the desk |
|---|---|
| Authority lock | Live submit and broker submit remain false |
| Human approval boundary | Operator must approve/reject paper or real actions |
| Read-only Schwab scope | Account suffix 8499 is broker truth, not broker authority |
| Cash reserve | Keeps optionality and prevents full deployment pressure |
| Ticket cap and daily cap | Bounds max loss per simulated ticket/day |
| Drawdown stepper | Shrinks new-ticket cap as NLV falls |
| Defined-risk structures | Prevent undefined-loss options in early authority phases |
| Quote-quality gates | Avoids giving back edge to wide spreads and ghost quotes |
| Support cushion | Blocks put-credit structures that are already too close to support |
| Expected-move hurdle | Prevents long-vol from paying any premium at any price |
| Portfolio heat | Surfaces accidental theme concentration |
| Process compliance | Blocks evidence pollution after rule breaches |
| Promotion gate | Keeps a lucky sample from becoming automation authority |

### Explicit Portfolio Hedges Not Yet Active

These are valid research topics but are not live recommendations:

| Hedge | Research requirement before use |
|---|---|
| Protective puts on live share book | Price the hedge, define protected exposure, compare cost to drawdown tolerance |
| Collars on concentrated holdings | Define upside give-up, downside floor, tax/assignment caveats, and operator intent |
| Index or sector hedges | Measure beta to QQQ/SMH/SPY and confirm hedge liquidity |
| Pair hedges | Need borrow/short mechanics and broker permission; not phase-1 safe |
| Volatility hedge | Needs product risk review and correlation proof |

OIC strategy material supports protective puts and collars as standard
structures, but that does not make them automatically appropriate here. The
desk first needs a beta/concentration measurement and a costed hedge card.

## Threshold Map

### Hard Authority Rails

These are not optimization knobs.

| Threshold | Current state |
|---|---|
| `liveTradingAllowed` | false |
| `brokerSubmitAllowed` | false |
| Broker adapter mode | OFF / preview-only |
| Paper ticket approval | operator-only |
| Paper ticket rejection/close/promotion | operator-only |
| Universe membership | operator-owned |
| Risk constants | operator-owned |

### Risk And Execution Gates

These can block paper staging or broker-preview preparation. They should fail
closed.

| Gate | Current threshold |
|---|---|
| Single-ticket cap | $500 config; effective cap may be lower only after accepted capital-scaling ack |
| Daily ticket cap | $1500 config |
| Open paper tickets | 5 |
| Strike-plan age | 180 minutes |
| Schwab option-chain age | 36 hours |
| Underlying source drift | <=5% |
| Visible quote floor | bid/ask >= $0.10 |
| Generic spread guard | <=35% of mid |
| Debit reward/risk | >=0.50 |
| Credit/risk | >=0.20 |

### Discovery Filters

These find candidates. They do not promote strategies.

| Filter | Current threshold |
|---|---|
| Readiness | >=72 |
| Confidence | >=2 |
| Days until earnings | <=21 |
| Paper bootstrap gates cleared | >=3 of 5 |
| Credit-spread variant scan | price <100, IV rank >50, support >=1 ATR |
| Wheel-proxy variant scan | price <30, IV rank >30 |
| Score calibration sample | overall >=30, monotonic bucket >=3 |

### Promotion Evidence Gates

These decide whether a strategy earns more automation authority. Current
evidence does not clear them.

| Gate | Current threshold |
|---|---|
| Scored paper outcomes | >=30 |
| Win-rate lower bound | >= payoff-implied breakeven +0.03 margin; fixed fallback 0.42 |
| Expectancy lower bound | >0 R |
| Profit factor | >=1.25 |
| Max drawdown | >= -6R |
| False-positive rate | warning above 45% |

### Advisory Thresholds And Hypotheses

These should guide research, not issue authority.

| Item | Status |
|---|---|
| 21 DTE | Review trigger; not causal proof |
| Evidence strength weak/moderate/strong | Advisory scalar, not authority switch |
| IV rank thresholds | Context and scanner input, not standalone strategy switch |
| Expected move ATR buckets | Long-vol pressure sensor |
| Percentile readiness gate | Current audit finding; proposed calibration, not implemented |
| Kelly sizing | Disabled until credible family-level evidence exists |

## Current Contradictions To Clean Up

1. Config cap versus current account formula:
   $500 max ticket is 20x the $25 NLV formula recommendation. The recommender
   is research-only and needs operator ack before it changes effective policy.

2. Readiness gate selectivity:
   Readiness >=72 admits 53% of the current universe, while operator-level
   default intends top-20% selectivity. This is a calibration item. Do not edit
   the gate without an operator decision.

3. Score interpretation:
   Readiness and scenario score have monotonicity violations and closed option
   records historically lack score fields. Treat them as rankers until closed
   option outcomes prove calibration.

4. Long-vol pricing gap:
   The current long-vol slate is unpriced, so the system cannot know whether
   the debit is reasonable, stretched, or hard. Pricing must occur earlier.

5. Strategy family imbalance:
   The funnel has been biased toward premium-buy structures even though the
   desk's own evidence and variance-risk-premium literature warn that naive
   long premium is a hostile base rate.

6. Spread versus liquidity mismatch:
   The 35% spread guard is necessary but not sufficient. The liquidity-composite
   audit is right to recommend future gating on ATM liquidity score.

7. DTE evidence gap:
   The 21-DTE convention cannot be validated because no closed scored cohort
   exists at or above 21 DTE. Keep it as a review trigger.

8. Duplicated constants:
   `MAX_DAILY_RISK_UNITS` and `MAX_KELLY_FRACTION` are duplicated in multiple
   modules today. Values agree, but drift protection should eventually
   single-source them without changing values.

9. Kelly formula split:
   Strategy lab and Kelly sizing use different Kelly formulations. That is fine
   while sizing is disabled, but it should be reconciled before any sizing
   authority depends on Kelly output.

10. Realized live option P/L gap:
    Schwab account cash, NLV, open P/L, paper P/L, and shadow P/L cannot prove
    realized live option profit. A closed transaction ledger is still missing.

## Research-Only Optimization Backlog

These are the highest-leverage next improvements that preserve safety.

| Priority | Work | Why it matters | Authority impact |
|---|---|---|---|
| P1 | Price long-vol candidates earlier in the cycle | Expected-move pressure cannot be evaluated while candidates are unpriced | none |
| P1 | Compare every premium-buy candidate against defined-risk alternatives | Prevents premium-buy monoculture and cap-based silent drops | none |
| P1 | Preserve entry-time score fields on every paper/shadow option record | Makes score calibration possible on closed option outcomes | none |
| P1 | Keep variant scanner paper-only but track outcomes by family | Builds evidence without relaxing production gates | none |
| P2 | Add costed hedge cards for protective puts, collars, and index hedges | Converts hedge talk into measurable cost/protection tradeoffs | none |
| P2 | Single-source duplicated risk/math constants without changing values | Prevents future drift | none if values unchanged; operator review for risk knobs |
| P2 | Add robust payoff estimator or lower clamp for payoff-aware win-rate gate | Reduces outlier sensitivity in promotion math | operator-owned if gate behavior changes |
| P2 | Add matched DTE cohorts | Turns 21-DTE convention into evidence or retires it | none |
| P2 | Surface ATM liquidity score as a risk-policy candidate gate | Aligns quote quality with actual tradability | operator-owned if blocking behavior changes |
| P3 | Wire a realized live option transaction ledger | Separates deposits, open P/L, realized option P/L, and paper P/L | none |

## Operating Rule For Monday

Do not force trades to make the account feel active. The desk should either:

1. produce a clean, priced, risk-passed paper candidate,
2. close and score the open fast-paper simulation when eligible,
3. price and shadow-register a defined-risk alternative, or
4. sit in cash and record exactly which gate protected the account.

All four are progress. Only the first three generate new evidence. None grant
live authority.

## 2026-06-28 Metric Research Addendum

This addendum turns the current metric findings into a short research queue.
Each item has a measurable signal and a falsifier, so the desk can tell the
difference between real improvement and more attractive reporting.

| Metric | Current read | Failure mode | Useful next measurement | Falsifier |
|---|---|---|---|---|
| Readiness selectivity | `readiness >= 72` admits 53% of the 146-name universe; default operator intent is top 20% | Fixed score cutoff drifts with the universe distribution | Report percentile rank of the live readiness cutoff each cycle | Closed option outcomes with readiness fields show the current fixed cutoff separates positive net R from lower buckets |
| Option-score calibration | Historical closed option records still report `optionScoreRows=0` | Scores stay rank-like and cannot size risk | Preserve readiness, scenarioScore, priorityScore, route, and setup family on every new option paper/shadow entry | 30+ closed option records with preserved scores show stable monotonic net-R buckets |
| Long-vol premium pressure | 7 current long-vol candidates are unpriced; closed long-vol beat rate is 34% | High readiness can mask an impossible premium hurdle | Price candidates earlier and record implied move / ATR bucket before structure choice | Priced long-vol candidates in the 10-20% implied-move bucket beat defined-risk alternatives after spread and decay |
| ATM liquidity quality | Spread gate is necessary but not sufficient; spread/liquidity audit is now surface-only | A name clears spread while failing OI/volume liquidity, creating false tradability | Track `atmLiquidityScore`, OI, volume, and spread together in risk evidence | Names that clear the current 35% spread gate but fail liquidity composite still close with acceptable modeled slippage |
| Capital cap realism | $500 config cap versus $25 current NLV formula recommendation | Paper tests can appear valid at a size that is not account-realistic | Record effective cap source and percent of NLV on every paper candidate | A future accepted cap formula or larger NLV makes the configured cap consistent with percent-of-NLV limits |
| Strategy-family breadth | Recent funnel history biased toward premium-buy structures | Evidence throughput stalls when the only generated family has poor base rates | Count generated, priced, risk-passed, and closed candidates by family each cycle | Defined-risk premium-sell and debit-spread families generate no clean risk-passed paper chances after pricing |
| DTE policy | No closed scored cohort at or above 21 DTE | A review convention gets mistaken for causal edge | Build matched cohorts by entry DTE, exit DTE, family, IV regime, and friction | Matched cohorts show 21-DTE review timing has no net-R or drawdown advantage |
| Drawdown gates | R-unit drawdown gate is not yet reconciled with small-account dollar risk | A strategy can pass R-unit math while being too painful for current NLV | Report max drawdown in both R units and percent of NLV | Current R-unit gate and percent-of-NLV drawdown gate always agree across promoted candidates |

Metric priority for the next research cycle:

1. Price long-vol candidates before any structure preference is trusted.
2. Preserve option entry scores until closed outcome calibration becomes possible.
3. Promote `atmLiquidityScore` from a diagnostic candidate to a reviewed risk-policy proposal only after the audit produces recurring mismatches.
4. Keep cap scaling as an operator-ack recommender; do not edit risk constants to force alignment.
5. Track strategy-family breadth as a funnel health metric, not as permission to add unproven families to approval queues.
