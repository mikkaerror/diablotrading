# Trend-signal comparison — which rule, and the overfitting trap

- **Date:** 2026-07-09
- **Author:** Claude (research lane). Research-only. SPY month-end data committed in
  `research/backtest_data/`. Addresses the two known weaknesses of the base rule:
  slow re-entry and bull-market whipsaw.
- **Data limit hit:** the connected market-data plan only served SPY reliably
  (AGG/QQQ and far-back dates were access-denied), so the true multi-asset model
  (bonds/international as the safe leg) needs a higher data tier or user-supplied
  CSVs. This study is SPY-vs-cash signal variants only.

## Results (real SPY data, 2 regimes)

| Signal | Crash 07–09 CAGR | Crash maxDD | Bull 22–26 CAGR | Bull switches |
|---|---|---|---|---|
| 12m return > 0 (base) | 4.8% | 0.0% | 19.0% | 1 |
| 10-month SMA (Faber) | **11.3%** | −1.9% | 11.7% | 6 |
| 6m return > 0 (fast) | 10.9% | −1.9% | 14.0% | 5 |
| dual: 12m AND 10mSMA | 4.8% | 0.0% | 11.3% | 7 |
| either: 12m OR 10mSMA | 11.3% | −1.9% | 19.5% | 0 |
| *hold SPY* | *−10.3%* | *−47.3%* | *19.5%* | *–* |

## What's real here

1. **The base 12m-return rule re-enters too slowly** — confirmed. In the crash it
   made 4.8% vs 11.3% for the moving-average rule, at essentially equal protection.
   It sits in cash too long after the bottom and misses the rebound.
2. **The moving-average rule re-enters faster but whipsaws in bulls** — 6 switches
   and an 11.7% vs 19% lag in 2022–26. Faster signals catch recoveries and chop in
   calm markets.
3. **There is a genuine speed-vs-whipsaw tradeoff, and no rule wins both cleanly.**
   Where you sit on it is a choice, not an optimization with a single right answer.

## The overfitting caveat (this is the important part)

The "either 12m OR 10m-SMA" rule looks best in *both* windows — crash protection
*and* zero bull-market drag. **Do not trust that at face value.** I compared five
rules on two windows and reported the winner; that is textbook in-sample selection,
the exact data-mining trap McLean & Pontiff quantify (published edges lose ~half
their return out of sample). Two specific reasons the "OR" rule's edge is likely
overstated:

- It only exits when **both** signals turn bearish, so it protects **less in a fast
  crash** (e.g. 2020's −34% in a month) that completes before both monthly signals
  flip. Both 2008 and the 2022–26 dips were slow enough to flatter it.
- Two windows is a tiny sample; the ranking among these rules is well within noise.

## Honest conclusion

Any of the standard trend rules delivers the one benefit that matters: **avoiding a
sustained crash.** The exact signal (12m return vs 10-month average vs a
combination) is a secondary tuning knob with real, opposing tradeoffs — and
optimizing it hard on two windows is the mistake, not the insight. The disciplined
move is to pick **one simple, standard rule** (12-month return or 10-month moving
average — both are literature-standard and both dodge the crash) and follow it
mechanically, rather than fish for the combination that looks best in a backtest.
Simplicity and consistency beat a fitted rule you won't trust when it hurts.

## What would actually advance this (needs data access)

- A **bond safe leg** (real GEM): hold AGG/T-bills instead of flat cash in
  downtrends — bonds rallied in 2008 and would likely improve the defensive return,
  but *hurt* in 2022 when stocks and bonds fell together. Needs AGG history
  (currently access-denied on this plan).
- **More regimes / a continuous multi-decade run** to test signal robustness out of
  sample — the only real cure for the overfitting caveat above.
- Both require either a higher market-data tier or user-supplied price CSVs, which
  the `inferno_dual_momentum_backtest.py` engine already accepts.
