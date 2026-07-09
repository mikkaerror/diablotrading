# Inferno Campaign Plan — Prove or kill the one candidate edge

- **Date:** 2026-07-03
- **Author:** Claude (research lane)
- **Stage:** research-only plan. No authority change. `liveTradingAllowed=false`,
  `brokerSubmitAllowed=false` throughout, until an explicit, separate promotion.
- **For:** the operator + Codex. This is the roadmap the whole desk now serves.

## The single goal

Everything the desk does now has exactly one purpose: **determine, with
real-friction paper evidence, whether the 7–14 DTE pre-earnings straddle on
liquid large-caps is a real, tradeable edge — or a shadow mirage.** Prove it, or
kill it. Nothing else is a better use of the evidence loop, the compute, or your
time.

This plan is deliberately narrow. A desk that tries to prove everything proves
nothing. One hypothesis, tested honestly, is worth more than a hundred vague ones.

## What we know, and what we don't

**The signal (from 39 closed shadow outcomes, `dte_policy_analysis.json`):**
Long straddle entered 7–14 DTE before earnings, held through the event to
expiration, on liquid large-caps (ACN, MRVL, DELL, ORCL, CIEN, HPE). Mean net-R
**+0.87** (+0.49 excluding the 3 biggest wins), win **59%**, payoff **3.15:1**,
bootstrap 95% lower bound **+0.32**. The same structure at 22–35 DTE loses
(−0.41R). Mechanism: capture the pre-earnings **IV expansion** + the move, before
theta and post-earnings IV crush dominate.

**What the shadow does NOT prove (the three holes the campaign must close):**
1. **Friction is not applied** (`frictionRealized=false`). The +0.87R ignores the
   bid/ask you cross to enter a straddle. This is the single biggest risk to the
   edge. **The campaign's job #1 is to re-measure it with real spreads.**
2. **No dates** on the records → we cannot confirm the 39 outcomes span multiple
   earnings cycles. It could be one favorable season. **The campaign must run
   across ≥2–3 earnings cycles to establish regime-robustness.**
3. **Held to expiration only.** We haven't tested exiting the day after earnings
   (right after the IV crush), which may capture the vol-ramp edge while dropping
   the post-earnings drift risk. **Test both exits.**

## Critical path (ship sequence)

**Phase 0 — Unblock (in Codex's queue, specs written):**
- ✅ Payoff-aware win-rate promotion floor (shipped).
- ⬜ Paper/live drawdown decouple — lets the simulator run during the drawdown.
- ⬜ Chain-pull priority slate — puts liquid large-caps (the edge's names) in scope.
- ⬜ (bonus) ack-floor bug fix.

Until the decouple + chain-pull ship, the loop stays frozen and this campaign
cannot start. They are the gate.

**Phase 1 — Instrument the test (Codex, small):**
Point paper staging at the hypothesis explicitly:
- Candidate filter: `family = Long Straddle`, `entryDte ∈ [7,14]`, underlying is a
  liquid large-cap (ATM spread tight, high OI — the real liquidity read, not the
  miner set).
- **Apply real friction** to every paper fill: enter/exit at the actual bid/ask
  (or a modeled half-spread), not mid. Record `frictionRealized = true`.
- **Two exit variants per trade**, tracked separately:
  (a) hold-to-expiration (the shadow's assumption);
  (b) exit the session after the earnings report (post-IV-crush).
- Also stage a **cheaper proxy** for the small account: a 7–14 DTE debit
  spread / reduced-width structure that costs a fraction of the full straddle, to
  test whether the edge survives an affordable structure.

**Phase 2 — Run the campaign:**
- Accrue **≥30 scored paper outcomes** on the straddle rule, **spread across ≥2–3
  earnings cycles** (calendar time, not just count — because we can't confirm
  regime from the shadow).
- Track per-variant (full straddle vs proxy; hold-to-expiry vs post-earnings exit).
- Weekly read on the one-screen dashboard's evidence panel.

**Phase 3 — Decide (the whole point):** see decision gates below.

## Rigorous test design

| Dimension | Specification |
|---|---|
| **Entry** | 7–14 calendar days before the earnings date. |
| **Universe** | Liquid large-caps only: tight ATM bid/ask (say ≤10–15% of mid) AND meaningful ATM OI. The chain-pull fix must surface these. |
| **Structures** | (1) full ATM straddle (the signal); (2) affordable proxy (7–14 DTE debit spread / narrower structure) for the $-constrained account. |
| **Friction** | **Real.** Enter/exit at bid/ask (or half-spread). This is the make-or-break variable the shadow skipped. |
| **Exit** | Track both: hold-to-expiry, and exit the day after earnings. |
| **Sample** | ≥30 scored outcomes, across ≥2–3 earnings cycles. |
| **Metrics** | net-R with bootstrap 95% lower bound; profit factor; max drawdown; win rate vs payoff-implied breakeven. |

## Structure-family arm — is the edge VEGA or DIRECTION? (added 2026-07-06)

The shadow only tested two families: Long Straddle (wins at 7–14 DTE) and
Vertical Debit (loses; but only n=2 in the 7–14 window, so *untested* there, not
disproven). There is a mechanistic hypothesis worth resolving explicitly:

> The 7–14 DTE edge is a **vega / IV-expansion** effect — implied vol ramps into
> earnings and long-vega structures profit regardless of direction.

Rank structures by net long-vega (how much they ride the IV ramp):

| structure | net vega | cost | keeps the edge if it's vega? |
|---|---|---|---|
| **Straddle** | ~2× ATM | high ($700–1,900 large-cap) | yes (strongest) |
| **Strangle** | ~1.5× | medium | yes |
| **Single long call/put** | ~1× | **low ($200–400)** | yes, + directional |
| **Vertical debit spread** | ~0 net (short leg cancels) | low | **no — throws away the vega** |

The data is consistent with this: straddle wins, vertical loses — the vertical
is the one structure that discards the vega. **So the vertical is the *wrong*
cheap proxy** if the edge is vega. The right affordable proxy is a **single long
option or a strangle** — cheaper than a straddle, still long vega, and both fit
the account and a sane paper budget.

**Test at 7–14 DTE, on the same liquid large-caps, same friction:** straddle,
strangle, single long call, single long put, and a vertical debit spread. Reading:
- If straddle/strangle/single-long win but the vertical loses → the edge is
  **vega**; trade the cheapest long-vega structure the account can afford (single
  long option), and stop generating verticals.
- If the vertical *also* wins at 7–14 DTE → the edge is partly **timing/direction**;
  the cheap vertical becomes the affordable workhorse.
Either answer is decisive and directly solves the account-size problem.

## Decision gates (pre-registered — decide the rule before you see the data)

- **Gate A — after Phase 0 ships:** Is the loop actually staging 7–14 DTE straddle
  candidates on liquid names? If not, the fixes didn't land; debug before running.
- **Gate B — after ~15 real-friction outcomes:** Early read. If net-R is clearly
  negative with friction, or the win rate has collapsed below the ~24% payoff
  breakeven → the edge is likely a friction artifact. Consider stopping early.
- **Gate C — after ≥30 outcomes across cycles (the verdict):**
  - **PROVEN** — net-R bootstrap lower bound **> 0**, profit factor ≥ 1.25,
    consistent across cycles → graduate to a **tiny live pilot** (only after the
    account is sized appropriately and you give an explicit, separate live ack).
    Even then: start at 1 contract / minimum size.
  - **KILLED** — lower bound ≤ 0, or the edge lives only in the unaffordable full
    straddle and dies in the proxy, or it only worked in one cycle → **stop
    generating the strategy.** Do not trade it.

## The honest meta-gate

This campaign is also the test of whether the **desk itself** is worth
continuing. The 7–14 DTE straddle is the *best* thing in months of data. If it
dies under real friction, that is strong evidence the retail-earnings-options
premise does not produce a tradeable edge for this account — and the right,
self-respecting move is to **stop pouring time and money into it**, not to go
find the next vague hypothesis. Name that possibility now, while you're calm, so
the Gate-C "kill" branch is a real option and not an emotional cliff.

Conversely: if it *survives* real friction across cycles, you will have done
something most retail traders never do — found and rigorously proven a specific,
mechanistic edge before risking size. That is the version of this project worth
finishing.

## ⚠ Threshold catch (found 2026-07-06 — must fix before the campaign runs)

The paper/live decouple shipped with `PAPER_TICKET_BUDGET_DOLLARS = 500`. That
budget **blocks the full straddle on every liquid large-cap** — the exact
structure this campaign exists to prove:

| name | ~straddle debit (max loss) | fits $500 paper budget? |
|---|---|---|
| TXN | ~$1,925 | no |
| ASML | ~$12,505 | no |
| BMI | ~$910 | no |
| AEHR | ~$1,070 | no |
| edge names (ACN/ORCL/DELL/MRVL) | ~$700–1,800 | **no** |
| TE / HIVE / CLSK (cheap miners) | $55–150 | yes |

At $500, the paper loop would gather straddle evidence **only on the cheap
illiquid miners** — the opposite of the liquid-large-cap edge. Paper is
simulated (no real dollar), so the budget can be larger for the *evidence*
question without any real-money implication.

**Fix (no code change — the limit is env-configurable):** run the campaign with
`INFERNO_PAPER_TICKET_BUDGET=2000` (and `INFERNO_PAPER_DAILY_BUDGET` to match) so
the full large-cap straddle can be *papered*. Keep the two arms distinct:
- **Edge-confirmation arm** (paper budget ~$2000): does the full straddle edge
  reproduce on liquid large-caps with real friction? This needs the room.
- **Tradeability arm** (whatever the account can afford): does a cheaper proxy
  capture it? This is the $500-ish structure.

The $500 default is fine for the general defined-risk credit-spread lane; it is
just too small for the straddle-evidence arm specifically.

## Top-down coherence check (2026-07-06) — read this before believing the edge

**What holds together (encouraging):** one mechanism — *vega / pre-earnings IV
expansion* — explains three independent cuts at once: the smooth DTE gradient
(≤21 DTE wins, ≥22 loses, sharp threshold), the structure ranking
(straddle > strangle > single-long > vertical, matching net-vega), and the
robustness at a wider window (**0–21 DTE: n=68, mean +0.69R, bootstrap LB +0.26**;
22+ DTE: −0.42R). Independent cuts agreeing on one mechanism is hard to fake — a
point *for* the edge being real.

**The tension that must be resolved (the crux skeptical flag):** the desk's *own*
aggregate long-vol data says long premium is **structurally losing** — realized
moves undershoot implied by **−10.6%**, beat rate **34%** (the variance risk
premium; options are priced rich). Yet the ≤21 DTE straddle subset wins **59%**
and returns **+0.71R held to expiry.** Held to expiry, a straddle wins ≈ when the
move beats its breakeven (≈ the implied move), so a 59% win vs a 34% aggregate
beat rate is a ~25-point gap. That gap is **either**:
- (a) a **real timing edge** — entering 7–14 DTE buys vega *before* the IV ramp
  fully prices in, so you pay a cheaper debit relative to the eventual move; **or**
- (b) an **artifact** — a generous shadow mark/exit model and/or a favorable-regime
  small sample with no dates to check.

**The current shadow data cannot distinguish (a) from (b).** That is the whole
reason the campaign exists. The real-friction, real-mark, multi-cycle paper test
is precisely what separates a genuine timing edge from a well-dressed illusion.
Hold the skeptical prior: most "edges" that appear in simulated data die under
real fills. If this one collapses toward the −0.42R / 34% aggregate reality once
friction and honest marks are applied, it was (b). If it survives, it was (a) —
and you have something rare.

**Window refinement:** run the campaign on the **0–21 DTE window (sweet spot
7–14)**, not just 7–14 — larger sample, still robust (LB +0.26), sharp 22-DTE
cutoff to exclude.

## Safety rails (unchanged throughout)

- Entirely paper until Gate C says PROVEN. No real dollar at risk in the campaign.
- `liveTradingAllowed` / `brokerSubmitAllowed` stay hard-off. A live pilot is a
  separate, explicit, operator-acked step — never automatic.
- The drawdown pause on **live** capital remains fully in force.
- Position sizing for any eventual pilot comes from account size, not conviction.

## One-line summary

Ship the two fixes → point the paper loop at 7–14 DTE straddles on liquid
large-caps **with real friction, across cycles** → at 30 outcomes, the data tells
you honestly whether you have a strategy or a science project. Either answer is
worth more than another month of ambiguity.
