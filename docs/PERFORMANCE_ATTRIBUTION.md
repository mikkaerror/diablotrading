# Performance Attribution, Edge Half-Life, and Slippage

Phase A research note. This is what closes the loop on the desk: when a paper
outcome closes, we should be able to say *why* and *whether the auditor was
right*, score how much edge our rules have left, and quantify the gap between
paper and live.

Three sub-areas, one document. Each one ends with the operator-grade rule we
ship.

## 1. Performance attribution

### The Brinson framework — the asset-management standard

Gary Brinson, Randolph Hood, and Gilbert Beebower (1986, *Financial Analysts
Journal*) decomposed active return into three orthogonal effects:

```text
Allocation effect = Σ (wₚ,ⱼ − wᵦ,ⱼ) · Rᵦ,ⱼ
Selection effect  = Σ  wᵦ,ⱼ · (Rₚ,ⱼ − Rᵦ,ⱼ)
Interaction       = Σ (wₚ,ⱼ − wᵦ,ⱼ) · (Rₚ,ⱼ − Rᵦ,ⱼ)

Active return     = Allocation + Selection + Interaction
```

`wₚ,ⱼ` is portfolio weight in sector j; `wᵦ,ⱼ` is benchmark weight; `Rₚ,ⱼ`
and `Rᵦ,ⱼ` are realised returns. Their 1986 conclusion was that allocation
explained ~90% of pension-fund variance — an answer the industry has been
arguing about ever since, but the framework itself has been standard for
forty years.

Translated to a small options desk, the analogues are:

- **Sector → strategy family.** Long premium, credit spread, calendar,
  vertical, etc.
- **Benchmark → naive equal-weight slate.** The "what would we have made if
  we just took every approval-ready ticket equal-weight?" counterfactual.
- **Allocation → what we chose to size into.** Did we overweight the
  families that paid?
- **Selection → which tickets we picked inside each family.**
- **Interaction → cross-term we mostly want to drive to zero (avoids
  double-counting).**

### Risk-adjusted ratios — pick the right denominator

The Sharpe ratio (Sharpe 1966) divides excess return by total volatility.
That punishes upside the same way it punishes downside, which is wrong for
asymmetric-payoff strategies. The literature ladder:

| Ratio | Numerator | Denominator | When it bites |
|---|---|---|---|
| **Sharpe** | excess return | total σ | universal but mis-prices long-vol |
| **Sortino** (Sortino 1980) | excess return | downside σ only | better for asymmetric-payoff strategies |
| **Calmar** | annualised return | max drawdown | rewards survival |
| **Ulcer Index** (Martin 1989) | — | quadratic mean of drawdown depth-time | the "investor stress" measure; penalises long shallow drawdowns |
| **Martin / UPI** (Martin 1989) | excess return | Ulcer Index | combines depth AND duration of drawdown |

For our desk, the right primary measure is **Sortino**, because every
strategy on the slate has explicit max loss and asymmetric payoff shape, and
**Ulcer Index** as the secondary because we care more about "how long were
we underwater" than "what was the single worst day".

### The Eckhardt counter-intuition rule — what attribution should never let us forget

William Eckhardt (Schwager, *The New Market Wizards* 1992): "What feels good
is often the wrong thing to do… In the long run, the majority loses. The
implication for the trader is that to win you have to act like the
minority."

Operational form for the auditor: when an attribution decomposition says we
*won* on a comfortable trade (consensus-aligned, in-trend, taken near
support), the auditor should flag that and ask whether the win is repeatable
or a survivorship artefact. The desk has plenty of bullets that flag *bad*
trades; we have none that flag *comfortable wins* — Eckhardt says those are
the dangerous ones.

### Operator-grade attribution rule we ship

A closed paper outcome cannot be marked "learned-from" until its
attribution decomposition exists. If the decomposition shows the winning
trade was selection-only with zero allocation effect, the win is honest. If
the win was allocation-only (everyone in that family won), the rule that
picked the family is what learned, not the rule that picked the ticket.

## 2. Edge half-life

### The fundamental law of active management

Grinold (1989), expanded with Kahn in *Active Portfolio Management* (2000):

```text
IR ≈ IC · √Breadth
```

Where `IR` is the information ratio (alpha / tracking error), `IC` is the
information coefficient (correlation between predicted and realised
returns), and `Breadth` is the number of *independent* bets per year.

Two operational consequences for us:

- We do not have many bets. The slate is ~10-20 tickets per cycle. Breadth
  is small, which means even a modest IC produces decent IR — *if* we keep
  IC honest.
- IC is the part that decays. Once a rule's IC drops below noise, breadth
  cannot save it.

### Post-publication decay

The Israel-Moskowitz (2013) line of work, extended by McLean-Pontiff (2016):
published anomalies see Sharpe ratios drop ~50% post-publication. Stein
(2009) on overcrowded long-short adds the mechanism — when a strategy
becomes well-known, capital arbs the edge away.

For a private desk, the analogue is: any rule that has been on our slate
long enough that the universe of names it favours starts to behave
*differently after our rule fires* is decaying. We will not detect that by
looking at strategy-level returns; we have to look per-rule.

### Bayesian online change-point detection — what to use instead of CUSUM alone

CUSUM (Page 1954) is what we currently use in `inferno_regime_drift.py`. It
is fast and well-understood, but it has two weaknesses:

- It does not produce a probability — only a binary "change / no change"
  verdict.
- It is sensitive to the choice of reference baseline.

Adams-MacKay (2007) Bayesian Online Change-Point Detection (BOCPD) is the
modern alternative: it maintains a probability distribution over "run
length" (time since the last change-point) and updates it message-passing
style at each new observation. The output is `P(change | data)` for every
recent timestep.

For per-rule edge decay, BOCPD is more honest than CUSUM. We do not retire
"this rule is dead"; we report "this rule has P=0.62 of having entered a
new regime in the last six observations."

### Operator-grade edge-decay rules we ship

Two rules, one diagnostic:

- **Per-rule hit rate with Wilson lower bound.** For each conviction auditor
  bullet, track the proportion of closed outcomes where the bullet correctly
  predicted (a bear bullet on a loser, a bull bullet on a winner). Compute
  the Wilson lower 95% CI. When the Wilson lower drops below 0.50 over a
  rolling window, the rule is a candidate for retirement.
- **Half-life estimator.** For each rule, fit a simple exponential decay on
  the per-period hit rate. Report the half-life in calendar weeks. Rules
  with half-life < 12 weeks are flagged as "fast-decay — likely a fitted
  artefact."

## 3. Slippage and the paper-to-live gap

### Almgren-Chriss (2000) — the cost-vs-risk frontier

Robert Almgren and Neil Chriss (2000, *Journal of Risk*) modelled execution
as a tradeoff between two costs:

- **Market impact cost** — the worse fill you get for trading faster.
- **Volatility risk** — the worse outcome you get for trading slower.

Permanent impact is the move that survives after you finish; temporary
impact is the move that recovers. For a small options desk our orders are
not large enough to move the underlying, but the same model applies to
filling at the mid vs paying the spread to get in fast.

### The Roll (1984) bid-ask spread estimator

Even without quote data, Roll (1984) showed you can estimate the effective
spread from the autocovariance of close-to-close returns:

```text
ŝ = 2 · √( −Cov(ΔPₜ, ΔPₜ₋₁) )       (when covariance is negative)
```

This is useful for the underlying. For options, where bid-ask is wider and
quote feeds are unreliable for the back of the chain, the right primary
source is the Schwab option-chain API (which Codex scaffolded in
`inferno_schwab_options.py`). When Schwab quotes are not available, fall
back to a strategy-family-specific spread heuristic:

| Strategy family | Typical %-spread of mid (heuristic) | Notes |
|---|---|---|
| Front-month long premium, liquid name | 1–3% | tightest, most liquid |
| Vertical / debit spread, liquid name | 2–5% | per-leg widens combined |
| Calendar / diagonal | 3–8% | depends on back-month liquidity |
| Iron condor / four-leg structure | 5–12% | aggregate of all legs |
| Earnings week, less-liquid name | 5–20% | event premium widens spreads |

These are heuristic anchors, not measurements. The slippage module's job is
to refine them with realised data once we have it.

### The paper-to-live gap, decomposed

Following the literature (Hasbrouck 1991, 2009), the gap has four
components:

1. **Quoted spread cost.** What you pay to cross.
2. **Effective spread = realised spread + adverse selection.** Roll's
   measure plus the systematic loss to better-informed traders.
3. **Market impact.** What you move the quote by trading. Negligible for us
   at $500/ticket.
4. **Latency / partial fills.** What the quote does between your decision
   and your fill.

For our desk, component 2 dominates. Our paper fills assume mid; real fills
will be closer to the bid (when selling) or the ask (when buying), and
when the market is moving against us we will get the worse side of that
spread systematically.

### Operator-grade slippage rule we ship

A `slippage_adjusted_expected_pnl` field for every audited ticket and every
closed outcome:

```text
slippage_adjusted_expected_pnl
  = paper_expected_pnl
  − (entry_spread_pct · contracts · contract_multiplier)
  − (exit_spread_pct · contracts · contract_multiplier)
  − (adverse_selection_haircut · paper_expected_pnl)
```

Where the `adverse_selection_haircut` is a per-strategy-family constant
(initially 0.15 for long premium, 0.20 for credit spread, 0.25 for
calendar/diagonal) refined as live evidence accumulates.

The promotion math then uses this adjusted PnL, not paper PnL. This alone
will probably reveal that some of our "ready" strategies do not clear the
promotion bar after slippage — which is exactly what we want to know
*before* live submit is enabled.

## Synthesis — the three rules in one sentence each

1. **Attribution: every closed outcome must be decomposed into allocation
   vs selection effect, with a separate flag for "comfortable win" so we
   do not learn the wrong lesson.**
2. **Edge decay: every conviction auditor bullet carries a Wilson-bounded
   hit rate and a half-life estimate; bullets that fall below their floor
   become retirement candidates.**
3. **Slippage: every expected PnL on the desk is the
   slippage-adjusted version, not the paper-mid version; the promotion
   math reads only the adjusted number.**

## How this lands in code

Three modules (see `docs/RESEARCH_ROADMAP.md` Phase A code deliverables):

- `inferno_outcome_attribution.py` — Brinson-style decomposition of every
  closed paper outcome, plus the Eckhardt comfortable-win flag.
- `inferno_rule_edge_decay.py` — per-bullet Wilson hit rate + half-life
  estimator + BOCPD layer on top of CUSUM.
- `inferno_slippage_estimator.py` — Schwab-quote-preferred, heuristic
  fallback, four-component decomposition.

All three are research-only, diagnostic-only, promotable=False. The
authority manifest does not change. Broker submit stays OFF.

## Citations

Tags follow `docs/THEORY_REFERENCES.md`:

- **BHB-1986** — Brinson, Hood, Beebower (1986). "Determinants of Portfolio
  Performance." *Financial Analysts Journal* 42(4): 39–44.
- **SHARPE-1966** — Sharpe (1966). "Mutual Fund Performance." *Journal of
  Business* 39(1).
- **SORTINO-1980** — Sortino, Van der Meer (1980/1991). The Sortino ratio.
- **MARTIN-1989** — Martin, McCann (1989). *The Investor's Guide to Fidelity
  Funds.* Ulcer Index introduction.
- **ECKHARDT-MW93** — Eckhardt in Schwager (1992), *The New Market Wizards*.
- **GRINOLD-1989** — Grinold. "The Fundamental Law of Active Management."
  *Journal of Portfolio Management*.
- **GRINOLD-KAHN-2000** — Grinold, Kahn. *Active Portfolio Management*, 2nd
  ed. McGraw-Hill.
- **ISRAEL-MOSKOWITZ-2013** — Israel, Moskowitz. "The Role of Shorting,
  Firm Size, and Time on Market Anomalies." *Journal of Financial
  Economics*.
- **MCLEAN-PONTIFF-2016** — McLean, Pontiff. "Does Academic Research
  Destroy Stock Return Predictability?" *Journal of Finance*.
- **STEIN-2009** — Stein. "Presidential Address: Sophisticated Investors
  and Market Efficiency." *Journal of Finance*.
- **ADAMS-MACKAY-2007** — Adams, MacKay. "Bayesian Online Changepoint
  Detection." *arXiv:0710.3742*.
- **ALMGREN-CHRISS-2000** — Almgren, Chriss. "Optimal Execution of
  Portfolio Transactions." *Journal of Risk* 3(2): 5–39.
- **ROLL-1984** — Roll. "A Simple Implicit Measure of the Effective
  Bid-Ask Spread in an Efficient Market." *Journal of Finance* 39(4).
- **HASBROUCK-1991** — Hasbrouck. "Measuring the Information Content of
  Stock Trades." *Journal of Finance* 46(1).
- **PAGE-1954** — Page. "Continuous Inspection Schemes." *Biometrika*
  41(1/2): 100-115. (CUSUM origin.)

## What this does NOT do

- It does not enable live submit.
- It does not change capital deployment.
- It does not loosen the paper-evidence gate.
- It does not produce an ML model that "predicts winners". Attribution
  honesty is the precondition for any ML layer, not a substitute for one.

## Next session pick-up

If this work spans sessions, the next session inherits:

1. This document is the synthesis. Read it before coding.
2. THEORY_REFERENCES.md will have the new citation tags slotted in.
3. The three module skeletons may be partially complete in
   `inferno_outcome_attribution.py`, `inferno_rule_edge_decay.py`,
   `inferno_slippage_estimator.py`. Look at the test files first to see
   the contracts.
4. `coordination/model_notes.jsonl` will carry the last work-in-progress
   note tagged with `attribution`, `edge-decay`, or `slippage`.
