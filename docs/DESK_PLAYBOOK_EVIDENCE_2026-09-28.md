# Desk playbook: what the evidence says about trends, fades, options and profit

September 28, 2026. Research only; not advice. Each rule names its evidence,
where it lives in code, and what would falsify it on *our* data. Literature is
cited as author/year/journal; the desk's own numbers come from saved artifacts.

## 1. Trends: own strength, measured three ways

| Rule | Evidence | In code |
|---|---|---|
| Rank names by 3–12 month relative strength; hold winners | Cross-sectional momentum (Jegadeesh & Titman 1993, JF); industry momentum explains much of it (Moskowitz & Grinblatt 1999, JF) | Capex Flow RS vs universe; layer ranking; basket momentum |
| Stay long only while the name's own trend is up | Time-series momentum (Moskowitz, Ooi & Pedersen 2012, JFE) | Trend points; Bearish = AVOID |
| Names near highs keep outperforming | 52-week-high effect (George & Hwang 2004, JF) | `breakout` entry state |
| Size momentum by volatility and expect crashes after sharp market rebounds | Vol-managed momentum (Barroso & Santa-Clara 2015, JFE); momentum crashes (Daniel & Moskowitz 2016, JFE) | Basket sizing; **gap:** add inverse-vol sizing to Capex Flow tickets |
| Never average down | Desk verdict 2026-07-15 (buy-low worst on this basket) | Instrument text; playbook §5.4 |

Falsifier on our data: `capexFlow` cohorts fail to beat the equal-weight
universe at 63 sessions across ≥ 10 cohorts.

## 2. Fades: a timing tool, not a strategy

Short-horizon reversal is real (Jegadeesh 1990, JF; Lehmann 1990, QJE) but
concentrated in illiquid names and largely consumed by trading costs. For
this desk, fades are used only to **time entries and exits inside a trend**:

| State (code: `entry_timing`) | Rule | Action |
|---|---|---|
| pullback | up-trend, ≤ 1.0 ATR above support | preferred entry |
| breakout | ≤ 1% below resistance on RVOL ≥ 1.3 | strength entry |
| extended | ≥ 3.5 ATR above support | start 1/3 size, add on pullback |
| exhaustion | extended + ATR z ≥ 1.5 + RVOL ≥ 1.3 | no new entry; trim-watch tactical |

Experiment: lane `capexFlowTimed` (BUY names only in pullback/breakout) vs
`capexFlow`. If timed entries do not beat untimed ones after ≥ 10 matured
cohorts, drop the overlay. Today all top names are extended: momentum leaders
rarely offer pullbacks, which is itself the cost of timing.

## 3. Earnings: trade the drift, not the event premium

- Prices keep drifting in the direction of an earnings surprise for weeks
  (post-earnings-announcement drift; Bernard & Thomas 1989, JAR).
- Implied moves overstate realised moves on average; our 65-event ledger has
  implied 27% vs realised 10% and a 21.5% long-vol beat rate.
- Rule: no pre-earnings long straddles; prefer entering capex-flow names
  **after** a positive earnings reaction, and suppliers after their big
  customers raise guidance (Cohen & Frazzini 2008, JF).
- Gap: the desk does not store post-earnings reactions yet (needs D1 + M6).

## 4. Options: sell expensive, buy cheap, and only where spreads allow

- Options are on average priced above the volatility later realised (the
  variance risk premium; Carr & Wu 2009, RFS; Bakshi & Kapadia 2003, RFS).
  Buying out-of-the-money options has negative average returns (Coval &
  Shumway 2001, JF).
- Rule, implemented in `inferno_vol_edge.py`: compare 30–45 DTE at-the-money
  IV with realised volatility. IV/RV ≥ 1.30 = **rich** (defined-risk premium
  selling allowed); ≤ 0.90 = **cheap** (longer-dated debit structures allowed,
  paper first); in between = shares.
- Today (12 captured chains): 5 rich, 7 fair, 0 cheap. Median IV/RV ≈ 1.25.

### The profitability killer: bid/ask spreads

| Measure | Value |
|---|---|
| Median ATM spread at ~35 DTE, captured names | **17.7% of mid** |
| Names passing the live 10% gate | **2 of 12** (IREN, AAPL) |
| Average leg spread on staged paper tickets | 27% of mid |

Illustration: a put spread for a $1.00 credit built from legs with $2.00 and
$1.00 mids at 17% spreads loses about half the spread on each leg on entry and
again on exit, ≈ $0.51, roughly **half the maximum profit**, before the trade
does anything. The backward short-premium study assumed 0.1R friction; at
these spreads the real friction is several times that, enough to erase its
+0.20R edge. Rules:

1. Options only where the ATM spread is ≤ 10% of mid (live) / ≤ 20% (paper).
2. Always limit orders at or near mid; never market orders on options.
3. Otherwise use **shares**, whose spreads are pennies.
4. Record every fill vs mid so friction becomes measured, not modelled (M7).

## 5. Profitability: what actually moves the number

1. **Costs first.** Spreads, fees and slippage are the only certain part of
   any trade. At a ~$850 account, one bad options fill can exceed a month of
   expected edge.
2. **Position sizing.** Risk a fixed fraction per idea (the capital-scaling
   formula currently gives ~$277 per ticket); size by volatility; cap layers.
   Kelly sizing stays off until paper evidence exists (expectancy ledger).
3. **Base rates.** Measure every lane against the equal-weight universe and
   SPY; activity is not return. The account's flow-adjusted return is −26.7%
   vs SPY +4.1% since June 17: the benchmark is the bar to clear.
4. **Fewer, better decisions.** Turnover without measured edge only adds cost.

## 6. What changed in code today

- `inferno_vol_edge.py` (new): IV30 vs realised, event flag, spread gates.
- `inferno_capex_flow.py`: instrument choice now uses IV/RV and liquidity when
  a chain exists (ivRank proxy otherwise, labelled); entry-timing states.
- Pick scorecard lane `capexFlowTimed` for the timing experiment.

## 7. Gaps handed on

- Capture Schwab chains for Capex Flow BUY/WATCH names (only 12 captured);
  fix `avgImpliedVolatility`, which averages −999 placeholders (HIVE shows
  −137.9) — Codex, Schwab lane.
- Live trade journal: Sep 10–21 option trades show in the transaction ledger
  without instrument detail, so realised live P/L is unknown — Codex.
- Inverse-volatility sizing for Capex Flow tickets — next Claude step.
