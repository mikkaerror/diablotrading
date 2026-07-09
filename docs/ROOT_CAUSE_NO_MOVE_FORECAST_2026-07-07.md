# Root cause — the straddle can't stage because the desk has no move forecast

- **Date:** 2026-07-07
- **Author:** Claude (research lane). Research-only. No authority/risk/gate change.
- **Status:** this supersedes the assumption in the liquidity handoff that fixing
  liquidity unblocks the straddle campaign. It does not. This does.

## The finding, precisely

The long-vol edge screen (`inferno_trade_evidence.long_vol_hurdle`) is
**philosophically correct**: it only lets a long straddle/strangle stage for paper
if there is a positive edge, defined as

```
edge = forecastRealizedMovePct - (impliedMovePct + frictionPct)
status = "eligible-for-paper-comparison"  requires  forecast is not None AND edge > 0
```

You should only buy premium when you forecast the stock will move **more** than the
options are pricing in, net of friction. That is exactly right.

**But `forecastRealizedMovePct` is never produced.** It is read from the item in
one place (`inferno_trade_evidence.py:373`) and computed by **no model anywhere in
the codebase**. Live data confirms it: **0 non-null instances** across all
`data/*.json`. So `forecast` is always `None`, the hurdle always short-circuits to
`status = "shadow-only-missing-forecast"`, and therefore
`paperComparisonAllowed = False` for **every long straddle/strangle, always.**

## Why this is *the* 1-of-30 root cause

- Every long-vol ticket fails `decision_card` with `long-vol-premium-hurdle` →
  never stages for paper. That is 100% of straddles, independent of liquidity.
- The one scored event on the board is a **CALL_DEBIT_SPREAD** — a vertical.
  Verticals are not in `LONG_VOL_STRATEGIES`, so they **bypass** the hurdle
  entirely. That is *why the only event we have is a vertical, and why the
  straddle families sit at exactly 0.*
- Liquidity, capital-fit, data-freshness are all real, but they are **upstream
  noise** relative to this. Even with every one of them fixed, the straddle arm
  stages **zero**, because the hurdle refuses it for want of a forecast.

The gate is not miscalibrated. It is **correctly refusing to buy premium with no
view on whether realized will beat implied.** That refusal is the honest one.

## What this means (the hard part)

This is the structural reason the long-premium program has no demonstrable edge.
Buying a straddle with **no realized-move forecast** is, by construction, paying
the variance risk premium and hoping. The desk's own screen knows this and blocks
it. We have been trying to unblock a funnel whose final gate is honestly telling
us we have no edge signal.

So "fix the gate so straddles flow" would be exactly the wrong move — it would
manufacture candidates by deleting the one check that requires an edge. Do not do
that.

## The only honest options

1. **Build a realized-move forecast.** The single legitimate path to a meaningful
   straddle campaign: a model that estimates realized move around earnings and
   compares it to the implied move — e.g., a name's history of realized-vs-implied
   earnings moves (does it systematically move more than priced?), plus any
   conditioning signal (dispersion, term structure, prior surprise). Only names
   where forecast > implied + friction stage. *Then* the campaign tests a real
   hypothesis instead of a coinflip. This is real work and may still conclude "no
   edge" — but it would be an honest test.
2. **Test the families that don't need a vol forecast.** Verticals/directional
   structures bypass the hurdle because their edge source is direction/defined
   risk, not realized-vs-implied vol. If the desk has any directional signal, the
   vertical arm is the only one it can honestly stage today. (Caveat: the replay
   shows verticals *underperforming* straddles, and the one live vertical lost —
   so this is not a promising base either.)
3. **Accept the verdict early.** If there is no forecast model and no intent to
   build one, then the long-premium program has no basis, and the honest move is
   to stop developing it now rather than accrue 30 events of a blind trade to
   arrive at the KILL we can already see coming.

## Recommendation

Do **not** weaken the hurdle. Either commit to building the realized-move forecast
(option 1) — which is the only thing that could turn this into a real edge — or
recognize that its absence *is* the answer for the straddle. The daily verdict
monitor will keep accruing the vertical arm honestly in the meantime; but the
straddle arm cannot produce a single event until a forecast exists.

## Handoff note (corrects the liquidity handoff)

`docs/CODEX_HANDOFF_LIQUIDITY_GATE_2026-07-07.md` says the liquidity fix unblocks
event #2. That is true only for the **vertical** arm. The **straddle** arm stays
at 0 until a `forecastRealizedMovePct` model exists. Both handoffs are still worth
shipping (liquidity is genuinely miscalibrated), but neither stages a straddle.
