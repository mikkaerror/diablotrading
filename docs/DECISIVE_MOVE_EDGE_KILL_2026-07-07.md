# Decisive finding — the move-edge is negative and the one conditioning signal fails declustering

- **Date:** 2026-07-07
- **Author:** Claude (research lane). Research-only. No authority/risk/gate change.
- **Bottom line:** the desk's own 100-record realized-vs-implied ledger already
  contains the answer for the long-straddle program, and it is **no edge**. This
  is now shown from data, not prior.

## The variance risk premium is negative in this universe

From `data/inferno_expected_move_ledger.json` (100 closed long-vol records):

- mean implied move **32.5%**, mean realized abs move **21.9%** → **move edge
  −10.6%.** Stocks move materially *less* than the options price in.
- beat rate **34%** (realized beat implied in only 34 of 100).
- The ledger's own verdict: `move-edge-negative / historical-edge-not-admissible`.

Buying premium in this universe is, on average, paying ~10 points of implied move
you don't get back. That is the variance risk premium working against the buyer,
exactly as theory predicts.

## The one conditioning signal — low implied move — is a two-name mirage

The only positive cohort was the 10–20% implied-move bucket (beat 56%, +0.91R,
n=43), which is also the band the desk's hurdle targets. Decomposed by name:

| name | n | sumR | meanR |
|---|---|---|---|
| DELL | 9 | +40.9 | **+4.54** |
| HPE | 3 | +9.1 | +3.05 |
| MRVL | 8 | +2.6 | +0.33 |
| (6 others) | 23 | all ≤ 0 | −0.3 to −0.9 |

- DELL + HPE = **+50.0R = 127% of the bucket's +39.3R total.** Every other name
  net-negative but MRVL.
- **10–20% band excluding DELL/HPE: n=31, meanR −0.35, beat 39%.**
- **Whole ledger excluding DELL/HPE: n=83, meanR −0.36.**

Strip 2 of 18 names and every cohort — including the "best" one — is a loss. The
low-implied-move signal that looked like the seed of a forecast is DELL and HPE
and nothing else.

Note: DELL's **+4.54R mean over 9 trades** is an extreme outlier and may be a data
artifact (e.g. a mismarked entry debit inflating R). Either way it does not help:
if real, it is one name; if artifactual, the headline +0.33R is overstated and the
program is worse than shown.

## What this resolves

1. **Option 1 of the root-cause memo (build a move forecast) has been tested in
   its simplest defensible form** — condition on implied-move bucket, use the
   historical realized/implied relationship. The signal does not survive
   declustering. The data to build a forecast exists; the *signal* to build it on
   does not.
2. The "0 of 30 scored paper outcomes" framing implied the evidence wasn't in yet.
   It largely is: **100 closed long-vol outcomes across 18 names, declustered, say
   no.** A forward paper campaign would gather cleaner (friction-charged,
   pre-registered) evidence, but its honest prior is now strongly negative, not
   merely agnostic.
3. This is all still **friction-blind** (the ledger, like the DTE replay, does not
   charge spread). Real friction makes it worse, never better.

## Recommendation (unchanged direction, now decisive)

- **Do not weaken any gate to make straddles flow.** The gates are correctly
  refusing a negative-edge trade.
- **Do not invest in a move-forecast model on this universe/structure** unless a
  *new* conditioning variable is proposed that plausibly survives declustering
  (something structural, not another slice of the same 18 names). Absent that, the
  expected value of building it is negative.
- **The straddle program's verdict is KILL, supportable from data.** The forward
  campaign can still run as confirmation and to catch the small chance the
  declustered forward sample differs — but resourcing should reflect that this is
  a confirmation of "no," not a search for "yes."
- The **vertical/directional arm** remains the only family that could stage
  without a vol forecast, but the replay shows it underperforming straddles and
  the one live vertical lost — so it is not a rescue, just the next thing to test
  honestly if there's appetite.

## The honest one-liner

The desk kept asking "why can't we stage the straddle?" The deepest answer is:
because it has no edge, and every gate that blocks it is telling the truth.
