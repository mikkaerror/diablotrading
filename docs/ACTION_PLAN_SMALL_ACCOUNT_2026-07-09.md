# The Action Plan — everything this research concluded, on one page

- **Date:** 2026-07-09
- **Author:** Claude (research lane). Educational/decision-support, not personalized
  financial advice — I'm not a financial advisor. It distills what the investigation
  found into a concrete, runnable process. You decide what to act on.

## The whole conclusion, in three sentences

1. The pre-earnings options strategies the desk was built on don't have a
   capturable edge at a small account — buying premium is a documented loser,
   selling it is thin and costs more in data than it makes below ~$5–10k.
2. The one strategy that survived every test — literature, real-data backtest, and
   an overfitting stress test — is a **simple monthly trend rule on a broad index**,
   whose real value is *not losing half your money in a crash*.
3. At ~$1,100 the strategy barely matters to the dollar outcome; **adding to the
   account matters ~10× more than anything you trade inside it.**

## What to actually do (pick one of two)

### Option A — Simplest (recommended default)
Hold one low-cost, broad-market index fund (an S&P 500 or total-US-market ETF).
Add to it whenever you can. Ignore everything else. Over a full cycle this beats the
overwhelming majority of active retail traders, at zero effort and near-zero cost.
The catch you accept: you ride the full drawdown in a crash (e.g. −50% in 2008),
and recover with the market.

### Option B — Same, plus crash insurance (if a −50% drop would be catastrophic)
Add the trend overlay the backtests validated. Once a month (same day each month),
do this 15-minute check:

1. Look up the index ETF's price today, and its price **12 months ago**.
2. If **today's price is higher** than 12 months ago → be **in** the index next
   month (buy/hold it).
3. If **today's price is lower** than 12 months ago → be **out**: move to a
   short-term Treasury ETF or cash until the next monthly check.
4. Do nothing else until next month. No daily watching, no reacting to headlines.

That rule, on real data, turned the 2008 crash from −47% into roughly flat, held up
across every lookback from 6–12 months, and cost only a couple percent a year of
lagging during calm bull markets. It's insurance: a small premium in good years, a
large payout in a crash.

## Honest expectations (so you're not surprised)

- **It won't make you rich at $1,100.** A great year is ~$150. This controls risk
  and compounds slowly; it is not income.
- **Option B will sometimes annoy you** — it sells after a drop and buys back
  higher in sharp V-shaped dips (whipsaw). That's the cost of the crash protection.
  Follow the rule mechanically; don't second-guess it monthly.
- **Costs are the silent killer** — use a zero-commission broker and a fund with a
  tiny expense ratio. On a small account, fees matter more than cleverness.

## Where the real leverage is

Every branch of this research returned the same truth: at this size, the account
grows from **contributions**, not returns. $150/year from a great market year vs.
what consistent additions to the base can do — the additions win by an order of
magnitude. The most valuable financial "strategy" available to you right now is
boring: keep costs at zero, hold the index, protect against a crash if you want to,
and put your energy into growing the base rather than trading the ~$1,100.

## What to stop doing

- Stop paying (or considering paying) for options/earnings data at this size — the
  math says it loses in every scenario until the account is many times larger.
- Stop looking for a clever edge to make money fast on a tiny account. The research
  looked hard, from many angles, and the honest answer is that it isn't there — and
  you don't need it.

## Provenance (so you can trust this)

Backed by: `STRATEGY_DEEP_DIVE_2026-07-08`, `STRATEGY_ECONOMICS_SCALE_2026-07-09`,
`STRATEGY_LANDSCAPE_ACCESSIBLE_EDGES_2026-07-09`,
`DUAL_MOMENTUM_FAIR_TEST_2026-07-09`, `DUAL_MOMENTUM_ROBUSTNESS_2026-07-09`, and the
runnable engine `inferno_dual_momentum_backtest.py` with committed inputs in
`research/backtest_data/`. Not financial advice; educational synthesis of the
research you commissioned.
