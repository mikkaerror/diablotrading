# Trading Discipline — Deep Dive Addendum

**Stage:** research-only
**Promotable:** False
**Authority change:** none
**Date:** 2026-06-22
**Builds on:** `docs/TRADING_DISCIPLINE_RESEARCH_2026-06-22.md`

The first research pass synthesized public studies. This addendum goes deeper
along four axes: (1) the desk's own evidence ledger, (2) primary academic
sources, (3) options-market microstructure mechanics retail traders typically
miss, and (4) specific application to the SNX and AZZ candidates in the
approval queue. The conclusion is uncomfortable: the desk's own data and the
external evidence converge to suggest both pending candidates are wealth-
depleting setups.

---

## Part 1 — The desk's own ledger says something the discipline doc didn't

Pulled and analyzed `data/inferno_expected_move_ledger.json` directly. The
top-line in the existing discipline doc is "96 observations, 31.25% beat
rate, -11.45pp realized-minus-implied." That summary hides the actual edge
shape, which is dramatically more informative.

### Finding 1: The entire long-vol edge is two tickers in one regime

Per-ticker decomposition of the 96 observations:

```
ticker    n    beats   beat%   meanR    sumR
DELL      11   11      100%    +4.26    +46.81
HPE       6    6       100%    +2.74    +16.43
MRVL      9    9       100%    +0.31    +2.76
ORCL      12   0         0%    -0.65    -7.80
CIEN      13   2        15%    -0.39    -5.06
AGX       11   0         0%    -0.92   -10.09
VNET      9    0         0%    -0.41    -3.71
PL        8    0         0%    -0.66    -5.28
ACN       8    0         0%    -0.10    -0.81
HPE       6    6       100%    +2.74   +16.43
KEYS      5    0         0%    -0.32    -1.62
```

DELL and HPE together (17 of 96 observations) account for +63.24R. The other
79 observations have a beat rate of 16.5% and mean outcome -0.418R, summing
to -33.04R. **The ledger's apparent positive expectancy (+0.315R per trade)
exists only because of DELL and HPE. Strip those two tickers and the
strategy loses an average of 42% of debit per trade** with a Z-score of -6.7
against the null hypothesis of zero edge — statistically extreme.

The DELL/HPE outliers are not a strategy; they are a regime. DELL realized
91.5% on a 13-15% implied move in multiple cohorts (sample: realized 91.5%
on implied 13.2%, on implied 14.1%, on 14.4%, on 14.6%, on 22.9%). HPE
realized 68.5% on implied 7-21%. These are 4-10× implied-move beats. They
occurred in a specific window when AI-data-center repricing was rolling
through the names. They are unrepeatable on demand.

The discipline doc's prescription — "long vol should be admitted only when
a written forecast explains why realized movement or IV expansion can
exceed the implied move + theta + slippage + alternatives" — is exactly
right. The strict reading is: the desk has never demonstrated that
forecasting skill on any ticker besides DELL and HPE in a specific regime.

### Finding 2: The strategy is decaying over time

Chronological cohorts of 24 observations each:

```
cohort     dates                    n    beats   beat%   meanR    sumR
1 (oldest) May 15 – Jun 5           24   20      83%    +2.02   +48.40
2          Jun 5  – Jun 13          24    8      33%    +0.17    +4.07
3          Jun 13 – Jun 18          24    2       8%    -0.58   -14.01
4 (newest) Jun 18                   24    0       0%    -0.34    -8.26
```

This is not a clean training-period effect — it's a steep decay. The most
recent 48 observations have a 4% beat rate. The model that generated cohort
1's 83% beat rate is no longer producing that edge in the same form. Either
the regime ended (most likely; the DELL/HPE move-windows are behind us), or
the screen is now finding lookalikes that lack the underlying catalyst that
drove the original moves.

In either case, the prior used to size the next trade is the recent cohort,
not the all-time average. The recent cohort is unambiguously negative-
expectancy.

### Finding 3: There's a narrow implied-move sweet spot

Bucketing all 96 observations by implied-move size:

```
implied move    n    beats   beat%   meanR    realized%
0-10%           3    2       67%    +0.34    23.9%
10-20%          40   21      52%    +0.95    29.7%   ← sweet spot
20-30%          34    7      21%    -0.28    17.0%
30-50%          7    0        0%    +0.13     8.8%
50-100%         2    0        0%    +1.21    12.0%
100%+           10   0        0%    -0.25    17.1%
```

Edge concentrates entirely in implied moves of 10-20%. Above that, the
implied move is over-priced relative to what underlyings actually realize.
The 100%+ implied-move bucket — 10 observations with 0% beat rate — is the
worst category by win rate; these are setups where the market is screaming
"event happening" and option premium has fully absorbed the expectation,
leaving no edge for the buyer.

This finding is consistent with the de Silva/Smith/So 2024 paper documenting
that retail traders concentrate purchases in high-expected-volatility names
and lose 10-14% on those setups specifically.

### Finding 4: PL in the fast-paper cohort exits tomorrow

The PL fast-paper LONG_STRANGLE position exits Monday 6/22. PL has 8 prior
observations in the long-vol ledger: 0 beats, -5.28R total, -0.66R per
trade. The ticker has never beaten its implied move in the desk's data. The
position is statistically likely to close as a loss; that's not a strategy
failure, it's the expected outcome on this name.

---

## Part 2 — Primary academic sources, in their own words

### Barber & Odean 2000: "Trading Is Hazardous to Your Wealth"

66,465 discount-brokerage households 1991-1996. The most active 20% of
traders earned 11.4% annualized net of costs; the market returned 17.9%.
That's a **6.5 percentage-point annual underperformance** for the most-
active retail cohort. Average household turnover was 75% per year.

The mechanism is not bad stock picking. The mechanism is transaction costs
on excessive trading. The implication for the desk: every trade has to
clear not just its directional edge but also the friction cost of executing.
Wide-bid-ask names compound this.

[Source: J. of Finance 55(2), 773-806](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00226)

### Odean 1998: "Are Investors Reluctant to Realize Their Losses?"

10,000 discount-brokerage accounts 1987-1993. Investors realized winners
1.5-2× more often than losers, even controlling for tax effects and
rebalancing. The disposition effect cost the average household ~4.4%
annually in foregone returns because the losers they held kept losing.

The implication for the desk: the no-averaging-down rule (TRADE_MANAGEMENT
PLAYBOOK §5.4 shipped today in commit d6944e2) covers half of this. The
other half is "don't close winners early just to bank the gain." For Lane A
debit ladders especially, the asymmetric payoff structure means winners
must be allowed to run; closing all winners at +50% capture wipes out the
tail that compensates for the 60% loss rate.

[Source: J. of Finance 53(5), 1775-1798](https://faculty.haas.berkeley.edu/odean/papers%20current%20versions/areinvestorsreluctant.pdf)

### Carr & Wu 2009: "Variance Risk Premiums"

Across S&P 500, S&P 100, Dow, Nasdaq 100, and major individual stocks, the
variance risk premium (the gap between option-implied variance and
subsequently realized variance) is on average significantly negative. That
is: option sellers are compensated for bearing volatility risk.

This is the foundational empirical justification for premium-selling
strategies (credit spreads, iron condors, the short side of the wheel).
The premium is real, persistent, and statistically significant.

But — critical caveat — the VRP is documented on broad indices and
liquid single names. **It does NOT prove that every single-name credit
spread has positive expectancy.** And the premium-selling P&L profile is
"frequent small wins, occasional large losses." Without proper sizing and
exit discipline, the tail event eats years of accumulated wins.

[Source: Rev. of Financial Studies 22(3), 1311-1341](https://www.researchgate.net/publication/24045465_Variance_Risk_Premiums)

### MacLean, Thorp & Ziemba 2011: "Kelly Capital Growth Investment Criterion"

The Kelly criterion maximizes long-run log growth ONLY when the
probability estimates feeding it are correct. With estimation error:

- A 10% error in expected returns can produce 50% over-betting under
  full-Kelly.
- Fractional Kelly (½K or ¼K) sacrifices ~25% of growth rate but reduces
  drawdown variance by ~75% and dramatically reduces ruin risk under
  uncertainty.
- "Fractional Kelly with full information is equivalent to full Kelly
  with shrinkage estimators" — i.e., shrink your edge estimate toward
  zero when you don't have a reliable sample.

For the Inferno desk at 1 closed outcome of 30 required, the credible edge
estimate is "unknown." Any Kelly-derived sizing is operating on a shrinkage
prior that is mostly zero. The discipline doc's "the desk should not
activate Kelly from one scored outcome" is consistent.

[Source: Long-Term Capital Growth — MacLean/Thorp/Ziemba](https://www.stat.berkeley.edu/~aldous/157/Papers/Good_Bad_Kelly.pdf)

### de Silva, Smith & So 2024: "Losing is Optional"

Most relevant to the Inferno desk. Documents that retail options traders
lose **5-9% on average per options trade, and 10-14% on options purchased
before high-expected-volatility earnings announcements**.

The mechanism is three-fold:
1. Retail overpays for options relative to subsequently realized vol
2. Retail incurs bid-ask spreads averaging 12.6% (Bryzgalova et al. 2023)
3. Retail responds sluggishly to announcements, missing the IV-crush
   window

SNX has 4 days to earnings. Buying a debit vertical here is precisely the
trade the de Silva paper documents as the worst-performing retail behavior.

[Source: Stanford GSB / MIT Sloan working paper, Jan 2025](https://www.timdesilva.me/files/papers/losing_optional.pdf)

---

## Part 3 — Microstructure: what kills long-vol retail trades

These mechanics are not in the playbook because they sit one level deeper
than directional thesis. They explain why directionally-correct retail
trades still lose money.

### IV crush after earnings: 30-60% magnitude

Front-month implied volatility on large-cap equities commonly drops
**30-60% in a single session after earnings**. The ATM straddle that cost
$8 the day before can be worth $4 the next day even if the stock moved 5%,
because the volatility contraction destroyed more value than the directional
delta gain created.

This is a feature of buying options before earnings, not a bug. The market
is pricing in the event-driven vol; once the event is resolved, the vol
collapses on a predictable schedule. The buyer is paying for an event-
window IV bump that mechanically deflates by morning.

For the desk: any long-vol position held through an earnings print needs
the realized move to substantially exceed the implied move (the 10-20%
implied-move sweet spot from the ledger applies). At the higher implied-
move buckets (30%+), the IV crush is large enough that even directionally
correct trades lose.

### Dealer gamma exposure (GEX): the hidden flow

Market-makers carry an aggregate gamma exposure across all options they
have sold. They hedge it. Their hedging flow moves the underlying.

- **Positive net GEX:** dealers are long gamma. They sell into rallies and
  buy into dips to stay delta-neutral. The effect: range-bound, pinning
  behavior around large-OI strikes.
- **Negative net GEX:** dealers are short gamma. They buy into rallies
  and sell into dips. The effect: trend amplification, volatility
  expansion.

Retail buying calls into earnings shifts dealer GEX more negative (dealers
sold the calls; their delta hedging accelerates the underlying move). Post-
earnings, the calls expire OTM and dealer gamma collapses back to baseline.
The retail buyer rode a wave they helped create but didn't profit from.

For the desk's Vertical Call setups on SNX and AZZ: both names will see
dealer gamma flows around the strikes. We can't see those flows directly
from Schwab data, so we're trading blind to the largest single source of
intraday price action on event days.

[Source: SpotGamma GEX education](https://spotgamma.com/gamma-exposure-gex/)

### Vanna and charm: the path-dependent exposure

- **Vanna:** rate of change of delta with respect to IV. A long-call
  position has positive vanna — as IV rises, delta rises (you want IV up).
  Conversely, if IV falls (IV crush), delta falls. This is the second-
  order term that drives the value collapse.
- **Charm:** rate of change of delta with respect to time. As expiration
  approaches, ITM call delta migrates toward 1 and OTM call delta
  migrates toward 0. Holding a debit spread close to expiration produces
  delta that mechanically erodes if the stock doesn't move.

For the desk: this is why the 21 DTE review trigger (revised BACKLOG #10)
matters. Past 21 DTE, the charm-driven delta erosion accelerates and the
trader is increasingly betting on a directional move *in the last few
days*, against the worst time-decay profile of the option lifecycle.

---

## Part 4 — SNX and AZZ tomorrow: what the data actually says

This is the operationalization. The discipline doc's prescription, applied
to the actual pending decisions.

### SNX

From `data/inferno_strike_plan.json`:

```
ticker:                   SNX
current underlying price: $285.05
strike plan built at:     $233.90  ← 21.9% stale
days to earnings:         4
strategy:                 CALL_DEBIT_SPREAD (Vertical Call)
expiration:               2026-07-17
max loss:                 $660  (41% of $1,599 NLV)
reward/risk:              0.515  (just above the 0.5 minimum)
ATM bid-ask spread:       78.43%  ← "untradeable"
ATM liquidity score:      11 / 100
quote quality:            29 / 100 = "poor"
implied move:             3.27%
distance to resistance:   2.09%  ← almost at the lid
trend:                    Neutral
alignment:                Fragile (38.1 / 100)
strength:                 Lagging (33.74 / 100)
```

Multi-axis fail. Pulling the threads:

1. **Stale strike plan.** The plan was built when SNX was at $234. The
   stock is now at $285 — a 22% move that already happened. The strike
   selection and the implied-move math are calibrated to a stock that no
   longer exists. The strike plan's own staleness threshold
   (`maxUnderlyingSourceDivergencePct: 5.0`) is exceeded by 4.4× and the
   system should have flagged this.

2. **ATM spread is 78% wide.** The option's mid-price is somewhere
   between bid and ask, but the spread is so wide that any execution
   takes 30-40% of the option's value as friction before the trade has
   started. The Bryzgalova 2023 paper documents 12.6% average retail
   bid-ask. SNX's ATM spread is 6× that.

3. **Implied move 3.27% on a name 2.09% from resistance.** Even if the
   trade works directionally, there's almost no room before hitting
   resistance. The realized-move-needs-to-exceed-implied math is
   working against us before we enter.

4. **Max loss $660 = 41% of NLV.** Outside any sane sizing protocol. The
   formula recommends $25. The config caps at $500. This trade exceeds
   even the lax config cap.

5. **4 DTE to earnings.** Buying long vol 4 days from an event is exactly
   the trade de Silva/Smith/So documents as the worst-performing retail
   behavior (5-9% average loss, 10-14% on high-volatility earnings).

The desk's own ledger doesn't have SNX history. The closest comparables in
the data are ORCL (similar large-cap tech, 12 trades, 0/12 beat rate,
-7.80R) and ACN (similar services exposure, 8 trades, 0/8 beat rate,
-0.81R).

**Recommendation: reject.** Not because SNX is a bad stock — because this
specific trade structure on this specific data has every failure mode the
research identifies. If you want exposure to SNX, the cleaner expression is
shares with a stop, or wait for post-earnings IV crush and revisit.

### AZZ

From `data/inferno_strike_plan.json`:

```
ticker:                   AZZ
current underlying price: $153.04
strike plan built at:     $145.87  ← 4.9% stale (within tolerance)
days to earnings:         17
strategy:                 CALL_DEBIT_SPREAD (Vertical Call)
max loss:                 $730  (46% of $1,599 NLV)
reward/risk:              0.370  ← BELOW the 0.5 minimum
ATM bid-ask spread:       149.82%  ← "untradeable"
ATM liquidity score:      5 / 100  ← worse than SNX
quote quality:            27 / 100 = "poor"
quality flags:            no-liquid-contracts, wide-atm-spread,
                          thin-atm-liquidity
implied move:             2.70%
distance to resistance:   2.90%
trend:                    Bullish
alignment:                Developing (52.5 / 100)
strength:                 Neutral (48.57 / 100)
```

AZZ is worse than SNX on the things that matter:

1. **Reward/risk 0.37 is BELOW the desk's own 0.5 minimum.** This is
   `debitSpreadRewardRisk: 0.3699, minDebitSpreadRewardRisk: 0.5`. The
   trade should not have been promoted to the approval queue. There's
   either a bug in the gate, or the threshold was relaxed somewhere.
   Either way, this is a structural fail of the desk's own
   pre-commitment.

2. **ATM spread is 150% wide.** "No liquid contracts" flag. Executing
   this trade means accepting that the immediate mark-to-market will
   be ~50-60% underwater purely from bid-ask, before any directional
   move.

3. **Implied move 2.70% on a name 2.90% from resistance.** Even less room
   than SNX. The math says: this trade needs an unlikely upside spike to
   matter, in a window where you're paying enormous friction to enter.

4. **Max loss $730 = 46% of NLV.** Worse than SNX on sizing.

5. **17 DTE to earnings.** Outside the 4-day "buying into earnings"
   window but inside the 14-21 DTE charm-accelerating zone, with low
   implied move suggesting the market doesn't expect the earnings to move
   the stock much.

The desk's ledger doesn't have AZZ history. AZZ is small-cap industrial
infrastructure (transmission services). Closest comparable: AGX (also
industrial-services adjacent, 11 observations, 0% beat rate, -10.09R).

**Recommendation: reject.** This trade has a sub-minimum reward/risk ratio.
That alone is binding — the desk's own discipline says don't take it.

### What both rejections look like in `today.sh` tomorrow

```
SNX  CALL_DEBIT_SPREAD  | risk up to $660  | reward 0.52R  | 4d earnings
    paper-trade this? n
    -> rejected SNX

AZZ  CALL_DEBIT_SPREAD  | risk up to $730  | reward 0.37R  | 17d earnings
    paper-trade this? n
    -> rejected AZZ
```

Rejection is not "missing out." Rejection is preserving capital for the
next setup. The 30-outcome promotion gate accrues evidence in both
directions — a rejection that turns out to have been a winner is data; a
loss avoided is data; both update the prior.

---

## Part 5 — What this addendum changes about the strategy stance

The first-pass discipline doc said "long-vol around earnings has
historically negative expectancy at retail per SSRN study." This addendum
goes further:

**The desk's own evidence shows the same thing, but with structure:**

- All-time long-vol expectancy excluding DELL/HPE: -0.42R per trade
- Recent 48-trade cohort expectancy: -0.46R per trade
- 0% beat rate when implied move > 30%
- Sweet-spot beat rate (10-20% implied): 52%, +0.95R per trade
- PL specifically: 0/8 historical beat rate

**Combined with primary literature:**
- Barber & Odean: most-active retail underperforms by 6.5pp/year
- Odean disposition: 1.5-2× more likely to sell winners than losers
- Carr & Wu VRP: premium-selling has structural compensation; premium-
  buying has structural disadvantage on broad indices
- de Silva/Smith/So: 5-9% retail options loss on average, 10-14% on
  high-vol earnings names
- MacLean/Thorp/Ziemba Kelly: at 1 closed outcome, sizing decisions
  should shrink to zero

**Combined with microstructure:**
- 30-60% IV crush after earnings on large-cap equities
- ATM spreads on SNX (78%) and AZZ (150%) are 6-12× the retail average
- Dealer gamma flows that retail can't see drive intraday action
- Charm acceleration past 21 DTE makes hold-to-expiration costly

The composite prescription is sharper than the first-pass doc:

1. **No new long-vol entries above 20% implied move.** The desk's own
   ledger says these never beat. Hard filter.
2. **No long-vol entries when ATM spread > 30%.** Friction eats edge
   before the trade starts.
3. **No long-vol entries above 25% of NLV max loss.** Even with the
   config cap at $500, both pending candidates are $660-$730. Both
   should be auto-rejected on sizing.
4. **No long-vol entries within 7 days of earnings unless the implied
   move is in the 10-20% sweet spot.** SNX has implied 3.27% — outside
   the sweet spot in the wrong direction (too quiet to support the
   debit).
5. **Reject any trade below the desk's own reward/risk minimum.** AZZ at
   0.37 R/R should not have been queued.

---

## Part 6 — Honest framing about ambition

The desk's stated ambition is 10%/month over a year. The math of that is
3.14× in 12 months. The research is consistent:

- Top 1.6% of day traders are profitable in a given year (Barber 2013)
- ~9% of retail F&O traders are profitable in a fiscal year (Indian
  regulator data)
- 89% of retail options traders lose money
- Average retail option trade returns -5 to -9% net of friction
- Earnings-window retail option trades return -10 to -14% on average

Sustained 10%/month would put you in the **0.1-0.3% tail** of retail
options traders. It's not impossible. It's also not the base case from
any data we have.

The right interpretation of the ambition is not "size like 10%/month is
achievable." It's "the only path to that tail is process discipline that
exceeds 99% of retail." Which means: every decision should be on the
side of survival and evidence quality, not on the side of activity or
"let's go."

The math compounds either way. At the desk's current NLV ($1,599):
- 10%/month for 12 months → $5,020 (3.14×)
- 3%/month for 12 months → $2,278 (1.42×)
- 1%/month for 12 months → $1,803 (1.13×)
- -2%/month for 12 months → $1,253 (0.78×)

The gap between "3%/month sustained" and "10%/month sustained" is the
gap between a great year and a generational year. The gap between "1%
sustained" and "0% sustained" is what most retail traders actually live.
Slow, compounding, survival-first is the path that hits any of these.
Going for the tail is what destroys the account.

---

## Sources

**Desk evidence (primary):**
- `data/inferno_expected_move_ledger.json` (96 observations, queried
  2026-06-22)
- `data/inferno_strike_plan.json` (SNX + AZZ items, queried 2026-06-22)
- `data/inferno_approval_queue.json` (pending decisions)
- `data/inferno_fast_paper_ledger.json` (PL/GOOG/SHLS/SPXC exit-eligible
  today)

**Primary academic literature:**
- [Barber & Odean (2000): Trading Is Hazardous to Your Wealth](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00226)
- [Odean (1998): Are Investors Reluctant to Realize Their Losses?](https://faculty.haas.berkeley.edu/odean/papers%20current%20versions/areinvestorsreluctant.pdf)
- [Carr & Wu (2009): Variance Risk Premiums](https://www.researchgate.net/publication/24045465_Variance_Risk_Premiums)
- [MacLean, Thorp & Ziemba: The Kelly Capital Growth Investment Criterion](https://www.stat.berkeley.edu/~aldous/157/Papers/Good_Bad_Kelly.pdf)
- [de Silva, Smith & So (2024): Losing is Optional — Retail Option Trading and Expected Announcement Volatility](https://www.timdesilva.me/files/papers/losing_optional.pdf)
- [Bryzgalova, Pavlova & Sikorskaya (2023): Retail Trading in Options and the Rise of the Big Three Wholesalers](https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13285)

**Microstructure:**
- [SpotGamma: Gamma Exposure (GEX)](https://spotgamma.com/gamma-exposure-gex/)
- [SpotGamma: IV Crush Explained](https://support.spotgamma.com/hc/en-us/articles/15249330755859-IV-Crush-Explained-What-It-Is-When-It-Happens-and-How-to-Trade-It)
- [FlashAlpha: IV Crush Explained with Data](https://flashalpha.com/articles/iv-crush-explained-earnings-volatility-collapse)
- [VannaCharm: Dealer Gamma, Vanna, Charm Exposure Analysis](https://medium.com/option-screener/introducing-vannacharm-dealer-gamma-vanna-and-charm-exposure-analysis-f2f703d2de59)

**Retail mortality:**
- [MIT Sloan: Retail investors lose big in options markets](https://mitsloan.mit.edu/ideas-made-to-matter/retail-investors-lose-big-options-markets-research-shows)
- [Quantified Strategies: Options Trading Statistics](https://www.quantifiedstrategies.com/options-trading-statistics/)
- [Lambda Finance: What Percent Of Options Traders Are Profitable](https://www.lambdafin.com/articles/what-percent-of-options-traders-are-profitable)
