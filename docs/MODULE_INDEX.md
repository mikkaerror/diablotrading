# Inferno Module Index

Curated index of every `inferno_*.py` module, grouped by the layer it operates in. Each row gives a one-line purpose, the canonical input/output artifacts, and whether the module runs on a schedule or only on operator command.

This is the *navigational* doc — when you need to find which module owns a piece of behaviour, start here, then open the module's docstring for the contract. Module docstrings are the source of truth; this file is a directory.

Last updated: 2026-05-25.

For the one-page purpose and strategy brief, start with
[`MISSION_CONTROL.md`](MISSION_CONTROL.md). This file is the module directory,
not the mission statement.

## Layer overview

```
Foundation        — config, I/O, web server, shared primitives
Data ingestion    — bring evidence into the desk
Monitoring        — what is happening right now
Decision          — what should the operator do today
Breathing         — is the system alive and stable
Thinking          — math, hypotheses, counterfactuals
Integration       — chained outputs that combine the layers above
Observability     — render the brain for humans
Operations        — paper / broker / cloud surfaces
Safety            — authority, risk, secrets
```

## Foundation

| Module | Purpose | Output |
|---|---|---|
| `inferno_config.py` | Centralised config: paths, allowed suffixes, shortcut strings, timezone helper | `local_now()` |
| `inferno_io.py` | Atomic write helpers with errno-35 retry. Canonical write primitive | `atomic_write_*`, `append_text` |
| `server.py` | Local dashboard server + canonical `DATA_DIR`/`REPORTS_DIR` | served on `:8000` |

## Data ingestion

| Module | Purpose | Schedule |
|---|---|---|
| `inferno_dawn_pipeline.py` | Morning data refresh — scores the slate, emails the brief | 06:00 daily |
| `inferno_downloads_manager.py` | Catalogue and import files dropped into the watch directory | continuous |
| `inferno_downloads_watch.py` | LaunchAgent-loaded file-system watch on `~/Downloads` | continuous |
| `inferno_ticker_universe_audit.py` | Verify the tracker universe is healthy and complete | each ops sweep |
| `inferno_data_readiness_audit.py` | Confirm the desk has the data it needs for today's run | each ops sweep |
| `inferno_watchlist_ingest.py` | Bridge from `data/inferno_watchlist_input.json` to the Google Sheet; now writes column A directly via gspread (staged-file fallback if creds missing) | operator-triggered + autorefresh |
| `inferno_tos_watchlist_extract.py` | **NEW** Accessibility-tree scrape of the live TOS watchlist with Downloads CSV fallback; populates the ingest input slot | every 5 min |
| `inferno_watchlist_reconciler.py` | **NEW** Three-way drift detector across TOS extract ∪ sheet ∪ tracker | every 5 min + on-demand |
| `inferno_watchlist_autorefresh.py` | **NEW** 5-minute closed-loop coordinator: extract → (apply if delta) → reconcile → dawn refresh breadcrumb | every 5 min LaunchAgent |
| `install_inferno_watchlist_autorefresh_service.py` | **NEW** LaunchAgent installer for the autorefresh service | operator-triggered |
| `inferno_schwab_oauth.py` | Local read-only Schwab OAuth helper: auth URL, token exchange, refresh, ignored vault status | operator-triggered + daily ops refresh |
| `inferno_schwab_options.py` | **NEW** Read-only Schwab option-chain adapter for bid/ask, Greeks, liquidity, and expected-move enrichment | on-demand + future strike cycle |
| `inferno_schwab_account_sync.py` | **NEW** Read-only Schwab account/balance/position sync for the approved suffix; TOS-independent broker truth, no order endpoints | `reports/schwab_account_sync_latest.txt` |

## Monitoring (what is happening)

| Module | Purpose | Artifact |
|---|---|---|
| `inferno_doctor.py` | End-to-end desk health check; every subsystem PASS/FAIL | `data/inferno_doctor.json`, `reports/doctor_latest.txt` |
| `inferno_ops_maintenance.py` | Hourly sweep: tracker / staleness governor / broker preview refresh | `reports/ops_maintenance_latest.txt` |
| `inferno_daily_success.py` | Green/yellow/red scorecard over five safety + operational criteria | `reports/daily_success_latest.txt` |
| `inferno_watchdog.py` | Continuous failure detector + alert dispatcher | `reports/watchdog_latest.txt` |
| `inferno_secret_hygiene.py` | Verify no credentials are leaking into artifacts | `data/inferno_secret_hygiene.json` |
| `inferno_live_book_review_packet.py` | Compact "what exactly blocks new capital" packet over the live book | `reports/live_book_review_packet_latest.txt` |
| `inferno_reporting_preflight.py` | Read-only freshness/SMTP/Schwab/TOS attach-state check before any brief is sent or trusted | `data/inferno_reporting_preflight.json`, `reports/reporting_preflight_latest.txt` |
| `inferno_reporting_summary.py` | Shared read-only reporting language used by morning brief, action pulses, live sync, and command center | importable helpers (no artifact) |

## Decision (what to do today)

| Module | Purpose | Artifact |
|---|---|---|
| `inferno_approval_cadence.py` | Decide-today batting order with urgency scoring | `reports/approval_cadence_latest.txt` |
| `inferno_decision_brief.py` | Per-ticker context memo for each pending name | `reports/decision_briefs_latest.txt` |
| `inferno_trade_conviction_audit.py` | **NEW** Per-ticket bull / bear / disagreement / falsification math case with peer-reviewed citations | `reports/trade_conviction_audit_latest.txt` |
| `inferno_promotion_gap.py` | Gate-by-gate distance from broker promotion | `reports/promotion_gap_latest.txt` |
| `inferno_threshold_sensitivity.py` | Sweep four threshold profiles and report what each would promote | `reports/threshold_sensitivity_latest.txt` |
| `inferno_approval_queue.py` | Operator approve/reject/expire commands | `data/inferno_approval_queue.json` |
| `inferno_approval_inbox.py` | Pending-ticket inbox view | `reports/approval_inbox_latest.txt` |
| `inferno_approval_dispatch.py` | Route approved tickets to the staging lanes | side-effects on staging |
| `inferno_schwab_daily_ops.py` | Refresh and classify Schwab option-chain tape for daily decisions | `reports/schwab_daily_ops_latest.txt` |
| `inferno_strike_selector.py` | Choose strikes for approved tickets, with concentration governor | `data/inferno_strike_plan.json` |
| `inferno_capital_allocator.py` | Allocate paper capital across approved tickets | `data/inferno_capital_allocation.json` |
| `inferno_edge_research.py` | Score the shovel universe by lane and theme | `data/inferno_edge_research.json` |
| `inferno_risk_policy.py` | Centralised risk caps + violation surfaces | `data/inferno_risk_policy.json` |
| `inferno_exposure_analytics.py` | Concentration and setup-mix verdict | `data/inferno_exposure_analytics.json` |
| `inferno_operator_briefing.py` | Daily "what do I trade today" memo — the operator-facing summary of approval-ready tickets | `reports/operator_briefing_latest.txt` |
| `inferno_capital_deployment_readiness.py` | Manual-review capital readiness brief; sizes the desk against caps without touching the broker | `reports/capital_deployment_readiness_latest.txt` |
| `inferno_capital_launch_check.py` | One-command capital preflight refreshing the read-only safety artifacts | `reports/capital_launch_check_latest.txt` |
| `inferno_account_optimization.py` | Research-only growth, contribution, concentration, and contract-risk stress test from live Schwab truth | `reports/account_optimization_latest.txt` |
| `inferno_sizing_positioning_timing.py` | Total-NLV sleeve drift, candidate price reconciliation, and dated deployment timing overlay | `reports/sizing_positioning_timing_latest.txt` |
| `inferno_market_mastery_plan.py` | Source-ranked strategy, sizing, exit, behavior, and Browser learning action register | `reports/market_mastery_next_actions_latest.txt` |
| `inferno_portfolio_heat.py` | Total-NLV economic-theme heat across live shares and open paper maximum loss | `reports/portfolio_heat_latest.txt` |
| `inferno_wheel_shadow.py` | Capital, assignment, lot-size, yield, and downside-stress feasibility for wheel structures | `reports/wheel_shadow_latest.txt` |
| `run_inferno_daily_model_refresh.sh` | One research-only refresh sequence for tracker, Schwab truth, TOS metrics, evidence, alternatives, capital, and health | terminal + canonical reports |

## Breathing (is the system alive?)

| Module | Purpose | Artifact |
|---|---|---|
| `inferno_heartbeat.py` | Central liveness ledger; every subsystem records its own pulse | `data/inferno_heartbeat.json` |
| `inferno_tos_export_stability.py` | Verifier with retry-and-backoff + fail-mode classifier | `data/inferno_tos_export_stability.json` |
| `inferno_tos_export_chain.py` | **NEW** 11-step end-to-end TOS export diagnostic with first-failure attribution | `data/inferno_tos_export_chain.json` |
| `inferno_skills_audit.py` | Stale-skill auditor across every inferno_*.py module | `reports/skills_audit_latest.txt` |
| `inferno_night_prep.py` | **NEW** Bedside check that every layer is ready for tomorrow morning, now including Schwab/TOS source posture | `reports/night_prep_latest.txt` |
| `install_inferno_nightly_optimize_service.py` | Installs the weekday 18:30 research-only refresh loop in launchd | local LaunchAgent |
| `inferno_evidence_goal_loop.py` | Evaluated paper-evidence control loop with value classification, adaptive cadence, falsifiable beliefs, Obsidian memory, and hard authority stops | `reports/evidence_goal_loop_latest.txt` + `knowledge/agent-loop/` |
| `install_inferno_evidence_goal_loop_service.py` | Installs the weekday 13:40 bounded evidence loop in launchd | local LaunchAgent |
| `inferno_housekeeping.py` | Prune stale artifacts after they exceed retention | side-effects on `data/` |

## Thinking (math, hypotheses, proof)

| Module | Purpose | Artifact |
|---|---|---|
| `inferno_theme_synthesizer.py` | Multi-axis evidence cube with Wilson + bootstrap CIs | `reports/theme_synthesizer_latest.txt` |
| `inferno_hypothesis_lab.py` | Generate testable hypotheses across five templates with backtests | `reports/hypothesis_lab_latest.txt` |
| `inferno_hypothesis_ledger.py` | Append-only memory of every hypothesis; trajectory classifier | `data/inferno_hypothesis_ledger.json` |
| `inferno_strategy_replay.py` | Research-only replay of strategy lab over closed shadow outcomes | `reports/strategy_replay_latest.txt` |
| `inferno_strategy_lab.py` | Production strategy promotion gate (lab verdict) | `data/inferno_strategy_lab.json` |
| `inferno_counterfactual.py` | Policy-level replay over closed shadow set with ranked verdicts | `reports/counterfactual_latest.txt` |
| `inferno_devils_advocate.py` | Sign-flip-bootstrap falsification of every claimed edge | `reports/devils_advocate_latest.txt` |
| `inferno_evidence_strength.py` | Composite 0–1 scalar over Wilson lower, expectancy lower, sample size, falsification | `reports/evidence_strength_latest.txt` |
| `inferno_kelly_sizing.py` | Conservative quarter-Kelly fractional sizing with bootstrap CI bounds | `reports/kelly_sizing_latest.txt` |
| `inferno_vol_premium.py` | IV-bucket VRP discriminator via two-sample bootstrap on mean R | `reports/vol_premium_latest.txt` |
| `inferno_bayesian_winrate.py` | Beta-binomial Bayesian posterior on win rate; Wilson's complement | `reports/bayesian_winrate_latest.txt` |
| `inferno_regime_drift.py` | Two-sided CUSUM change-point detection per strategy stream | `reports/regime_drift_latest.txt` |
| `inferno_information_gain.py` | Mutual information ranking of features over win/loss outcomes | `reports/information_gain_latest.txt` |
| `inferno_options_math.py` | Black-Scholes primitives: d1/d2, implied move, deltas, IV-rank conversion | pure library, no artifact |
| `inferno_tos_custom_metrics.py` | Read-only registry/value capture for user-authored ThinkScript custom columns | `reports/tos_custom_metrics_latest.txt` |
| `inferno_schwab_price_history.py` | Read-only Schwab daily candle adapter for OHLCV-derived TOS metric mirrors | `reports/schwab_price_history_latest.txt` |
| `inferno_schwab_tos_metrics_sync.py` | Publishes Schwab-derived TOS custom metrics into the canonical model artifact | `reports/schwab_tos_metrics_sync_latest.txt` |
| `inferno_tos_metric_theory_audit.py` | Anti-confirmation audit that checks whether TOS custom metrics support, challenge, or merely contextualize a thesis | `reports/tos_metric_theory_audit_latest.txt` |
| `inferno_tos_formula_math.py` | Pure local mirror for TOS-style RVOL, trend, support/resistance, momentum, and strength formulas | pure library, no artifact |
| `inferno_tos_formula_audit.py` | Read-only drift audit comparing tracker values to the local TOS formula mirror | `reports/tos_formula_audit_latest.txt` |
| `inferno_walk_forward.py` | Chronological train/validate split; six-state edge survival ladder | `reports/walk_forward_latest.txt` |
| `inferno_factor_regression.py` | Hand-rolled logistic regression on one-hot features; bootstrap-CI coefficients | `reports/factor_regression_latest.txt` |
| `inferno_math_verify.py` | Cross-module invariant checker over every math artifact | `reports/math_verify_latest.txt` |
| `inferno_paper_bootstrap.py` | Seeds paper ledger at relaxed gating so promotion math can earn Phase 2 | `reports/paper_bootstrap_latest.txt` |
| `inferno_fast_paper_cohort.py` | Cycles isolated next-session option simulations from the broader bootstrap slate; never counts toward promotion | `reports/fast_paper_cohort_latest.txt` |
| `inferno_slate_normalizer.py` | Scale-invariant percentile ranks; fixes the broken absolute-threshold gates | `reports/slate_normalized_latest.txt` |
| `inferno_conviction_research.py` | Research-only whole-universe map of giants, sleepers, near-term winners, and contradictions | `reports/conviction_research_latest.txt` |
| `inferno_outcome_attribution.py` | Research-only Brinson-style decomposition of closed paper/shadow outcomes | `reports/outcome_attribution_latest.txt` |
| `inferno_rule_edge_decay.py` | Research-only Wilson + half-life monitor for conviction-audit rule bullets | `reports/rule_edge_decay_latest.txt` |
| `inferno_slippage_estimator.py` | Research-only quoted/effective spread and family slippage anchor table | `reports/slippage_estimator_latest.txt` |
| `inferno_portfolio_correlation.py` | Research-only effective bet count, concentration, and pairwise outcome correlation monitor | `reports/portfolio_correlation_latest.txt` |
| `inferno_drawdown_protocol.py` | Research-only drawdown-state sizing ladder and recovery discipline monitor | `reports/drawdown_protocol_latest.txt` |
| `inferno_consensus_monitor.py` | Research-only crowdedness monitor over Schwab skew, own-side lean, and family-pair fusion | `reports/consensus_monitor_latest.txt` |
| `inferno_schwab_edge_signals.py` | Research-only bridge from Schwab option-chain data to tiered operator signal lanes | `reports/schwab_edge_signals_latest.txt` |
| `inferno_math_config.py` | **NEW** Audited target source of truth for math knobs — seeds, resample counts, thresholds, vocabulary | pure library, no artifact |
| `inferno_performance_analytics.py` | Per-ticket performance with block-reason histogram | `data/inferno_performance_analytics.json` |
| `inferno_expectancy_ledger.py` | Net-R expectancy by evidence source, strategy family, and construction admissibility | `reports/expectancy_ledger_latest.txt` |
| `inferno_dte_policy_analysis.py` | Observational entry/exit DTE cohorts with a non-causal 21-DTE comparison | `reports/dte_policy_analysis_latest.txt` |
| `inferno_trading_behavior_audit.py` | Turnover, winner/loser holding time, journal coverage, and re-entry audit | `reports/trading_behavior_audit_latest.txt` |
| `inferno_research_cycle.py` | Periodic research roll-up across the thinking layer | `data/inferno_research_cycle.json` |
| `inferno_scenario_evidence.py` | Research-only underlying-move observations for the daily scenario slate | `reports/scenario_evidence_latest.txt` |
| `inferno_scenario_backtest.py` | Research-only scorecard comparing today's 10+ scenario slate against closed paper/shadow evidence | `reports/scenario_backtest_latest.txt` |
| `inferno_paper_mark_to_market.py` | Research-only current-mid refresh for open paper tickets; feeds trade-management rules without mutating the ledger | `reports/paper_mark_to_market_latest.txt` |
| `inferno_trade_management.py` | Research-only per-position playbook auditor for open paper tickets; recommends holds, trims, stops, and pre-event exits without mutating the ledger | `reports/trade_management_latest.txt` |
| `inferno_outcome_reviewer.py` | Re-score closed paper outcomes against expectations | `data/inferno_outcome_reviewer.json` |
| `inferno_shadow_evidence.py` | Shadow ledger of paper tickets and their outcomes | `data/inferno_shadow_evidence.json` |

## Integration (chained outputs)

| Module | Purpose | Cadence |
|---|---|---|
| `inferno_daily_loop.py` | Master 15-step read-only operator routine + narrative | 06:30 + 16:30 weekdays |
| `inferno_model_command_center.py` | Cross-model coordination + onboarding digest | each daily loop |
| `inferno_central_command.py` | Cross-subsystem coordination surface | as needed |
| `inferno_deploy_preflight.py` | Pre-deployment all-systems-check | manual + cloud builds |
| `inferno_action_pulse.py` | Twice-daily action-pulse email (near open + before close); the easy-access tactical layer | ~09:00 + ~15:30 weekdays |
| `inferno_usage_optimizer.py` | Compact read-first / do-not-paste handoff packet for new model sessions | `reports/usage_optimizer_latest.txt` |
| `run_inferno_paper_evidence_harvest.sh` | One-command paper evidence refresh across director/reducer/observations/reviews/backtest | market prep + after close |
| `run_inferno_paper_mark_to_market.sh` | Refresh current mids for open paper tickets | before trade-management review |
| `run_inferno_trade_management.sh` | Render the playbook-based open-position recommendation card | after paper mark-to-market |

## Observability (watch the brain)

| Module | Purpose | Artifact |
|---|---|---|
| `inferno_brain_console.py` | Single-screen view of the brain's current state | `reports/brain_console_latest.txt` |
| `inferno_brain_cycle_journal.py` | Snapshot every artifact per cycle; 90-cycle rolling history | `data/cycles/YYYY-MM-DD-HHMM/` |

## Operations — TOS

| Module | Purpose | Notes |
|---|---|---|
| `inferno_tos_session_probe.py` | Read TOS accessibility tree, identify the active window | read-only |
| `inferno_tos_ui_route.py` | Route TOS to Monitor → Account Statement (dry-run by default) | UI automation |
| `inferno_tos_export_verifier.py` | Preflight the export bridge without firing it | read-only |
| `inferno_tos_export_bridge.py` | Actual export-shortcut firing (operator-guarded) | UI automation |
| `inferno_tos_account_statement_scraper.py` | Pull Account Statement from accessibility tree as a fallback | read-only |
| `inferno_tos_session_probe.py` | Live thinkorswim window inspection | read-only |
| `inferno_tos_sandbox.py` | paperMoney-mode helpers | read-only |
| `inferno_tos_fill_ingest.py` | Ingest fills from the TOS export into the paper ledger | side-effects on paper |
| `inferno_desktop_automation.py` | macOS automation primitives shared across TOS modules | low-level |

## Operations — Paper

| Module | Purpose | Artifact |
|---|---|---|
| `inferno_paper_test_director.py` | Coordinator for paper-staged tickets | `data/inferno_paper_test_director.json` |
| `inferno_paper_bottleneck_reducer.py` | Builds a 10+ scenario paper/shadow evidence slate without widening authority | `data/inferno_paper_bottleneck_reducer.json` |
| `inferno_scenario_evidence.py` | Tracks reducer names as non-tradable underlying observations | `data/inferno_scenario_evidence.json` |
| `inferno_paper_evidence_loop.py` | Track paper outcomes from staging through close | `data/inferno_paper_evidence_loop.json` |
| `inferno_paper_execution.py` | Stage paper orders (paperMoney only) | side-effects on paper ledger |
| `inferno_paper_exit_auditor.py` | Audit open paper positions for stale exits | `data/inferno_paper_exit_auditor.json` |
| `inferno_live_account_sync.py` | Read-only sync from Schwab account API first, TOS statement fallback second | `data/inferno_live_account_sync.json` |
| `inferno_live_position_review.py` | Classify live positions as supported / review / fragile | `data/inferno_live_position_review.json` |
| `inferno_execution_clerk.py` | Build broker-preview blueprints (no live submit) | `data/inferno_execution_clerk.json` |
| `inferno_broker_preview.py` | Preview-mode broker order construction | preview-only |

## Operations — Cloud

| Module | Purpose | Notes |
|---|---|---|
| `inferno_cloud_control_plane.py` | Cloud-side control plane (Cloud Run / scheduler) | |
| `inferno_cloud_execution_auditor.py` | Audit cloud-side execution | |
| `inferno_cloud_state.py` | Cloud-side state snapshots | |

## Safety

| Module | Purpose | Notes |
|---|---|---|
| `inferno_authority_controller.py` | Compute the desk's authority manifest from current evidence | writes `data/inferno_authority_manifest.json` |
| `inferno_risk_policy.py` | Risk caps and policy enforcement | |
| `inferno_risk_gate_audit.py` | Consolidated map of which risk gates are blocking promotion right now | `reports/risk_gate_audit_latest.txt` |
| `inferno_blowup_guardrails.py` | Six named pre-trade ruin-prevention rules tied 1:1 to historical blow-ups (Niederhoffer, LTCM, Archegos, Amaranth, Karen-the-Supertrader, Cordier); diagnostic-only | `reports/blowup_guardrails_latest.txt` |
| `inferno_secret_hygiene.py` | Verify no credentials leak into artifacts | |
| `inferno_process_compliance.py` | Research-only paper-entry circuit breaker for missing plans, size breaches, and potential averaging down | `reports/process_compliance_latest.txt` |

## Conventions

Every module follows the same shape (see `docs/ENGINEERING_CONVENTIONS.md` for the full spec):

1. Module docstring with a *what it does* + *what it does NOT do* section.
2. `<MODULE>_STAGE = "<name>-research-only"` constant if the module is diagnostic.
3. `build_<name>()` → `dict` builder, `save_<name>()` → side-effect, `<name>_text()` → render.
4. `parse_args()` + `main()` for CLI entry.
5. Writes use `inferno_io.atomic_write_*` (not raw `Path.write_text`).
6. Tests live at `tests/test_<module>.py` and freeze the contract.

When adding a new module, pick the layer it belongs to in this index, copy the shape of the nearest existing module in that layer, and update this index in the same PR.
