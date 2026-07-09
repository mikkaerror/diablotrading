# Pre-Registered Kill/Confirm Gates — the one campaign, dated

- **Registered:** 2026-07-06 (before the campaign accumulated evidence — this is
  the point: no moving the goalposts after seeing results).
- **Author:** Claude (research lane). Research-only. `liveTradingAllowed=false`,
  `brokerSubmitAllowed=false` — unchanged, not in question.
- **Purpose:** give the pre-earnings long-premium campaign a clean, dated verdict
  instead of an endless polish loop. The honest prior is **NO edge**. These gates
  make "no" a cheap, clean answer.

## The unit of evidence

`eventId = ticker + earnings-date`. Count **distinct events**, never trades.
Correlated repeats on the same name do not add independent evidence. All CIs are
cluster-bootstrap resampled by `eventId`.

## CONFIRM (all must hold, simultaneously, on distinct-event evidence)

| Gate | Threshold |
|---|---|
| Distinct events | ≥ 30, spanning ≥ 2–3 earnings cycles |
| Win-rate Wilson lower (by event) | ≥ payoff-implied breakeven + 0.03 margin |
| Expectancy lower bound (cluster-bootstrap) | > 0 |
| Profit factor | ≥ 1.25 |
| Cluster-bootstrap 95% CI on mean net-R | **lower bound > 0** (does not cross zero) |
| Max drawdown | ≥ −6R |
| False-positive rate | ≤ 0.45 |
| Concentration | no single name contributes > 35% of total net-R |

If all hold → the campaign has found something. Promote to the operator for a
human decision. Not before.

## KILL (any one triggers a dated NO — stop developing this family)

1. **≥ 30 distinct events reached AND the cluster-bootstrap 95% CI on mean net-R
   crosses zero.** This is the straddle lead's known failure mode. If it recurs at
   n≥30, the family is noise. Stop.
2. **Expectancy lower bound ≤ 0 at n ≥ 30.** No positive expectancy → no edge.
3. **Concentration failure:** the result depends on ≤ 2 names (any 2 names > 60%
   of net-R). Not a strategy, a coincidence.
4. **Time-box: 60 days from registration (→ 2026-09-04) without reaching 30
   distinct events.** If the funnel physically cannot produce 30 testable events
   in two months, that is itself the verdict: the desk cannot generate the
   evidence its own promotion gate requires. Stop and reallocate.

## What the daily run does with this file

Each nightly run scores current distinct-event evidence against the table above
and writes one line to `data/campaign_verdict_log.csv`
(`date, distinct_events, mean_netR, ci_low, ci_high, expectancy_lb, profit_factor,
top_name_share, status`) where `status ∈ {accruing, CONFIRM, KILL}`. The first day
`status` is `CONFIRM` or `KILL`, the campaign is over and the operator is told.

## Boundary (unchanged)

The daily run never approves a paper ticket, never touches authority, never edits
a risk constant. It gathers and scores evidence. The operator renders the final
call when a gate trips. See CLAUDE.md §8.
