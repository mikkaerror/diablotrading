# Inferno Runbook

This is the "what do I do when something feels off?" guide for the desk.

## Daily Defaults

### Next-week operating workflow

Use this order when the desk needs to be boring, repeatable, and ready before
the open:

```bash
./run_inferno_reporting_preflight.sh
./run_inferno_dawn_cycle.sh
./run_inferno_schwab_daily_ops.sh
./run_inferno_live_account_sync.sh
./run_inferno_live_position_review.sh
./run_inferno_risk_gate_audit.sh
./run_inferno_model_command_center.sh
./run_inferno_action_pulse.sh --phase manual --deployable-cash 1050 --send --force-send
```

Operator flow:

- Open thinkorswim manually only when a fresh broker capture is needed.
- If TOS is already open, reveal that existing window. Do not open another instance.
- Run reporting preflight before trusting or forcing a brief.
- Read the morning/open/pre-close emails in three sections: `What changed`, `What matters today`, and `What action is allowed`.
- Any real-money order still requires explicit human confirmation before final submission.

### Start the local dashboard

```bash
python3 server.py
```

If you change backend files like `server.py`, `inferno_execution_clerk.py`, or the morning runner, stop and restart this command so the dashboard is not serving stale process logic.

Then open:

- `http://localhost:8000`

### Check the desk in one command

```bash
python3 inferno_doctor.py
./run_inferno_deploy_preflight.sh
./run_inferno_cloud_control_plane.sh
./run_inferno_cloud_execution_audit.sh
./run_inferno_data_readiness_audit.sh
python3 inferno_secret_hygiene.py
```

What it verifies:

- SMTP is configured
- the dawn and watchdog agents are loaded
- the 5:58 AM wake is scheduled
- the Mac is not falling asleep too aggressively on AC
- today’s run and watchdog status are fresh
- the market-context audit confirms `Z:AE` confirmation coverage across the tracker
- the data-readiness audit tells you which numbers are safe for prep and which still need broker confirmation
- the secret-hygiene audit verifies that env files, credentials, backups, and generated artifacts are not drifting into tracked repo state

### Keep TOS from popping open repeatedly

The desktop LaunchAgent should be installed without `--export-first`:

```bash
python3 install_inferno_desktop_automation_service.py install --require-tos-running
```

Background agents may ingest existing Downloads exports, but they must not
foreground or trigger a fresh thinkorswim export unless this local config flag
is deliberately changed:

```bash
TOS_BACKGROUND_EXPORT_ALLOWED=0
```

Leave that value at `0` for normal operation. Manual/supervised export remains
available when the operator explicitly runs the export bridge.

### Attach-only broker visibility mode

It is safe to leave thinkorswim closed during normal research, tracker updates,
daily-loop checks, paper-evidence generation, and email brief delivery. The desk
now separates three states:

- `visible`: the existing TOS window is visible to the attach-only probe.
- `running-not-visible`: TOS is running, but the current Space/window is hidden from the probe.
- `not-running`: TOS is closed or unavailable and must be opened manually only if broker capture is needed.

Background automation must never open a new TOS instance. These flags should
remain conservative for normal operation:

```bash
TOS_EXPORT_AUTOMATION_ENABLED=0
TOS_BACKGROUND_EXPORT_ALLOWED=0
```

Use this mode when the Mac is hot, slow, or on battery. Open thinkorswim only
when you need to capture a fresh export, reconcile a live watchlist, or manually
stage an order from the broker preview.

The deploy preflight is the shipping-grade version of that check. It adds
compile checks, local regression tests, shell-wrapper validation, cloud-native
pipeline smoke, and an explicit split between cloud readiness and desktop
broker-window readiness.

If you only want the repo-safe deployment gate that can run in GitHub Actions,
use:

```bash
./run_inferno_deploy_preflight.sh --profile ci
```

If you want to isolate one lane, use:

```bash
./run_inferno_deploy_preflight.sh --profile cloud
./run_inferno_deploy_preflight.sh --profile desktop
```

Profiles keep the readout honest. A healthy cloud lane should not be blocked by
a local thinkorswim window, and a healthy desktop lane should not pretend the
cloud schedule is armed.

The cloud control-plane verifier is the operator-grade version of that question:

```bash
./run_inferno_cloud_control_plane.sh
```

It checks whether this machine can actually deploy and manage the Cloud Run /
Cloud Scheduler stack right now.

The cloud execution auditor is the proof-of-run layer:

```bash
./run_inferno_cloud_execution_audit.sh
```

It checks the latest dawn and strike Cloud Run executions, confirms the expected
email success log lines were emitted, verifies the schedulers are enabled, and
confirms the GCS state vault still contains the core paper/shadow evidence
artifacts.

To turn that into an exception-only operator alarm:

```bash
./run_inferno_cloud_execution_audit.sh --alert-on-failure
```

Healthy runs stay quiet. Unhealthy runs can send one SMTP alert per day for the
same failure signature, which keeps repeated manual checks from flooding your
inbox.

## Manual Commands

### Rebuild and send the live brief

```bash
./run_inferno_dawn_cycle.sh
```

Do not use bare system Python for this step unless that interpreter already has the Backtest dependencies installed. The wrapper is the safe operator path because it runs through the Backtest virtual environment.

### Rebuild without rerunning BC/P/Q/R

```bash
./run_inferno_dawn_cycle.sh --skip-updates
```

This still rebuilds:

- the snapshot payload
- the `Z:AE` market-context confirmation columns
- the market-context audit artifact
- the edge-research and execution artifacts downstream

### Rebuild without sending email

```bash
./run_inferno_dawn_cycle.sh --skip-email
```

### Check watchdog health

```bash
python3 inferno_watchdog.py
```

### Check the approval queue

```bash
python3 inferno_approval_queue.py status
./run_inferno_approval_inbox.sh
./run_inferno_approval_dispatch.sh status
```

### Check the execution desk

```bash
python3 inferno_execution_clerk.py
```

### Build paper-only strike plans

```bash
./run_inferno_strike_cycle.sh
```

This writes:

- [data/inferno_strike_plan.json](data/inferno_strike_plan.json)
- [reports/strike_plan_latest.txt](reports/strike_plan_latest.txt)
- [data/inferno_paper_execution_ledger.json](data/inferno_paper_execution_ledger.json)
- [reports/paper_execution_ledger_latest.txt](reports/paper_execution_ledger_latest.txt)
- [data/inferno_shadow_evidence.json](data/inferno_shadow_evidence.json)
- [reports/shadow_evidence_latest.txt](reports/shadow_evidence_latest.txt)
- [data/inferno_strategy_lab.json](data/inferno_strategy_lab.json)
- [reports/strategy_lab_latest.txt](reports/strategy_lab_latest.txt)

Run this after regular options markets open. A 6 AM Mountain run can produce stale or zero option quotes.

### Run the capital launch check

```bash
./run_inferno_capital_launch_check.sh --deployable-cash 1000
```

This is the one-command preflight before real cash is deployed. It refreshes
live account sync, live position review, capital readiness, live-book blockers,
risk gates, and the model command center. A `blocked` verdict means no new
capital. A `manual-ready-with-warnings` verdict means a human can review a trade,
but automation remains locked and warnings must be accepted explicitly.

### Send the twice-daily action pulse

```bash
./run_inferno_action_pulse.sh --phase open --deployable-cash 1000 --send
./run_inferno_action_pulse.sh --phase preclose --deployable-cash 1000 --send
```

The action pulse is the easy-access tactical email. It refreshes the read-only
Schwab options tape when configured, refreshes the read-only ops loop, builds
the daily-loop digest, builds the capital launch check, and sends a short
operator memo. It cannot submit orders or change authority.

Install the weekday schedule:

```bash
python3 install_inferno_action_pulse_service.py install --deployable-cash 1000
python3 install_inferno_action_pulse_service.py status
```

Default local times:

- `07:05` Mountain: open watch, after the dawn refresh and before market open
- `13:30` Mountain: pre-close watch, before the equity close

### Refresh Schwab option-chain tape

```bash
./run_inferno_schwab_daily_ops.sh
```

This refreshes the local Schwab OAuth token when possible, pulls read-only
option chains for the active execution/approval/watchlist slate, classifies
each chain into `tradable-research`, `paper-ready`, `manual-review`, or
`avoid-chain`, and writes:

- [data/inferno_schwab_daily_ops.json](data/inferno_schwab_daily_ops.json)
- [reports/schwab_daily_ops_latest.txt](reports/schwab_daily_ops_latest.txt)

Use it before strike selection if you want the latest broker-grade spread,
liquidity, IV, Greek, and expected-move checks.

OAuth lifecycle:

```bash
python3 inferno_schwab_oauth.py status
python3 inferno_schwab_oauth.py ensure
```

`ensure` reuses a healthy access token and serializes refreshes across the
desk. Account, option-chain, price-history, and TOS-metric jobs should not
require separate operator refreshes.

If status says `reauthorizationRequired: True`, run:

```bash
python3 inferno_schwab_oauth.py restart
```

Complete Schwab consent once and paste only the newest full redirect URL. A
full restart is a broker authorization boundary; the desk can make it a
single clear step but cannot automate around Schwab's required re-consent.
The doctor begins warning at consent-grant age five days so this can be done
proactively rather than after a morning data failure. That threshold is a desk
lead-time policy because Schwab does not report refresh-token expiry in the
current token response.

To inspect the paper execution ledger without rebuilding:

```bash
python3 inferno_paper_execution.py status
```

To inspect conservative strategy-promotion evidence:

```bash
python3 inferno_strategy_lab.py status
```

To inspect the research-only shadow lane:

```bash
python3 inferno_shadow_evidence.py status
```

The ledger is paper-only. It records rejected and blocked tickets too, so we can
measure false positives and liquidity failures instead of quietly forgetting
them.

The shadow evidence ledger goes one step further: it tracks valid options plans
that were blocked from execution and later scores the hypothetical expiration
outcome. It is explicitly not an approval source and cannot unlock live broker
submission.

If the primary paper queue is dead, the paper-test director can publish a wider
paper-only rehearsal plan from the broader eligible slate. The shadow lab will
prefer that expanded plan when it is fresh, so research continues without
changing the live execution queue:

- [data/inferno_paper_rehearsal_strike_plan.json](data/inferno_paper_rehearsal_strike_plan.json)
- [reports/paper_rehearsal_strike_plan_latest.txt](reports/paper_rehearsal_strike_plan_latest.txt)

Risk limits are documented in:

- [docs/RISK_POLICY.md](docs/RISK_POLICY.md)

### Review paper outcomes

```bash
./run_inferno_outcome_review.sh
```

This closes eligible open paper tickets after expiration and writes:

- [reports/paper_outcome_review_latest.txt](reports/paper_outcome_review_latest.txt)

The morning pipeline now attempts this review automatically before writing the
latest snapshot. Outcome review warnings do not block the morning email.

### Build offline broker previews

```bash
./run_inferno_broker_preview.sh
```

This writes:

- [data/inferno_broker_preview.json](data/inferno_broker_preview.json)
- [reports/broker_preview_latest.txt](reports/broker_preview_latest.txt)

This does not connect to thinkorswim or Schwab. It only creates broker-neutral
order previews from clean paper-staged tickets.

### Build performance analytics

```bash
./run_inferno_performance_analytics.sh
```

This writes:

- [data/inferno_performance_analytics.json](data/inferno_performance_analytics.json)
- [reports/performance_analytics_latest.txt](reports/performance_analytics_latest.txt)

This is the promotion/demotion engine. It tracks block reasons, false-positive
rates, closed-ticket expectancy, strategy summaries, and whether any setup has
earned a review for more authority.

### Refresh the whole research lane

```bash
./run_inferno_research_cycle.sh
```

This is the simplest “do the backtest” command now. It rebuilds:

- shadow evidence
- performance analytics
- the real strategy lab
- the research-only shadow replay
- the hypothesis lab
- the hypothesis ledger
- the scenario observation ledger for underlying-move evidence
- the scenario backtest scorecard for the current paper/shadow slate

Use this when you want one fresh evidence picture before market prep or before
we let another model collaborate on research decisions.

This cycle is also refreshed by the ops-maintenance sweep now, so the desk
keeps one current research snapshot even when you do not run the script
manually.

### Score today's scenario slate against closed evidence

```bash
./run_inferno_paper_evidence_harvest.sh
```

Use this when you want the full paper-evidence pass: director, reducer,
scenario observation capture, outcome review, paper evidence audit, exit audit,
and scenario backtest.

For narrow debugging:

```bash
./run_inferno_scenario_evidence.sh
./run_inferno_scenario_backtest.sh
```

This writes:

- [data/inferno_scenario_evidence.json](data/inferno_scenario_evidence.json)
- [reports/scenario_evidence_latest.txt](reports/scenario_evidence_latest.txt)
- [data/inferno_scenario_backtest.json](data/inferno_scenario_backtest.json)
- [reports/scenario_backtest_latest.txt](reports/scenario_backtest_latest.txt)

This is the “what can today actually teach us?” layer. It compares the current
paper bottleneck reducer slate against closed paper and shadow outcomes by
ticker, strategy family, and days-to-earnings window. It is research-only:
`promotable=false`, `liveTradingAllowed=false`, and `brokerSubmitAllowed=false`.
The scenario evidence step adds a separate underlying-move observation lane so
the desk can learn from watched names before option fills close; those
observations stay separate from option P/L evidence.

### Size the allocator for actual deployable cash

```bash
./run_inferno_capital_allocator.sh --deployable-cash 525
```

Use this before a Thursday/Friday deployment window so the sleeves, starter
ticket cap, and reserve cash reflect the real dollars you expect to have
instead of the desk's default planning base.

### Build exposure analytics

```bash
./run_inferno_exposure_analytics.sh
```

This writes:

- [data/inferno_exposure_analytics.json](data/inferno_exposure_analytics.json)
- [reports/exposure_analytics_latest.txt](reports/exposure_analytics_latest.txt)

This is the portfolio/context risk layer. It checks sector concentration, setup
concentration, high-correlation clusters, and broad-market regime before the
desk graduates toward more broker authority.

### Review the live book against tracker conviction

```bash
./run_inferno_schwab_account_sync.sh
./run_inferno_live_account_sync.sh
./run_inferno_live_position_review.sh
./run_inferno_live_book_review_packet.sh
```

This writes:

- [data/inferno_schwab_account_sync.json](data/inferno_schwab_account_sync.json)
- [reports/schwab_account_sync_latest.txt](reports/schwab_account_sync_latest.txt)
- [data/inferno_live_account_sync.json](data/inferno_live_account_sync.json)
- [reports/live_account_sync_latest.txt](reports/live_account_sync_latest.txt)
- [data/inferno_live_position_review.json](data/inferno_live_position_review.json)
- [reports/live_position_review_latest.txt](reports/live_position_review_latest.txt)
- [data/inferno_live_book_review_packet.json](data/inferno_live_book_review_packet.json)
- [reports/live_book_review_packet_latest.txt](reports/live_book_review_packet_latest.txt)

Use this when you want a read-only answer to:

- which holdings still align with the tracker
- which names look fragile even if they are profitable
- which positions are supported by long-term shovel research or shadow evidence

Schwab account API is the preferred source for balances and positions. The
legacy TOS account-statement scrape remains a supervised fallback, but TOS is
not required when `Account data source: schwab-account-api` and `TOS required
for account sync: False` appear in the live sync report.

`review` is still an acceptable live-position-review verdict. It means the
automation succeeded and surfaced a name that deserves a human check before
adding size.

The review packet is the capital-deployment translation layer. It adds support
cushion, resistance headroom, earnings bucket, P/L cushion, review heat, and an
explicit unlock checklist so the desk knows whether a live holding is a hard
blocker or only a warning.

### Build online-world shovel edge research

```bash
./run_inferno_edge_research.sh
```

This writes:

- [data/inferno_edge_research.json](data/inferno_edge_research.json)
- [reports/edge_research_latest.txt](reports/edge_research_latest.txt)
- [data/inferno_market_context_audit.json](data/inferno_market_context_audit.json)
- [reports/market_context_audit_latest.txt](reports/market_context_audit_latest.txt)
- [data/inferno_ticker_universe_audit.json](data/inferno_ticker_universe_audit.json)
- [reports/ticker_universe_audit_latest.txt](reports/ticker_universe_audit_latest.txt)

This is the thematic research layer for tech shovel names: compute, chips,
cloud/data rails, cybersecurity, ad rails, creator platforms, and payment rails.
It separates catalyst trades from long-term accumulation candidates and now
blends in confirmation metrics like RVOL, trend, and structure proximity.

The ticker-universe audit is the onboarding guardrail. Run it anytime you add
fresh names to the tracker and before you trust new rows in the morning brief.

```bash
./run_inferno_ticker_universe_audit.sh
```

### Run ops maintenance

```bash
./run_inferno_ops_maintenance.sh
```

Use this when the desk built the market snapshot correctly but surrounding ops
artifacts feel stale. It safely refreshes:

- ticker-universe hydration audit
- next-week data readiness audit
- downloads watch / fill-ingest status
- morning brief email recovery from the saved snapshot
- broker-preview artifact (paper-only, broker-neutral)
- stale-approval governor (demotes pending tickets older than 5 market days)
- watchdog status without duplicate alert spam

If you want that sweep on a timer during the day, install the optional
LaunchAgent:

```bash
python3 install_inferno_ops_maintenance_service.py install
```

### Refresh the shared model command center

```bash
./run_inferno_model_command_center.sh
```

This writes:

- [data/inferno_model_command_center.json](data/inferno_model_command_center.json)
- [reports/model_command_center_latest.txt](reports/model_command_center_latest.txt)
- [coordination/active_missions.json](coordination/active_missions.json)
- [coordination/model_notes.jsonl](coordination/model_notes.jsonl)

Use this when you want one canonical brain for multiple models working the same
desk. It aggregates deployment health, live-book review, paper evidence, and
current missions into one memo that Claude or Codex can both read safely.

Common collaboration commands:

```bash
./run_inferno_model_command_center.sh note \
  --author codex \
  --title "What changed" \
  --body "Short operator note for the next model." \
  --priority high \
  --tags handoff,ops

./run_inferno_model_command_center.sh mission-add \
  --title "Tighten strike selector" \
  --body "Investigate low-liquidity fallback logic before Monday open." \
  --owner codex \
  --status pending \
  --priority high \
  --tags automation,risk
```

### Run the central supervisor command

```bash
./run_inferno_central_command.sh
```

This is the shortest full-desk refresh for a human or collaborating model. It:

- runs ops maintenance
- rebuilds the shared command center
- captures the latest doctor verdict
- writes:
  - [data/inferno_central_command.json](data/inferno_central_command.json)
  - [reports/central_command_latest.txt](reports/central_command_latest.txt)

For a fast new-model landing packet:

```bash
./run_inferno_central_command.sh onboard
./run_inferno_usage_optimizer.sh
```

The usage optimizer writes:

- [data/inferno_usage_optimizer.json](../data/inferno_usage_optimizer.json)
- [reports/usage_optimizer_latest.txt](../reports/usage_optimizer_latest.txt)

Use it to keep Codex/Claude handoffs small: read the listed files first,
avoid pasting generated data/logs by default, and replace repeated manual
checks with the one-command shortcuts it prints.

### Build automation authority manifest

```bash
./run_inferno_authority_controller.sh
```

This writes:

- [data/inferno_authority_manifest.json](data/inferno_authority_manifest.json)
- [reports/authority_manifest_latest.txt](reports/authority_manifest_latest.txt)

This is the permission layer. It combines snapshot freshness, execution queue,
paper evidence, exposure warnings, broker-preview state, and live-trading flags
into one explicit authority level. Broker adapters must treat this as a hard
gate before any future account-connected action.

### Build capital sleeve allocation

```bash
./run_inferno_capital_allocator.sh
```

This writes:

- [data/inferno_capital_allocator.json](data/inferno_capital_allocator.json)
- [reports/capital_allocator_latest.txt](reports/capital_allocator_latest.txt)

This is the allocator layer. It separates catalyst-trade risk from long-term
accumulation, assigns sleeve weights, and publishes a tactical options budget
without pretending that every good name belongs in the same bucket.

### Build the thinkorswim paperMoney sandbox

```bash
./run_inferno_tos_sandbox.sh
```

This writes:

- [data/inferno_tos_sandbox_session.json](data/inferno_tos_sandbox_session.json)
- [reports/tos_sandbox_session_latest.txt](reports/tos_sandbox_session_latest.txt)
- [data/inferno_tos_fill_log_template.csv](data/inferno_tos_fill_log_template.csv)
- [data/inferno_tos_fill_log.csv](data/inferno_tos_fill_log.csv)

This is the paperMoney rehearsal packet. It turns authority-approved execution
intents into a short list of names that may be staged in thinkorswim's paper
account, plus a manual fill log so outcome review stays auditable.

If the sandbox says `ready=false`, do not improvise. Fix the authority layer or
the execution queue first.

### Build the paper-test director

```bash
./run_inferno_paper_test_director.sh
```

This writes:

- [data/inferno_paper_test_director.json](data/inferno_paper_test_director.json)
- [reports/paper_test_director_latest.txt](reports/paper_test_director_latest.txt)

Use this when you want the shortest honest answer to:

- what can be paper-staged right now
- which names are blocked only because you have not approved them yet
- which names are actually bad paper tests because risk, structure, or liquidity says no

This is the fastest command to run before market open if you want a clean human
decision loop without weakening the desk's authority gates.

### Audit the paper evidence loop

```bash
./run_inferno_paper_evidence_loop.sh
./run_inferno_paper_exit_auditor.sh
```

This writes:

- [data/inferno_paper_evidence_loop.json](data/inferno_paper_evidence_loop.json)
- [reports/paper_evidence_loop_latest.txt](reports/paper_evidence_loop_latest.txt)

Use this when you want to know what the paper lane is missing right now:

- approvals
- staged fill capture
- open paper exits
- enough scored trades to support promotion

The exit audit adds a narrower open-position lens:

- which paper positions need to be closed now
- which ones deserve same-day review
- whether the fill log and ledger drifted apart

### Scan Downloads for broker-style CSVs

```bash
./run_inferno_downloads_manager.sh
```

This writes:

- [data/inferno_downloads_manager.json](data/inferno_downloads_manager.json)
- [reports/downloads_manager_latest.txt](reports/downloads_manager_latest.txt)

The scanner looks for recent trading-like CSVs in your Downloads folder,
normalizes supported files into the canonical fill log, archives processed
copies, and quarantines suspicious unsupported broker files for review.

This is intentionally conservative. Random CSVs should be ignored; weird
trading-like CSVs should be quarantined, not silently imported.

### Trigger the experimental thinkorswim export bridge

```bash
./run_inferno_tos_session_probe.sh
python3 inferno_tos_export_bridge.py run --dry-run
python3 inferno_tos_export_bridge.py run
```

This bridge is disabled by default. It activates thinkorswim and fires a local
export shortcut. It is export-only and should be treated as best-effort UI
automation, not a broker API. On macOS the live trading window commonly belongs
to the `java-arm` process, so the session probe should stay in the loop.
The live bridge also has a cooldown guard now, so repeated runs within the
cooldown window will skip cleanly instead of re-firing the shortcut.

### Verify the thinkorswim export path first

```bash
./run_inferno_tos_session_probe.sh
./run_inferno_tos_ui_route.sh --dry-run
./run_inferno_tos_export_verifier.sh
./run_inferno_tos_export_verifier.sh --require-enabled
```

This does not press keys. It checks the local config, app path, shortcut parse,
System Events accessibility path, watch agent status, whether thinkorswim is
actually running, whether the main `Main@thinkorswim` window is visible, and
whether the current workspace panel is considered safe for future automation.

When you want the desk to route itself into the export-safe view before any
future shortcut fires, use the guarded UI route helper:

```bash
./run_inferno_tos_ui_route.sh --dry-run
./run_inferno_tos_ui_route.sh
```

This route is intentionally narrow. It only knows how to bring thinkorswim to
the front and travel to `Monitor > Account Statement`. If the main window is
missing, it writes a failure report and stops.

Persist the local export/watch config:

```bash
python3 setup_inferno_export.py
python3 setup_inferno_export.py --enable-export --shortcut command+shift+e
```

### Run the export-plus-intake watcher

```bash
./run_inferno_downloads_watch.sh
./run_inferno_downloads_watch.sh --export-first
./run_inferno_desktop_automation.sh --export-first --require-tos-running
```

This optionally triggers the export bridge, then scans Downloads, updates the
canonical fill log, and ingests fills back into the paper ledger.

The desktop automation coordinator is the preferred "one button" local cycle.
It always runs the export verifier first, then chains the guarded watch lane
and a fresh paperMoney sandbox rebuild into one auditable report.

Optional LaunchAgent installer:

```bash
python3 install_inferno_downloads_watch_service.py status
python3 install_inferno_downloads_watch_service.py install
python3 install_inferno_downloads_watch_service.py install --export-first
python3 install_inferno_downloads_watch_service.py uninstall
```

Optional desktop-coordinator LaunchAgent:

```bash
python3 install_inferno_desktop_automation_service.py install --export-first --require-tos-running
python3 install_inferno_desktop_automation_service.py status
python3 install_inferno_desktop_automation_service.py uninstall
```

### Import paperMoney fills back into the desk

```bash
./run_inferno_tos_fill_ingest.sh
```

This writes:

- [data/inferno_tos_fill_ingest.json](data/inferno_tos_fill_ingest.json)
- [reports/tos_fill_ingest_latest.txt](reports/tos_fill_ingest_latest.txt)

This importer reads [data/inferno_tos_fill_log.csv](data/inferno_tos_fill_log.csv),
matches rows back to paper tickets, and updates realized paper outcomes before
performance analytics run.

Use the `ticketId` from the sandbox packet whenever possible. That keeps the
match exact and avoids ambiguity if you ever stage more than one structure on
the same name.

### Approve or reject a live name

```bash
python3 inferno_approval_queue.py approve TICKER
python3 inferno_approval_queue.py reject TICKER
python3 inferno_approval_queue.py reset
```

Email-style shortcut:

```bash
python3 inferno_approval_queue.py ingest --text "APPROVE CEG ABC12345"
python3 inferno_approval_queue.py ingest --text "DENY THR DEF67890"
python3 inferno_approval_inbox.py status
python3 inferno_approval_dispatch.py status
```

The morning brief now includes an `Approval Desk Quick Reply` section with the
exact commands for every pending ticker. Reply with one of those lines from the
approved inbox, and the next ops-maintenance sweep will update the queue and
refresh the execution desk automatically.

The desk also sends one dedicated approval email per pending ticker. Those
subjects already carry the queue token, so a reply body of only `approve` or
`deny` is sufficient. Ops maintenance backfills any unsent prompts without
re-sending the same token repeatedly.

### Demote stale pending approvals

```bash
python3 inferno_approval_queue.py expire
python3 inferno_approval_queue.py expire --ttl-market-days 7
```

The staleness governor demotes any ticker that has sat `pending` for more
than 5 market days (configurable) to `research-only` and writes an
`expirationReason` such as `approval-stale-6-market-days`. It only demotes;
it never approves a name and never re-promotes an already-decided ticker.

The same governor runs automatically inside `./run_inferno_ops_maintenance.sh`,
so this CLI is for ad-hoc cleanup or to test a different TTL.

### Run the operator daily loop

```bash
./run_inferno_daily_loop.sh
python3 inferno_daily_loop.py status
python3 inferno_daily_loop.py onboard
```

The daily loop chains every operator-facing read-only diagnostic into one
combined digest at `data/inferno_daily_loop.json` and
`reports/daily_loop_latest.txt`. Each step is failure-isolated, so a single
failing diagnostic does not abort the rest. Steps, in order:

1. approval cadence (batting order with decide-today flags)
2. per-ticker decision briefs
3. promotion gap (current vs lab thresholds)
4. threshold sensitivity sweep (calibration backtest)
5. strategy replay (shadow-as-paper)
6. daily success scorecard (green / yellow / red)
7. TOS export stability (verifier with backoff + fail-mode classifier)
8. skills audit (which subsystems went silent)
9. heartbeat ledger (which subsystems are still beating)
10. theme synthesizer (evidence cube: setup × regime × sector × IV × DTE, Wilson + bootstrap CIs)
11. hypothesis lab (generates and backtests testable claims with confidence intervals)
12. hypothesis ledger (trajectory memory: strengthening / weakening / stable / abandoned)
13. counterfactual replay (rank decision policies against closed shadow outcomes)
14. command-center brain refresh
15. brain cycle journal (snapshot every artifact into `data/cycles/YYYY-MM-DD-HHMM/`)

After all steps complete the loop also appends one row to the
stream-of-consciousness narration log at
`data/inferno_brain_narrations.jsonl` (bounded to the last 365 rows).

The combined digest also includes a short natural-language narrative
paragraph that reads like a colleague-handoff: where the desk stands, what
to decide today, and what to keep an eye on. The `onboard` subcommand
prints the new-model digest pulled from the command-center brain — useful
when a fresh model session is starting work.

### Run the living-and-breathing diagnostics standalone

The three new modules can each be run on their own:

```bash
python3 inferno_tos_export_stability.py                 # observation-only, 3 attempts default
python3 inferno_tos_export_stability.py --attempts 5    # for a more patient probe
python3 inferno_skills_audit.py                         # which skills went silent?
python3 inferno_heartbeat.py summary                    # which subsystems are alive?
python3 inferno_heartbeat.py record dawn_cycle --status ok --summary "morning brief"
```

The TOS stability runner re-runs the existing verifier with backoff and
classifies each attempt into a fail-mode bucket (e.g. `tos-not-running`,
`accessibility-blocked`, `window-missing`, `panel-unsafe`). It never invokes
the export shortcut and never enables recovery actions — it's the safe
"is the path stable?" probe.

### Watchlist closed-loop (autorefresh)

The closed-loop chain pulls tickers from TOS, updates the Earnings Tracker
sheet, and reconciles drift — automatically, every 5 minutes.

Install the LaunchAgent once:

```bash
# surveillance-only (extract + reconcile, no sheet writes)
python3 install_inferno_watchlist_autorefresh_service.py install

# full closed loop (also applies deltas to the sheet)
python3 install_inferno_watchlist_autorefresh_service.py install --auto-apply
```

The agent fires `inferno_watchlist_autorefresh.py` every 300 seconds. Each
tick:

1. `inferno_tos_watchlist_extract.py` reads the live TOS window via the
   accessibility tree (falls back to a recent CSV in `~/Downloads`).
2. If the snapshot has new tickers vs the last tick and `--auto-apply` is
   on, `inferno_watchlist_ingest.py apply` writes them to column A of
   `Earnings Tracker`.
3. `inferno_watchlist_reconciler.py` cross-checks TOS ∪ Sheet ∪ tracker
   and flags drift.
4. If anything changed, a `data/inferno_dawn_refresh_request.json`
   breadcrumb is dropped that the morning loop honours.

Manual one-shot equivalents (same modules, no LaunchAgent):

```bash
python3 inferno_tos_watchlist_extract.py        # one extract
python3 inferno_watchlist_ingest.py preview     # safe diff
INFERNO_WATCHLIST_CONFIRM=1 \
  python3 inferno_watchlist_ingest.py apply     # push deltas to the sheet
python3 inferno_watchlist_reconciler.py         # double-check pass
```

Override the watchlist name (default is `Earnings`):

```bash
INFERNO_TOS_WATCHLIST_NAME="Earnings Master" python3 inferno_tos_watchlist_extract.py
```

Disable the direct-sheet writer (forces staged-file fallback):

```bash
INFERNO_WATCHLIST_SHEET_DISABLED=1 python3 inferno_watchlist_ingest.py apply --confirm
```

Trigger the BC/P/Q/R formula refresh inline after appending:

```bash
INFERNO_WATCHLIST_TRIGGER_FORMULAS=1 INFERNO_WATCHLIST_CONFIRM=1 \
  python3 inferno_watchlist_ingest.py apply
```

The reconciler is the safety net — if the extractor missed a ticker, the
next tick's drift report surfaces it as `in TOS but not in sheet`.

The historical plan and the four open questions that drove the design live
in `docs/archive/WATCHLIST_INGEST_PLAN.md` for archeology.

### Bedside check: is the desk ready for tomorrow morning?

```bash
python3 "<repo-root>/inferno_night_prep.py"
```

The night-prep diagnostic walks fourteen checkpoints and reports a
top-line `readyForMorning` boolean:

- LaunchAgents loaded for dawn cycle, daily loop, watchdog, ops
  maintenance
- Doctor, ops maintenance, and daily loop artifacts are fresh enough
- Authority manifest still pinned to `paper-evidence-only`
- TOS export chain artifact exists and reports its verdict
- Schwab options source posture is known
- TOS read-only capture posture is known
- Cycle journal has at least one entry
- Watchlist input slot exists or is creatable
- Brain narration log has rows

It also emits a `dataSourcePosture` block:

- `schwabOptionsReady` tells us whether broker-grade option-chain data is
  currently enriching strike selection.
- `tosCaptureReady` tells us whether the already-open TOS window is ready for
  read-only broker capture.
- `overnightMathReady` can still be true when TOS is closed. That is the
  intended low-power posture; open TOS manually only when broker evidence is
  required.

Verdict ladder: `ready` (every check passes), `warming` (some warnings
but nothing fatal), `blocked` (at least one hard failure). The brain
console surfaces this verdict in the BREATHING line so you don't have
to re-run the diagnostic to see it.

See `docs/OVERNIGHT_DATA_PLAN.md` for the before-bed Schwab/TOS source
authority checklist.

### Diagnose the native TOS export path end-to-end

When the export verifier or stability runner says blocked and you need to
know which exact link broke, run the chain diagnostic:

```bash
python3 inferno_tos_export_chain.py
python3 inferno_tos_export_chain.py status   # last memo
python3 inferno_tos_export_chain.py --json   # structured output
```

The chain walks eleven steps in order: `config-loaded`, `app-installed`,
`app-running`, `accessibility-ok`, `main-window-present`, `panel-safe`,
`account-authorized`, `ui-route-dry-run`, `shortcut-valid`,
`applescript-builds`, `ingest-ready`. Each step reports PASS / FAIL /
SKIPPED with an attributed `detail` and a per-step `remediation` string.
Once a step fails, downstream steps that depend on it are marked SKIPPED
rather than re-run — so the operator can fix one link at a time and
re-walk the chain.

The chain never invokes the export shortcut and never enables recovery
mode. Output lands at `data/inferno_tos_export_chain.json` and
`reports/tos_export_chain_latest.txt`. The brain console also surfaces the
chain's verdict and first-failure attribution in the `BREATHING` line.

The skills audit walks every `inferno_*.py` module and `run_inferno_*.sh`
wrapper, finds the most-recent matching artifact in `data/` or `reports/`,
and classifies each skill as fresh / stale / silent / unknown.

The heartbeat ledger is a tiny append-only log that any scheduled service
can write to with `record_heartbeat(source, status, summary)`. The `summary`
subcommand prints which subsystems are still beating, which have gone
stale (over 36h), and which have gone silent (over 96h).

### Run the thinking layer standalone

The three modules below turn the desk from "monitors itself" into
"churns out testable ideas." All three are research-only, never promote
authority, and never modify shadow / lab / approval state.

```bash
python3 inferno_theme_synthesizer.py     # cube the evidence; rank edges + anti-edges
python3 inferno_hypothesis_lab.py        # generate and backtest hypotheses
python3 inferno_hypothesis_ledger.py summary  # trajectory of every hypothesis ever proposed
```

The **theme synthesizer** slices closed shadow outcomes across five axes
(setup × regime × sector × IV-rank bucket × days-to-earnings bucket) and
reports per-cell metrics with Wilson lower bounds on win rate and bootstrap
confidence intervals on expectancy. Cells whose Wilson lower clears the
production win-rate floor of 0.42 are reported as **edges**; cells whose
Wilson upper sits below that floor with negative mean expectancy are
reported as **anti-edges**.

The **hypothesis lab** reads the theme cube, the pending tickets, and the
strategy replay, then phrases each finding as a testable hypothesis from one
of five templates: `dimension-edge`, `dimension-anti-edge`,
`pending-match-edge`, `pending-mismatch`, `insufficient-but-trending`.
Each hypothesis carries its own Wilson / expectancy / profit-factor block
and a `testConfidence` score (0..1) weighted on Wilson lower, sample size,
and expectancy lower. The top hypotheses are ranked by `testConfidence`.

The **hypothesis ledger** is the desk's thinking memory. Each cycle it
takes the lab's output, compares each hypothesis to its previous
appearance, and tags it as `new`, `strengthening`, `weakening`, `stable`,
or `abandoned`. Hypotheses are deduped by id so the ledger sees the same
claim across cycles and tracks how confidence in it shifts as evidence
accumulates.

### Watch the brain operate

Three commands give you a window into what the brain is doing without
parsing JSON or opening fifteen text files:

```bash
python3 inferno_brain_console.py                 # one screen, current state
python3 inferno_brain_console.py --watch         # live-refresh every 30 s
python3 inferno_brain_console.py --json          # structured JSON for piping
python3 inferno_brain_console.py --save          # also write reports/brain_console_latest.txt

tail -f data/inferno_brain_narrations.jsonl      # stream-of-consciousness log
                                                  # one JSON row per cycle, append-only

ls data/cycles/                                  # list past cycle snapshots
cat data/cycles/2026-05-11-0630/narrative.txt    # read the brain at any past cycle
python3 inferno_brain_cycle_journal.py list      # same listing, scripted
```

The **brain console** is a pure read of existing artifacts. It pulls
together the desk verdict, decide-today queue, top hypotheses, ledger
trajectory deltas, theme cube counts, heartbeat status, TOS stability,
skills audit, and the latest narrative paragraphs into a single screen.
Missing or stale artifacts are flagged at the bottom rather than
crashing the view.

The **narration log** (`data/inferno_brain_narrations.jsonl`) is an
append-only stream that the daily loop adds one row to each cycle. Each
row is a single-line JSON object with timestamp, desk verdict, decide
list, top-hypothesis id and confidence, and the full narrative. The log
is bounded to the most recent 365 rows so it never grows unbounded.

The **cycle journal** (`data/cycles/YYYY-MM-DD-HHMM/`) is the time
machine. After every daily-loop fire, every key artifact is snapshotted
into a fresh directory keyed by the cycle's timestamp. The journal keeps
the most recent 90 cycles (≈45 weekday days at twice per day) and prunes
the rest automatically. Each cycle directory contains a `manifest.json`,
a `narrative.txt` with the operator-facing memo, and copies of all the
JSON artifacts the daily loop produced.

Together these three give you: an *instant* view (console), a *streaming*
view (narration log), and a *historical* view (cycle journal).

### Install the daily-loop schedule

```bash
python3 install_inferno_daily_loop_service.py install
python3 install_inferno_daily_loop_service.py install --times 06:30 12:30 16:30
python3 install_inferno_daily_loop_service.py status
python3 install_inferno_daily_loop_service.py uninstall
```

The installer writes a LaunchAgent that fires the wrapper at the given local
times on weekdays only. Default times are 06:30 (after dawn cycle) and 16:30
(after market close). Logs land in:

- `logs/inferno_daily_loop.stdout.log`
- `logs/inferno_daily_loop.stderr.log`

### Run and schedule the bounded evidence goal loop

The evidence goal loop wraps the paper/fast-paper harvest in the controls that
make a recurring automation safe: process and authority prechecks, persistent
state, command isolation, independent safety/execution/value graders, a
per-command timeout, a two-iteration cap, duplicate-work suppression, and
stop-on-no-progress behavior.

```bash
./run_inferno_evidence_goal_loop.sh run
./run_inferno_evidence_goal_loop.sh run --duplicate-cooldown-minutes 60
./run_inferno_evidence_goal_loop.sh verify
python3 inferno_evidence_goal_loop.py status

python3 install_inferno_evidence_goal_loop_service.py install
python3 install_inferno_evidence_goal_loop_service.py status
python3 install_inferno_evidence_goal_loop_service.py uninstall
```

The default schedule is 13:40 local on weekdays, after the 13:30 action pulse
and before the U.S. equity close. It cannot approve tickets, submit orders,
change the universe, or widen authority. Any authority drift or process breach
stops the cycle before paper evidence is mutated.

Run verdicts are intentionally outcome-specific:

- `productive` — the fixed evaluator accepted evidence or blocker progress.
- `maintenance` — stale artifacts were repaired without evidence gain.
- `no-op` — the cycle was safe and fresh but changed no accepted metric.
- `skipped-duplicate-work` — meaningful state was unchanged inside the
  cooldown.

Each saved run writes an Obsidian-compatible Markdown note under
`knowledge/agent-loop/runs/`. Open `knowledge/` as an Obsidian vault and use
`Agent Loop Runs.base` to review structured run properties. JSON remains the
machine source of truth.

### Backup before editing source

```bash
./scripts/inferno_backup.sh inferno_strike_selector.py
./scripts/inferno_backup.sh inferno_doctor.py tests/test_inferno_doctor.py
```

Snapshots land in `_backups/YYYY-MM-DD/<basename>.<HHMMSS>` and `_backups/`
is git-ignored. Use this before any code change so a recovery copy exists
even when git status is mid-flight.

### What the doctor now surfaces

Two informational lines have been added to `python3 inferno_doctor.py`:

- `Top block-reason bucket` — the heaviest category from
  `blockReasonCategories` in performance analytics. Useful to see at a glance
  why the funnel is stuck (commonly `approval-missing` or
  `size-cap-violation`). Always reports `PASS` because it is a signal, not a
  failure.
- `Setup concentration governor` — the cap, current primary count, and the
  number of plans demoted to shadow by `apply_setup_concentration_governor`.
  Demotions are evidence the cap is working; this line never bumps warnings.

The dashboard now exposes these same approval actions directly inside the `Order Intent Desk`, which is the preferred operator flow.

Once a name becomes `approval-ready`, use the desk's `Copy Ticket` action to grab the broker-review blueprint before routing anything inside thinkorswim.

### Prune old artifacts

```bash
python3 inferno_housekeeping.py --dry-run
python3 inferno_housekeeping.py
```

### Rank the slate without trusting absolute score scale

Use this when the raw `readyScore` looks like it is on the wrong scale but
the relative ordering still matters:

```bash
python3 inferno_slate_normalizer.py
python3 inferno_slate_normalizer.py status
```

This writes `reports/slate_normalized_latest.txt` and is research-only.
It does not override the live conviction gates.

## Where The Important Files Live

### Health and state

- [data/inferno_ops_status.json](data/inferno_ops_status.json)
- [data/inferno_watchdog_status.json](data/inferno_watchdog_status.json)
- [data/inferno_approval_queue.json](data/inferno_approval_queue.json)
- [data/inferno_execution_queue.json](data/inferno_execution_queue.json)
- [data/inferno_strike_plan.json](data/inferno_strike_plan.json)
- [data/inferno_paper_execution_ledger.json](data/inferno_paper_execution_ledger.json)
- [data/inferno_exposure_analytics.json](data/inferno_exposure_analytics.json)
- [data/inferno_edge_research.json](data/inferno_edge_research.json)
- [data/inferno_authority_manifest.json](data/inferno_authority_manifest.json)
- [data/inferno_tos_sandbox_session.json](data/inferno_tos_sandbox_session.json)
- [data/inferno_tos_fill_ingest.json](data/inferno_tos_fill_ingest.json)
- [data/inferno_downloads_manager.json](data/inferno_downloads_manager.json)
- [data/inferno_tos_export_bridge.json](data/inferno_tos_export_bridge.json)
- [data/inferno_downloads_watch.json](data/inferno_downloads_watch.json)
- [data/latest_snapshot.json](data/latest_snapshot.json)

### Human-readable outputs

- [reports/morning_brief_latest.txt](reports/morning_brief_latest.txt)
- [reports/morning_brief_latest.html](reports/morning_brief_latest.html)
- [reports/paper_tickets_latest.txt](reports/paper_tickets_latest.txt)
- [reports/long_term_buys_latest.txt](reports/long_term_buys_latest.txt)
- [reports/execution_desk_latest.txt](reports/execution_desk_latest.txt)
- [reports/strike_plan_latest.txt](reports/strike_plan_latest.txt)
- [reports/paper_execution_ledger_latest.txt](reports/paper_execution_ledger_latest.txt)
- [reports/paper_outcome_review_latest.txt](reports/paper_outcome_review_latest.txt)
- [reports/broker_preview_latest.txt](reports/broker_preview_latest.txt)
- [reports/performance_analytics_latest.txt](reports/performance_analytics_latest.txt)
- [reports/exposure_analytics_latest.txt](reports/exposure_analytics_latest.txt)
- [reports/edge_research_latest.txt](reports/edge_research_latest.txt)
- [reports/authority_manifest_latest.txt](reports/authority_manifest_latest.txt)
- [reports/tos_sandbox_session_latest.txt](reports/tos_sandbox_session_latest.txt)
- [reports/tos_fill_ingest_latest.txt](reports/tos_fill_ingest_latest.txt)
- [reports/downloads_manager_latest.txt](reports/downloads_manager_latest.txt)
- [reports/tos_export_bridge_latest.txt](reports/tos_export_bridge_latest.txt)
- [reports/downloads_watch_latest.txt](reports/downloads_watch_latest.txt)

### Logs

- [logs/inferno_dawn.stdout.log](logs/inferno_dawn.stdout.log)
- [logs/inferno_dawn.stderr.log](logs/inferno_dawn.stderr.log)
- [logs/inferno_watchdog.stdout.log](logs/inferno_watchdog.stdout.log)
- [logs/inferno_watchdog.stderr.log](logs/inferno_watchdog.stderr.log)

## If The Brief Is Missing

Run this first:

```bash
python3 inferno_doctor.py
```

Then check:

1. Did today’s run happen?
   - open [data/inferno_ops_status.json](data/inferno_ops_status.json)
2. Did the watchdog rescue it?
   - open [data/inferno_watchdog_status.json](data/inferno_watchdog_status.json)
3. Did the updater jobs fail?
   - open [logs/inferno_dawn.stderr.log](logs/inferno_dawn.stderr.log)
4. Is the latest local brief still stale?
   - open [reports/morning_brief_latest.txt](reports/morning_brief_latest.txt)

If you need a same-day recovery:

```bash
./run_inferno_dawn_cycle.sh
```

## If The Dashboard Looks Right But Email Did Not Arrive

Check:

```bash
python3 inferno_doctor.py
```

Then verify:

- `.env.smtp` still exists locally
- `emailSent` is `true` in [data/inferno_ops_status.json](data/inferno_ops_status.json)
- the SMTP account still accepts the app password

If needed, send a fresh brief manually:

```bash
./run_inferno_dawn_cycle.sh
```

## PyCharm Clarifier

You do not need PyCharm open for the desk to run.

The automation uses:

- the Backtest project files on disk
- the Backtest virtual environment Python
- the script filenames listed in the runner

What you do need:

- the project path still exists
- the `venv` still exists
- the Mac is awake or able to wake
- the Mac user session is logged in

## If The Sheet Or Scores Look Broken

The runner already tries to self-heal two common breakpoints:

- column `R` ATR repair
- columns `U:Y` score formula sync

If you want to force a rebuild:

```bash
./run_inferno_dawn_cycle.sh --skip-email
```

Then inspect:

- [data/inferno_ops_status.json](data/inferno_ops_status.json)
- [reports/morning_brief_latest.txt](reports/morning_brief_latest.txt)

## If TOS-Style Formula Values Look Off

Run the local formula mirror audit:

```bash
./run_inferno_tos_formula_audit.sh --limit 20
```

Then inspect:

- [reports/tos_formula_audit_latest.txt](reports/tos_formula_audit_latest.txt)
- [docs/TOS_FORMULA_MIRROR.md](docs/TOS_FORMULA_MIRROR.md)

The audit is diagnostic-only. It compares RVOL, trend, support, resistance,
and momentum against local history calculations and does not touch Sheets,
Schwab, TOS, or any staging queue.

## If You Need Your Special TOS Metrics In The Model

Create the editable ThinkScript metric registry:

```bash
./run_inferno_tos_custom_metrics.sh --init-registry
```

Pull formulas from the local TOS custom quote cache:

```bash
./run_inferno_tos_custom_metrics.sh --init-registry --pull-formulas-from-cache
```

Then review or edit each custom column's exact ThinkScript in:

- [data/tos_custom_metric_registry.json](data/tos_custom_metric_registry.json)

To capture current TOS-produced values, export the watchlist/custom quote table
to CSV and run:

```bash
./run_inferno_tos_custom_metrics.sh --values-csv "/path/to/tos-export.csv"
```

For the six OHLCV-only screenshot metrics, prefer the Schwab sync instead of a
manual TOS export:

```bash
./run_inferno_schwab_tos_metrics_sync.sh --from-snapshot --limit 12
```

This fetches Schwab daily candles, recomputes RVOL, Pv52H, MOM, ATR%,
Strength, and SUP/RES, then publishes the same
`data/inferno_tos_custom_metrics.json` artifact used by the model.

Then run the anti-confirmation theory audit:

```bash
./run_inferno_tos_metric_theory_audit.sh --limit 12
```

This checks whether each metric supports the thesis, challenges it, or is only
context. It also calls out formula caveats such as raw dollar MOM not being
scale-safe and ATR% being a risk/sizing signal rather than a directional edge.

Then inspect:

- [reports/tos_custom_metrics_latest.txt](reports/tos_custom_metrics_latest.txt)
- [reports/schwab_tos_metrics_sync_latest.txt](reports/schwab_tos_metrics_sync_latest.txt)
- [reports/tos_metric_theory_audit_latest.txt](reports/tos_metric_theory_audit_latest.txt)
- [docs/TOS_CUSTOM_METRICS.md](docs/TOS_CUSTOM_METRICS.md)
- [docs/SCHWAB_PRICE_HISTORY.md](docs/SCHWAB_PRICE_HISTORY.md)

Captured values are joined by ticker into the next tracker snapshot as
`tosCustomMetrics` and into `marketContext.tosCustomMetrics`.

## Labels And Roles

These are the names that matter:

- `Inferno Runner`
  - refreshes and sends
- `Inferno Watchdog`
  - verifies and rescues
- `Approval Desk`
  - stages decisions
- `Inferno Doctor`
  - gives a fast health answer
- `Inferno Housekeeping`
  - keeps runtime artifacts under control

## Suggested Weekly Hygiene

### Once a week

```bash
python3 inferno_housekeeping.py
python3 inferno_doctor.py
```

### Once a month

- review false positives
- review missed winners
- clean up threshold drift
- decide whether the approval rules earned more autonomy
