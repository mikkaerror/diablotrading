# Sizing, Positioning, and Timing Research - 2026-06-19

**Stage:** research-only
**Authority:** unchanged; no order staging or broker submit
**Account source:** Schwab read-only sync for approved suffix 8499

## Decision

The next move is not to spend the allocator's full $299.96 long-term budget.
That budget is computed from available cash, while the portfolio policy is
defined as a percentage of total NLV. Current holdings must be subtracted
before new cash is called deployable.

At $1,599.17 NLV, the current account is:

| Sleeve | Current | Standard target | Evidence-adjusted target |
|---|---:|---:|---:|
| Shares | 62.48% | 50% | 50% |
| Live options | 0% | 25% | 0% |
| Cash | 37.52% | 25% | 50% |

The evidence-adjusted target moves the unearned options sleeve into cash. The
strategy lab has one scored loss and a zero risk cap, so the 25% options target
is a future capacity target, not capital that should be spent elsewhere today.

The account is therefore about $199.65 overweight shares and $199.66
underweight cash relative to the evidence-adjusted target.

## Sizing

### Live options

| Measure | Current value |
|---|---:|
| Evidence-adjusted live max loss | $0 |
| Research reference max loss per ticket | $25 |
| Research reference daily max loss | $75 |
| Promotion evidence | 1 of 30 |

The $25 floor is already 1.56% of NLV because one percent of the account is
only $15.99. A typical $149.98 defined-risk contract is 9.38% of NLV. Contract
size, not confidence, is the binding constraint.

Kelly sizing is only useful when the probability and payoff estimates are
credible. The original Kelly framework maximizes long-run logarithmic growth,
but estimation uncertainty can make an apparently optimal fraction badly
oversized. With one scored observation, the desk does not have an empirical
Kelly input. The correct fraction remains zero for live options.

Sources:

- [Kelly's original 1956 paper](https://www.princeton.edu/~wbialek/rome/refs/kelly_56.pdf)
- [Using the Kelly Criterion for Investing](https://webhomes.maths.ed.ac.uk/mckinnon/blackouts/StochOptFinanceAndEnergySpringer/Chap1_KellyZiemba.pdf)

### Shares

For a new name, the mechanically reasonable bands at current NLV are:

| Band | Dollars |
|---|---:|
| 5% starter | $79.96 |
| 7.5% starter ceiling | $119.94 |
| 10% review cap | $159.92 |

Those are position-size bands, not immediate buying capacity. Under the
Standard 50% share target, current new-share capacity is $0. Under a deliberate
65% aggressive equity ceiling, capacity is only about $40.22.

There are two ways to return to 50% shares without pretending cash is
available twice:

1. Trim about $199.65 of current equity into cash.
2. Add about $399.31 of new cash and leave it in cash.

No trim is required immediately. The practical rule is to freeze additions to
TE, IREN, HIVE, and CLSK while the existing thematic sleeve remains above the
target. New deposits can dilute the concentration without forcing a rushed
sale.

FINRA notes that multiple securities can still create concentration risk when
they share a sector or economic driver. That is the current issue: four
tickers, but substantial overlap in AI power, compute, and Bitcoin economics.

Sources:

- [FINRA concentration risk](https://www.finra.org/investors/insights/concentration-risk)
- [FINRA asset allocation and diversification](https://www.finra.org/investors/investing/investing-basics/asset-allocation-diversification)
- [Investor.gov rebalancing guidance](https://www.investor.gov/introduction-investing/getting-started/asset-allocation)
- [Investor.gov dollar-cost averaging](https://www.investor.gov/introduction-investing/investing-basics/glossary/dollar-cost-averaging)

## Positioning

### Existing positions

| Ticker | NLV weight | Positioning action |
|---|---:|---|
| TE | 23.39% | Hold thesis; freeze additions |
| IREN | 15.00% | Hold thesis; freeze additions |
| HIVE | 13.32% | Hold thesis; freeze additions |
| CLSK | 10.78% | Hold thesis; freeze additions |

This is not a sell instruction. It separates "continue holding" from "send
more capital." Existing ownership does not waive the fresh-add gate.

### CHKP

Check Point is the stronger quality candidate. Q1 2026 revenue increased 5%,
security-subscription revenue increased 11%, non-GAAP operating margin was
40%, and adjusted free cash flow was $457 million. These figures support the
quality thesis.

The timing data is conflicted, however. The tracker used $114.32 while Schwab's
June 18 close was $122.33, a 7.01% difference. At the Schwab close, CHKP was
about 4.09% above the tracker's support level. One share would be roughly 7.65%
of current NLV.

Conclusion: quality watchlist, not an immediate order. Reconcile Monday's
broker quote and support geometry first.

Source:

- [Check Point Q1 2026 results filed with the SEC](https://www.sec.gov/Archives/edgar/data/1015922/000117891326002310/a2635159.htm)

### DBX

Dropbox is cheaper and closer to technical support, but the fundamental
trade-off is less comfortable. Q1 revenue grew 0.8%, paying users declined
slightly, and unlevered free cash flow was $236.4 million. The company also
reported $2.68 billion of term-loan principal and higher interest expense.

Schwab's June 18 close was $25.97 versus the tracker's $25.72, only a 0.97%
difference. Four shares would cost about $103.88, or 6.50% of NLV.

Conclusion: the cleaner price setup, but the weaker balance-sheet and growth
profile. Keep it behind CHKP in quality ranking and require support to hold
after the June 25 macro releases.

Sources:

- [Dropbox Q1 2026 results](https://investors.dropbox.com/news-releases/news-release-details/dropbox-announces-first-quarter-2026-results)
- [Dropbox Q1 2026 Form 10-Q](https://www.sec.gov/Archives/edgar/data/1467623/000146762326000031/dbx-20260331.htm)

## Paper Positioning

The shadow long-vol sample currently beat its implied-move hurdle only 31.25%
of the time, with mean realized move edge of -11.45 percentage points. This is
not promotion evidence, but it is enough to reject another paper cohort
dominated by straddles and strangles.

For the next five-slot exploratory cohort:

- Maximum two long-vol structures.
- At least two defined-risk directional structures.
- One neutral or credit comparison when price and risk gates permit.
- Maximum one ticket per underlying.
- No more than two tickets sharing the same dominant sector or event date.

Options liquidity must be judged from bid/ask spread and depth, not ticker
fame. OIC notes that unusually wide spreads often reflect uncertainty in
hedging the underlying. Theta and gamma also accelerate near expiration, which
supports the desk's preference for later-session quotes and avoiding late,
short-dated entries.

Sources:

- [OIC options liquidity FAQ](https://www.optionseducation.org/referencelibrary/faq/general-information)
- [OIC pricing, Greeks, and market dynamics](https://www.optionseducation.org/news/march-office-hours-faqs-option-pricing-greeks-and-market-dynamics)

## Timing: June 22-26, 2026

### Monday, June 22

- Refresh Schwab account, equity prices, option chains, and support levels.
- Do not use the opening print for sizing.
- Close PL, GOOG, SHLS, and SPXC exploratory simulations using later-session
  bid/ask quotes.
- Refill the paper cohort only after those outcomes are recorded.
- No live options.

### Tuesday, June 23

- Review CHKP and DBX after one full post-holiday session.
- A share starter requires both total-account capacity and broker-confirmed
  support. Under the Standard target, current capacity is zero.

### Wednesday, June 24

- Preserve flexibility ahead of Thursday's release cluster.
- BEA schedules U.S. international-transactions data for 8:30 a.m. ET.
- EIA schedules the weekly petroleum report for 10:30 a.m. ET.

### Thursday, June 25

- BEA schedules first-quarter GDP, corporate profits, state GDP/personal
  income, and May personal income/outlays for 8:30 a.m. ET.
- Census schedules May durable goods for 8:30 a.m. ET.
- Wait at least 60 minutes after release before rerunning support, spread, and
  sizing checks. Rates-sensitive technology and high-beta compute names can
  reprice together.

### Friday, June 26

- Census schedules advance economic indicators for 8:30 a.m. ET.
- Add only if Thursday's repricing held support and the total-account sleeve
  still permits the position.

Official calendars:

- [BEA release schedule](https://www.bea.gov/news/schedule)
- [Census economic indicator schedule](https://www.census.gov/economic-indicators/calendar-listview.html)
- [EIA weekly petroleum schedule](https://www.eia.gov/petroleum/supply/weekly/schedule.php)
- [June 17, 2026 FOMC statement](https://www.federalreserve.gov/newsevents/pressreleases/monetary20260617a.htm)

## Action Order

1. Use total NLV rather than available cash as the allocation denominator.
2. Freeze additions to the current four-name theme; do not force an immediate
   trim.
3. Reconcile CHKP and DBX with Monday broker quotes.
4. Close and score the four exploratory simulations.
5. Refill paper evidence with a more balanced strategy mix.
6. Keep live option risk at $0.
7. Revisit share deployment after Thursday's macro repricing or after enough
   new cash arrives to restore the evidence-adjusted cash target.

The account does not need more activity. It needs every next dollar to improve
either evidence quality or portfolio independence.
