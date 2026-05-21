# Portfolio Construction — Phase B Research Note

Last updated: 2026-05-20.

This is the long-form research synthesis for Research Roadmap **Phase B**:
the portfolio-level layer. It covers correlation structure (Dalio's "Holy
Grail"), the Grinold Fundamental Law of Active Management, drawdown
protocol math, and capacity analysis — all reduced to operating implications
for a $500-ticket manual options book on 7-21 DTE.

Read this after `docs/PERFORMANCE_ATTRIBUTION.md` (the Phase A note that
unblocked this layer). The two compose: post-trade learning tells the desk
what each trade contributed to the slate; portfolio construction tells the
desk how those slates compose into a return stream that doesn't blow up.

This doc is research-only. No new authority is implied. Broker submit stays
OFF. The 30-closed-scored-paper-outcomes promotion gate stays in force.

## 1. Why this phase, and why now

The Phase A modules are honest about one thing: they wait for closed
outcomes. The Brinson decomposition, per-rule edge decay, and slippage
anchors all populate meaningfully once 30-50 paper outcomes close. **Phase
B is the layer that sits *between* "we have outcomes" and "we have
conviction in the next ticket."**

Without Phase B, the desk has fifteen well-researched single-name theses
and no read on whether they're actually fifteen bets or one bet repeated
fifteen times. That distinction is the difference between a desk that
compounds and a desk that takes one body blow and stops.

Three problems Phase B solves:

1. **Correlation blindness.** If five tickets are all "AI capex
   beneficiaries" with long-vol structures into earnings, a single AI
   sentiment reversal blows up all five simultaneously. The desk has no
   way to see this today.
2. **Drawdown drift.** Without a drawdown protocol, the temptation when
   six straight losers hit is to either size up (revenge trading) or
   freeze (paralysis). Both lose. A pre-committed protocol — what
   Druckenmiller and Tudor Jones call "cutting size in half at -10%" — is
   the operator's pre-trade Ulysses contract.
3. **Capacity blindness.** A $500 ticket might be too big for a name
   where the desk would need to be 40% of the day's volume on a tight
   strike. Capacity isn't an institutional problem; it's an everyday
   problem for retail in illiquid options.

## 2. Modern Portfolio Theory — the foundation

Markowitz (1952) established the variance-covariance framework: the
variance of a portfolio is

```text
σ²_P = Σᵢ wᵢ² σᵢ² + 2 Σᵢ<ⱼ wᵢ wⱼ σᵢ σⱼ ρᵢⱼ
```

The cross-term is the entire story. For uncorrelated bets (ρ = 0), the
cross-term collapses and risk falls as `1/√N`. For perfectly correlated
bets (ρ = 1), the cross-term saturates and risk does not fall with N — you
are running one trade in N ways and paying the spread N times for the
privilege.

The operating implication for this desk is not "compute a 30-ticket
correlation matrix." It's smaller and sharper: **before adding a new
ticket, ask which existing tickets it correlates with under the realistic
adverse scenario.**

The scenarios that actually matter:

- A SPY-down-2% day. Which existing tickets get cheaper together?
- A semis-down-5% day. Which sector concentration was hidden inside the
  slate?
- An earnings-week IV-crush event. Which long-premium tickets all collapse
  on the same Friday?
- A Fed surprise. Which rates-sensitive tickers move together?

Correlation is a function of *which axis you're measuring on*. Realised
return correlation across closed outcomes is the cleanest version. Sector
tag co-occurrence is a usable proxy until enough outcomes exist.

## 3. The Holy Grail — Dalio's central insight

Ray Dalio's "Holy Grail of Investing" (Bridgewater, 2011) is the cleanest
prescriptive statement of Markowitz: **if you can find 15-20 truly
uncorrelated return streams of equal expected return and equal volatility,
the portfolio Sharpe ratio can be roughly 4× the individual stream's
Sharpe ratio** while drawing on the same alpha pool.

The geometry, with N equal-σ streams of pairwise correlation ρ:

```text
σ²_P / σ²_individual = 1/N + (N−1)/N · ρ

For ρ = 0:  σ_P / σ = 1/√N   →   15 streams cut risk by ~75%
For ρ = 0.3: ratio ≈ 0.59     →   most "diversification" lives here
For ρ = 0.7: ratio ≈ 0.86     →   barely diversified at all
For ρ = 1.0: ratio = 1.0      →   no diversification
```

The empirical trap: most "diversification" lives at ρ ≈ 0.3-0.5, which buys
you a 40-60% risk reduction at best. The Holy Grail's promise only
materializes when ρ approaches zero, and getting genuine ρ ≈ 0 takes
deliberate work — most stock pickers' "diversified portfolio" of 20 names
has a single equity-beta factor sitting at ρ > 0.7 across all of them.

For an options desk specifically:

- **Within-sector earnings plays are nearly perfectly correlated** in IV
  crush dynamics. A KO straddle and a PEP straddle into the same Friday
  share more than their sector — they share an event-vol regime.
- **Long-vol structures across the slate are correlated** on calm days.
  All of them bleed theta together.
- **The cleanest decorrelation comes from mixing direction and timeframe**:
  a short-dated long-vol play + a longer-dated short-vol play + a
  long-equity-direction debit spread + a defensive put-side hedge are
  more independent than five long-vol plays in different names.

Effective bet count (Grinold-Kahn 2000):

```text
N_effective = 1 / Σᵢ wᵢ²        (Herfindahl-style)
```

If five equally-weighted positions all share the same risk factor,
`N_effective` looks like 5 but the *effective independent bets* is closer
to 1. The desk's portfolio correlation module should report both.

## 4. Grinold's Fundamental Law of Active Management

Grinold (1989) formalized the active-management identity:

```text
IR ≈ IC · √Breadth
```

where IR is the information ratio (Sharpe-like risk-adjusted alpha), IC is
information coefficient (predictive skill per bet), and Breadth is the
number of independent bets.

Three operating implications for a 7-21 DTE manual options desk:

1. **Breadth matters quadratically in disguise.** Doubling Breadth at
   constant IC raises IR by √2 ≈ 41%. That's a real lift, but only if
   the new bets are *independent*. Twenty bets of which fifteen are the
   same trade equal an effective breadth of six.
2. **IC compounds with Breadth, not against it.** The trap is to assume
   higher IC requires fewer, bigger bets. The math says the opposite for
   small-account compounding: small bets, independent, with positive IC,
   compound faster than one big bet with the same IC.
3. **The Klarman SIT-OUT discipline is a Breadth discipline.** Days when
   nothing clears the gates are days when adding a marginal-IC bet would
   pull average IC down faster than √Breadth could keep up. The empty
   slate is the right answer.

For this desk's scale, the operational breadth ceiling is the operator's
attention budget: roughly 5-12 actively-monitored tickets at once. The
math says the desk should be biased toward filling that ceiling with
*independent* bets, not toward sub-filling it with similar bets.

## 5. Drawdown protocol — the Ulysses contract

A drawdown protocol is a pre-committed rule for how the desk responds to
losing streaks. The literature here is thinner than for entry signals
because most academic finance is uncomfortable with discretionary sizing,
but the operating literature (Tudor Jones, Druckenmiller, Schwager's
*Market Wizards*) is unanimous:

> The first job in a drawdown is to stop the drawdown.

Concrete protocols used by professional discretionary traders:

| Drawdown depth | Action |
|---|---|
| 0% to −5% | Normal sizing. Trade the plan. |
| −5% to −10% | Cut new-ticket size in half. Existing tickets unchanged. |
| −10% to −15% | Cut new-ticket size to one-quarter. No new positions in already-correlated families. |
| −15% to −20% | Stop opening positions. Manage existing book only. |
| −20% | Full stop. Review the last 30 outcomes before reopening. |

The depth thresholds vary across operators. The structure does not. Three
features matter:

1. **The threshold is pre-committed and written down.** Every operator
   who has not pre-committed has eventually held a losing position too
   long while telling themselves the next trade would recover it.
2. **The step-down is automatic.** "I'll consider it" is not a protocol.
3. **Re-entry is gated on a positive event, not a feeling.** Two clean
   closed wins, or a fresh edge research result, or 30 days clean —
   anything observable, not "I feel ready."

Math: the **Calmar ratio** (Young 1991) tracks annualized return divided
by max drawdown. **MAR** is the same idea over a longer window. Neither
should be optimized directly — they're after-the-fact diagnostics — but
both are useful as honesty checks. A strategy with a 30% return and a 50%
max drawdown has a Calmar of 0.6, which is poor; one with a 15% return
and a 10% max drawdown has a Calmar of 1.5, which is excellent.

The **time-to-recovery** metric is underrated. A 10% drawdown that
recovers in two weeks is a different beast than a 10% drawdown that takes
nine months. Operators should track both numbers, not just the depth.

The **Ulcer Index** (Martin 1989) — used in the Phase A note — captures
"how stressful did this drawdown feel" by squaring the daily drawdown
percentage. Two drawdowns of equal depth but different time-under-water
will have very different Ulcers. For a manual operator's mental health,
Ulcer is often a more honest metric than max DD.

## 6. Capacity — the constraint nobody talks about

Capacity in the institutional sense — "how much capital can this strategy
absorb before its own activity moves prices" — does not bind a $500-ticket
desk in the obvious way. But the analogous constraint *does* bind:
**operator attention** and **option-chain liquidity per name** are the
desk's capacity bottlenecks.

The Lo (2004) Adaptive Markets framing is useful here. Markets are not
efficient; they are *adaptive*. An edge that worked at small scale stops
working when too many participants chase it. For retail options
specifically, the edges that don't decay are the ones that institutional
participants can't trade economically — illiquid options, idiosyncratic
single-name events, weekday-specific dynamics in second-tier names.

The Medallion case study (Renaissance, closed to outside capital in 1993)
is the cleanest empirical proof: even the highest-Sharpe fund ever
operated had to cap AUM to preserve edge. For our desk, the analogous
question is whether adding more tickets to the current 5-10/day cadence
materially degrades the average IC of those tickets.

Kacperczyk-Sialm-Zheng (2005) found that *concentrated* mutual funds
(those that bet heavily in a few industries) outperformed *diversified*
funds — but only conditional on stock-picking skill. Diversification is
free risk reduction; concentration is risk taken in exchange for
expression of an actual view. Both are valid; the danger is concentrated
exposure achieved by *accident* (correlation blindness) rather than by
*intent*.

For this desk:

- **Per-name capacity** is set by the option-chain liquidity. A name where
  the Schwab edge bridge classifies as `thin-data` cannot absorb a $500
  ticket without giving back 20-50% to the spread.
- **Per-family capacity** is set by the correlation structure. Five
  long-vol plays in the same week share one risk factor.
- **Per-operator capacity** is the daily attention budget — empirically
  5-12 active tickets, optimistically.

## 7. What we build — three Phase B modules

### `inferno_portfolio_correlation.py` (top priority)

Reads the closed-outcome ledger and the active slate, computes:

- **Pairwise PnL correlation** across closed tickets, grouped by strategy
  family and by sector tag where available.
- **Effective bet count**: 1 / Σ wᵢ², where weights are normalized by
  risk units (debit paid / max loss).
- **Concentration heatmap**: per-sector ticket count, per-family ticket
  count, per-DTE-bucket ticket count.
- **Adverse-scenario co-movement**: for each ticket in the active slate,
  count how many other slate tickets share the dominant sector / family /
  direction.
- **Verdict ladder**:
  - `diversified` — Effective bet count > 0.7 × headcount AND no family
    > 40% of slate
  - `concentrated-by-intent` — Single family > 50% of slate AND operator
    has flagged the thesis as deliberate
  - `concentrated-by-drift` — Single family > 50% of slate AND no flag
  - `awaiting-outcomes` — Insufficient closed outcomes to compute
    realised correlations

### `inferno_drawdown_protocol.py`

Tracks rolling drawdown across the desk's closed-outcome equity curve
(once outcomes exist) or against a synthetic equity curve derived from
the paper ledger PnL field. Computes:

- **Current drawdown depth** (from rolling peak)
- **Max drawdown** over the lookback window
- **Time-to-recovery** in trading days when a drawdown has resolved
- **Ulcer index** (Martin 1989)
- **Calmar ratio** (annualized return / max drawdown)
- **Sizing recommendation** against the table in §5 above — strictly
  advisory, never authority-bearing

### `inferno_capacity_check.py` (Phase B optional / Phase C bridge)

Per-name and per-family capacity headroom. Pulls the Schwab edge bridge's
liquidity bucket and produces an answer to "is this ticket size
appropriate for this name's chain depth?" Built only after the first two
modules are stable.

## 8. Success criteria

Phase B is considered shipped when:

- `inferno_portfolio_correlation.py` runs cleanly against current data,
  emits a research-only verdict, and is wired into the command center.
- `inferno_drawdown_protocol.py` runs cleanly, has the sizing-step-down
  table baked in, and feeds the doctor freshness check.
- Both modules have ≥20 contract tests each.
- `docs/PROJECT_STATUS.md` row for Phase B is added.
- Coordination note dropped.
- Authority unchanged. Broker submit OFF. 30-outcome promotion gate intact.

## 9. Anti-goals

- **No automatic position sizing.** The drawdown protocol *advises*; the
  operator decides. Automating sizing without a closed-loop track record
  is exactly the failure mode the Karen-the-Supertrader case study
  illustrates.
- **No correlation-based auto-rejection of tickets.** Concentration
  warnings are warnings. The operator may have a deliberate concentration
  thesis (Druckenmiller's "go big when you're right") that the model
  should flag, not block.
- **No capacity throttling on broker-submit.** Broker submit is OFF
  regardless. Capacity math is research-only.

## 10. How Phase B unlocks Phase C

The crowdedness / consensus signal in Phase C ("are we the last person
into this trade?") cannot be measured without a correlation baseline. If
the desk doesn't know which of its own positions correlate, it cannot
measure how its slate correlates with *consensus positioning*. Phase B
delivers the correlation primitive that Phase C uses.

## Citations

Primary references (added to `docs/THEORY_REFERENCES.md`):

- **MARKOWITZ-1952** — Markowitz, "Portfolio Selection," J. Finance 7(1)
- **DALIO-HOLY-GRAIL** — Dalio, *Principles* and Bridgewater research
  notes; popularized in "How the Economic Machine Works" public material
- **GRINOLD-1989** — Grinold, "The Fundamental Law of Active Management,"
  J. Portfolio Management 15(3)
- **GRINOLD-KAHN-2000** — Grinold & Kahn, *Active Portfolio Management* 2e
- **YOUNG-1991** — Young, "Calmar Ratio: A Smoother Tool," Futures
  magazine, Oct 1991
- **MARTIN-1989** — Martin & McCann, *The Investor's Guide to Fidelity
  Funds*, Ulcer Index definition
- **CONSTANTINIDES-1986** — Constantinides, "Capital Market Equilibrium
  with Transaction Costs," J. Political Economy 94(4)
- **LO-2004** — Lo, "The Adaptive Markets Hypothesis," J. Portfolio
  Management 30(5)
- **KACPERCZYK-SIALM-ZHENG-2005** — "On the Industry Concentration of
  Actively Managed Equity Mutual Funds," J. Finance 60(4)
- **SCHWAGER-MARKET-WIZARDS** — Schwager, *Market Wizards* series, drawdown
  protocols across multiple interviewed traders
- **KELLY-1956** — Kelly, "A New Interpretation of Information Rate,"
  Bell System Technical Journal — base case for drawdown-aware sizing

New citation tags to add: MARKOWITZ-1952, DALIO-HOLY-GRAIL, YOUNG-1991,
CONSTANTINIDES-1986, LO-2004, KACPERCZYK-SIALM-ZHENG-2005.

## Operating principle

> Fifteen well-researched theses do not constitute fifteen bets. Fifteen
> bets exist only when each thesis can be wrong without the other fourteen
> also being wrong. Portfolio construction is the discipline of paying
> attention to *that* condition, not just to whether each individual
> thesis is sound.
