# Project Status

Last updated: 2026-05-19.

The desk's "where are we right now" memo. Read this first.

## Verdict

**Healthy manual-only desk.** Live account sync is healthy for the configured
approved suffix, the live book is clear, capital can be reviewed manually with
warnings, and all automated live trading remains locked.

Latest readiness sweep: 2026-05-19 14:13 MT. Capital deployment readiness is
`manual-ready-with-warnings`; risk gates are `manual-only`; math verification is
`clean`; paper evidence is still the bottleneck with 30 closed scored outcomes
remaining before any automation promotion. The new conviction v2 layer now
adds best-balanced rankings, and the paper lane can auto-select approval-only
setups for simulated paper evidence while keeping live orders locked.

`reports/model_command_center_latest.txt` is now the PM landing page. If this
doc disagrees with that artifact, the command-center artifact wins.

## Priorities (in order)

1. Capital deployment readiness: review operator-entered cash manually, keep live submit OFF.
2. Live account lane: read-only, scoped to the configured approved suffix.
3. Paper evidence: run the 12-scenario reducer, then score the top-five focus names.
4. Tracker sync: clean, fail-closed on vendor gaps.
5. Morning brief + ops maintenance: fresh, no silent failures.
6. Docs + artifacts: easy for the next model to inherit.

## Current state

| Lane | State | Notes |
|---|---|---|
| Command center | current | executive summary + canonical report map |
| Usage optimizer | shipped | low-context handoff packet for Codex/Claude sessions |
| Desk health | healthy | doctor green; paper lane still needs evidence volume |
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
| Paper bootstrapper | shipped | seeds paper ledger at relaxed gating so promotion math can earn Phase 2 |
| Paper bottleneck reducer | shipped | targets 12 paper/shadow scenarios daily; top five become review focus |
| Slate normalizer | shipped | scale-invariant percentile ranks; absolute gates are no longer brittle |
| Math config (audit surface) | shipped | one file pins seed / resample / threshold / verdict defaults for migration |
| Trade conviction audit | shipped | per-ticket math case (bull / bear / disagreements / falsification triggers / blow-up risks) with peer-reviewed citations; refuses to be a yes-man |
| Master-trader principles | shipped | four operator-grade rules wired into the conviction auditor: PTJ R:R floor (bear < 1.5x, disagreement < 1.0x), Taleb steamroller bear on concave structures, Marks pendulum bear on rich IV + long premium, Klarman SIT-OUT advisory when nothing clears readiness 75 with classified edge; long-form synthesis in docs/MASTER_TRADERS.md, 14 new citations in THEORY_REFERENCES.md |
| System map + cleanup | shipped | docs/SYSTEM_MAP.md slotted as the read-this-first doc; MODULE_INDEX now covers 97/97 modules (was 89/97); pre-migration legacy removed (briefing_job.py, run_morning_inferno.sh, root index.html / app.js / styles.css); OPERATING_MODEL frontend refs updated to point at frontend/modules/ |
| Blow-up guardrails | shipped | six named rules tied 1:1 to historical blow-ups (Niederhoffer, LTCM, Archegos, Amaranth, Karen-the-Supertrader, Cordier); diagnostic-only visibility layer over the operator briefing slate |
| Conviction research map | shipped | research-only whole-universe ranking for giants, sleepers, near-term winners, long-term buy zones, and contradictions |
| Theory references | shipped | one place for primary literature tags used by the audit |
| Scenario backtest | shipped | daily 10+ scenario slate now compares against closed paper/shadow evidence by ticker, strategy family, and DTE window |
| Scenario evidence | shipped | daily 10+ slate now records research-only underlying observations so the backtest can learn before fills close |
| Paper evidence | auto-paper evidence lane | 1 auto-selected paper setup staged; 30 closed scored outcomes still needed |

## Live truth lives in artifacts, not docs

| Question | File |
|---|---|
| Is anything broken? | `reports/doctor_latest.txt` |
| What matters right now? | `reports/model_command_center_latest.txt` |
| What should a new model read first? | `reports/usage_optimizer_latest.txt` |
| What does the brain see right now? | `inferno_brain_console.py` |
| Did today count as a good day? | `reports/daily_success_latest.txt` |
| What is the live book? | `reports/live_position_review_latest.txt` |
| What exactly blocks new capital? | `reports/live_book_review_packet_latest.txt` |
| Can I size tomorrow's capital? | `reports/capital_deployment_readiness_latest.txt` |
| Which risk gates are blocking? | `reports/risk_gate_audit_latest.txt` |
| What did the paper lane produce? | `reports/paper_test_director_latest.txt` |
| What 10+ scenarios should we track? | `reports/paper_bottleneck_reducer_latest.txt` |
| What did the scenario observations teach us? | `reports/scenario_evidence_latest.txt` |
| What can today's scenario slate honestly teach us? | `reports/scenario_backtest_latest.txt` |
| Do the formulas still check out? | `reports/math_verify_latest.txt` |
| What's the math case for each ready trade? | `reports/trade_conviction_audit_latest.txt` |
| Which blow-up patterns is today's slate brushing against? | `reports/blowup_guardrails_latest.txt` |
| Which giants, sleepers, and winners deserve attention? | `reports/conviction_research_latest.txt` |
| What is the morning brief? | `reports/morning_brief_latest.txt` |

If this doc disagrees with those artifacts, the artifacts win.

## What is clean

- Vendor gaps fail closed instead of aborting the refresh.
- Sheet hydration self-heals broken `Setup Rec` / `Signal Trigger` cells.
- The TOS lane stays read-only. Background export triggering is disabled; manual/supervised export remains available.
- Watchlist intake now flows TOS → sheet → reconcile every 5 minutes.
- Command-center reporting now starts with executive summary, math status, and canonical report map.
- Usage optimizer now creates a compact read-first / do-not-paste handoff to reduce repeated context spend.

## What still needs work

- Paper evidence: more closed promotion-quality samples; reducer now provides 12 daily scenarios, scenario observations capture underlying moves, scenario backtest labels thin evidence explicitly, and approval-only names can become paper-only auto selections when all risk gates pass.
- Live execution authority: intentionally not enabled.
- Capital deployment: manual review only; no automated submission.
- Automation promotion: live/manual confirmation only until paper evidence clears promotion gates.
- Paper candidate quality: auto-paper selected names can now advance evidence without waiting on live-style approval; hard-blocked names stay blocked.

## Next moves

1. Treat deployable cash as manual-review capital only; no live automation.
2. Run the command center, capital readiness, and risk gate audit before sizing any ticket.
3. Let the paper loop accumulate. Use the reducer's top-five focus list for
   review, use scenario evidence to capture underlying movement, then use
   scenario backtest to decide what the full 12-scenario slate can and cannot
   teach us after the fact.
4. Use `reports/conviction_research_latest.txt` as the watchlist intelligence layer: giants for bell-cow confirmation, sleepers for investigation, contradictions for restraint.
5. Keep the morning ops lane green so the desk stays trustworthy.
6. Start fresh sessions from `reports/usage_optimizer_latest.txt` instead of old chat history.
7. Refresh this doc when the desk's verdict shifts. The four other anchor
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
