# Paper Test Loop

The paper loop turns conviction into evidence without risking live capital.

## Daily Rehearsal

1. Refresh the lane.

```bash
./run_inferno_strike_cycle.sh
```

2. Read the paper state.

```bash
./run_inferno_paper_test_director.sh
./run_inferno_paper_bottleneck_reducer.sh
./run_inferno_paper_evidence_loop.sh
./run_inferno_paper_exit_auditor.sh
```

3. Use the reducer for evidence throughput.

```bash
cat reports/paper_bottleneck_reducer_latest.txt
```

The reducer targets 12 daily scenarios and highlights the top five. Only rows
marked `PAPER` are eligible for paperMoney staging. Rows marked `SHADOW` are
for observation and after-the-fact scoring only.

4. Approve sparingly.

```bash
python3 inferno_approval_queue.py approve TICKER
./run_inferno_strike_cycle.sh
```

5. Stage only when the sandbox says the ticket is stageable.

6. Log fills immediately.

```bash
./run_inferno_tos_fill_ingest.sh
./run_inferno_paper_evidence_loop.sh
```

7. Close and score outcomes.

```bash
./run_inferno_outcome_review.sh
./run_inferno_strike_cycle.sh
python3 inferno_doctor.py
```

## Paper States

- `ready-to-paper-stage`: at least one clean paper ticket is available.
- `approval-bottleneck`: viable candidate exists, approval is missing.
- `research-watch`: no clean ticket, but names are worth monitoring.
- `no-viable-paper-tests`: slate is too weak, expensive, illiquid, or broken.
- `scenario-slate-ready`: reducer produced the daily paper/shadow evidence slate.
- `scenario-slate-thin`: reducer ran, but the tracker did not have enough clean
  non-Avoid rows to reach the scenario target.

## Canonical Artifacts

- [reports/paper_test_director_latest.txt](../reports/paper_test_director_latest.txt)
- [reports/paper_bottleneck_reducer_latest.txt](../reports/paper_bottleneck_reducer_latest.txt)
- [reports/paper_evidence_loop_latest.txt](../reports/paper_evidence_loop_latest.txt)
- [reports/paper_exit_audit_latest.txt](../reports/paper_exit_audit_latest.txt)
- [reports/tos_sandbox_session_latest.txt](../reports/tos_sandbox_session_latest.txt)
- [data/inferno_tos_fill_log.csv](../data/inferno_tos_fill_log.csv)

## Standard

The desk needs scored paper outcomes, positive expectancy, tolerable drawdown,
clean exposure, and preview-safe payloads before any live authority can expand.
