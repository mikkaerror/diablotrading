# Research Notes

A running notebook of options-theory, trading-theory, and Renaissance /
Jim Simons material the desk is incorporating into the conviction audit
and the broader theory layer.

Each entry has the same structure:

> **[Topic]** — one-paragraph finding · primary source · what it means
> for *our* desk specifically · whether it landed in code (and where) or
> whether it stayed as theory.

Two rules govern this file:

1. Numbers and references stay verifiable. If a number is from a
   secondary source (blog, vendor) and we couldn't find a peer-reviewed
   primary, label it `[gray]` so a future session knows to upgrade or
   discard it.
2. Every entry ends with **What this means for our desk** — an explicit
   operational consequence. If we can't write one, the finding is
   interesting but not actionable yet, and we say so.

---

## 1. Options & earnings

### 1.1 Earnings IV crush — magnitude and frequency

**Finding.** Across a 10-year CBOE study of S&P 500 earnings events,
the realized post-earnings move was *smaller* than the straddle-implied
move in roughly 72% of cases. Implied volatility typically peaks the
day before earnings and crushes 30–50% in a single overnight session,
with the largest moves in biotech (binary catalysts) and the smallest
in utilities (predictable cash flows). The full picture is a gradual
2–3-week IV ramp, a sharp 2–3-day spike, then the overnight collapse.
Source: CBOE 10-yr S&P sample summarised across multiple vendor write-
ups; `[gray]` because the underlying CBOE white paper is not paywalled
but we cite it second-hand. Primary academic anchor:
[Diavatopoulos et al. (2012)](https://www.sciencedirect.com/science/article/abs/pii/S0378426611002901)
and [Andrade, Ekkayokkaya & Frijns (2018)](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/earnings-announcement-returns-of-the-loser-portfolio/AB1D38B8B45D6B58CC92E32C9DCC79B6).

**What this means for our desk.** The structural drag is *quantified*,
not just directional. A long earnings straddle that closes flat is
roughly the modal outcome, not the tail. The new
[`CBOE-72`](THEORY_REFERENCES.md) citation tag lets the auditor say
"~72% of S&P single-name earnings settled with realized < implied" out
loud, rather than the softer "long vol fights the variance risk premium."
Operational consequence: the auditor's bear for long premium is now
backed by a concrete frequency. We do *not* assert this number applies
to every single-name; biotech and small-cap distributions are
right-skewed. Future work: build `inferno_realized_vs_implied_ledger`
to track *our* sample's ratio and replace `[CBOE-72]` with our own.

### 1.2 Variance risk premium — single-name vs. index

**Finding.** [Bollerslev, Tauchen & Zhou (2009)](https://public.econ.duke.edu/~boller/Published_Papers/rfs_09.pdf)
show that the variance risk premium — the gap between option-implied
and realized variance — is a strong predictor of equity returns at the
quarterly horizon. Combined with the P/E ratio, it explains > 25% of
quarterly market-return variance. Index VRP is larger and more reliable
than single-name VRP; [Carr & Wu (2009)](https://academic.oup.com/rfs/article/22/3/1311/1593068)
document that single-name premia are real but smaller and noisier.

**What this means for our desk.** Two consequences. First, the VRP
drag the auditor cites is heaviest *cross-sectionally on the index* —
single-name straddles fight a real but more idiosyncratic headwind.
Second, the predictability of equity returns *from* VRP is at the
quarterly horizon, not the multi-day earnings horizon we trade — so we
do not claim VRP forecasts earnings outcomes for any one name. Both of
these qualifications are now baked into the long-premium bear text.

### 1.3 Volatility skew / risk reversal as a predictor

**Finding.** The volatility spread (call IV minus put IV at matched
strikes) predicts stock returns by ~64–66 bps/month per
[Cremers & Weinbaum (2010)](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/deviations-from-putcall-parity-and-stock-return-predictability/9E70D31E2F8FCFDFA6FA9D29A98F95FA).
Skew steepens before earnings, with OTM-put IV often elevated relative
to OTM-call IV. Risk-reversal sign and slope have modest predictive
power for next-month returns.

**What this means for our desk.** A skew check is on the roadmap but
not in code yet. The proper hook is the snapshot pipeline — if the
sheet captures skew (OTM put/call IV differential), the auditor can
add a disagreement rule: "trend is Bullish but risk reversal is
negative (puts bid up)." For now this stays in the research notes; we
do not invent a bear claim without the data to back it.

### 1.4 Post-earnings announcement drift (PEAD)

**Finding.** The drift after an earnings surprise is one of the most
robust anomalies in finance — [Ball & Brown (1968)](https://onlinelibrary.wiley.com/doi/10.1111/j.1475-679X.1968.tb00010.x)
discovered it; [Bernard & Thomas (1989)](https://www.jstor.org/stable/2491062)
documented it persisting for 60+ trading days post-event. Options
markets price *some* of the drift but do not fully discount it;
implied volatilities before and after earnings do not behave like a
pure risk-premium story.

**What this means for our desk.** Our trade window (DTE ≤ 21) ends
*before* the bulk of PEAD plays out. PEAD is not our edge — it is a
post-trade drift we are explicitly *not* capturing. The auditor
should make this honest: a long-straddle exit at the day-of-earnings
open captures the realized-vs-implied bet, *not* the multi-week drift.
Falsification trigger: do not roll a long-premium ticket into PEAD-
horizon hopes — that is changing the bet mid-trade.

---

## 2. Trading theory

### 2.1 Fractional Kelly under parameter uncertainty

**Finding.** [Thorp's "Understanding the Kelly Criterion"](https://rybn.org/halloffame/PDFS/2008_Understanding_Kelly_New.pdf)
and the empirical follow-up by Rotando & Thorp (1992) show that
half-Kelly captures ~75% of full-Kelly's compound growth at roughly
half the drawdown, and that in simulation, half-Kelly users had a 90%
probability of avoiding ruin under estimation-error conditions where
full-Kelly users had ~50%. Quarter-Kelly captures ~50% of growth with
much shallower drawdowns — the right answer when win rate and R are
both estimated, not known.

**What this means for our desk.** Quarter-Kelly (our current cap) is
in the "right answer" band for a desk with zero closed paper outcomes.
We do not promote to half-Kelly until evidence-strength rises out of
`no-evidence`. The auditor now cites Rotando & Thorp (1992) on the
quarter-Kelly choice so the rationale is sourced, not asserted.

### 2.2 Backtest overfitting and the deflated Sharpe ratio

**Finding.** [López de Prado & Bailey](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551)
show that the Sharpe ratio reported from a strategy *selected after
many trials* is biased upward; the Deflated Sharpe Ratio (DSR)
corrects for selection bias under multiple testing and non-Normal
returns. Without that correction, almost any backtest that searches
even a small parameter grid produces apparent edges that vanish out
of sample. The Probability of Backtest Overfitting (PBO) framework
makes this concrete: if you tested N parameter combinations, the
probability that the winning one beats the median out-of-sample
needs to be evaluated explicitly.

**What this means for our desk.** This is the single most important
trading-theory result for us right now, because the slate normalizer
*does* test many cells. The auditor's new state-of-evidence line cites
this explicitly: "below `EVIDENCE_PRIOR_ONLY_SAMPLES` closed samples,
no apparent edge in the slate can be distinguished from a multi-trial
artifact." Future work: integrate a deflated-Sharpe check into
`inferno_walk_forward` or `inferno_strategy_lab` so that promotion
math accounts for trial count automatically.

### 2.3 Disposition effect — what closes us out of winners too early

**Finding.** [Shefrin & Statman (1985)](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1985.tb05002.x)
documented "the disposition to sell winners too early and ride losers
too long." Four psychological drivers: loss aversion, mental
accounting, regret avoidance, and self-control. The effect is robust
across decades of retail trade data; sophisticated investors show it
too but to a lesser degree.

**What this means for our desk.** Pre-committed falsification triggers
are *the* defense against this. A "exit if realized < 50% of implied
move" rule decided *before* the trade is opened is qualitatively
different from a "should I cut this?" decision made staring at a red
P/L. The auditor already enforces pre-commitment — this finding
confirms why, and we now cite Shefrin & Statman 1985 in MATH §21 as
the behavioural anchor for the falsification-trigger section.

### 2.4 Transaction costs and short-DTE drag

**Finding.** Bid-ask spreads on short-DTE options widen sharply during
vol events; even outside vol events, the per-trade frictional cost on
a 0–5 DTE single-leg trade can be a meaningful percentage of total
trade cost. [Lo (2008), "Hedge Funds"](https://press.princeton.edu/books/paperback/9780691145983/hedge-funds)
and the arXiv survey [Optimal Trading Under Alpha Decay](https://arxiv.org/pdf/2502.04284)
both make the same point: small statistical edges are extremely
fragile to round-trip costs.

**What this means for our desk.** Our 7–21 DTE window is *not* 0DTE,
so spread is more forgiving than the 0DTE literature suggests. But
the principle still holds: we should refuse to size a ticket where
the per-leg spread is a large fraction of the implied move. Future
work: add a `slippage_check` to the conviction audit that fires a
disagreement when `(bid_ask_spread / mid_price) * leg_count` exceeds
some fraction of the implied move.

---

## 3. Jim Simons / Renaissance / Medallion

### 3.1 The shape of the actual edge

**Finding.** Medallion's 1988–2022 CAGR is ~39.9% net of (very high)
fees; pre-fee returns averaged ~71.8% from 1994 through mid-2014.
[Quartr's breakdown](https://quartr.com/insights/edge/renaissance-technologies-and-the-medallion-fund)
and [Cornell Capital Group's analysis](https://www.cornell-capital.com/blog/2020/02/medallion-fund-the-ultimate-counterexample.html)
both reconstruct returns from filings; the magnitudes match. Critical
qualifier: Medallion makes hundreds of thousands of tiny trades on
very thin per-trade margins; holding periods range seconds to a
couple of weeks.

**What this means for our desk.** Medallion's edge is *not*
transferable as a strategy. Capacity, infrastructure, and signal
construction are completely different from anything an earnings-options
desk does. What *is* transferable is the philosophical posture —
thousands of small uncorrelated edges, not one big idea. This is the
single principle the new `docs/SIMONS_PRINCIPLES.md` makes operational.

### 3.2 Berlekamp's Kelly contribution

**Finding.** [Elwyn Berlekamp](https://en.wikipedia.org/wiki/Elwyn_Berlekamp)
ran Medallion in 1989–1990 and posted 55.9% net. His major
contribution was Kelly-style sizing — taking each signal's expected
edge and the joint covariance and turning it into a position size,
not just a buy/sell call. Berlekamp returned to Berkeley after selling
his share. The Kelly framework stayed.

**What this means for our desk.** Sizing is half the edge. Our
quarter-Kelly cap is the same family of decision; we have it because
of Thorp-Rotando 1992 (estimation error), not because of Berlekamp,
but the lineage is shared. Citation lands in
[`THEORY_REFERENCES.md`](THEORY_REFERENCES.md) under `[BER91]`.

### 3.3 Hidden Markov models for regime detection

**Finding.** Renaissance applied speech-recognition techniques —
particularly Hidden Markov Models fit via Baum-Welch — to detect
when the market had transitioned from one statistical regime to
another. Source: [Zuckerman (2019), *The Man Who Solved the Market*](https://novelinvestor.com/notes/the-man-who-solved-the-market-by-gregory-zuckerman/);
academic anchor for HMM finance applications: [Hamilton (1989), Econometrica](https://www.jstor.org/stable/1912559).

**What this means for our desk.** Our two-sided CUSUM regime-drift
detector (`inferno_regime_drift.py`, MATH §12) is the *correct family*
of tool — change-point detection on a univariate signal — but a
simpler instance. Upgrading to a small HMM is plausible future work
*after* we have enough closed paper outcomes to fit transition
probabilities. Not today.

### 3.4 Why Medallion stays closed and RIEF underperforms

**Finding.** Medallion has been closed to outside money since 1993.
The reason is capacity: high-frequency stat-arb edges saturate at a
capital threshold below which they print, above which market impact
eats them. RIEF (the institutional fund) follows slower strategies
and posted ~8.5% in 2018 against Medallion's 76% the same year.

**What this means for our desk.** Capacity is a property of the
strategy, not just the bankroll. The desk's bankroll is small enough
that capacity is not a constraint *for us today*, but it *is* a
reason to never assume that what works at $1k risk per ticket will
keep working at $50k. Future work: a `capacity_governor` check that
flags when ticket-size growth crosses a noticeable fraction of the
target's average daily option volume.

### 3.5 The cultural primitives

**Finding.** From multiple syntheses of Zuckerman's book and
employee interviews:

- *One model.* All researchers feed signals into one combined model.
  No silos.
- *Bad ideas are good, no ideas are terrible.* The culture rewards
  exploring even unpromising hypotheses; the worst sin is to not try.
- *Shared compensation pool.* No individual stars. Performance is
  attributed to the firm.
- *Survival before growth.* Simons: "Our job is to survive. If we're
  wrong, we can always add later."
- *Models decay.* What worked last year may not work next; signals
  must be re-validated continuously.
- *Advantage must be real after costs.* Backtest-pretty edges that
  don't survive transaction costs are not real.

**What this means for our desk.** All six principles are
philosophical, not numeric — but they translate. The new
[`SIMONS_PRINCIPLES.md`](SIMONS_PRINCIPLES.md) maps each principle
to a concrete artifact or behaviour in our codebase, so the next
session can read the principle alongside the module that enforces it.

---

## 3a. Second-pass additions (this session)

After the initial cut, deeper reads on the theta curve, term-structure
arbitrage, vector Kelly, and López de Prado / Bailey produced the
following operational additions to the audit. Every one survives the
two-rule standard: cite-able and tied to a desk input.

- **Theta acceleration bear.** Any long-premium structure with DTE ≤ 30
  now carries an explicit bear quoting the 3–5× decay multiplier vs.
  60-DTE, tagged `[THETA-CURVE]`. Our 7–21 window sits in the worst
  part of the curve for long premium, and the audit now says so.
  Test pinned: `test_short_dte_long_premium_carries_theta_acceleration_bear`.

- **Calendar-spread disagreement.** When the chosen structure buys
  vol (straddle / strangle), the audit now surfaces a disagreement
  bullet naming the calendar spread as the typed alternative for a
  pure vol-crush view, tagged `[CAL-SPREAD]`. We do not claim the
  calendar is *better* — we claim a long straddle is *not* the
  cheapest expression of the vol-crush thesis. Test pinned:
  `test_long_straddle_surfaces_calendar_spread_as_disagreement`.

- **CBOE-72 frequency cite.** The long-vol bear used to say "the win
  comes from a small minority"; it now quantifies that minority at
  ~28% of S&P single-name earnings events per the CBOE 10-yr sample,
  tagged `[CBOE-72]` and `[gray]` (vendor-summarised). Test pinned:
  `test_cboe_72_fact_appears_in_long_straddle_bear`.

- **PEAD-roll trigger.** Every audit now carries a pre-commit
  falsification trigger: do not roll a long-premium ticket past its
  planned exit into the multi-week post-earnings-drift horizon. PEAD
  is real (Bernard & Thomas 1989, tag `[BT89]`) but lives outside our
  7–21 DTE window, so rolling silently changes the bet. Test pinned:
  `test_pead_trigger_present_on_every_audit`.

- **Disposition-effect pre-commit.** Falsification triggers now
  carry an explicit "decide every exit *before* sizing" clause citing
  Shefrin & Statman 1985 (`[SS85]`). Behavioural anchor, not statistical.

- **Multi-trial honesty.** State-of-evidence now cites López de Prado
  & Bailey's Deflated Sharpe (`[LdP-DSR]`) — the slate normalizer
  tests many cells, so any apparent edge needs selection-bias
  correction before it can be called posterior. Test pinned:
  `test_state_of_evidence_cites_deflated_sharpe`.

- **Quarter-Kelly cap is sourced.** State-of-evidence explicitly
  cites Rotando & Thorp 1992 (`[RT92]`) — half-Kelly captures ~75%
  of full-Kelly growth at ~half the drawdown; quarter-Kelly is the
  right band when win rate *and* R are both still estimated. The
  cap is no longer asserted; it is anchored to an empirical result.
  Test pinned: `test_state_of_evidence_cites_rotando_thorp`.

## 4. What did NOT make it into the model

For honesty: every research session collects more material than it
should keep. Things we read but deliberately did *not* incorporate:

- **Risk-reversal disagreement rule.** Real predictive power, but
  the snapshot pipeline does not capture OTM put/call IV split. We
  refuse to bear-cite a number we cannot reproduce from our data.
- **Vector Kelly across the slate.** Thorp's portfolio Kelly is the
  right tool *eventually* — but with zero closed paper outcomes the
  joint covariance is unestimable. The slate concentration governor
  is the conservative substitute today. Citation lives in
  [`THEORY_REFERENCES.md`](THEORY_REFERENCES.md) under `[THORP-VEC]`.
- **Single-stock HMM regime detector.** Beautiful in theory; the
  CUSUM in `inferno_regime_drift.py` is in the same family and is
  appropriate for our sample size. We will revisit once ≥ 60 closed
  paper outcomes are on the books.
- **Single-stock HMM regime detector.** Beautiful in theory, expensive
  to fit credibly with our sample size. We will revisit once we have
  ≥ 60 closed paper outcomes.
- **Detailed Renaissance signal taxonomy.** Trend / mean-reversion /
  pairs / autocorrelation, etc. None of these are our edge; cataloguing
  them as "things we don't do" adds no operational value.
- **0DTE-specific spread research.** Our DTE window is 7–21, not 0–2.
  The 0DTE literature is sharper than our regime, so it would mislead
  if quoted naively.

The standard for keeping is the same standard the auditor uses for
bull/bear bullets: it must be tied to an explicit input the desk
already produces or can produce, and it must be cite-able.
