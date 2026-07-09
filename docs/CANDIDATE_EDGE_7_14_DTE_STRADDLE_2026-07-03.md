# Research Finding — A candidate edge: 7–14 DTE pre-earnings straddles on liquid large-caps

- **Date:** 2026-07-03
- **Author:** Claude (research lane)
- **Stage:** research-only. This is a hypothesis with a robust *shadow* signal.
  It is **not** a green light to trade real money. `liveTradingAllowed=false`,
  `brokerSubmitAllowed=false`.
- **For:** the operator + Codex. The single most decision-relevant finding in
  the desk's closed evidence.

## TL;DR

Mining the 150 closed outcomes in `inferno_dte_policy_analysis.json`, exactly
one cut shows a **robust positive edge**, and it is mechanistically sensible:

> **Long straddle, entered 7–14 days before earnings, on liquid large-caps.**

| cut | n | mean net-R | win rate | bootstrap 95% lower bound |
|---|---|---|---|---|
| Long Straddle **7–14 DTE** | 39 | **+0.87** | **59%** | **+0.32** |
| Long Straddle 15–21 DTE | 22 | +0.42 | 32% | −0.29 (not robust) |
| Long Straddle 22–35 DTE | 27 | **−0.41** | 7% | −0.70 |
| Vertical Debit (all) | 50 | −0.39 | 38% | −0.57 |
| **Everything (all 150)** | 150 | +0.09 | 37% | −0.14 |

The aggregate desk edge is ~zero. But it is **hiding a strong, narrow edge inside
a losing average**: 7–14 DTE straddles are decisively positive, while the same
structure at 22–35 DTE is one of the worst cuts in the book. Averaging them
together (the "long premium" monoculture) is why the desk looks edgeless.

## Why this is not a data ghost

- **Not one-ticker:** 7 distinct liquid names — ACN(9), MRVL(7), DELL(6),
  ORCL(6), CIEN(5), HPE(4). (ACN is 23% of the cohort — some concentration, not
  fatal.)
- **Not one-trade:** mean is +0.87R raw; still **+0.49R** after deleting the
  three biggest wins. The edge survives outlier removal.
- **Not multiple-comparisons fishing:** only 4 cuts had n≥8; ~0.2 false positives
  expected at 5%; this cut's lower bound (+0.32) is far from marginal.
- **Payoff math is healthy:** avg win +1.9R, avg loss −0.6R → payoff 3.15:1 →
  breakeven win rate 24%. Actual win rate 59%. Wide margin of safety.
- **Mechanism is real:** 7–14 DTE captures the pre-earnings **IV expansion** (vega
  gains as implied vol ramps into the event) plus the move, while avoiding the
  theta bleed that kills the 22–35 DTE cohort and the last-day IV crush of 0–6
  DTE. The edge is *timing the vol ramp*, not predicting direction.

## The three caveats that must gate any excitement

1. **All 39 are `risk-failed` (non-admissible).** The desk's gates rejected every
   one — almost certainly because a full large-cap straddle debit exceeds the
   ticket cap. So this is an edge on structures **the ~$788 account cannot
   currently afford.** This is the central tension, not a footnote.
2. **Shadow, modeled friction.** These are simulated fills with modeled (not
   realized) slippage. Real spreads on entry/exit could erode the edge. The
   +0.32 lower bound has margin, but real friction is the live risk.
3. **59% win rate is high for long straddles** (typical is 40–50%). Either the
   7–14 DTE entry genuinely times the IV ramp well, or the shadow **exit model is
   generous**. Must be checked against realized paper exits.

## What to do with it (in priority order)

1. **Make this THE hypothesis the paper loop proves.** Once the paper/live
   decouple + priority-slate chain-pull ship, point paper staging squarely at
   *7–14 DTE straddles on liquid large-caps* (ACN, MRVL, DELL, ORCL, CIEN, HPE and
   peers). Gather ~30 real-friction paper outcomes on this exact rule. That single
   test decides whether the desk has a real edge. Nothing else is a better use of
   the evidence loop.
2. **Solve the account-size tension.** A full ORCL/ACN straddle is unaffordable at
   $788. Options: (a) paper it now (simulated, no capital needed — this is what the
   decouple unlocks); (b) test a **cheaper proxy that captures the same IV-ramp
   mechanism** — e.g. a 7–14 DTE debit *spread* or a straddle on a lower-priced
   liquid name — and see if the edge survives the cheaper structure; (c) with a
   larger account, the full straddle becomes affordable.
3. **Scrutinize the exit model.** Pull the actual exit logic behind these shadow
   R's; confirm the 59% win rate isn't an artifact of optimistic marks.
4. **Kill the losers explicitly.** The data says 22–35 DTE straddles and Vertical
   Debits are negative-edge. Stop generating them as candidates; they're diluting
   everything.

## Honest bottom line

For the first time, the desk's own evidence contains something that looks like a
real edge — narrow, mechanistic, on tradeable names, statistically robust in
shadow. It is **not** proven (shadow, non-admissible, unpriced friction), and it
may be **untradeable at the current account size** until it's shown to survive in
a cheaper structure. But it is the one lead worth everything: it turns the paper
evidence loop from "grind 30 random outcomes" into "prove or kill one specific,
promising rule." That is the difference between a science project and a strategy.

No real money. Prove it on paper first.
