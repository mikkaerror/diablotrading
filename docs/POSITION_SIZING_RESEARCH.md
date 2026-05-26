# Position Sizing & Bankroll Allocation — Research Note

**Stage:** research-only, no authority changes
**Date:** 2026-05-25
**Scope:** The Inferno manual options desk specifically — 7-21 DTE earnings-driven trades, mix of LONG_STRADDLE / LONG_STRANGLE / CALL_DEBIT_SPREAD / PUT_CREDIT_SPREAD, currently $1,108 NLV with `MAX_SINGLE_TICKET_DOLLARS = $500` and an `inferno_capital_scaling.py` recommender pinned at 1% of NLV with a $25 floor and $2,000 ceiling.
**Question:** Does 1% per ticket actually make sense for *this* bankroll and *this* strategy, grounded in the literature rather than rule-of-thumb?

---

## TL;DR

1. **1% per ticket is conservative-correct as a *starting* point**, but the reasoning matters: it's not arbitrary, it's the band where risk-of-ruin stays below 1% under realistic options outcome distributions even when you have no proven edge.
2. **The current desk has zero proven edge** (0 closed scored outcomes against a 30-target gate). Under that condition, every serious source — Kelly's own formula, Sinclair, Tharp — says size *as small as the structural floor allows*. That's exactly what the scaling module does today.
3. **The 1% rule is wrong in a specific way once evidence accumulates**: it treats a 50%-win-rate defined-risk credit spread the same as a 38%-win-rate long-straddle, but the Kelly math says these should have very different sizes. The right next iteration is per-strategy-family sizing keyed off demonstrated win rate × payoff ratio.
4. **The daily cap (3× single-ticket = 3% NLV) is too loose for an earnings-driven desk**, because earnings-day positions are not independent — they share systematic vol-regime exposure. Correlation-aware daily caps would tighten this to ~2× during heavy earnings clustering.
5. **Below $2,500 NLV the formula structurally can't enforce 1%** (the $25 floor wins, effective % becomes ~1-2.5%). This is a real fact about minimum viable options trades, not a bug; the right operator response is "trade rarely while sub-$2.5k, accumulate evidence in the auto-paper lane, let NLV grow before scaling tickets."

---

## 1. The math foundations

### 1.1 Kelly Criterion (Kelly, 1956)

For a binary outcome bet with win probability `p`, loss probability `q = 1 − p`, and payoff ratio `b` (win-size ÷ loss-size), the growth-optimal fraction of bankroll to bet is:

```
f* = (b·p − q) / b
```

Full Kelly maximises the geometric growth rate. Two properties matter here:

- **f\* is extremely sensitive to estimates of p and b.** A 5-point overestimate of win rate can double the recommended size. In practice you don't know `p` and `b` precisely, especially with fewer than 50-100 closed trades. The literature is unanimous: estimation error is the primary practical limitation of Kelly.
- **Full Kelly produces 50-80% drawdowns** in realistic-variance applications. That's not academic — it's why nobody runs full Kelly with real money.

The convention is to use **half-Kelly** (multiply f\* by 0.5) or **quarter-Kelly** (×0.25). Half-Kelly retains roughly 75% of the maximum compound growth rate of full Kelly while cutting volatility in half. That's an exceptionally favourable trade-off, especially given parameter uncertainty.

### 1.2 Fixed Fractional (Vince's "Optimal f")

When you can't estimate Kelly cleanly, the fallback is to risk a fixed percentage of *current* equity per trade. Risk here means **maximum loss**, not premium paid — for a defined-risk options trade these are the same; for an undefined-risk trade you'd have to define a synthetic stop.

Industry conventions, repeatedly cited across the literature:

| Audience | Risk-per-trade band |
|---|---|
| Beginners / unproven edge | 0.5% – 1.0% |
| Active retail with proven edge | 1.0% – 2.0% |
| Professional / prop | 0.25% – 1.0% (lower because turnover is higher) |
| Anything above 3% | Considered reckless in modern literature |

The reason these numbers cluster between 0.5% and 2% isn't tradition — it's that **at 1% per trade, ten consecutive losses produces a 9.6% drawdown** (multiplicative: `1 − 0.99^10`). At 2% per trade, ten consecutive losses is 18.3%. At 5%, it's 40%. Above 40% drawdown the psychological cost is severe and the gain required to recover (1 / (1 − DD) − 1) starts to exceed what the strategy can realistically produce.

### 1.3 Tharp R-multiples (Van Tharp, *Trade Your Way to Financial Freedom*)

Tharp's framing: define `R` as your dollar risk per trade. Express all outcomes as multiples of R. Build a histogram of `R-multiples` from your closed trades. A "good" trading system has expectancy `E[R]` between +0.4 and +1.0 over a sample of 100+ trades.

This frame matters here because **it requires evidence to even know if the strategy works.** Until you have an R-distribution, the responsible move is to size R as small as your structural minimum allows. Once you have an R-distribution, you can solve for an `f` that keeps risk-of-ruin acceptable for that specific distribution.

---

## 2. What the literature says about options specifically

### 2.1 Sinclair (*Volatility Trading*, 2013; *Positional Option Trading*, 2020)

Sinclair is the most rigorous practitioner-author on the option-edge side. Two ideas matter here:

- **The edge in options comes from the volatility risk premium** — the spread between implied and realised volatility. Long-vol strategies (straddles, strangles) are statistically negative-expectancy *on average* because IV > RV most of the time. To make a long-vol strategy positive-expectancy, you need a *selection* edge: knowing when IV is mispriced low relative to forthcoming RV.
- **Position sizing should be derived from edge, not from rule-of-thumb.** Sinclair argues that if you can't quantify the edge, you shouldn't trade size. His advice for unproven strategies: trade the smallest size your platform supports until enough data accumulates to estimate edge.

### 2.2 Empirical results on long straddles around earnings

The most-cited public backtest (Kris Abdelmessih, "Straddles, Volatility, and Win Rates"; also corroborated by Option Alpha's long-straddle earnings backtests): **long straddles bought into earnings on liquid US names produce around a 40% win rate and a negative average return** when entered uniformly. AAPL specifically: 41.38% win rate, **−1.31% average return per cycle over 10 years**.

Translation: a naive "buy a straddle into every earnings" strategy is a slow bleed. The volatility crush after the announcement systematically destroys more option value than the realised move creates. **The strategy only becomes positive-expectancy under selection** — picking the subset of earnings where IV is materially mispriced low relative to the eventual realised move.

This is critical for the Inferno desk because:

1. The strategy generator's job is exactly that selection. The `inferno_strategy_alternative_scorer` and the cap-aware-strangle variant system exist to find the sub-slice of the slate where the long-vol setup has selection edge.
2. **Until the desk has 30+ closed scored outcomes**, it cannot know whether its selection actually clears the volatility risk premium. The base-rate prior is *negative* expectancy. Kelly under negative-expectancy = zero (don't trade) or negative (take the other side).

### 2.3 Defined-risk premium-selling strategies (PUT_CREDIT_SPREAD, IRON_CONDOR)

Different statistical profile from long-vol. The empirical literature on premium selling shows:

- Win rates typically **60–75%** depending on how far OTM the short strike is.
- Loss-to-win ratio inverts: max loss is usually 2-5× max gain.
- Average expectancy is **positive but small** because you're harvesting the volatility risk premium directly.
- Tail risk is real: a 5-sigma move on a credit spread is a full max-loss event, and credit-spread tails fatter than the normal distribution would suggest.

This means premium-selling strategies justify **larger position sizes than long-vol on the same bankroll**, because the win rate is higher and the expected value is positive. A 65%-win-rate / 0.5-payoff credit spread has Kelly f\* ≈ 30%; half-Kelly ≈ 15%. Apply the standard "uncertainty discount" of further halving and you arrive at **roughly 7-8% per ticket as the upper bound**, well above the 1% rule.

So the same 1% cap is **slightly too conservative for premium-selling** and **possibly aggressive for long-vol** — but the practical answer isn't "trade premium-selling at 7%," it's "1% is fine as a starting cap; differentiate per-strategy-family later once evidence exists."

### 2.4 Earnings-day correlation

Earnings trades are not statistically independent. On any given earnings day, all positions share:

- Market-regime vol exposure (the VIX backdrop affects every IV).
- Sector exposure if the slate clusters (a typical post-earnings season has correlated banks, then correlated tech, etc).
- Macroeconomic announcement risk (CPI / FOMC days).

The "3 trades × 1% = 3% of NLV at risk per day" calculation **assumes independence**. With realistic correlation (call it 0.4), the effective single-day VaR is closer to 2.0% per cycle, not 3%. The literature on correlated bets in fixed-fractional sizing (Vince Chapter 9) recommends a "correlation haircut" of roughly `√(1 + (n-1)·ρ) / √n` applied to the daily cap. For n=3, ρ=0.4: haircut ≈ 0.85, so the effective daily cap should be ~2.5% rather than 3%.

---

## 3. Where 1% sits on the spectrum for the Inferno desk

| Lens | What it says about 1% per ticket |
|---|---|
| **Kelly under no-edge prior** | Says 0% (don't trade). 1% with a $25 floor = "smallest viable size while evidence accumulates" — correct interpretation. |
| **Half-Kelly under optimistic priors** (50% win rate, 2:1 payoff) | f\* = 25%, half = 12.5%, quarter = 6.25%. 1% is well below this — leaves growth on the table *if* the optimistic priors are real. They're unproven. |
| **Half-Kelly under realistic priors** (40% win rate, 1.5:1 payoff) | f\* ≈ 0%, hovering negative. 1% is actually larger than the math justifies for naive long-vol. |
| **Fixed-fractional convention** | 1% is the conservative end of the standard 1-2% band. Defensible to any reviewer. |
| **Risk-of-ruin at $1,108 NLV** | At 1% per trade and a (pessimistic) 40% win rate with 1:1 payoff, RoR over 100 trades is ~2%. At 2%, RoR climbs to 12%. At 5%, RoR is essentially certain. 1% is the conservative band. |
| **Drawdown tolerance** | At 1% per trade, ten straight losses = 9.6% drawdown. At 2%, 18.3%. Most retail traders psychologically tolerate 10-15% drawdown before breaking discipline. |
| **Industry consensus** | Median guidance across tastytrade, Option Alpha, professional prop training is **1-2% per trade for retail options**, **0.5-1% for unproven strategies**. The desk is exactly on that mark. |

**Verdict**: 1% is *correct-defensible* as the starting rule. It's slightly conservative for a proven edge and slightly too loose for naïve long-vol — but absent evidence, conservative is the right asymmetry. The number passes every smell test in the literature.

---

## 4. Where the current rule has real gaps

### 4.1 Strategy-blind sizing

Right now, `inferno_capital_scaling.py` applies the same `MAX_SINGLE_TICKET_DOLLARS` to a $500 long-straddle as it does to a $500 put-credit-spread. The math says these should have different caps once evidence exists. Specifically:

| Strategy family | Typical win rate | Typical payoff ratio | Half-Kelly under that prior |
|---|---|---|---|
| LONG_STRADDLE / LONG_STRANGLE | 38-45% | 1.3-1.8 | 0-3% |
| CALL_DEBIT_SPREAD / PUT_DEBIT_SPREAD | 40-50% | 1.0-1.5 | 0-4% |
| PUT_CREDIT_SPREAD / CALL_CREDIT_SPREAD | 60-75% | 0.3-0.7 | 6-15% |
| IRON_CONDOR | 65-80% | 0.2-0.5 | 4-12% |

The 1% blanket rule is the right place to *start* but the right place to *iterate to* is family-aware sizing keyed off the rolling-30-day evidence per family. The `inferno_paper_velocity` module and the strategy-attribution data already produce the per-family closed-outcome data needed to do this once the 30-outcome gate clears.

### 4.2 Edge-conditional sizing

The cleanest version of the above: instead of hard-coded per-family caps, compute the cap from the rolling empirical edge.

```
cap_per_family = min(
    MAX_SINGLE_TICKET_DOLLARS,            # the operator-pinned hard cap
    NLV × max(0, kelly_fraction × 0.5),   # half-Kelly from rolling outcomes
    ceiling,
)
```

Where `kelly_fraction` is computed each cycle from `outcomes_for_family[-30:]` (the same 30-outcome promotion window). This makes the system **self-adjust** as edge becomes visible: strategies with proven positive expectancy get larger caps; strategies still bleeding stay floored.

This is the natural follow-on artifact to `inferno_capital_scaling.py`. I'd call it `inferno_position_sizing.py` (or extend the existing module) and gate it behind the same promotion-target threshold the rest of the desk uses.

### 4.3 Correlation-aware daily cap

Current daily cap = `single × 3 = 3%` of NLV at 1% per ticket. The literature suggests this is too loose for earnings-clustered slates. The right fix is to apply a correlation haircut when the slate's positions share an earnings day, a sector, or an underlying macro event:

```
effective_daily_cap = daily_cap × correlation_haircut(slate)
correlation_haircut = √(1 + (n − 1) · ρ) / √n     # Vince Ch. 9
```

For a typical 3-ticket earnings day with ρ ≈ 0.4: haircut ≈ 0.85 → 2.55% effective daily exposure rather than 3%. For a 5-ticket FOMC-day slate with ρ ≈ 0.6: haircut ≈ 0.72 → 2.16% rather than 3.5%.

### 4.4 Drawdown-conditional cap

The current symmetric scaling already shrinks the cap as NLV falls (which professional risk frameworks recommend). What it doesn't do is **accelerate the shrinkage in drawdown**. The literature suggests a stepwise rule:

| Trailing drawdown from peak | Cap multiplier |
|---|---|
| < 10% | 1.0× (normal) |
| 10-20% | 0.5× (half-sized) |
| 20-30% | 0.25× (quarter) |
| > 30% | pause for review |

This is straightforward to bolt onto the scaling module as a peak-NLV tracker plus a stepped multiplier on the recommended cap.

### 4.5 Minimum-viable-trade floor honesty

Below ~$2,500 NLV the 1% rule cannot be enforced (the $25 structural floor wins). The honest operator message is: **"the desk is below the band where the formula works; you are choosing between not trading at all or trading at a tighter floor (≈2.3%)."** Currently the module reports this as `[at floor]` and `effectivePctOfNLV` 2.26% — which is the right disclosure. Once NLV crosses ~$2,500 the floor stops binding and the formula picks up cleanly.

---

## 5. Concrete refinements ranked by ROI

These are sequenced by leverage — biggest gain per unit of work first. None of them touch live trading authority; all of them stay research-only / promotable=False until clear ack.

1. **Per-family caps once 30 outcomes accrue.** Extend `inferno_capital_scaling.py` to read `inferno_paper_velocity` per-family rollups and emit a cap-per-family recommendation. Use half-Kelly on rolling-30 outcomes with the 1% blanket as a floor. *Leverage: turns a static cap into a self-adjusting one. Time: ~half a day. Blocked on: needing 30 outcomes per family.*

2. **Correlation-haircut on daily cap.** Add a `correlation_haircut(slate)` helper that looks at shared earnings dates, sectors, and macro events on the current slate and applies the Vince haircut. *Leverage: tightens daily exposure on actually-correlated slates. Time: ~2 hours. Not blocked on anything.*

3. **Stepped drawdown reduction.** Track peak NLV in the ack file; apply the stepped multiplier above. *Leverage: forces de-risking during drawdowns instead of letting fixed-% scaling do all the work. Time: ~1 hour. Not blocked.*

4. **R-multiple ledger.** Replace ad-hoc PnL tracking with an explicit `R = realized PnL / max loss at entry` field on every closed outcome. Plot the R-distribution after 30 outcomes. *Leverage: makes the Kelly inputs visible, enables (1) above. Time: 2-3 hours; ledger schema change. Worth doing soon.*

5. **Risk-of-ruin display.** One-liner in the scaling artifact: given current cap and current empirical win-rate / payoff (or priors when no data), what's the probability of ruin over the next 100 trades? *Leverage: keeps the operator honest about the real risk being taken. Time: 1 hour.*

---

## 6. The honest answer to "does 1% make sense"

Yes. For your bankroll and your strategy as it stands today, 1% per ticket with a $25 floor and $2,000 ceiling is the most defensible number in the literature.

It's conservative-correct because:

- You have **zero closed scored outcomes**, which under any rigorous framework (Kelly, Sinclair, Tharp) means you have no evidence the strategy is positive expectancy. Under that condition the right size is "as small as the structural floor allows."
- The base-rate empirical research on naive long-straddle-into-earnings is *negative* expectancy. Your strategy's edge over that base rate is unproven. 1% bets the smallest amount consistent with collecting evidence quickly enough to update.
- 1% × 10 losses = 9.6% drawdown, comfortably inside the discipline-preserving band.
- 1% matches the conservative end of every retail and professional convention.

What 1% is **not** is *optimal* — there is no optimal until evidence exists. Once you have 30 closed outcomes per strategy family, the right move is to let the per-family Kelly math adjust the cap upward for proven-edge families and keep it floored for unproven ones. That's the work item in §5(1).

For the smaller meta-question — "do I need to keep updating limits as the account grows?" — the answer the `inferno_capital_scaling.py` module already gives is no. Once you `accept` the formula, the cap auto-tracks NLV both up and down within ±20% drift, and only requires fresh ack on >25% drawdown or a formula-parameter change. The cap moves with the account.

---

## Sources

- Kelly, J. L. (1956). "A New Interpretation of Information Rate." *Bell System Technical Journal.* The original Kelly paper.
- Sinclair, E. (2013). *Volatility Trading.* 2nd ed. Wiley. Chapters on edge measurement and risk management.
- Sinclair, E. (2020). *Positional Option Trading: An Advanced Guide.* Wiley. Chapters on trade sizing and unknowable risks.
- Vince, R. (1990). *Portfolio Management Formulas.* Wiley. Optimal-f and the correlation haircut framework.
- Tharp, V. (2007). *Trade Your Way to Financial Freedom.* McGraw-Hill. R-multiple methodology.
- Abdelmessih, K. "Straddles, Volatility, and Win Rates." *Moontower.* https://moontowermeta.com/straddles-volatility-and-win-rates/
- Option Alpha. "Long Straddle Earnings Option Strategy Backtest Results." https://optionalpha.com/podcast/long-straddle-earnings-option-strategy
- Longbridge. "Options Position Sizing: Kelly Criterion Explained." https://longbridge.com/en/academy/options/blog/options-position-sizing-kelly-criterion-explained-100160
- Backtest Base. "Kelly Criterion Calculator | Free Trading Position Size Tool." https://www.backtestbase.com/education/how-much-risk-per-trade
- ACY. "How Much Should You Risk per Trade? (1%, 2%, or Less?)" https://acy.com/en/market-news/education/market-education-how-much-risk-per-trade-trading-compounding-growth-j-o-20250728-134034/
