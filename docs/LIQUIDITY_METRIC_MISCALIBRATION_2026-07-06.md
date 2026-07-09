# Decision Memo — The liquidity gate rejects tradeable large-caps (current 0-tickets bottleneck)

- **Date:** 2026-07-06
- **Author:** Claude (research lane)
- **Stage:** research-only. Recalibrates a *quality* gate — not a loosening of
  real-money risk. `liveTradingAllowed=false`, `brokerSubmitAllowed=false`.
- **For:** operator + Codex. After the decouple/chain-pull/budget shipped, the
  campaign still stages **0 paper tickets**. This memo shows why: the
  `atmLiquidityScore` / `thin-atm-liquidity` gate is miscalibrated and rejects
  the liquid names the campaign needs.

## TL;DR

The liquidity gate flags **Google's options as "thin."** When a metric calls
GOOG thin, the metric is wrong, not the market. Live chain data:

| name | ATM spread | chain depth | `atmLiquidityScore` | `thin-atm-liquidity`? |
|---|---|---|---|---|
| **GOOG** | **4.7%** (tight) | top OI 7,279 / vol 8,275 | **61** | **flagged thin** |
| FCX | 6.5% | OI 61-band | 61 | flagged thin |
| **IREN** (meme-miner) | 2.6% | OI/vol ~16k (frenzy) | **90 "usable"** | clean |
| TXN | 16.8% | liquid chain, low-OI ATM strike | **20** | flagged thin |

`thin-atm-liquidity` fires on **10 of 12** names. A flag that fires on Google and
TXN isn't detecting thin markets — it's mis-set.

## Three concrete flaws

**1. It conflates speculative flurry with execution quality.** The score is
`spread band + raw OI + raw volume` (`liquidity_score_for_contract`). Raw
volume/OI reward a meme-stock options frenzy (IREN: OI/vol ~16k → 90) over a
deep, orderly market (GOOG: 61). For *getting filled at a fair price*, GOOG is far
safer than IREN — the ranking is backwards. Volume ≠ fillability; **spread** is the
execution signal, and GOOG's 4.7% beats IREN in the way that actually matters.

**2. The `< 70` threshold over-rejects.** GOOG scores 61 on a tight 4.7% spread and
a deep chain, and is flagged thin. If a genuinely liquid mega-cap can't clear the
bar, the bar rejects essentially every realistic candidate — which is exactly what
we observe (0 tickets stage).

**3. It's ATM-strike-fragile.** TXN scores 20 because the single strike chosen as
"ATM" happened to be a low-OI hole, even though the TXN chain has liquid strikes
nearby. Scoring off one strike lets a liquid name look untradeable.

## Why it matters right now

This gate is the **current binding bottleneck**. The decouple removed the cap
wall; the chain-pull put GOOG/TXN/FCX in scope — and then this gate rejects them
as "thin." So the campaign that's supposed to test the straddle on liquid
large-caps can't stage a single one, on a metric that rates a crypto-miner's
options above Google's.

## Fix (recalibrate the quality gate — not a risk loosening)

1. **Make ATM bid/ask *spread* the primary tradeability gate.** Spread is the
   direct execution cost. Gate on `atmSpreadPct ≤ ~10-12%` (GOOG 4.7% and FCX 6.5%
   pass; TXN 16.8% and the wide miners fail). Use OI as a *secondary floor* (e.g.
   ATM-window OI ≥ some minimum), and stop letting raw *volume* alone lift a
   wide-spread name over the line.
2. **Lower / re-derive the composite threshold.** 70 is too high for the current
   scoring. Either drop it (~50-55) or, better, replace the composite pass/fail
   with the spread-primary rule above.
3. **Make ATM robust.** Compute the ATM liquidity from a *window* of the nearest
   3-5 strikes (median OI/spread), not a single strike, so one OI hole can't tank
   a liquid name.
4. **Validate against a reference set (the key discipline).** Add a test: a basket
   of known-liquid names (GOOG, AAPL, MSFT, SPY, TXN-class) **must pass** the
   liquidity gate on normal chains. If they don't, the gate is miscalibrated *by
   construction.* This is the guardrail that would have caught this months ago.

## Honest caveats

- Some current names *are* genuinely untradeable (BMI 98% spread, AZZ 32%) — those
  should still fail. The fix must keep rejecting truly wide names; it just must
  stop rejecting GOOG/FCX-class ones.
- This does not touch real-money risk. It changes which *simulated* candidates the
  paper loop will evaluate. Live authority is untouched.
- Pair with the event-cap + clustering work: once liquid names stage, the
  distinct-event cap ensures the resulting evidence is independent.

## Acceptance

- After recalibration, GOOG/FCX-class names on tight-spread chains **pass** the
  liquidity gate; BMI/AZZ-class wide chains still **fail**.
- The reference-basket test passes.
- The campaign begins staging paper tickets on liquid large-caps in the 0-21 DTE
  earnings window.
- No authority flag changes.
