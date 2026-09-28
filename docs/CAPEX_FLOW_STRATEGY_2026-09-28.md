# Capex Flow: follow the hyperscaler dollars to the names they reach

September 28, 2026. Strategy specification, research-only. Implemented as
`inferno_capex_flow.py`, forward-scored as lane `capexFlow` by
`inferno_pick_scorecard.py`, shown daily in the Desk Editor email. No orders.
Not financial advice; every rule below is a hypothesis to be measured.

## Thesis in one paragraph

The four largest spenders guided roughly **$733bn** of 2026 capex against
**$409bn** actually spent in their last full years (+79%), and three of four
raised guidance mid-year. That money becomes revenue for suppliers in a rough
order: chips, networking and servers first; power, cooling and electrical
contractors alongside; semicap and materials after. The strategy owns the
layers the money is reaching *now*, confirmed by price, and changes instrument
with conditions instead of forcing one structure.

## Why this can work (and where it usually fails)

- **Supplier returns lag customer news.** Cohen & Frazzini found stock prices
  under-react to news about a firm's major customers, so suppliers follow their
  customers with a lag ([JF 2008](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2008.01379.x);
  [AQR summary](https://www.aqr.com/Insights/Research/Journal-Article/Economic-Links-and-Predictable-Returns)).
  Hyperscaler guidance raises are exactly this kind of customer news.
- **The spenders themselves are the wrong side.** Firms that sharply raise
  capital investment tend to underperform afterwards
  ([Titman, Wei & Xie 2004](https://www.nber.org/papers/w9951)). We follow the
  dollars to the recipients, not the investors.
- **The desk's own verdict:** buy strength, manage by trend, never average
  down (`MOMENTUM_VS_BUYLOW_VERDICT_2026-07-15.md`).
- **How it fails:** supplier stocks key off the *rate of change* of capex, not
  its level. +79% cannot repeat, so 2027 growth will slow even if dollars rise.
  The other failure is funding: this cycle is increasingly paid for by debt and
  equity rather than operating cash (see the tape below). Crowding is real; the
  theme is consensus, so the edge must come from timing, layer selection and
  instrument choice, not from "AI is big".

## Layer 1 — the tap (top-down regime)

Source: `research/capex_tape.json` (sourced figures, updated each earnings season).

| Spender | Last full year | 2026 guide | Funding signal |
|---|---:|---:|---|
| Microsoft | $115.9bn (FY Jun-26) | ~$175bn run-rate | FCF positive |
| Alphabet | $91.4bn (2025) | $195–205bn | FCF turned negative; ~$100bn debt, ~$80bn equity |
| Amazon | $131.8bn (2025) | ~$220bn | TTM FCF negative |
| Meta | $69.7bn (2025) | $130–145bn | ~$0 FCF; buybacks suspended; new debt |

Sources: FMP annual cash-flow statements; [TMT Finance, Aug 2026](https://www.tmtfinance.com/intel/2026-hyperscaler-capex-tops-us700bn-analysis);
[ValueAdd tracker, Aug 11 2026](https://valueaddvc.com/ai-spending);
[CNBC, Jul 28 2026](https://www.cnbc.com/2026/07/28/hyperscalers-face-higher-capex-scrutiny-after-alphabet-report-panned.html).

| Regime | Rule | Throttle | Today |
|---|---|---:|---|
| accelerating-funded | growth ≥ 10%, ≥ 3 of 4 FCF-positive | 1.0 | |
| **accelerating-stretched** | growth ≥ 10%, spending outruns cash | 0.8; capital-dependent names ×0.6 | **current** |
| plateau | growth < 10% | 0.5 | |
| cut | ≥ 2 spenders cut guidance | 0 — no new positions, exit tactical | |

## Layer 2 — the pipes (value chain)

`research/capex_value_chain.json`: 106 tracker names in 12 layers, each with
*order* (1 = direct order book, 2 = second order, 3 = indirect) and *funding*
(paid supplier, capital-dependent, regulated/contracted). Developers and
neoclouds (IREN, CLSK, CRWV, NBIS…) depend on open capital markets, so a
stretched regime haircuts them hardest. Layer assignment is analyst-made from
industry labels; issuer revenue exposure is not yet verified (gap D1).

## Layer 3 — flow confirmation (per name)

Score = (50 + trend points + relative-strength points + near-support bonus −
valuation guard) × order weight × regime throttle.

- Trend: Uptrend +20, Bullish +15, Neutral 0, Basing −5, Bearish −25.
- Relative strength vs the tracker universe median, from frozen scorecard
  cohorts (currently 20 days): ±2 points per 1%, capped at ±20.
- BUY needs score ≥ 60, an up trend and positive RS; WATCH ≥ 45; Bearish is
  always AVOID. Weights are stated, not fitted.

## Instrument follows conditions

| Condition | Instrument |
|---|---|
| BUY, any IV | **Shares** are the core (fractional is fine at this size). Add on strength; never average down. |
| BUY and IV rank ≥ 60, earnings > 7 days | Or enter by **selling a defined-risk put spread at support** (30–45 DTE): paid to wait. This is the family with the only positive backward evidence on the desk. |
| BUY and IV rank ≤ 30 | **Paper-test** a 60–120 DTE call spread (time for flows to show up; short pre-earnings debit spreads tested badly). |
| WATCH, paid supplier, IV rich | Optional put spread at support; otherwise wait. |
| Earnings ≤ 7 days | Half size or wait. |
| Never | Pre-earnings long straddles (killed 2026-07-09 unless implied < the name's history). |

## Sizing and exits

- Account-shaped sizing from the basket lane (`inferno_ai_basket_sizing.py`);
  one layer ≤ 40% of the lane; capital-dependent ≤ 25% in a stretched regime.
- Options risk per ticket ≤ the live capital-scaling cap (currently ~$277).
- Core shares exit on a Bearish trend for two consecutive snapshots or below
  the 200-day; tactical below the 50-day.
- Put spreads: take 50% of max profit or exit at 21 DTE. Call spreads: exit at
  50% loss or 21 DTE.
- Thesis break: regime → plateau halves the lane; regime → cut exits new and
  tactical positions.
- Operator long-term holds (TE, IREN, HIVE, CLSK) stay excluded from exit
  logic, as already decided in the basket lane.

## Today's read (2026-09-28)

Regime **accelerating-stretched**. Strongest layers by mean score: servers/
systems, memory/storage, compute, semicap, networking/optics. Weakest:
nuclear, data-center REITs, power generation, developers. Top five frozen into
the scorecard: CRDO, MPWR, GNRC, CLFD, TEL. Spenders are +4.0% vs the universe
over 20 days, a positive customer-momentum read.

## How we will know if it works

- Lane `capexFlow` vs the equal-weight tracker universe and SPY at 21/63/126
  sessions, frozen daily. First 21-session results ≈ late October.
- Paper put-spread and call-spread entries recorded through the normal gates
  once the short-premium paper route exists (Codex mission S2).
- **Falsifier:** after ≥ 10 matured cohorts at 63 sessions, a mean excess
  return vs the universe at or below zero ends the stock-selection claim.

## Data gaps (next)

- D1 Issuer revenue exposure and quarterly revenue acceleration: FMP plan
  denies quarterly statements for most names; SEC EDGAR companyfacts is free
  but blocked from the sandboxes — must run on the Mac host (Codex).
- D2 The tape needs a refresh after each earnings season (next: late October).
- D3 Implied volatility vs realised for instrument choice (entry snapshots, M6).
