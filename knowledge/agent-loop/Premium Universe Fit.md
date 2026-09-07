---
type: research-belief
status: diagnostic-only
date: 2026-09-06
tags: [premium, assumptions, universe-fit, research-only]
---

# Premium universe fit

Belief: high dollar premium can reflect stock price, time and volatility;
neither nominal price nor sector enthusiasm establishes option value. Evaluate
forecast move versus all-in breakeven over the correct horizon, separately
from capital fit and upside participation.

Evidence: the September 4 snapshot has 183 names, 110 at/above the credit
route's $100 cutoff, but zero excluded solely by that cutoff. Semiconductors
have 4.13% median daily ATR; infrastructure construction/services 3.953%.
The saved ORCL call spread caps at +3.9174% of spot for 0.8182R maximum profit.
Eleven of 17 priced alternatives fit the $500 construction limit; 17 fit the
$2,000 simulated budget; zero pass all saved checks. NVT/IREN/ACN structures
expire before the listed earnings event.

Falsifier: a chronological, event-grouped holdout using original quotes and
reconciled option outcomes shows the existing broad cutoffs deliver stable net
R and downside quality across matched tenor/cohort groups. The current saved
data cannot establish that result.

Durable rule: largest realized moves selected after outcomes are tail context,
not typical-event calibration. Do not use days-to-earnings as option tenor,
ATR as standard deviation, budget fit as value, or zero new candidates as
accepted progress. A narrower spread must expose the upside it sells away.

Implementation: `inferno_score_threshold_audit.universe_premium_context` and
`inferno_expected_move_ledger.premium_comparability`. Independent tests in
`tests/test_inferno_universe_premium_audit.py` replay the actual discovery and
long-vol policy predicates, verify payoff/date calculations, and preserve
missing inputs, distinct budget layers and the read-only boundary.

See [[Calibration Evidence Contract]] and
[[PREMIUM_UNIVERSE_REVIEW_2026-09-06]]. Source timestamps and row-level payoff
diagnostics are in `data/inferno_score_threshold_audit.json`.

Validation: 36 focused checks and 1,996 full-suite tests pass. All 12 math
artifacts pass invariants; secret hygiene and `git diff --check` are clean.
Doctor remains in attention for existing operational/data-readiness issues;
research-only and broker-submit-off boundaries remain verified. Manual audit
acceptance is maintenance only: zero promotion-evidence or accepted-progress
points; monetary model cost is unavailable, not assumed zero.
