# Strategy research — the accessible-edge landscape beyond pre-earnings vol

- **Date:** 2026-07-09
- **Author:** Claude (research lane). Research-only. Evidence-grounded survey; no
  authority/gate/risk change. This widens the search after the pre-earnings-vol
  branch was mapped (buy-side KILL; sell-side thin + unviable at this account).
- **Reproducibility note:** this is a strategy survey, not an automated desk gate.
  The follow-up dual-momentum backtest engine has unit coverage, but the real-data
  CSV behind the companion memos is not committed yet.

## The lens

For a ~$1,100 retail account under real pressure, a strategy is only worth
researching if it has: (a) a *documented* edge in the literature, (b) friction low
enough to survive small size, (c) cheap/free data, (d) a tail that won't wipe the
account. Options on single names failed (c is expensive, friction is 5–10%). So the
question becomes: what *directional*, low-friction edges clear that bar?

## The honesty haircut (applies to everything below)

McLean & Pontiff (*Does Academic Research Destroy Stock Return Predictability?*):
across 82 published anomalies, returns were **~26% lower out-of-sample and ~58%
lower (roughly half) post-publication.** Cause: data-mining bias + investors
learning and arbitraging the edge away. So **halve every headline number below**
before believing it. Many anomalies do retain *some* premium post-publication
because of limits to arbitrage — but assume the paper overstates by ~2x.

## The candidates, ranked for a small account

### 1. Trend-following / time-series & dual momentum (best fit)

- **Evidence:** Moskowitz-Ooi-Pedersen (2012) and Hurst-Ooi-Pedersen's *Century of
  Evidence*: a 12-month time-series-momentum rule across diversified markets earned
  **~11% excess/yr at roughly half the volatility of equities over 100+ years**,
  and *survives* transaction costs (net ~7.3% even after 2/20 fees). Antonacci's
  dual momentum (relative + absolute) tested at 17.4%/yr vs 8.9% for global equities
  with **max drawdown 22.7% vs 60%**.
- **Why it fits:** implementable in a handful of liquid ETFs, **near-zero friction**
  (a few bps), **free data** (prices only), monthly rebalance (near-passive), and
  it is as much a *drawdown-control overlay* as an edge — absolute momentum moves you
  to cash/bonds in downtrends, which is what halves the drawdowns.
- **Caveats:** the strongest evidence is on *diversified futures*; a few-ETF retail
  version has a lower Sharpe and real *whipsaw* drawdowns. Trend had a weak
  2011–2020 stretch. Dual momentum "works well at $5k+" (up to 5 ETFs) — at $1,100
  it's cramped but doable with fractional shares. After the 50% haircut, treat the
  realistic expectation as *modest single-digit annual excess with materially lower
  drawdowns*, not 17%.

### 2. Post-earnings-announcement drift (PEAD) — real but ironic

- **Evidence:** one of the oldest, most persistent anomalies (Ball-Brown 1968;
  Bernard-Thomas 1990: ~8–9%/quarter, ~35% annualized gross on surprise deciles).
  Directional: hold the direction of the earnings surprise for weeks.
- **The catch:** PEAD is *strongest exactly where trading is most expensive* — small,
  low-price, low-volume, wide-spread stocks. The friction that creates the drift
  also eats it, and it has decayed with algorithmic trading. On *liquid large-caps*
  (tradeable cheaply by retail) the drift is real but smaller; after the 50%
  haircut it's a thin directional edge, not 35%.
- **Fit:** directional stock trades (no options → far cheaper than the desk's
  approach), needs an earnings-surprise (SUE) feed, which is cheap/free-ish.
  Plausible as an *active* research thread, secondary to momentum.

### 3. Pre-earnings single-name vol (the desk's focus) — confirmed poor fit

Friction (5–10% option spreads) dominates any edge at small size; the sell-side
edge is thin, selection-dependent, shrinking, and — per the economics model — earns
less than its data costs below ~$5–10k. Documented here for completeness; not
recommended at this scale.

## The synthesis (honest)

- The **most defensible thing for a small, stressed account is a trend/dual-momentum
  ETF overlay** — not because it's a big edge (after the haircut it's modest), but
  because it is *cheap, robust across a century, near-passive, and drawdown-
  controlled.* It's a wealth-*compounding and capital-protection* tool, not an
  income engine.
- **PEAD** is the best *active* directional edge to research next if you want
  something with more engagement, with eyes open about the friction irony.
- **The binding constraint is still account size, not strategy discovery.** At
  $1,100, even a real 10–15% edge is ~$110–165/yr. Every accessible edge runs into
  the same arithmetic the economics model already established: modest percentages on
  a small base are modest dollars. The research keeps returning the same structural
  truth — *the edge that matters most right now is growing the base, not refining the
  signal.*

## What honest next research looks like (if we continue)

1. Backtest a concrete **dual-momentum ETF rule** (e.g. monthly: hold SPY/EFA
   whichever is stronger if its 12m return beats T-bills, else bonds/cash) on free
   price data — measure realistic net-of-cost return and drawdown at $1,100 with
   fractional shares. Cheap, honest, and directly actionable.
2. Only if there's appetite: a **liquid-universe PEAD** study using a free earnings
   calendar + SUE proxy, friction-charged, out-of-sample.

Both are $0, use free data, and — unlike the options work — could actually be
*run* at this account size. That is the honest frontier of "strategy research" from
here.

## Sources

- Hurst, Ooi, Pedersen — A Century of Evidence on Trend-Following Investing:
  https://fairmodel.econ.yale.edu/ec439/hurst.pdf
- Moskowitz, Ooi, Pedersen — Time Series Momentum (2012):
  https://www.sciencedirect.com/science/article/pii/S0304405X11002613
- Alpha Architect — Time-Series Momentum, the historical evidence:
  https://alphaarchitect.com/time-series-momentum-aka-trend-following-the-historical-evidence/
- Antonacci Dual Momentum (TuringTrader summary):
  https://www.turingtrader.com/portfolios/antonacci-dual-momentum/
- Bernard & Thomas / PEAD review (ScienceDirect):
  https://www.sciencedirect.com/science/article/pii/S2214635020303750
- McLean & Pontiff — Does Academic Research Destroy Stock Return Predictability?:
  https://www.fmg.ac.uk/sites/default/files/2020-08/Jeffrey-Pontiff.pdf
- Why Has PEAD Declined Over Time (Columbia/CEASA):
  https://business.columbia.edu/sites/default/files-efs/imce-uploads/CEASA/Events%20Page/PEAD_Declined_over_time.pdf
