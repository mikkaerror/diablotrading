# Dual-momentum backtest — real SPY data, honest result

- **Date:** 2026-07-09
- **Author:** Claude (research lane). Research-only. Real EOD data via the
  connected market-data MCP; engine `inferno_dual_momentum_backtest.py`.
- **Reproducibility note:** the raw month-end data file used for this memo is not
  committed in the repo. Treat the figures as a research note until the input CSV
  is attached or regenerated; the engine now has a deterministic unit test for the
  rule mechanics.
- **Model tested:** SPY-vs-cash 12-month absolute-momentum timing (own SPY when its
  trailing 12m return beats cash, else hold cash/T-bills at ~4%/yr). This is the
  drawdown-control core of trend/dual momentum, and the only version runnable at
  ~$1,100.

## Result (evaluated window 2023-01 → 2026-06, 41 months)

| Strategy | CAGR | Vol | Sharpe | Max DD | $1,100 → |
|---|---|---|---|---|---|
| **Timing (SPY/cash)** | 17.0% | 12.3% | 1.15 | −8.6% | **$1,883** |
| Buy & hold SPY | 19.5% | 12.7% | 1.30 | −8.6% | $2,021 |
| Hold cash | 4.1% | 0% | — | 0% | — |

**The timing overlay lost:** ~2.5%/yr less return, and it did NOT reduce the max
drawdown (same −8.6%). It held cash 5 of 41 months (defensive in early 2023 after
the 2022 decline) and missed part of the recovery — textbook trend whipsaw.

## Why this window is unfair to trend-following (read this before concluding)

- The 12m lookback consumes 2022, so the *evaluated* period is 2023–2026 — almost
  entirely bull market. The one selloff (Feb–Apr 2025, ~19%) was **V-shaped** and
  recovered fast, which is exactly where timing models whipsaw and lose.
- Trend-following's documented edge is **avoiding sustained bears** (2000–2002,
  2008) — cutting a −50% index drawdown to ~−23% (Antonacci). There is **no such
  bear in this window**, so the mechanism that justifies it never gets to act.
- SPY here is close-price (not dividend-adjusted), understating buy-&-hold SPY by
  ~1.3%/yr — so hold-SPY actually beat the timing model by even a bit more.

## Honest conclusion

On recent (bull-heavy) data, the simple timing overlay is a **drag, not an edge** —
it costs return and provides no drawdown help when the only declines are sharp
V-shapes. This is consistent with the literature: trend-following earns its keep
over *long* samples containing real bears, and lags in extended bull runs. It is a
**crash-insurance / drawdown-control tool**, not a return enhancer — and insurance
looks like pure cost in a year with no fire.

Two things this reinforces:
1. **No free lunch here either.** Even the "best accessible edge" underperformed
   plain SPY over this window. The honest expectation for a small account is: buy-
   and-hold a broad index does very well in bull markets; the timing overlay only
   pays off by softening a major bear, at the cost of lagging in bulls.
2. **The dollars are small regardless.** $1,883 vs $2,021 on $1,100 over 3.5 years —
   a $138 difference. At this account size the strategy *choice* barely moves the
   outcome; the account *size* is what matters.

## To test it fairly (optional next step)

Pull SPY (and a bond ETF) month-ends back through **2007–2010** so the evaluated
window includes the 2008 bear — the regime where the timing model is supposed to
shine (cutting the ~−55% SPY drawdown to ~−20%). That single slice would show the
drawdown-protection benefit that this bull-only window structurally cannot.

## The through-line (unchanged)

Every branch of this research keeps returning the same structural truth: the edges
that exist are modest and regime-dependent, and at ~$1,100 the binding constraint
is account size, not strategy. The most reliable "strategy" for a small account
remains: hold a low-cost broad index, keep costs near zero, and grow the base.
