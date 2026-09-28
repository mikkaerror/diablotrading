# System Map

One-page architecture for the Inferno desk. Read this before changing code,
touching broker automation, or handing work to another model.

## Mission

Build an automated earnings/options research desk that can refresh data, score
setups, collect paper evidence, and brief the operator without granting live
trading authority prematurely.

The concise command brief lives in [`MISSION_CONTROL.md`](MISSION_CONTROL.md).
Use this file for architecture; use Mission Control for purpose and strategy.
Use [Model Research Guidelines](MODEL_RESEARCH_GUIDELINES.md) for assumption
reviews and challenger experiments. Those guidelines govern research design;
they do not implement new scoring rules or expand execution authority.

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

The dawn entry point bounds its complete child job; command-center inputs are
cached only within one build. Account freshness distinguishes usable observations
from failed attempts, and unchanged due work respects finite retry windows.
See [[DESK_CLEANUP_2026-09-22]] for measurements and regression evidence.

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

The 07:35 Mountain options refresh writes a verified completion receipt through
`inferno_refresh_handoff.py`. The 07:50 morning brief requires its same-session
source timestamps and unchanged hashes before work and before delivery; an
unguarded fallback is prohibited. The 07:30/17:10 diagnostic digest preserves
its cadence and labels source build times. Doctor and command center expose
the handoff. See [[REFRESH_BRIEF_HANDOFF_2026-09-07]].

Mutable evidence ledgers retain a compatibility `generatedAt` creation stamp,
but lifecycle freshness is explicit: `createdAt`, `updatedAt`,
`lastSuccessfulAt`, `lastAttemptAt`, `sourceDataAsOf`, and
`lifecycleStatus`. A failed refresh may update only the attempt/failure record;
it cannot advance the last successful evidence timestamp or make an old source
look current. The first producers on this contract are the paper-execution and
shadow-evidence ledgers; command-center summaries expose their lifecycle data.

Score calibration is an archive diagnostic, not a fitted probability model.
New paper, shadow, and scenario entries preserve an immutable
`entryScoreSnapshot`; refreshes may update display ranks but cannot replace
the captured prediction or manufacture a missing legacy snapshot. Calibration
separates paper and shadow rows, reports repeated ticker/expiration exposure
and premature shadow reviews, and uses native-rank quartiles for priority.
Legacy rows remain unverified for model fitting. Future shadow expiration
reviews wait until the following day and require the exact expiration-day
equity close from a later Schwab daily-history snapshot; missing history waits
without substituting a current mark. This is an intrinsic proxy, not a fill or
broker settlement. See [[MODEL_CALIBRATION_REVIEW_2026-09-06]] for evidence,
remaining limitations, and predeclared challenger experiments.

Conviction now preserves valid zeros, labels reviewed missing/invalid inputs,
rejects nonmeaningful fallback P/E and excludes past events from forward lists.
Its scores, grades and source penalties remain uncalibrated. The threshold
audit distinguishes single-predicate selectivity from complete eligibility.
See [[ASSUMPTIONS_AND_BIG_PICTURE_2026-09-12]] for source-label limitations,
overlapping inputs and the unchanged-production-threshold review.

Paper outcome review is now a read-only operator queue. Expiration never
closes a paper ticket. Fill ingestion defaults to a non-mutating preview,
including legacy scheduled `ingest` calls and missing-report status fallbacks.
Only the dedicated operator fill wrapper (or `record-fill`, scoped to its
selected ticket) opts into applying fills. Preview runs preserve the last
actual ingest report and all ledger lifecycle timestamps. See
[[OPERATOR_OUTCOME_BOUNDARY_REPAIR_2026-09-07]].

The strategy lab admits only closed paper fills reconciled to the saved fill
CSV and imported fingerprint, with matched identity, execution facts and
fill-adjusted risk. Intrinsic estimates remain visible as reported outcomes
without sample credit. Lab/lineage/completeness, the paper gap, velocity and
loop progress use this distinction. Saved-log consistency does not establish
independent broker execution or costs. See
[[PAPER_OUTCOME_QUALIFICATION_2026-09-07]]. The same qualifier now reconciles
P/L against entry/exit/quantity and explicit gross/net fee basis. Unknown fees
stay unknown; supplied costs affect scoring only when source and execution
metadata agree. See [[PAPER_FILL_ECONOMICS_2026-09-07]].

## Canonical Truth

Generated artifacts beat durable docs when they disagree.

| Question | Canonical artifact |
|---|---|
| Smallest safe handoff | `reports/usage_optimizer_latest.txt` |
| Compact supervisor picture | `reports/model_command_center_onboard_latest.txt` |
| Current supervisor picture | `reports/model_command_center_latest.txt` |
| One-line desk verdict | `reports/central_command_latest.txt` |
| Compact watchlist research priorities | `reports/watchlist_brief_latest.txt` |
| Desk Editor morning facts (Claude-owned; reporting only) | `reports/desk_editor_latest.txt` |
| Health check | `reports/doctor_latest.txt` |
| Formula integrity | `reports/math_verify_latest.txt` |
| Secret hygiene | `reports/secret_hygiene_latest.txt` |
| Paper bottleneck | `reports/paper_bottleneck_reducer_latest.txt` |
| Paper blocker diagnosis | `reports/paper_blocker_swarm_latest.txt` |
| Liquidity/premium blocker matrix | `reports/liquidity_premium_matrix_latest.txt` |
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
| Full industry roles, timelines and issuer-review gaps | `reports/industry_coverage_latest.txt` |
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

`reports/score_threshold_audit_latest.txt` also joins the tracked universe and
reference taxonomy to saved alternative pricing and the effective ticket-cap
policy. It distinguishes nominal-price discovery filters from actual contract
loss, exposes call-spread upside caps and expiration/earnings coverage, and
labels selected large-move history as tail evidence. The JSON preserves source
timestamps and missing inputs. Counterfactual filter counts are diagnostic;
they never feed selection or staging. Expected-move candidates carry explicit
option-tenor comparability metadata and cannot claim matched-horizon fair value.

The same audit and `reports/trade_management_latest.txt` expose entry/exit
economics: target/stop dollars, return denominator, whole-unit scale-out
feasibility and full-loss stress. MTM uses actual paper-fill credit/debit and
quantity where present, suppresses incomplete-leg P/L, and keeps midpoint
and bid/ask liquidation estimates distinct. Earnings countdowns age from
dated evidence; undated counts remain unknown. Management is advisory and
does not execute exits, change campaign exit assignments or tune thresholds.
The pure `inferno_trade_evidence.entry_economics` helper is the common source
of entry price, quantity and adjusted payoff denominators for MTM and exit
reports. Invalid fills/counts remain unknown. Marks with a known mismatch
against the ticket's current entry basis cannot fire price rules; their fetch
status, timestamp and rejection reasons remain visible. Planning price and
actual fill price are displayed separately.

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

`inferno_liquidity_premium_matrix.py` reconciles the current pricing pass,
source-candidate blocker swarm, and expected-move ledger. It reports both
priced-variant rows and deduplicated ticker/quote observations so alternatives
sharing one snapshot are never counted as independent market failures. Its
source-premium pressure remains provenance for the original long-vol candidate,
not a failure of an alternative structure; structure-specific premium blocks
must come from that structure's own pricing risk record. Its snapshot clock
time is descriptive provenance, not an intraday timing claim; it does not
create or alter a gate.

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
- `./inferno watchlist` — compact research-first view of the current tracker; it does not expose ticket, approval, or order workflow
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
- `./inferno schedule` — all installed Inferno LaunchAgents and Codex automation schedules, including repeat intervals, plus read-only custom-cadence and exact same-minute timing observations; it never changes a schedule
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

### Research measurement audit

`./inferno research-audit` builds a read-only cross-desk measurement report from
saved paper/shadow evidence, calibration, issuer research, short-premium study,
cash attribution and loop economics. `inferno_research_audit.py` writes
`data/inferno_research_audit.json` and `reports/research_audit_latest.txt`; doctor
and command center summarize unresolved gaps. The existing daily refresh runs it
before the command center. Source hashes and observed deltas do not imply new
validated outcomes. It sends no mail and is not a trading or promotion gate.
`inferno_research_records.py` adapts canonical shadow `items` for retrospective
walk-forward/factor diagnostics. See
[measurement audit](RESEARCH_MEASUREMENT_AUDIT_2026-09-28.md) for limitations and
prospective evaluation requirements.

### Historical decision archive

`./inferno archive` captures and searches an append-only local history of paper,
shadow, fast-simulation, scenario, approval-state, strike-proposal and operator-log
sources. Exact compressed snapshots, source hashes, recorded reasons, corrections
and contract-exposure grouping live under `data/decision_archive/` (private,
permanent retention; no automatic pruning). Supported persistence writes capture
immediately; daily refresh sweeps remaining saved sources. Doctor and command
center expose `reports/decision_archive_latest.txt`. It performs no ticket or
broker action and is not a promotion input. [Archive contract](DECISION_ARCHIVE.md).
