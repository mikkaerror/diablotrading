# Theory References

The desk leans on a small set of well-cited results. This file is the one
place the audit modules cite from. New citations land here first, then any
module that uses one references it by its short tag (e.g. `[VRP-BK03]`).

Citations are deliberately conservative. Most are decades old, robustly
replicated, and survive peer review. We do not cite blog posts as primary
evidence; we cite them only when the underlying paper is paywalled and the
post correctly reproduces a numeric result we can re-derive.

## Options pricing primitives

- **[BS73]** Black, F., & Scholes, M. (1973). *The Pricing of Options and
  Corporate Liabilities.* Journal of Political Economy, 81(3), 637–654.
  — d1/d2, the European call/put formula, the canonical hedging argument.
  Lives in `inferno_options_math.py`.

- **[Merton73]** Merton, R. C. (1973). *Theory of Rational Option Pricing.*
  Bell Journal of Economics, 4(1), 141–183.
  — dividend extension, American boundary conditions, no-arbitrage proofs.

## Implied volatility around earnings

- **[Patell-Wolfson79]** Patell, J. M., & Wolfson, M. A. (1979).
  *Anticipated information releases reflected in call option prices.*
  Journal of Accounting and Economics, 1(2), 117–140.
  — first systematic evidence that IV rises into known information
  releases. The earnings IV ramp is not a recent discovery; it's been
  observable for 45 years.

- **[Diavatopoulos12]** Diavatopoulos, D., Doran, J. S., Fodor, A., &
  Peterson, D. R. (2012). *The information content of implied volatility
  and option volume around earnings announcements.* Journal of Banking &
  Finance, 36(3), 786–802.
  — IV crushes after earnings; long-premium structures need realised move
  > implied move to break even. The empirical anchor for our
  "if realised < 50% of implied move, exit" falsification trigger.

- **[Andrade-Ekkayokkaya-Frijns18]** Andrade, S. C., Ekkayokkaya, M., &
  Frijns, B. (2018). *Earnings announcement returns of straddles.*
  Journal of Financial and Quantitative Analysis, 53(5), 2207–2236.
  — net-of-vol-crush realised expectancy on at-the-money straddles
  held across earnings. Headline: average return is negative; the right
  tail comes from a small minority of names with realised > implied move.

## Variance risk premium

- **[VRP-BK03]** Bakshi, G., & Kapadia, N. (2003). *Delta-hedged gains and
  the negative market volatility risk premium.* Review of Financial
  Studies, 16(2), 527–566.
  — long-volatility positions have negative expected payoff in the
  cross-section because implied vol is systematically above realised vol.
  Selling premium has structural positive expectancy; buying it does not,
  absent a directional thesis or a vol-mispricing claim.

- **[CarrWu09]** Carr, P., & Wu, L. (2009). *Variance risk premiums.*
  Review of Financial Studies, 22(3), 1311–1341.
  — index and single-name VRP magnitudes; the single-name premium is real
  but smaller and noisier than the index premium.

## Statistical machinery the desk uses

- **[Wilson27]** Wilson, E. B. (1927). *Probable inference, the law of
  succession, and statistical inference.* Journal of the American
  Statistical Association, 22(158), 209–212.
  — Wilson score CI for a binomial proportion. The desk's win-rate gates
  use Wilson lower, not the naive `wins/n`, because Wilson is well-behaved
  at small n and near 0/1.

- **[Phipson-Smyth10]** Phipson, B., & Smyth, G. K. (2010). *Permutation
  P-values should never be zero: calculating exact P-values when
  permutations are randomly drawn.* Statistical Applications in Genetics
  and Molecular Biology, 9(1).
  — the `(1 + k)/(B + 1)` correction in the sign-flip bootstrap. Without
  it, an unusual but real edge prints `p = 0.000`, which the desk would
  rightly distrust.

- **[Efron-Tibshirani93]** Efron, B., & Tibshirani, R. J. (1993). *An
  Introduction to the Bootstrap.* Chapman & Hall.
  — percentile bootstrap CI on the mean and on differences of means;
  underpins the expectancy CI and the two-sample bootstrap on R-units.

- **[Wasserman10]** Wasserman, L. (2010). *All of Statistics.*
  Springer.
  — beta-binomial conjugate posterior derivation; mutual information
  estimator under sampling noise; CUSUM properties.

- **[Page54]** Page, E. S. (1954). *Continuous Inspection Schemes.*
  Biometrika, 41(1/2), 100–115.
  — the original CUSUM construction; the regime-drift detector is a
  two-sided variant.

## Sizing

- **[Kelly56]** Kelly, J. L. (1956). *A new interpretation of information
  rate.* Bell System Technical Journal, 35(4), 917–926.
  — full-Kelly fraction `f* = p/a - q/b`. The desk uses *quarter-Kelly*,
  not full, because (a) win rate and R are estimated with finite-sample
  error and (b) full-Kelly maximises growth in the limit but tolerates
  drawdowns most operators cannot psychologically hold.

- **[MacLean-Thorp-Ziemba10]** MacLean, L. C., Thorp, E. O., & Ziemba,
  W. T. (eds.) (2010). *The Kelly Capital Growth Investment Criterion.*
  World Scientific.
  — fractional Kelly under parameter uncertainty; the standard reference
  for why a quarter is conservative-but-not-pathological.

## Empirical earnings results

- **[CBOE-72]** CBOE 10-year S&P 500 earnings sample (cited
  second-hand via several vendor write-ups in 2023–2024). Realized
  post-earnings move was *smaller* than the straddle-implied move in
  ~72% of single-name earnings events. Labelled `[gray]` until we
  obtain the CBOE primary or reproduce the number on our own ledger.
  Operational use: anchor the long-premium bear quantitatively, not
  just structurally.

- **[BTZ09]** Bollerslev, T., Tauchen, G., & Zhou, H. (2009). *Expected
  Stock Returns and Variance Risk Premia.* Review of Financial Studies,
  22(11), 4463–4492.
  — index-level VRP predicts quarterly equity returns; combined with
  P/E it explains > 25% of variance. Single-name VRP is real but
  smaller and noisier. Anchors the "VRP is heaviest cross-sectionally
  on the index, not on any single name" qualifier.

- **[CW10]** Cremers, M., & Weinbaum, D. (2010). *Deviations from
  Put-Call Parity and Stock Return Predictability.* Journal of
  Financial and Quantitative Analysis, 45(2), 335–367.
  — volatility spread (call IV minus put IV at matched strikes)
  predicts stock returns by ~64–66 bps/month. Not in code yet; the
  hook would be the snapshot pipeline if it captures OTM skew.

- **[BB68]** Ball, R., & Brown, P. (1968). *An Empirical Evaluation of
  Accounting Income Numbers.* Journal of Accounting Research, 6(2),
  159–178.
  — original PEAD identification.

- **[BT89]** Bernard, V. L., & Thomas, J. K. (1989). *Post-Earnings-
  Announcement Drift: Delayed Price Response or Risk Premium?*
  Journal of Accounting Research, 27, 1–36.
  — multi-decade replication; drift persists for 60+ trading days.
  Operational consequence: our 7–21 DTE window ends before PEAD plays
  out — PEAD is *not* our edge.

## Cross-sectional momentum

- **[JT93]** Jegadeesh, N., & Titman, S. (1993). *Returns to Buying
  Winners and Selling Losers: Implications for Stock Market Efficiency.*
  Journal of Finance, 48(1), 65–91.
  — intermediate-horizon winners tend to keep winning. Operational
  consequence: the conviction map rewards bullish trend/readiness
  alignment, but only when support/resistance and options structure do
  not contradict the chase.

## AI / semiconductor / data-center regime context

- **[SIA26]** Semiconductor Industry Association (2026). *Global Annual
  Semiconductor Sales Increase 25.6% to $791.7 Billion in 2025.*
  — industry-cycle context for why AI compute, memory, networking,
  equipment, and data-center infrastructure remain a real macro theme.
  This is not a trade signal; it is backdrop.

- **[WSTS25]** World Semiconductor Trade Statistics (Autumn 2025
  forecast). Global semiconductor market forecast for 2026.
  — forward industry-cycle context; used only as regime evidence, never
  as ticker-level permission.

- **[Gartner26]** Gartner (2026). Worldwide IT spending forecast with
  data-center systems spending above $650B and server spending driving
  growth.
  — data-center capex context for power, cooling, servers, networking,
  and accelerator supply-chain names.

- **[NVDA-FY26Q4]** NVIDIA (2026). Fourth-quarter fiscal 2026 financial
  results.
  — leader-level monetisation check for the AI infrastructure boom. The
  desk uses it as context for the basket, not as permission to chase any
  single name without local evidence.

## Behavioural anchors

- **[SS85]** Shefrin, H., & Statman, M. (1985). *The Disposition to
  Sell Winners Too Early and Ride Losers Too Long: Theory and
  Evidence.* Journal of Finance, 40(3), 777–790.
  — the disposition effect. Four drivers: loss aversion, mental
  accounting, regret avoidance, self-control. The reason the audit
  forces *pre-committed* falsification triggers instead of "we'll see
  in the moment."

## Sizing — empirical follow-ups to Kelly

- **[RT92]** Rotando, L. M., & Thorp, E. O. (1992). *The Kelly
  Criterion and the Stock Market.* American Mathematical Monthly,
  99(10), 922–931.
  — half-Kelly captures ~75% of full-Kelly compound growth at
  ~half the maximum drawdown. Quarter-Kelly captures ~50% of growth
  with much shallower drawdowns. Empirical anchor for our
  quarter-Kelly cap under estimation error.

## Backtest hygiene

- **[LdP-DSR]** Bailey, D. H., & López de Prado, M. (2014). *The
  Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest
  Overfitting and Non-Normality.* Journal of Portfolio Management,
  40(5), 94–107.
  — the Sharpe ratio reported on a strategy *selected* after many
  trials is biased upward. The Deflated Sharpe Ratio corrects for
  selection bias under multiple testing. Together with the PBO
  (Probability of Backtest Overfitting) framework, this is the
  single most relevant trading-theory result for any system — like
  ours — that searches a slate of candidate cells.

- **[BBLZ17]** Bailey, D. H., Borwein, J., López de Prado, M., & Zhu,
  Q. J. (2017). *The Probability of Backtest Overfitting.* Journal
  of Computational Finance, 20(4), 39–69.
  — companion to DSR; gives the PBO estimator.

## Regime detection — Simons-flavour anchors

- **[HAM89]** Hamilton, J. D. (1989). *A New Approach to the Economic
  Analysis of Nonstationary Time Series and the Business Cycle.*
  Econometrica, 57(2), 357–384.
  — the canonical Hidden Markov / regime-switching model in
  economics. Renaissance famously applied speech-recognition HMMs to
  financial data; our two-sided CUSUM is in the same family
  (change-point detection on a univariate signal) but simpler.

- **[BER91]** Berlekamp, E. (interview record, Medallion 1989–1990).
  Berlekamp ran Medallion in 1989–1990 and posted 55.9% net by
  applying Kelly-style sizing to the firm's signals. The Kelly
  framework stayed at Renaissance after he returned to Berkeley.
  Sourced via Zuckerman (2019); `[gray]` until we cite a peer-reviewed
  paper directly attributable to Berlekamp's Renaissance work.

- **[ZUC19]** Zuckerman, G. (2019). *The Man Who Solved the Market:
  How Jim Simons Launched the Quant Revolution.* Portfolio.
  — the standard secondary source on Renaissance's history, culture,
  signal taxonomy, and decay-and-rebuild cadence. `[gray]` for any
  numeric claim that does not also have a peer-reviewed anchor;
  durable for the cultural primitives in [`SIMONS_PRINCIPLES.md`](SIMONS_PRINCIPLES.md).

## Theta / gamma / vega timing

- **[THETA-CURVE]** Industry replication of the non-linear theta
  curve: an option with ~60 DTE loses time value relatively slowly; in
  the final 30 days the decay rate is roughly 3–5× the 60-DTE rate,
  with the final week accelerating further. `[gray]` — the curve is
  derivable directly from Black-Scholes (`[BS73]`) by taking ∂V/∂t,
  but the 3–5× multiplier is broker-education material rather than a
  peer-reviewed result. Operational use: our 7–21 DTE window puts a
  long-premium ticket squarely in the steepening part of the theta
  curve.

- **[VEGA-COLLAPSE]** Vega effectively collapses to zero the moment
  earnings releases — the implied vol that supported the option's
  price disappears. Conceptually identical to the IV-crush papers
  (`[DIAV12]`, `[ANDR18]`); cited here separately to anchor the
  *immediate* timing of the crush (overnight, single tick) rather
  than the multi-day post-event behaviour.

## Term-structure alternatives

- **[CAL-SPREAD]** Pre-earnings IV term structure typically shows
  steep backwardation: front-month ATM IV substantially above
  back-month ATM IV. A calendar spread — short the front, long the
  back — captures the front-month IV crush without taking the full
  long-premium VRP drag. This is broker/vendor material; the
  underlying math is straightforward Black-Scholes term structure.
  Operational use: when the auditor's bear case is dominated by the
  long-premium VRP drag and the operator has a vol view rather than
  a directional view, a calendar spread is the *typed* alternative
  the audit should name explicitly.

## Multi-position sizing

- **[THORP-VEC]** Thorp's vector / portfolio Kelly extension —
  Princeton-Newport Partners ran ~100 simultaneous bets at any time,
  ~20% annualised over 28 years. Sized correctly under joint
  covariance, not as independent Kellys summed. The single most
  important *aggregate* sizing result: when bets correlate, treating
  them as independent overstates the total optimal fraction. Source:
  Thorp (1975), *Portfolio Choice and the Kelly Criterion*. The
  desk's quarter-Kelly cap is per-ticket; correlation across tickets
  is bounded by the slate concentration governor, not by a vector
  Kelly solve. Future work: when paper evidence supports it, replace
  the global hard-cap-per-day with a vector-Kelly fraction that
  accounts for slate correlation.

## Why this matters

Every quantitative bear point and every falsification trigger in the
trade-conviction audit cites one of these tags. The point is not academic
window-dressing — the point is that when the desk says "long this
straddle is fighting the variance risk premium," there is a 22-year-old
peer-reviewed paper behind that statement, not a Discord post.

When a citation is missing for a claim, the claim is downgraded from
"theory" to "heuristic" in the audit output. Heuristics are allowed; they
are just labelled honestly.
