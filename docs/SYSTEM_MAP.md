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
   when the local OAuth token is healthy.
4. Daily/ops pipelines generate reports, doctor checks, morning/pre-close
   briefs, and command-center artifacts.
5. Paper and shadow lanes collect outcomes until strategy evidence earns more
   authority.
6. Broker/TOS lanes remain read-only unless the operator gives explicit final
   confirmation for a specific action.

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
| Paper variant backfill | `reports/paper_variant_scanner_latest.txt` |
| Score/threshold assumptions | `reports/score_threshold_audit_latest.txt` |
| Scenario learning | `reports/scenario_backtest_latest.txt` |
| Live book posture | `reports/live_position_review_latest.txt` |
| Capital readiness | `reports/capital_deployment_readiness_latest.txt` |
| Recurring deposit forecast | `reports/deposit_plan_latest.txt` |
| Broker cash attribution | `reports/cash_attribution_latest.txt` |
| Ticket cap and call posture | `reports/ticket_cap_policy_latest.txt` |
| Schwab option chains | `reports/schwab_options_latest.txt` |
| Schwab daily operator tape | `reports/schwab_daily_ops_latest.txt` |

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
- `./inferno oauth` — Schwab OAuth status/refresh/restart
- `./inferno daily-ops` — Schwab daily options operations tape
- `./inferno action-pulse` — tactical action pulse; no email unless `--send`
- `./inferno deposit-plan` — recurring deposit forecast, separate from broker cash
- `./inferno cash-ledger` — broker cash-change reconciliation without profit inference
- `./inferno ticket-cap` — construction ticket band, simulated paper budget, and call-options posture
- `./inferno capital-check` — capital launch check; defaults to deployable cash 0
- `./inferno strike-cycle` — strike cycle; defaults to deployable cash 0
- `./inferno approvals` — approval queue status only
- `./inferno schedule` — LaunchAgent and Codex automation schedule
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
