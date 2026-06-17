# Project Status

Last updated: 2026-06-17.

The desk's "where are we right now" memo. Read this first.

For the shortest durable command brief, start with
`docs/MISSION_CONTROL.md`.

## Verdict

**Healthy read-only desk; manual deployment can be reviewed with warnings.**
Live account sync uses Schwab account API as broker truth for the configured
approved suffix, Schwab option tape is fresh, and all automated live trading
remains locked. The legacy live book is now explicitly marked as
operator-declared long-term holds, so TE, IREN, HIVE, and CLSK no longer hard
block fresh-capital review solely because short-term structure is fragile.

Latest readiness sweep: 2026-06-17 13:52 MT. Capital launch is
`manual-ready-with-warnings`; risk gates are `manual-only`; math verification is
`clean`; Schwab options data is fresh as the primary read-only option quote
tape; paper evidence is still the bottleneck with 30 closed scored outcomes
remaining before any automation promotion. Current live account read: NLV
$1,565.47, cash $599.93, four supported declared long-term holds, zero live-book
hard blockers.

`reports/model_command_center_latest.txt` is now the PM landing page. If this
doc disagrees with that artifact, the command-center artifact wins.

## Priorities (in order)

1. Strategy requirements: keep objectives, gates, data authority, and evidence standards aligned in `docs/STRATEGY_REQUIREMENTS.md`.
2. Mission clarity: keep the one-page command brief in `docs/MISSION_CONTROL.md` sharper than the rest of the docs.
3. Capital deployment readiness: review operator-entered cash manually, keep live submit OFF.
4. Schwab option tape: keep OAuth refresh, chain quality, and strike/risk integration green.
5. Live account lane: read-only, scoped to the configured approved suffix.
6. Paper evidence: run the 12-scenario reducer, then score the top-five focus names.
7. Tracker sync: clean, fail-closed on vendor gaps.
8. Morning brief + ops maintenance: fresh, no silent failures.
9. Docs + artifacts: easy for the next model to inherit.

## Current state

| Lane | State | Notes |
|---|---|---|
| Command center | current | executive summary + canonical report map |
| Mission control | shipped | one-page mission, strategy thesis, data authority, decision ladder, boundaries, and next build priorities |
| Strategy requirements | shipped | hedge-fund-style charter mapping objectives, data requirements, strategy families, gates, metrics, and promotion standards |
| Usage optimizer | shipped | low-context handoff packet for Codex/Claude sessions |
| Desk health | healthy | doctor healthy; paper lane still needs evidence volume |
| Authority manifest | `paper-evidence-only` | hard-pinned, broker submit OFF |
| Live account sync | healthy | matched configured approved suffix; source is Schwab account API |
| Live book | healthy, read-only | 4 matched positions · TE/IREN/HIVE/CLSK declared long-term holds · supported=4, fragile=0, hard blockers=0 |
| Capital deployment | `manual-ready-with-warnings` | deployable cash $599.93; max options risk $89.99; max starter ticket $89.99; reserve $269.97; live submit still OFF |
| Risk gate audit | `manual-only` | 5/12 pass; hard fails 0; promotion fails 3; warnings 4 |
| Tracker | synced | 146 sheet / 146 snapshot; HIVE, TE, CLSK appended; IREN already existed; 0 critical/advisory ticker issues |
| Watchlist closed-loop | shipped | 5-min autorefresh, three-way reconciler |
| Schwab account API | active, read-only | `inferno_schwab_account_sync.py` refreshes approved-account balances/positions, redacts raw account numbers, persists holdings only for the configured suffix, and feeds live account sync without requiring TOS; no order endpoints |
| Schwab options API | active, read-only | OAuth helper and token refresh are live; the option-chain adapter adds quote-quality score/label, liquidity buckets, spread friction, Greek completeness, ATM straddle expected-move proxy, fail-closed quality flags, and strike-selector/risk-policy enforcement when attached; no order endpoints |
| Schwab daily ops tape | active | `inferno_schwab_daily_ops.py` refreshes tokens when possible, pulls the active slate, classifies chains into `tradable-research` / `paper-ready` / `manual-review` / `avoid-chain`, and feeds the action pulse + strike cycle |
| Schwab edge signals | shipped, fresh | bridge module `inferno_schwab_edge_signals.py` reads the chain adapter output and emits per-ticker tier-classified lanes (`tradable-research` / `calibration-watch` / `thin-data` / `no-chain`) plus a cross-sectional regime read; current verdict is `thin-data-only` across AZZ, SNX, IREN, HIVE, TE, and CLSK; framework documented in `docs/SCHWAB_EDGE_OPPORTUNITIES.md` |
| Research Roadmap Phase A | shipped | post-trade learning layer complete: `inferno_outcome_attribution.py` (Brinson decomposition + Eckhardt comfortable-win flag, 12 tests), `inferno_rule_edge_decay.py` (Wilson lower bound + exponential half-life on per-bullet citation tags, 26 tests), `inferno_slippage_estimator.py` (Roll spread math + per-strategy-family **limit-pricing cushion** anchor table — measures the strike selector's worst-case-fill conservatism, not realized slippage; honest framing in module docstring; 29 tests); all three wired into model command center, doctor freshness, and PROJECT_STATUS; theory live in `docs/PERFORMANCE_ATTRIBUTION.md` |
| Research Roadmap Phase B | shipped | portfolio-level layer complete: `inferno_portfolio_correlation.py` (Markowitz/Dalio/Grinold math — pairwise PnL correlation, Herfindahl effective bet count, per-family/per-direction/per-DTE concentration, adverse-scenario overlap; live data immediately surfaced a real finding — 119 active tickets across only 2 families means effective bet count is 2.0, not 119; verdict `concentrated-by-drift`, 18 tests), `inferno_drawdown_protocol.py` (Ulysses-contract sizing ladder, Ulcer Index/Calmar/time-to-recovery math, research-only advisory only; 29 tests); both wired into command center and doctor freshness; theory + sizing ladder + capacity discussion in `docs/PORTFOLIO_CONSTRUCTION.md` |
| Research Roadmap Phase C | shipped | consensus / crowdedness layer complete: `inferno_consensus_monitor.py` reads Schwab edge bridge + portfolio correlation artifact and emits a five-tier verdict (`uncrowded` / `normal` / `crowded-watch` / `consensus-extreme` / `awaiting-data`) from three v1 signals — side-skew lean, own-side direction concentration, family-pair fusion (ρ≥0.70); live data surfaces `own-side-concentration: long-vol-heavy (62/119)` as the desk's current crowdedness lean; verdict today is `normal` (1 of 3 signals leaning); 19 tests; wired into command center and doctor; theory in `docs/CONSENSUS_AND_CROWDEDNESS.md` (Stein-2009, Brunnermeier-Nagel-2004, Lou-Polk-2013, Khandani-Lo-2007); Phase C explicitly lists "not built yet" so the next session knows the path to /movers, sector-ETF vol, VIX term structure, news sentiment |
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
| System map + cleanup | shipped | docs/SYSTEM_MAP.md slotted as the read-this-first doc; MODULE_INDEX now covers 97/97 modules (was 89/97); obsolete root shims removed while root static dashboard files remain preserved for GitHub Pages; OPERATING_MODEL frontend refs updated to point at frontend/modules/ |
| Blow-up guardrails | shipped | six named rules tied 1:1 to historical blow-ups (Niederhoffer, LTCM, Archegos, Amaranth, Karen-the-Supertrader, Cordier); diagnostic-only visibility layer over the operator briefing slate |
| Conviction research map | shipped | research-only whole-universe ranking for giants, sleepers, near-term winners, long-term buy zones, and contradictions |
| Theory references | shipped | one place for primary literature tags used by the audit |
| Scenario backtest | shipped | daily 10+ scenario slate now compares against closed paper/shadow evidence by ticker, strategy family, and DTE window |
| Scenario evidence | shipped | daily 10+ slate now records research-only underlying observations so the backtest can learn before fills close |
| Paper evidence | evidence-building | latest sweep found 0 stageable / 0 auto-paper tickets; 12 shadow scenarios refreshed; 30 closed scored outcomes still needed |

## Live truth lives in artifacts, not docs

| Question | File |
|---|---|
| Is anything broken? | `reports/doctor_latest.txt` |
| What matters right now? | `reports/model_command_center_latest.txt` |
| What should a new model read first? | `reports/usage_optimizer_latest.txt` |
| What is the shortest durable mission brief? | `docs/MISSION_CONTROL.md` |
| How is the system wired? | `docs/SYSTEM_MAP.md` |
| What strategy requirements govern the desk? | `docs/STRATEGY_REQUIREMENTS.md` |
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
| What does Schwab say about option tradability? | `reports/schwab_daily_ops_latest.txt` |
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
- The Schwab lanes are read-only. OAuth tokens stay ignored locally, token
  refresh is automated, account reads are limited to approved-suffix sync, and
  order endpoints are not part of the desk.
- Operator-declared long-term holds live in `data/operator_long_term_holds.json`;
  they stay visible in live-book review but do not hard-block fresh-capital
  review solely because short-term structure is fragile.
- Watchlist intake now flows TOS → sheet → reconcile every 5 minutes.
- Command-center reporting now starts with executive summary, math status, and canonical report map.
- Usage optimizer now creates a compact read-first / do-not-paste handoff to reduce repeated context spend.
- Strike selector now hard-blocks vertical-debit plans where worst-case debit exceeds 95% of strike width (`VERTICAL_DEBIT_MAX_WIDTH_RATIO`), closing the guaranteed-loss leak surfaced by the limit-cushion anomaly investigation.
- Risk policy now enforces a $0.10 visible-quote floor on every buy/sell leg (`VISIBLE_QUOTE_MIN_PRICE`); penny-bid legs no longer slip past the gate.
- Phase A slippage estimator is honestly framed as a limit-pricing cushion metric — Hasbrouck/Almgren-Chriss citations removed since realized-fill decompositions are not yet measurable.
- Export-bridge + export-verifier test suites are deterministic across hosts (both patch `TOS_APP_PATH` in setUp so the production `app_path.exists()` guard does not early-exit when TOS is not installed at the default location).

## What still needs work

- Paper evidence: more closed promotion-quality samples; reducer now provides 12 daily scenarios, scenario observations capture underlying moves, scenario backtest labels thin evidence explicitly, and approval-only names can become paper-only auto selections when all risk gates pass.
- Schwab calibration: option-chain quality is live, but historical chain storage / IV calibration / chain diffing are still next-layer research.
- Live execution authority: intentionally not enabled.
- Capital deployment: manual-ready-with-warnings for review only; no automated submission, and every real order still requires explicit final confirmation.
- Automation promotion: live/manual confirmation only until paper evidence clears promotion gates.
- Paper candidate quality: auto-paper selected names can now advance evidence without waiting on live-style approval; hard-blocked names stay blocked.

## Next moves

1. Treat deployable cash as manual-review-only: stay inside the capital guardrails, keep live submit OFF, and require explicit final confirmation before any real order.
2. Run the command center, capital readiness, Schwab daily ops tape, and risk
   gate audit before sizing any ticket.
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
