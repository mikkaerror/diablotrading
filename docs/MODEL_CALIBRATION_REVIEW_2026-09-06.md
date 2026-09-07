# Model calibration review — 2026-09-06

The first upgrade is to the evidence model. The archive is not ready to train
a trading challenger: historical score provenance is uncertain and most usable
shadow option outcomes were reviewed before their expiration session opened.
Changing score weights against those labels would optimize an accounting error.

## Measured weaknesses

Read-only local audit at 20:25 Mountain, using the persisted September 6 ledgers:

| Assumption under challenge | Evidence | Revised belief / action |
| --- | --- | --- |
| Hundreds of option rows are hundreds of independent trials | 907 finite-R closed rows: 3 paper, 904 shadow. Only 136 source/ticker/expiration exposure groups; 771 repeated rows; largest group 27. These groups are proxies, not independent earnings events. | Keep source and repeated-exposure denominators visible. Never use raw row count as independent sample size. |
| A closed shadow label represents an expiration payoff | 713/904 finite-R shadow rows were reviewed before expiration-day regular open; remaining 191 lack verified settlement-time lineage. The old reviewer used the latest mark and admitted expiration day at midnight. | Historical labels require reconciliation. Future reviewer waits until the next day and uses only an exact-date close in a later Schwab history snapshot. No old ticket was reopened or re-scored by this audit. |
| Stored ranks are the original predictions | Scenario merges refresh scores; paper/shadow merges replace score context while retaining earlier outcomes. All 907 option and 1,958 scenario rows lack the new immutable capture contract. | Capture entry scores prospectively. Preserve absent legacy provenance; do not backfill it with hindsight. |
| `priorityScore` belongs in 0–100 bands | All 725 scored option rows fell into 0–49. | Use native-value empirical quartiles, keep tied values together, and display source-specific groups. The 723 score-bearing shadow rows now occupy four groups of 182/180/181/180. |
| A readiness score of 95 should predict a 95% win rate | The prior diagnostic compared hit rates to score-band midpoints, despite stating that scores were ranks. | Remove probability-gap judgments. Diagnose option ranking against mean R; hit rate stays descriptive. |
| The assumption report updates its beliefs | Its prose said there were no closed option scores while calibration counted 725. Other claims named old candidates and permanently absent DTE cohorts. | Derive claims and unknown states from input artifacts; preserve source generation timestamps. |

The counted paper strategy report has 3 scored outcomes, 3 distinct events,
mean R −0.635417, and 27 outcomes still needed for its sample gate. That is
insufficient evidence of an advantage. Reaching the sample minimum alone would
not establish positive expectancy or authorize execution.

## Changes implemented

- Immutable entry-score snapshots for new paper, shadow, and scenario records;
  merging retains the original snapshot even when its fields are missing.
- Calibration reads each source once, separates paper/shadow summaries, labels
  legacy score provenance and repeated exposures, rejects nonfinite/boolean
  numeric inputs, and exposes definitely premature expiration reviews.
- Priority buckets now use native ranks. Probability-gap fields remain null for
  compatibility; they no longer affect verdicts. Option rank inversions use mean
  R so many tiny wins cannot hide worse payoff economics.
- Future shadow reviews use an exact expiration-day equity close from a later
  local Schwab history capture. No current-mark or neighboring-date fallback.
  Missing/conflicting history remains pending. Existing closed records stay intact.
- Assumption checks are source-driven. Zero passing candidates no longer receive
  a finding titled “creating measurable paper chances.” The bootstrap document
  now sends readers to the current paper count instead of asserting 0/30.

These are research/evidence changes. Risk constants, eligible universe,
approvals, paper ticket states, broker state, and authority were not changed by
the audit. No ledger-producing review command was run.

## Next challenger experiments

1. **Repair labels before optimizing ranks.** Build a separate reconciliation
   dataset with immutable entry economics, exact expiration-close provenance,
   event identity, and exclusion reasons. Do not overwrite the source ledger.
   Freeze the evaluator and dataset version before comparing models.
2. **Challenge readiness with simple baselines.** Compare the existing rank to a
   constant/no-signal baseline and a structure/premium-hurdle-only rank. Hold
   source, strategy, and horizon constant. Evaluate mean net R and downside,
   with spreads and fees stated; underlying direction alone is not option P/L.
3. **Ablate the technical story.** Compare the baseline to the same model plus
   normalized momentum/RVOL features. Treat TOS and Schwab mirrors of the same
   signal as one information source. Keep the extra features only if they add
   repeatable value on untouched later events, not merely better in-sample fit.
4. **Use honest temporal comparisons.** Keep all snapshots and strategy variants
   of an event in the same fold; training outcomes must be known before the
   test period begins. Freeze hyperparameters before reading the holdout. Report
   concentration, missingness and excluded rows alongside performance. A failed
   challenger is a useful result; it does not justify relaxing trading gates.

This follows the methodological distinction between prediction-time information
and leakage in [scikit-learn's guidance](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage)
and its cautions on [dependent samples and temporal evaluation](https://scikit-learn.org/stable/modules/cross_validation.html).
These are proposed research experiments, not a trained model or trading policy.

## Remaining limits

The old archive is retained and explicitly inadmissible for fitting; this pass
does not reconstruct historical entry scores or certify any strategy's edge.
Exact-date equity-close intrinsic values remain proxies for option outcomes.
Legacy paper outcome review, scenario calendar-day/price timing, and refreshed
entry economics need separate reconciliation before they can supply clean
training labels. Source separation does not remove correlated events. A new
LLM's availability does not resolve any of these measurement problems.

## Validation

63 focused tests passed. The full shared-workspace suite passed 1,974 tests,
including concurrent quote-model and stale-fixture repairs by another editor.
Math verification checked 12 artifacts with zero violations; secret hygiene and
`git diff --check` passed. Doctor verified paper-evidence-only authority and
broker submission off, while retaining 35 operational attention items.
This is verified engineering maintenance, with zero paper-evidence progress
points and no promotion-gap reduction.
