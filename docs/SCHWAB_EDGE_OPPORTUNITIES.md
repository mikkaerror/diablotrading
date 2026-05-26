# Schwab API — Edge Opportunities

Last updated: 2026-05-20.

A candid research note on how live Schwab market data can extend the desk's
edge, and — more importantly — where the popular framing ("arbitrage", "stay
ahead of the market") is misleading for a manual $500-ticket options book on
7-21 DTE.

Read this **after** `docs/SCHWAB_OPTIONS_API.md` (the integration plan) and
**alongside** `docs/RESEARCH_ROADMAP.md` (the three-phase learning plan). This
doc is research-only. No new authority is implied. Broker submit stays OFF.

## The honest framing

The desk operates at structural disadvantages versus the entities that publish
the prices Schwab feeds us:

- **Latency.** A retail OAuth-fed market-data adapter is somewhere between 50ms
  and several hundred ms behind the consolidated tape. Market makers see the
  same prints before we do.
- **Fill priority.** Our orders sit behind professional flow in the queue.
- **Ticket size.** $500 maximum risk per ticket forecloses the
  position-construction techniques (gamma scalping, vol-of-vol, dispersion)
  that pay for execution infrastructure.
- **DTE band.** 7-21 DTE is the window with the highest gamma and the worst
  bid-ask economics. We are paying tolls on the busiest bridge.

What that rules out, with no apology:

1. **True arbitrage** (model-free risk-free profit). Filled in milliseconds by
   market makers. Never available to us.
2. **Latency-driven statistical arb.** Pairs that converge in seconds. Foreclosed.
3. **Order-flow prediction.** Reading the tape to anticipate the next print.
   Foreclosed; we are *part of* the slow flow.
4. **HFT mispricing capture.** The signal exists for ~10ms. We can't reach it.

What it leaves open — and this is the productive list:

1. **Quality filtering** (don't bleed). Stop paying the spread tax.
2. **Calibration** (know when the option market is wrong about *your*
   universe). Compare implied to realized; sell rich, buy cheap.
3. **Patience** (sit out bad regimes). Klarman's "no" is the highest-EV trade
   most days.
4. **Selection** (a small universe, deeply followed). Out-research a marginal
   institutional analyst on 30-50 names. Possible.
5. **Sizing** (Kelly fraction × ceiling). Convert correct theses into compound
   returns by not blowing up.

Schwab's market-data lane materially helps items 1, 2, and 4. It does nothing
for 3 (a discipline question) and 5 (a sizing-policy question).

The right slogan is **not** "stay ahead of the market." The market is faster
than us, period. The right slogan is **"stay ahead of our past self."** Every
closed outcome should leave the desk better-calibrated than the trade before
it. Schwab data is fuel for that calibration loop.

## Hierarchy of edge from market data

Reading downward, each tier costs more to build and pays less per dollar of
effort. Spend top-down.

### Tier 0 — Free edge: stop bleeding

This is what the active Schwab adapter already does and what nothing else can replicate:
refusing to trade contracts where the bid-ask spread eats the edge before the
thesis can pay off.

Already shipped in `inferno_schwab_options.py`:

- `quoteQualityScore` / `quoteQualityLabel` (5 buckets)
- `liquidityScore` per contract (0-100)
- `spreadQuality` per contract (tight / acceptable / workable / wide /
  untradeable)
- `qualityFlags` (wide-atm-spread, thin-atm-liquidity, incomplete-greeks,
  missing-underlying-price, etc.)
- `topLiquidContracts` shortlist
- Strike-selector and risk-policy enforcement on attached quote quality

The marginal dollar from improving Tier 0 is small because the adapter already
captures most of the slippage tax. The audit point here is *staleness*: every
artifact needs a freshness assertion (see §Refresh cadence below).

### Tier 1 — Vol calibration: where the market is wrong about your universe

This is the next durable edge for a small universe and where the desk has the
most to gain from Schwab data. The thesis: market-implied vol is an unbiased
estimator *on average*, but **systematically biased on specific names and
specific event types**. A patient desk that measures implied-vs-realized on its
own universe over months can size into the asymmetry.

Metrics to build (not yet in the Schwab lane):

| Metric | Schwab endpoint | What it tells you |
|---|---|---|
| **IV rank (252d)** | `/marketdata/v1/pricehistory` + chain history | Where current ATM IV sits in its own 1y history. Sell-vol bias above 70; buy-vol bias below 30. |
| **IV percentile (252d)** | same | Fraction of days IV was below current. Less sensitive to outliers than IV rank. |
| **Realized vol (5d, 21d, 63d)** | `/marketdata/v1/pricehistory` | Underlying realized vol on close-to-close and Yang-Zhang OHLC estimators. |
| **Vol risk premium (VRP)** | derived | `ATM_IV − realized_vol(21d)`. Persistent positive VRP = sell-premium bias; negative = buy-premium bias. |
| **Implied-vs-realized event move** | per-ticker historical chain snapshots | At each prior earnings, what did the ATM straddle imply, and what was the realized close-to-close move? Compute hit rate and average error. |
| **IV term structure slope** | `/expirationchain` + chain | Front-month IV vs 30-60-90 day IV. Contango ≈ buy-vol regime; backwardation ≈ sell-vol regime. |
| **25-delta skew** | chain | 25Δ put IV − 25Δ call IV. Extreme skew = pricing of crash insurance; track its percentile. |
| **Earnings IV decomposition** | chain pre/post-earnings | Split observed IV into base-vol + event-vol component using the cross-expiration solver from Beckers (1981). |

Why this tier pays: market makers price options to be unbiased *on the
aggregate flow they see*. Your universe is small and idiosyncratic. They are
not optimized for your 30 names. You can be.

Build constraints: IV rank requires history. Today the desk relies on tracker
feed IV rank; replacing that with Schwab-native history needs ~60 trading days
of stored chain snapshots before it stops being noisier than the tracker. Start
storing now even if you don't use it for 3 months.

### Tier 2 — Cross-instrument: where two prices disagree

Same idea, but across instruments rather than across time. The desk's current
slate is single-name vol; the next layer is single-name vol *relative to* an
appropriate benchmark.

| Metric | Sources | What it tells you |
|---|---|---|
| **Single-name vs index implied vol** | chain + SPY/QQQ/IWM chain | Is NVDA's IV rich vs QQQ's IV, controlling for beta? Persistent gap = expectation embedded that the index doesn't share. |
| **Sector ETF dispersion** | sector ETF chain vs constituent chain | Dispersion = sum of constituent variances minus index variance. Mean-reverts. Retail can't trade it, but it's a regime sensor. |
| **Pair vol comparable** | two-name chains | AMD vs NVDA, KO vs PEP — earnings-window IV differences flag where one name is being priced for a bigger surprise than peers. |
| **Term structure cross-section** | chain term structure across universe | When 80% of your universe is in IV contango simultaneously, the regime is "buy vol cheap"; when 80% is in backwardation, "sell vol rich." Cheap regime classifier. |
| **Calendar / diagonal mispricing** | chain across expirations | The straddle in expiration A versus expiration B should respect a no-arbitrage relationship. Departures = either a known event (earnings) or a mispricing. Catching the second case is rare but real in illiquid names. |

Realistic expectation: Tier 2 produces **regime signals**, not trade tickets.
Use it to decide what *family* of strategies fits today, not to pick a
specific contract.

### Tier 3 — Positioning and flow

The most-overhyped tier in retail options literature. "Unusual options
activity" is a real signal in academic work (Pan-Poteshman 2006, Ge-Lin-Pearson
2016), but the cleanest version of the signal is in *call/put order
imbalance*, not the headline metrics retail subscriptions sell.

| Metric | Schwab endpoint | Caveats |
|---|---|---|
| **Volume/OI ratio per strike** | chain | High V/OI = new positioning. Useful as a co-confirmation, not a primary signal. |
| **Cross-sectional put/call ratio** | chain | Aggregate sentiment proxy. Mean-reverts. |
| **Movers feed** | `/marketdata/v1/movers` | Top up/down by % and volume. Regime sensor more than a trade source. |
| **Block-print proxy** | chain with snapshot diffing | Volume that appears between snapshots at a single strike, especially deep OTM, is a positioning footprint. Schwab doesn't give us the tape directly, but snapshot diffing is a workable approximation. |
| **Open-interest delta** | chain across days | Day-over-day OI changes show where money is staying versus where it's day-trading through. |

Realistic expectation: Tier 3 is **confirmatory** at this desk's size. If a
Tier 1 calibration signal lines up with Tier 3 positioning evidence, that's a
green light. If they conflict, sit out.

### Tier 4 — Microstructure (the bleeding edge)

Spread dynamics, queue position, effective vs quoted spread — Hasbrouck (1991)
territory. Manual options at 7-21 DTE cannot extract microstructure alpha. But
microstructure metrics are useful as **regime risk sensors**: when ATM spreads
widen materially during the trading day, makers are pricing in adverse
selection. That's a "step back" flag, not a "lean in" signal.

Skip Tier 4 as an edge source. Use it only as a kill-switch input.

## Schwab endpoint → metric crosswalk

A practical reference for what each endpoint unlocks. Already in the adapter is
marked ✅; gap is ⬜.

### `/marketdata/v1/chains` (already used)

✅ Bid/ask/mid/last per contract
✅ Greeks (Δ, Γ, Θ, V)
✅ Volume and open interest
✅ Implied volatility per contract
✅ ATM straddle expected move
⬜ 25Δ skew (compute from existing rows; no new endpoint call needed)
⬜ Risk-reversal price (25Δ call − 25Δ put)
⬜ Butterfly price (25Δ call + 25Δ put − 2× ATM straddle/2)
⬜ Volume/OI ratio per strike
⬜ Cross-strike skew curve fit

### `/marketdata/v1/pricehistory`

✅ Daily OHLCV adapter for focused symbols
✅ Recomputed TOS custom metrics: RVOL, Pv52H, MOM, ATR%, Strength, SUP/RES
⬜ 252-day close-to-close realized vol per underlying
⬜ Yang-Zhang OHLC realized vol (lower variance, captures overnight gap)
⬜ Earnings-window realized moves (one-day close-to-open after announcement)
⬜ Drawdown statistics per underlying
⬜ Beta and correlation vs SPY/QQQ/sector ETF (rolling 60d)

### `/marketdata/v1/quotes`

⬜ Underlying tick-level mark for liquidity-check before strike submission
⬜ Cross-asset mark (gold, oil, VIX, USD) for macro overlay
⬜ Pre-market and after-hours marks for gap-risk assessment

### `/marketdata/v1/movers`

⬜ Daily up/down movers by % and by volume — regime classifier
⬜ Universe expansion candidate detection (large mover not yet in watchlist)
⬜ Liquidity-of-the-day proxy (volume-leader churn)

### `/marketdata/v1/markets`

✅ Market hours (implicitly handled by local clock)
⬜ Holiday-aware DTE compression detection
⬜ Half-day reduced-liquidity warnings

### `/marketdata/v1/instruments`

⬜ Symbol search and fundamentals attachment (sector, market cap, exchange)
⬜ Float and shares-outstanding for short-interest math
⬜ Description and CUSIP for compliance / audit trail

### `/marketdata/v1/expirationchain`

⬜ Forward expiration calendar — fixes the "what expirations are listable"
   question without parsing chain payloads
⬜ Weekly vs monthly expiration distinction for liquidity buckets

## Refresh cadence — "constantly refreshing" done right

The wrong framing is "poll as fast as possible." The right framing is "poll on
the cadence that matches the decision horizon." Faster polling beyond that
buys nothing and burns rate-limit budget you'll need on a busy day.

Schwab Trader API standard rate limit is approximately **120 requests/minute**
(verify against your token's current limit; the policy has changed twice in
the past two years). That's ~7,200/hour. A focused universe of 100 names
asking for chain + price history + quote once every 90 seconds consumes about
2,000/hour. Budget is not the bottleneck.

Proposed tiered polling for a 100-name universe:

| Tier | What | Cadence | Reason |
|---|---|---|---|
| **Focus list** (top 5-10 names by readiness) | full chain + quote + 5d history | 30-60s during RTH | These are the names you might actually ticket today |
| **Working universe** (full 100-name watchlist) | quote + ATM chain slice | 5 min during RTH | Regime drift detection |
| **Universe** (250+ tickers with stored history) | quote only | 15 min during RTH | Keep history alive for IV rank window |
| **Movers** (`/movers`) | top 50 up + top 50 down | 15 min during RTH | Regime sensing + universe expansion |
| **Underlying price history** | EOD pull, all stored tickers | once daily at 4:15pm ET | IV rank denominator update |
| **Reference data** (`/instruments`) | sector + market cap | once weekly | Slow-changing context |

The two operating principles:

1. **Snapshot diffing beats raw polling.** Store the prior chain snapshot per
   ticker; only flag a change when a contract crosses a meaningful threshold
   (spread widened > 25%, volume spiked > 2× prior session average, OI
   changed > 10%). Most polls produce no actionable change. Diffing makes the
   live data lane *quiet* until it matters.

2. **Fail closed on staleness.** Any artifact older than its refresh cadence
   × 2 should be flagged stale and stop feeding strike selection. The desk
   already does this for tracker freshness; extend it to Schwab chain
   freshness.

After-hours discipline:

- **4:00-4:15pm ET:** Capture EOD closing chain snapshot for every working
  universe ticker. This is the canonical daily record.
- **4:15-5:00pm ET:** Pull underlying price history for IV rank denominators.
- **5:00pm-8:00am ET:** Quiet. The desk learns overnight, doesn't trade.
- **8:00-9:30am ET pre-open:** Refresh tokens; pull pre-market underlying
  marks; assemble the morning brief.

## What "constantly ahead" actually means

Reframing the user's question: you cannot be ahead of the market in time. You
can be ahead in **three other dimensions** that compound:

1. **Ahead in calibration.** A 6-month rolling implied-vs-realized log for
   your 100 names is a real edge that institutional analysts often don't keep,
   because they cover wider universes and rotate.
2. **Ahead in preparation.** When NVDA's earnings hit, you should already have
   the prior-eight-quarter ATM straddle vs realized move table on screen. The
   market reacts in seconds; *your decision should have been pre-computed*.
3. **Ahead in patience.** Most days, the right trade is no trade. The desk
   that says no 18 days a month and yes 2 days a month, on the right 2, beats
   the desk that grinds through every session.

The Schwab API is the substrate for items 1 and 2. Item 3 is a discipline
question the API cannot solve.

## What we have today vs what to build

### Already shipped (Phase 1 live read-only lane)

- Read-only chain adapter with quote-quality + liquidity + ATM expected move
- OAuth helper with local token refresh and ignored token vault
- Daily ops tape that classifies active symbols into tradable / review / avoid
- Strike selector integration
- Risk policy enforcement on quote-quality failures
- Fixture-driven testing without network

### Remaining Phase 1 carryover

- Daily chain snapshot history storage (prerequisite for everything in Tier 1)

### Proposed Phase 2 — Vol calibration layer

Three new modules, all research-only and diagnostic-only:

1. **`inferno_iv_calibration.py`** — Per-ticker IV rank (252d), IV percentile,
   realized vol (5d / 21d / 63d) using Yang-Zhang on stored price history, VRP
   = ATM_IV − realized_21d. Produces `reports/iv_calibration_latest.txt`.
2. **`inferno_vol_surface.py`** — Per-ticker term-structure slope, 25Δ skew,
   risk-reversal, butterfly. Flags ticker-days where any surface metric crosses
   its 1-year percentile threshold.
3. **`inferno_event_vol_history.py`** — Per-ticker earnings-window history:
   prior ATM straddle implied move, prior realized close-to-open move,
   per-ticker hit rate. Feeds the auditor's bear bullet on overpriced events.

### Proposed Phase 3 — Cross-instrument layer

Built only after Phase 2 has 60+ days of stored history:

1. **`inferno_cross_vol.py`** — Single-name vs index/sector vol ratio,
   beta-adjusted. Daily cross-sectional snapshot.
2. **`inferno_dispersion_monitor.py`** — Sector dispersion regime classifier;
   advisory only.
3. **`inferno_pair_vol.py`** — Pair-name vol comparables for the desk's
   "natural pairs" (AMD/NVDA, KO/PEP, GS/MS, XOM/CVX, etc.).

### Proposed Phase 4 — Positioning overlay

Built only when Phase 3 is stable and adding signal:

1. **`inferno_unusual_activity.py`** — V/OI per strike, day-over-day OI delta,
   block-print proxy from snapshot diffing. Confirmatory only.
2. **`inferno_movers_regime.py`** — `/movers` feed → regime classifier.
3. **`inferno_universe_expander.py`** — Movers + fundamentals filter →
   candidate names not yet in watchlist. Human review required.

### Refresh & ops infrastructure (build alongside Phase 2)

- **`inferno_chain_history.py`** — Daily EOD chain snapshot storage with
  retention policy (90 days hot, 1 year archive).
- **`inferno_chain_diff.py`** — Snapshot diffing engine. Only emits events
  when meaningful changes happen.
- **`inferno_schwab_freshness.py`** — Staleness assertions that fail closed
  into strike selection and the morning brief.
- **Doctor integration** — Extend `inferno_doctor.py` to assert Schwab
  freshness alongside tracker freshness.

## Anti-goals — what NOT to chase

A short list, learned the expensive way by other retail desks:

- **Latency arbitrage.** You will lose, every time, against entities that
  paid for colocation.
- **"Unusual options activity" newsletters.** By the time the alert reaches a
  retail subscriber, the spread has widened to bury the entry.
- **Dark-pool prints from third-party feeds.** Schwab doesn't give them to
  us; third parties that claim to are typically reselling delayed CBOE data.
  Spend nothing here.
- **0DTE flow chasing.** Outside our DTE band; gamma dynamics destroy retail
  manual execution. Some institutional desks make money here; we cannot.
- **"AI vol prediction" pre-trained models.** A small, calibrated linear
  model on your own 100-name universe with 252 days of stored history beats
  every black-box vol predictor sold to retail. Build the boring version.
- **"Catch the mispricing" within minutes.** The window for retail manual
  intervention is the *day*, not the minute. Optimize for daily decisions.

## How this connects to the existing roadmap

The three research phases in `docs/RESEARCH_ROADMAP.md` (post-trade learning →
portfolio-level → consensus risk) are **orthogonal** to the Schwab edge tiers
described here:

- Post-trade learning (Phase A) tells the desk *what it learned from the last
  ticket*.
- Schwab vol calibration (Phase 2 above) tells the desk *what the options
  market expects on its universe right now*.
- The two together produce a learning loop: yesterday's outcomes update the
  per-rule decay tracker, while today's Schwab calibration updates the
  variant-perception layer for new tickets.

A reasonable global build order, looking 3-6 months out:

1. Finish Research Roadmap Phase A (post-trade learning).
2. Build Schwab Phase 2 (vol calibration), starting with chain history
   storage so the IV-rank denominator is real.
3. Research Roadmap Phase B (portfolio-level correlation).
4. Schwab Phase 3 (cross-instrument vol) — depends on Phase B math.
5. Research Roadmap Phase C (consensus risk).
6. Schwab Phase 4 (positioning overlay).

Authority does not change at any step. Broker submit stays OFF. The 30
closed-scored-paper-outcomes promotion gate stays in force.

## Operating principle

> The desk's edge is not speed. It is the discipline to act only on calibrated
> asymmetries on a small universe, sized small enough to survive the wrong
> ones, with execution clean enough not to give the edge back at the bid-ask
> spread.

Schwab market data buys us the calibration and the execution-quality screen.
Discipline and sizing are not for sale.

## Sources

Primary references used in this note (citation tags live in
`docs/THEORY_REFERENCES.md`; new tags marked with †):

- BHB-1986 — Brinson, Hood, Beebower, "Determinants of Portfolio Performance"
- HASBROUCK-1991 — Hasbrouck, "Measuring the Information Content of Stock
  Trades"
- ALMGREN-CHRISS-2000 — Almgren & Chriss, "Optimal Execution of Portfolio
  Transactions"
- PAN-POTESHMAN-2006 † — "The Information in Option Volume for Future Stock
  Prices"
- GE-LIN-PEARSON-2016 † — "Why Does the Option to Stock Volume Ratio Predict
  Stock Returns?"
- BECKERS-1981 † — "A Note on Estimating the Parameters of the
  Diffusion-Jump Model of Stock Returns"
- YANG-ZHANG-2000 † — "Drift-Independent Volatility Estimation"
- KYLE-1985 — Kyle, "Continuous Auctions and Insider Trading"
- KLARMAN-MARGIN-OF-SAFETY — "Margin of Safety: Risk-Averse Value Investing
  Strategies for the Thoughtful Investor"

New citation tags to add to `docs/THEORY_REFERENCES.md` when Phase 2 begins:
PAN-POTESHMAN-2006, GE-LIN-PEARSON-2016, BECKERS-1981, YANG-ZHANG-2000.
