# System Map

One-page architecture for the Inferno desk. Read this before changing code,
touching broker automation, or handing work to another model.

## Mission

Build an automated earnings/options research desk that can refresh data, score
setups, collect paper evidence, and brief the operator without granting live
trading authority prematurely.

The concise command brief lives in [`MISSION_CONTROL.md`](MISSION_CONTROL.md).
Use this file for architecture; use Mission Control for purpose and strategy.

The current authority state is intentionally conservative:

```text
authorityLevel: paper-evidence-only
brokerSubmitAllowed: false
liveTradingAllowed: false
```

## Operating Loop

1. Tracker data refreshes from Google Sheets and local market-data scripts.
2. Scoring modules enrich the universe with readiness, conviction, risk, and
   evidence strength.
3. Schwab option-chain data is the primary read-only option quote-quality tape
   when the local OAuth token is healthy. A separately persisted, bounded
   supplemental tape may fill only missing chains from the complete current
   strategy-pricing slate, including bounded cap-fit fallback candidates; it
   never overwrites the primary tape or changes paper/live authority.
4. Daily/ops pipelines generate reports, doctor checks, morning/pre-close
   briefs, and command-center artifacts.
5. Paper and shadow lanes collect outcomes until strategy evidence earns more
   authority.
6. Broker/TOS lanes remain read-only unless the operator gives explicit final
   confirmation for a specific action.

Scheduled refreshes fail soft for individual read-only provider calls and
continue to their command-center/doctor pass. The heartbeat verdict is driven
only by scheduled sources; manual or intentionally inactive broker probes stay
visible without masquerading as a missed scheduled run.
The hourly maintenance sweep also rebuilds the deposit plan, cash attribution,
and growth stack after its broker-account refresh, before regenerating the
command center; it never turns planned or unattributed cash into authority.
LaunchAgent wrappers are bound to repository-owned orchestration scripts. When
macOS privacy blocks background access to the workspace, they execute a
deployed copy instead. The installer atomically replaces that copy, so an
overlapping scheduled start sees either the previous complete executable or the
new complete executable. Its checksum is audited in `./inferno schedule`; a
drift verdict means the job is not yet using the reviewed source.

Mutable evidence ledgers retain a compatibility `generatedAt` creation stamp,
but lifecycle freshness is explicit: `createdAt`, `updatedAt`,
`lastSuccessfulAt`, `lastAttemptAt`, `sourceDataAsOf`, and
`lifecycleStatus`. A failed refresh may update only the attempt/failure record;
it cannot advance the last successful evidence timestamp or make an old source
look current. The first producers on this contract are the paper-execution and
shadow-evidence ledgers; command-center summaries expose their lifecycle data.

## Canonical Truth

Generated artifacts beat durable docs when they disagree.

| Question | Canonical artifact |
|---|---|
| Smallest safe handoff | `reports/usage_optimizer_latest.txt` |
| Compact supervisor picture | `reports/model_command_center_onboard_latest.txt` |
| Current supervisor picture | `reports/model_command_center_latest.txt` |
| One-line desk verdict | `reports/central_command_latest.txt` |
| Health check | `reports/doctor_latest.txt` |
| Formula integrity | `reports/math_verify_latest.txt` |
| Secret hygiene | `reports/secret_hygiene_latest.txt` |
| Paper bottleneck | `reports/paper_bottleneck_reducer_latest.txt` |
| Paper blocker diagnosis | `reports/paper_blocker_swarm_latest.txt` |
| Paper fill worksheet | `reports/paper_capture_template_latest.txt` |
| Paper variant backfill | `reports/paper_variant_scanner_latest.txt` |
| Score/threshold assumptions | `reports/score_threshold_audit_latest.txt` |
| Scenario learning | `reports/scenario_backtest_latest.txt` |
| Live book posture | `reports/live_position_review_latest.txt` |
| Capital readiness | `reports/capital_deployment_readiness_latest.txt` |
| Recurring deposit forecast | `reports/deposit_plan_latest.txt` |
| Contribution and compounding forecast | `reports/growth_stack_latest.txt` |
| Schwab transaction facts | `reports/schwab_transaction_ledger_latest.txt` |
| Broker cash attribution | `reports/cash_attribution_latest.txt` |
| Ticket cap and call posture | `reports/ticket_cap_policy_latest.txt` |
| Schwab option chains | `reports/schwab_options_latest.txt` |
| Schwab chain-history readiness | `reports/chain_history_latest.txt` |
| Schwab chain-diff evidence | `reports/chain_diff_latest.txt` |
| Supplemental strategy-pricing quote coverage | `reports/strategy_quote_coverage_latest.txt` |
| Schwab daily operator tape | `reports/schwab_daily_ops_latest.txt` |
| AI-basket market refresh | `reports/ai_basket_refresh_latest.txt` |
| Full-tracker reference taxonomy | `reports/tracker_taxonomy_latest.txt` |
| Full-tracker registry | `reports/tracker_registry_latest.txt` |
| Full-tracker role review | `reports/tracker_role_review_latest.txt` |
| Full-tracker blank role-policy packet | `reports/tracker_role_policy_packet_latest.txt` and `reports/tracker_role_policy_packet_latest.csv` |
| Full-tracker role-policy contract | `reports/tracker_role_policy_latest.txt` |
| Runtime storage hygiene | Nightly logs-only trimming via `inferno_housekeeping.py`; evidence retention and Git maintenance remain manual |
| AI-basket input trust | `reports/ai_basket_data_contract_latest.txt` |
| Defined-risk short-premium evidence | `reports/short_premium_study_latest.txt` |

`reports/ticket_cap_policy_latest.txt` separates the operator's research
construction cap from live capital authority. Live sizing still inherits the
drawdown stepper and can be `$0` while the account is paused. Paper staging is
decoupled through `inferno_risk_policy.evaluate_strike_item(..., mode="paper")`
and uses the simulated paper budget from `inferno_config.py`; quote, liquidity,
spread, duplicate, source-divergence, and authority-tripwire gates still apply.

`reports/paper_test_director_latest.txt` can surface operator-routable paper
candidates, auto-selected research candidates, priced paper-research variants,
or construction-watch alternatives from the strategy-pricing lane. Those rows
are research visibility only for unattended agents: they do not approve, stage,
close, promote, or submit tickets.

`inferno_strategy_alternative_pricing.py` leads its research-chain work with
the pre-registered `SHORT_PREMIUM_DEFINED` arm, then prices the ordinary
defined-risk alternatives. When the paper-blocker swarm identifies a
cap-busting `LONG_STRADDLE`/`STRADDLE`, the pricing pass can also compare only
the cap-fit audit's bounded structures: a $5-wide-or-narrower debit spread, a
$1-wide-or-narrower credit spread, and a single long leg. The audit estimate
is an input to construction only—not a pass. Known market direction suppresses
opposite-side debit or single-leg attempts, while missing direction does not
invent a single-leg thesis. Live quotes, existing optimizer checks, the complete
paper-risk policy, and human review remain mandatory.

## Model Ownership

| Lane | Owner | Boundary |
|---|---|---|
| Capital readiness, risk gates, tests, docs, command-center hygiene | Codex | No live submit. No authority expansion. |
| Native thinkorswim export evidence path | Claude | Do not open extra TOS windows. Do not trade. |
| Paper evidence, shadow scenarios, backtest interpretation | Shared | Promotion requires closed scored outcomes. |

If a task overlaps owners, update `coordination/active_missions.json` and leave
a note in `coordination/model_notes.jsonl` through the command-center CLI.

## Safety Stack

- Never place trades without explicit human confirmation.
- Never open a new thinkorswim instance.
- Use only the already-open TOS window when the operator provides one.
- Live broker access is read-only and limited to the configured approved account.
- Paper evidence remains the promotion gate.
- Generated broker previews are not orders.
- Any failure in data freshness, account matching, or risk gates must fail closed.

## Start Commands

```bash
./inferno status
./inferno sync
./inferno today
```

`./inferno` is the unified operator control surface. It routes to the existing
tested subsystems instead of replacing them:

- `./inferno status` — one current desk state
- `./inferno sync` — full model/account/tracker refresh
- `./inferno today` — one-letter operator decision screen
- `./inferno doctor` — health check
- `./inferno preflight` — reporting readiness check
- `./inferno usage` — low-context handoff packet
- `./inferno tracker-taxonomy` — source-labelled full-tracker sector, industry, and broad economic-exposure coverage
- `./inferno tracker-registry` — full-tracker taxonomy and holdings coverage before DCA research
- `./inferno tracker-role-review` — operator-owned role and diversification decision queue; no weights or purchases
- `./inferno tracker-role-policy-packet` — blank full-row operator worksheet with source context; no decisions, imports, weights, or purchases
- `./inferno tracker-role-policy` — read-only validation of optional human role-policy input; rejects weights and makes no decisions
- `./inferno oauth` — Schwab OAuth status/refresh/restart
- `./inferno daily-ops` — Schwab daily options operations tape
- `./inferno action-pulse` — tactical action pulse; no email unless `--send`
- `./inferno deposit-plan` — recurring deposit forecast, separate from broker cash
- `./inferno growth-stack` — research-only layer of broker NLV, historical observed NLV trend, scheduled deposits, and explicit compounding assumptions; it never makes planned cash deployable or labels unattributed movement as return
- `./inferno schwab-transactions` — read-only, redacted broker transaction facts for cash reconciliation; it makes no trading request and never declares realized options P/L
- `./inferno cash-ledger` — broker cash-change reconciliation without profit inference
- `./inferno ticket-cap` — construction ticket band, simulated paper budget, and call-options posture
- `./inferno capital-check` — capital launch check; defaults to deployable cash 0
- `./inferno strike-cycle` — strike cycle; defaults to deployable cash 0
- `./inferno approvals` — approval queue status only
- `./inferno schedule` — all installed Inferno LaunchAgents and Codex automation schedules, including repeat intervals
- `python3 inferno_promotion_evidence_lineage.py` — read-only reconciliation of counted paper evidence versus quarantined fast and shadow research
- `./inferno onboard` — compact handoff packet for another model

## Verify Before Commit

```bash
python3 -m unittest discover tests
python3 inferno_math_verify.py
python3 inferno_secret_hygiene.py
./inferno doctor
git diff --check
```

Use tighter targeted tests first when iterating, but do not ship a meaningful
change without the broader verification pass.
