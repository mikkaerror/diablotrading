# Premiums, upside and the actual watchlist — 2026-09-06

The desk partly accounts for expensive, volatile stocks, but it does not yet
have a validated test of whether an option is worth its premium over the
intended holding period. A daily-ATR reference adjusts for a stock's movement;
it does not match option duration or isolate an earnings jump. Sector labels
describe exposure, not a demonstrated trading advantage.

Higher stock prices, more time and greater implied volatility can raise dollar
premiums. A call can still lose money when its stock rises if time decay or a
fall in IV offsets the directional gain. See [OIC option price behavior](https://www.optionseducation.org/referencelibrary/faq/option-price-behavior).
IV describes expected movement in either direction; it is not an upside
forecast. See [Schwab's IV explanation](https://www.schwab.com/learn/story/aligning-your-options-with-implied-volatility).

## What the saved data shows

Sources: September 4 tracker (16:27 Mountain), taxonomy (16:29) and alternative
pricing (18:56); September 6 saved ticket-cap policy. These are historical
snapshots, not refreshed executable quotes. Full source timestamps and row
denominators are in `data/inferno_score_threshold_audit.json` under
`universePremiumContext`; the human-readable output is
`reports/score_threshold_audit_latest.txt`.

| Cohort from reference taxonomy | Names | Median stock price | Median daily ATR | Names at/above $100 |
| --- | ---: | ---: | ---: | ---: |
| Semiconductors and equipment | 21 | $223.55 | 4.13% | 14 |
| Infrastructure construction and services | 14 | $261.89 | 3.95% | 10 |
| Industrials and infrastructure | 29 | $187.35 | 3.01% | 21 |
| Entire tracked universe | 183 | — | — | 110 |

Taxonomy uses cached reference data. It is not a calibrated sector policy.
The universe audit deduplicates tickers and discloses missing classifications.

## Assumptions that need correction

1. **Stock price is not spread affordability.** One credit-discovery route
   requires stock price below $100. This conflicts with much of the watchlist,
   but zero current rows pass all that route's other predicates when only the
   nominal-price cutoff is neutralized. Removing it alone adds zero candidates
   on this snapshot. The broader defined-risk short-premium route has no such
   cutoff. The audit now distinguishes structural coverage from the currently
   binding filter; it returns no new candidates.

2. **The long-vol evidence band is a policy assumption, not a valuation.**
   `inferno_trade_evidence.long_vol_hurdle` allows at most 20% implied move,
   and requires 10–20% within seven days of earnings. A synthetic 5% required
   move and a 25% required move are both blocked near earnings even with a
   positive supplied forecast edge. The lower bound can reject a cheaper
   event setup; the upper bound can reject a volatile one. That does not prove
   either is attractive. Both require matched outcome evidence. These enforced
   guards remain unchanged by this audit.

3. **Premium comparisons need actual expiration and event coverage.** Current
   metadata now identifies missing expiration, nonpositive tenor, and the lack
   of a matched option-horizon benchmark. It never substitutes days-to-earnings
   for days-to-expiration or treats ATR as standard deviation. Of 17 saved
   priced structures, three expire before the listed earnings date: NVT, IREN
   and ACN. They may serve a pre-event thesis, but do not cover that earnings
   jump. Same-date earnings/expiration remains timing-unknown.

4. **Making a trade cheaper can remove the desired upside.** The saved ORCL
   September 11 160/165 call spread costs $275 and can make at most $225
   (0.8182R). Its payoff caps at $165, only 3.9174% above the saved $158.78
   stock price. A larger expiration rally adds no profit beyond that cap.
   This is payoff geometry, not a recommendation or forecast. The diagnostic
   now reports this cap instead of treating budget fit as sufficient.

5. **Research construction, simulated budget and live capital differ.** The
   saved limits are $500 construction, $2,000 simulated paper, and $0 live
   capital. Eleven of 17 priced structures fit construction; all 17 fit the
   simulated budget; none passed the saved combined checks. Thirteen of those
   17 structures are the neutral defined-risk short-premium arm. Cheap enough
   and available to price does not establish that the structure expresses a
   bullish thesis. No limits were widened by this audit.

6. **The largest historical moves are not typical earnings outcomes.** The
   concurrent event study contains 68 selected large-move days across 20 names.
   Selecting observations after seeing their large outcomes biases a premium
   benchmark upward. Our review was incorporated into the concurrent change:
   inferred tail medians are descriptive, not inputs to per-name hurdle labels.
   The concurrent daily-ATR ladder rebase to 2/3/4 remains a descriptive
   heuristic, not a validated optimum. Neither that ladder nor curated
   one-session earnings moves establishes fair value for a multiweek option.

## A better research comparison

Freeze an evaluator before testing alternative cutoffs. For each independently
dated earnings event, retain all small and large outcomes, original forecasts,
entry spot, option expiration, quote time, actual strikes/premiums and planned
exit. Keep every variant of the same ticker/event in the same chronological
split. Training outcomes must already be observable at the next test entry.

Compare the unchanged policy with diagnostic counterfactuals using the same
source snapshots, contract loss budget and friction assumptions. Report results
by verified event coverage, option tenor, individual name and the descriptive
cohorts above. Compare bullish structures on their expiration payoff curves,
breakeven, maximum loss and capped upside; compare realized net option R only
where reconciled option-price evidence supports it. Shares may serve as an
underlying-return baseline, with their different capital requirement explicit.

A successful challenger needs repeatable improvement on untouched later events
under the existing evidence and downside gates, with concentration and missing
data disclosed. More passing rows, a favorable selected-event median, or higher
hit rate alone is not success. Correlated semis and infrastructure exposures
also need joint downside scenarios; sector variety does not imply independent
risk. No candidate, ticket or authority action is part of this comparison.

## Implementation and validation

The score-threshold audit now joins the actual universe, effective saved caps,
priced payoff geometry and event coverage, and flags selected-tail benchmarks.
Its catalog also corrects a documentation error: support/ATR is a warning in
the credit scanner, not an admission predicate. Comparability metadata was
included in concurrent commit `59ae9c6`; this audit's remaining changes are
diagnostic only and do not alter candidate selection or thresholds.

Validation: 36 focused and 1,996 full-suite tests pass; math invariants (12
artifacts), secret hygiene and diff whitespace checks pass. Doctor still
reports operational/data-readiness attention items. Results are recorded in
the accompanying knowledge note and manual audit run state. Historical label
integrity remains the blocker described in
[[MODEL_CALIBRATION_REVIEW_2026-09-06]]. No promotion progress is claimed.
