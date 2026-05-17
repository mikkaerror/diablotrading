# Project Status

Last updated: 2026-05-15.

The desk's "where are we right now" memo. Read this first.

## Verdict

**Healthy manual-only desk.** Live account sync is healthy for the configured
approved suffix, the live book is clear, capital can be reviewed manually with
warnings, and all automated live trading remains locked.

Latest readiness sweep: 2026-05-15 13:36 MT. Capital deployment readiness is
`manual-ready-with-warnings`; risk gates are `manual-only`; math verification is
`clean`; paper evidence is still the bottleneck with 30 closed scored outcomes
remaining before any automation promotion.

`reports/model_command_center_latest.txt` is now the PM landing page. If this
doc disagrees with that artifact, the command-center artifact wins.

## Priorities (in order)

1. Capital deployment readiness: review operator-entered cash manually, keep live submit OFF.
2. Live account lane: read-only, scoped to the configured approved suffix.
3. Paper evidence: produce closed promotion-quality samples.
4. Tracker sync: clean, fail-closed on vendor gaps.
5. Morning brief + ops maintenance: fresh, no silent failures.
6. Docs + artifacts: easy for the next model to inherit.

## Current state

| Lane | State | Notes |
|---|---|---|
| Command center | current | executive summary + canonical report map |
| Desk health | attention | doctor has 1 warning: no viable paper test slate |
| Authority manifest | `paper-evidence-only` | hard-pinned, broker submit OFF |
| Live account sync | healthy | matched configured approved suffix |
| Live book | clear, read-only | 0 positions · 0 fragile · 0 hard blockers |
| Capital deployment | `manual-ready-with-warnings` | operator-entered cash basis; manual review only |
| Risk gate audit | `manual-only` | 0 hard fails; promotion still blocked |
| Tracker | synced | 143 sheet / 143 snapshot; 0 critical/advisory ticker issues |
| Watchlist closed-loop | shipped | 5-min autorefresh, three-way reconciler |
| Falsification engine | shipped | sign-flip bootstrap on every claimed edge |
| Evidence strength scalar | shipped | geometric mean over Wilson · expectancy · N · falsification |
| Kelly sizing | shipped | bootstrap-conservative quarter-Kelly with global risk ceiling |
| Vol premium discriminator | shipped | two-sample bootstrap on (direction × IV bucket) mean R |
| Bayesian win rate | shipped | Beta-binomial posterior with weak conservative prior; Wilson's complement |
| Regime drift detector | shipped | two-sided CUSUM with first-half baseline; catches strategy decay |
| Information gain | shipped | mutual information feature ranking + permutation p-value |
| Black-Scholes primitives | shipped | d1/d2, implied move, deltas, IV-rank conversion (pure lib) |
| Walk-forward validator | shipped | chronological train/validate split; six-state edge survival ladder |
| Factor regression | shipped | hand-rolled logistic regression with bootstrap-CI coefficients |
| Math invariant verifier | shipped | cross-module sanity check against every formula in MATH.md |
| Slate normalizer | staged | scale-invariant percentile ranks; research-only, no authority promotion |
| Paper bootstrapper | shipped | seeds paper ledger at relaxed gating so promotion math can earn Phase 2 |
| Slate normalizer | shipped | scale-invariant percentile ranks; absolute gates are no longer brittle |
| Paper evidence | blocked for automation | no viable paper tests; 30 closed scored outcomes still needed |

## Live truth lives in artifacts, not docs

| Question | File |
|---|---|
| Is anything broken? | `reports/doctor_latest.txt` |
| What matters right now? | `reports/model_command_center_latest.txt` |
| What does the brain see right now? | `inferno_brain_console.py` |
| Did today count as a good day? | `reports/daily_success_latest.txt` |
| What is the live book? | `reports/live_position_review_latest.txt` |
| What exactly blocks new capital? | `reports/live_book_review_packet_latest.txt` |
| Can I size tomorrow's capital? | `reports/capital_deployment_readiness_latest.txt` |
| Which risk gates are blocking? | `reports/risk_gate_audit_latest.txt` |
| What did the paper lane produce? | `reports/paper_test_director_latest.txt` |
| Do the formulas still check out? | `reports/math_verify_latest.txt` |
| What is the morning brief? | `reports/morning_brief_latest.txt` |

If this doc disagrees with those artifacts, the artifacts win.

## What is clean

- Vendor gaps fail closed instead of aborting the refresh.
- Sheet hydration self-heals broken `Setup Rec` / `Signal Trigger` cells.
- The TOS lane stays read-only. Background export triggering is disabled; manual/supervised export remains available.
- Watchlist intake now flows TOS → sheet → reconcile every 5 minutes.
- Command-center reporting now starts with executive summary, math status, and canonical report map.

## What still needs work

- Paper evidence: more closed promotion-quality samples.
- Live execution authority: intentionally not enabled.
- Capital deployment: manual review only; no automated submission.
- Automation promotion: manual approval only until paper evidence clears promotion gates.
- Paper candidate quality: current slate has no clean stageable ticket under cap.

## Next moves

1. Treat deployable cash as manual-review capital only; no live automation.
2. Run the command center, capital readiness, and risk gate audit before sizing any ticket.
3. Let the paper loop accumulate. The reconciler + autorefresh handle
   intake; the question is sample size, not infrastructure.
4. Keep the morning ops lane green so the desk stays trustworthy.
5. Refresh this doc when the desk's verdict shifts. The four other anchor
   docs change rarely; this one is the dashboard.

## Model lanes

- Codex owns capital deployment readiness, risk gates, command-center hygiene, tests, and docs.
- Claude owns native thinkorswim export stabilization and should not change capital authority.
- Shared work must leave a note in `coordination/model_notes.jsonl` and refresh the command center.

## Refresh checklist

When the desk's state shifts materially, update:

- the **Verdict** line
- the **Current state** table
- the **What still needs work** list

Leave the priorities and operating principle alone — those are stable.
