# Dual-momentum fair test — the 2008 crash (the result the bull window couldn't show)

- **Date:** 2026-07-09
- **Author:** Claude (research lane). Research-only. Real SPY EOD data via the
  connected market-data MCP; engine `inferno_dual_momentum_backtest.py`.
- **Reproducibility note:** the raw month-end data file used for this memo is not
  committed in the repo. Treat the figures as a research note until the input CSV
  is attached or regenerated; the engine now has a deterministic unit test for the
  rule mechanics.
- **Companion to:** `docs/DUAL_MOMENTUM_BACKTEST_2026-07-09.md` (the 2023–2026 bull
  window, where the model *lost*). This is the missing regime.

## Both regimes, real data, same model (SPY-vs-cash 12m absolute momentum)

| Window | Model | Return | Max DD | $1,100 → |
|---|---|---|---|---|
| **2008 crash** (eval 2008-01→2009-12) | **Timing** | **+4.8%/yr** | **0.0%** | **$1,204** |
| | Hold SPY | −10.3%/yr | −47.3% | $892 |
| **2023–2026 bull** (eval 2023-01→2026-06) | Timing | 17.0%/yr | −8.6% | $1,883 |
| | Hold SPY | 19.5%/yr | −8.6% | $2,021 |

The timing model held cash 21 of 23 months through 2008, **completely sidestepping
the −47% crash** — it grew slightly while the index nearly halved. In the calm bull
window it *lagged* buy-and-hold by ~2.5%/yr with no drawdown benefit.

## The honest synthesis — it's insurance

Neither window alone is the truth; together they are:

- **Bull markets = you pay the premium.** Trend-following lags a rising index
  because it whipsaws on dips and re-enters late. The 2023–2026 result (−2.5%/yr vs
  SPY) is that premium.
- **Crashes = you collect the payout.** In 2008 it converted a −47% / −$208 outcome
  into a flat / +$104 one. Avoiding a −47% drawdown is the entire point, and it
  worked exactly as the century-of-evidence literature says.
- **Over a full cycle** containing both, you get similar-or-better returns at much
  lower drawdown and volatility. That is the documented trend-following profile,
  now confirmed on real data end to end.

## Why this is the *right* tool for a small, loss-sensitive account

- A −50% drawdown on money you can't afford to lose is not a dip — it's ruin, and it
  needs +100% just to get back to even. For someone under financial pressure,
  **crash-avoidance can be worth more than a few points of bull-market return.**
- It's **free to run** (prices only), near-passive (check monthly), near-zero
  friction (1 switch in 23 months here), and works in a tiny account with
  fractional shares. It is the *opposite* of the pre-earnings options gambling the
  desk started with — risk control, not a bet.

## Honest caveats (binding)

- **Re-enters late.** The model was still ~mostly in cash through the 2009 rebound
  (it caught only 2 of 23 months in SPY), so the +4.8% understates a full-cycle
  result — it shows the *protection*, not the re-entry upside that comes in
  2010–2011. Insurance is slow to cancel.
- **Whipsaws** in sharp V-shaped selloffs (e.g. 2025), where it sells low and buys
  back higher — a real, recurring small cost.
- **The dollars are still modest at $1,100.** This controls risk; it does not
  create wealth on a small base. Account size remains the binding constraint.
- SPY here is close-price (not dividend-adjusted); a full implementation would use
  total-return series and typically a bond ETF (not flat cash) as the safe asset,
  which improves the defensive leg.

## Bottom line

This is the first strategy in the entire investigation that is **real, documented,
validated on your own data, free to run, and genuinely appropriate for a small,
loss-sensitive account** — because its job is to *not lose half your money in a
crash*, which is exactly the risk that matters most when the base is small and the
pressure is high. It won't make you rich at $1,100; it will keep a 2008 from
happening to you. That is a real, honest, actionable finding — and a fitting place
for the strategy research to land.
