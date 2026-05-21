# Strategy Requirements

Current as of 2026-05-20.

This is the desk's hedge-fund-style operating charter. It translates the broad
mission - compound a small bankroll through disciplined, defined-risk trades -
into strategy families, data requirements, formulas, gates, and artifacts.

This document does not authorize live trading. Authority remains pinned by
`data/inferno_authority_manifest.json`.

## Objectives

1. Preserve optionality first. No single idea, ticker, sector, broker export,
   or model output is allowed to threaten the account.
2. Convert the AI infrastructure thesis into ranked, falsifiable trade ideas.
3. Prefer evidence-backed timing over broad bullishness.
4. Use options only when the option market is tradable: tight spread, enough
   open interest, sensible implied move, and defined maximum loss.
5. Learn from every paper and live outcome in R-units, not vibes.
6. Promote automation only when closed evidence, risk gates, and authority
   controls all agree.

## What "Hedge-Fund-Grade" Means Here

The desk borrows from durable hedge fund strategy families, not from mystique.
The top-level taxonomy follows HFR's major hedge fund buckets
(`[HFR-CLASS]`): equity hedge, event driven, macro, and relative value. The
useful playbook is:

| Strategy family | Hedge-fund pattern | Desk translation | Status |
|---|---|---|---|
| Equity hedge / thematic long-short | Long winners, short/fade weak peers, control beta | Long-biased AI infrastructure basket; shorts deferred until risk engine supports them | active research |
| Event-driven / catalyst | Trade around known events, estimate event risk | Earnings windows, guidance, product/capex catalysts, pre-earnings timing | active |
| Relative value / options volatility | Trade mispricing between implied, realized, and structure | Compare ATM implied move, ATR, support/resistance, IV rank, spread cost, and Greeks | active, Schwab live |
| Macro / CTA / trend | Follow persistent trends and regimes across assets | Market regime, QQQ/SMH/NVDA trend, VIX/rates context, sector breadth | partial |
| Statistical learning / quant | Many small tests, decay monitoring, anti-overfit discipline | Scenario slate, paper evidence, walk-forward, DSR/PBO roadmap, edge decay | in progress |
| Portfolio construction | Size by covariance, drawdown, and capacity | Portfolio correlation + drawdown protocol live as research-only gates; capacity next | active research |
| Crowdedness / reflexivity | Avoid everyone-owned trades at bad price | Schwab skew + own-side concentration + family-pair fusion live as research-only monitor; short interest / 13F later | active research |

## Data Authority Stack

| Data need | Primary source | Fallback | Required use |
|---|---|---|---|
| Ticker universe and model columns | Google Earnings Tracker | TOS watchlist extract | Universe and score source of truth |
| Option chain, bid/ask, Greeks, OI, IV | Schwab API | yfinance / local estimates | Strike quality, slippage, implied move |
| Broker cash, positions, fills | TOS account statement export | Manual operator confirmation | Reality check only, never auto-submit |
| Prices, ATR, RVOL, trend | Existing tracker scripts / market context layer | yfinance | Setup scoring and trend gates |
| Support/resistance | Market context layer | manual chart review | Entry timing and stop/target logic |
| Fundamentals and theme | SEC filings, earnings releases, industry data | analyst/vendor summaries | Long-term conviction context |
| Short interest / crowdedness | FINRA short-interest data, exchange data, Schwab OI/skew | vendor summaries | Consensus/reflexivity warnings |
| Futures/options positioning | CFTC COT where relevant | none | Macro crowding context |
| Closed outcomes | Paper ledger / shadow evidence / live fills | none | Promotion math and edge decay |

## Required Fields Before A Trade Can Be Considered

Every candidate should have these fields populated or explicitly marked
unavailable:

| Category | Required fields |
|---|---|
| Identity | ticker, company, sector/theme lane, market cap bucket |
| Catalyst | earnings date, days to earnings, event type, catalyst quality |
| Setup | setup recommendation, signal trigger, confidence, readiness |
| Price behavior | ATR%, 20-day ATR, RVOL, trend, support, resistance, distance to support/resistance |
| Options quality | expiration, DTE, strike, bid, ask, mid, spread percent, volume, open interest, IV, IV rank, delta, theta, vega |
| Expected move | ATM straddle mid, implied move percent, ATR-implied-move ratio, breakevens |
| Risk | max loss, target R, stop R, ticket size, daily risk units, setup concentration |
| Evidence | similar historical scenarios, paper outcomes, Wilson lower, expectancy CI, devil's-advocate p-value |
| Authority | paper/live mode, account suffix check, approval state, broker-submit flag |

## Objective Function

The desk is not optimizing for the prettiest chart. It is optimizing for
survivable expected growth after friction:

```text
expected_R_after_friction =
    p_win_lower * avg_win_R
    - (1 - p_win_lower) * abs(avg_loss_R)
    - slippage_R
    - theta_decay_R
    - event_gap_penalty_R
```

Minimum objective requirements:

| Requirement | Threshold |
|---|---|
| Expected R lower bound | > 0 before promotion |
| Wilson lower win rate | >= 0.42 before promotion |
| Evidence strength | >= 0.70 before promotion |
| Devil's advocate p-value | < 0.05 for "edge-holds" |
| Walk-forward verdict | survives |
| Single ticket max loss | <= configured cap |
| Daily risk units | <= configured cap |
| Account authority | broker submit disabled unless explicitly promoted |

## Trade Gate Stack

A candidate should pass gates in this order:

1. Data freshness gate: tracker, price, options, and account state are current
   enough for the intended action.
2. Universe gate: ticker is in the approved strategy universe or explicitly
   added with a reason.
3. Catalyst gate: earnings/event timing is known and not stale.
4. Setup gate: readiness, confidence, trigger, setup recommendation, and
   urgency are aligned.
5. Market context gate: trend, RVOL, support/resistance, and sector regime do
   not contradict the trade.
6. Options quality gate: spread, liquidity, Greeks, IV, and implied move are
   good enough for the structure.
7. Structure gate: defined risk, known max loss, target/stop written before
   entry.
8. Portfolio gate: no concentration breach by ticker, setup, theme, or
   correlated basket.
9. Evidence gate: paper/shadow history supports the rule cell.
10. Authority gate: current authority permits the action.

Failure at any gate either blocks the trade or demotes it to research-only.

## Strategy-Specific Requirements

### 1. AI Infrastructure Momentum / Quality

Goal: own or trade leaders and sleepers in the AI/datacenter supply chain when
trend, quality, and price action agree.

Required data:

- relative strength versus QQQ/SMH
- revenue/profitability quality where available
- RVOL and liquidity
- support/resistance
- earnings timing
- sector breadth

Blocks:

- extended above resistance with poor reward/risk
- weak volume on breakout
- theme crowding without fresh confirmation
- broad market risk-off regime

Evidence anchors: cross-asset momentum (`[AMP13]`), trend following
(`[HOP17]`), and quality/profitability (`[NM13]`).

### 2. Earnings Catalyst Timing

Goal: capture pre-event repricing without blindly paying through IV crush.

Required data:

- days to earnings
- IV rank / IV percentile
- ATM straddle implied move
- ATR and recent realized move
- options spread/liquidity
- exit plan before earnings unless the thesis explicitly holds through

Blocks:

- missing or negative earnings window
- realized move cannot plausibly beat implied move
- IV already in the "steamroller" zone for a long-premium structure
- spread friction too high

Evidence anchors: earnings IV and IV crush (`[Patell-Wolfson79]`,
`[Diavatopoulos12]`, `[Andrade-Ekkayokkaya-Frijns18]`) plus variance risk
premium (`[VRP-BK03]`, `[CarrWu09]`).

### 3. Defined-Risk Directional Options

Goal: express conviction with capped downside.

Required data:

- max loss
- breakeven
- target R and stop R
- delta / theta / vega
- bid/ask spread percent
- open interest and volume
- ticket size as percent of bankroll

Blocks:

- undefined risk
- no written exit
- spread percent too wide for account size
- ticket violates concentration or daily risk-unit cap

Evidence anchors: option pricing (`[BS73]`, `[Merton73]`), Kelly sizing
(`[Kelly56]`, `[MacLean-Thorp-Ziemba10]`), and SEC warnings on leverage,
options, and derivatives risk (`[SEC-HF]`, `[SEC-LEV]`).

### 4. Long-Term Buy-at-Discount Watchlist

Goal: separate "great business temporarily down" from "broken thesis."

Required data:

- drawdown from 20/50/200-day highs
- revenue/margin/FCF trend where available
- earnings revision direction
- balance-sheet risk
- long-term theme lane
- support zone and valuation context

Blocks:

- thesis deterioration
- falling knife with no support/reversal evidence
- liquidity or balance-sheet stress
- sector thesis breaking at the same time

### 5. Paper Scenario Slate

Goal: track 10+ daily scenarios so evidence accumulates faster than manual
trade approvals.

Required data:

- candidate score
- reason code
- setup family
- DTE bucket
- expected move
- realized move after close
- hypothetical entry/exit timestamps
- R-unit outcome after estimated slippage

Blocks:

- missing timestamp
- missing reason code
- no comparable outcome class
- no way to reconstruct the trade later

Evidence anchors: Wilson intervals (`[Wilson27]`), bootstrap methods
(`[Efron-Tibshirani93]`), sign-flip falsification (`[Phipson-Smyth10]`),
and deflated Sharpe / PBO (`[LdP-DSR]`, `[BBLZ17]`).

## Required Metrics

| Metric | Formula / rule | Why it matters |
|---|---|---|
| Spread percent | `(ask - bid) / mid` | Slippage tax; rejects untradeable options |
| Implied move percent | `ATM straddle mid / underlying` | What the options market is pricing |
| ATR move percent | `20-day ATR / price` | Realized movement proxy |
| Implied/ATR ratio | `implied move pct / ATR pct` | Flags expensive event premium |
| RVOL | current volume / average volume | Confirms participation |
| Support distance | `(price - support) / price` | Defines downside room |
| Resistance distance | `(resistance - price) / price` | Defines upside room |
| Expected R | weighted win/loss R after friction | Core trade value |
| Wilson lower | lower confidence bound on win rate | Avoids trusting tiny samples |
| Bootstrap expectancy lower | lower CI on mean R | Falsifies noisy average returns |
| Conservative Kelly | `max(0, mu_lo / variance_hi)`, capped | Sizes under parameter uncertainty |
| Drawdown | peak-to-trough account decline | Prevents ruin |
| Correlation | pairwise strategy outcome correlation | Prevents false diversification |
| Crowdedness | OI/skew/short-interest/positioning blend | Flags reflexive reversal risk |

## Promotion Requirements

No strategy can move beyond research/paper until all are true:

- at least 30 closed scored outcomes for that strategy cell
- clean data lineage for every outcome
- positive bootstrap expectancy lower bound
- Wilson lower win rate above threshold
- devil's-advocate p-value clears edge-holds
- walk-forward survives
- slippage-adjusted expectancy remains positive
- drawdown protocol allows new risk
- concentration governor clears
- secret hygiene and authority manifest are clean

## Immediate Build Priorities

1. Tighten Schwab quote-quality thresholds inside strike selection and risk
   policy, using the daily ops tape as the primary option-market screen.
2. Add Schwab chain history / IV calibration so implied-vs-realized checks use
   the desk's own stored evidence instead of one-off snapshots.
3. Add support/resistance and RVOL gates as first-class risk-policy inputs.
4. Expand paper scenario capture to produce more closed outcomes per week.
5. Add capacity / slippage decay limits once more closed evidence exists.
6. Extend crowdedness with short interest, /movers, sector ETF vol, and 13F
   context only after the v1 consensus monitor proves useful.

## One-Sentence Rule

If a trade cannot pass data freshness, option liquidity, defined risk,
expected-R, portfolio concentration, and authority gates, it is not a trade; it
is research.
