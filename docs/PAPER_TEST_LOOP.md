# Paper Test Loop

The paper loop turns conviction into evidence without risking live capital.

## Daily Rehearsal

1. Refresh the whole evidence lane when you want the boring one-command path.

```bash
./run_inferno_paper_evidence_harvest.sh
```

This chains the paper director, reducer, accelerated option simulation cohort,
scenario evidence, outcome review, paper evidence audit, exit audit, and
scenario backtest. Use the individual commands below when you need to debug a
specific stage.

The accelerated cohort scans the broader bootstrap-ranked universe, selects
the largest cap-fitting set of up to five structures, and closes each
simulation after the next market session at conservative Schwab bid/ask
liquidation prices. Its ledger is isolated from the true paper ledger. These
trades accelerate exploratory learning but never reduce the 30-trade promotion
gap.

The scheduled evidence goal loop also runs the universe cap-fit audit,
paper-test director, and paper blocker swarm. The swarm decomposes failed paper
candidates into independent lanes: operator action, data freshness, liquidity,
strike construction, premium hurdle, capital fit, alternative structure, and
concentration/process. Its coverage and finish rewards are diagnostic only; the
outcome reward remains zero until the fixed evaluator sees real paper progress.
A run is productive only when that evaluator sees a real delta such as a newly
verified paper candidate, a hard-blocker reduction, a closed fast-paper ticket,
a closed scenario observation, or a scored paper outcome.

2. Refresh the strike lane when the options plan itself needs rebuilding.

```bash
./run_inferno_strike_cycle.sh
```

3. Read the paper state.

```bash
./run_inferno_paper_test_director.sh
./run_inferno_paper_blocker_swarm.sh
./run_inferno_paper_bottleneck_reducer.sh
./run_inferno_fast_paper_cohort.sh
./run_inferno_scenario_evidence.sh
./run_inferno_paper_evidence_loop.sh
./run_inferno_paper_exit_auditor.sh
```

4. Use the reducer for evidence throughput.

```bash
cat reports/paper_bottleneck_reducer_latest.txt
./run_inferno_scenario_evidence.sh
./run_inferno_scenario_backtest.sh
cat reports/scenario_evidence_latest.txt
cat reports/scenario_backtest_latest.txt
```

The reducer targets 12 daily scenarios and highlights the top five. Only rows
marked `PAPER` are eligible for paperMoney staging. Rows marked `SHADOW` are
for observation and after-the-fact scoring only.

The scenario backtest then compares those names against closed paper/shadow
evidence. Treat `insufficient-data` as a useful warning, not a failure: it means
the setup can be tracked, but the desk has not earned confidence yet.

The scenario evidence lane is lighter than paper execution. It records the
daily slate as underlying-move observations and closes them after the review
horizon. Those observations help separate winners from noise, but they are not
fills, option P/L, approvals, or broker authority.

5. Let approval-only paper setups auto-select when risk is clean.

`auto-paper-selected` means the model found a setup where the only remaining
blocker is human approval. That is enough for simulated paper evidence, but it
does not authorize a live order.

6. Approve sparingly for live-style review.

```bash
python3 inferno_approval_queue.py approve TICKER
./run_inferno_strike_cycle.sh
```

7. Stage only when the sandbox says the ticket is stageable.

8. Log fills immediately.

```bash
./run_inferno_tos_fill_ingest.sh
./run_inferno_paper_evidence_loop.sh
```

9. Close and score outcomes.

```bash
./run_inferno_outcome_review.sh
./run_inferno_strike_cycle.sh
python3 inferno_doctor.py
```

## Paper States

- `ready-to-paper-stage`: at least one clean paper ticket is available.
- `auto-paper-selected`: viable paper-only candidate exists and approval is the only blocker.
- `approval-bottleneck`: viable candidate exists, approval is missing.
- `research-watch`: no clean ticket, but names are worth monitoring.
- `no-viable-paper-tests`: slate is too weak, expensive, illiquid, or broken.
- `fixable-blockers-present`: blocker swarm found a research/tooling route,
  such as refreshing divergent data or auditing bounded fallback structures.
- `operator-action-required`: blocker swarm found only human approval work;
  unattended code must not approve or reject.
- `market-quality-blocked`: blocker swarm found liquidity or premium-quality
  blockers that should remain out of paper staging.
- `scenario-slate-ready`: reducer produced the daily paper/shadow evidence slate.
- `scenario-slate-thin`: reducer ran, but the tracker did not have enough clean
  non-Avoid rows to reach the scenario target.
- `scenario-evidence-research-only`: daily slate observations are tracked as
  underlying-move evidence only; they cannot promote live authority.

## Canonical Artifacts

- [reports/paper_test_director_latest.txt](../reports/paper_test_director_latest.txt)
- [reports/paper_blocker_swarm_latest.txt](../reports/paper_blocker_swarm_latest.txt)
- [reports/paper_bottleneck_reducer_latest.txt](../reports/paper_bottleneck_reducer_latest.txt)
- [reports/scenario_evidence_latest.txt](../reports/scenario_evidence_latest.txt)
- [reports/scenario_backtest_latest.txt](../reports/scenario_backtest_latest.txt)
- [reports/paper_evidence_loop_latest.txt](../reports/paper_evidence_loop_latest.txt)
- [reports/paper_exit_audit_latest.txt](../reports/paper_exit_audit_latest.txt)
- [reports/tos_sandbox_session_latest.txt](../reports/tos_sandbox_session_latest.txt)
- [data/inferno_tos_fill_log.csv](../data/inferno_tos_fill_log.csv)

## Standard

The desk needs scored paper outcomes, positive expectancy, tolerable drawdown,
clean exposure, and preview-safe payloads before any live authority can expand.
