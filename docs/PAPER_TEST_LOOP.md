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
./run_inferno_paper_evidence_loop.sh
./run_inferno_paper_exit_auditor.sh
```

3. Approve sparingly.

```bash
python3 inferno_approval_queue.py approve TICKER
./run_inferno_strike_cycle.sh
```

4. Stage only when the sandbox says the ticket is stageable.

5. Log fills immediately.

```bash
./run_inferno_tos_fill_ingest.sh
./run_inferno_paper_evidence_loop.sh
```

6. Close and score outcomes.

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

## Canonical Artifacts

- [reports/paper_test_director_latest.txt](../reports/paper_test_director_latest.txt)
- [reports/paper_evidence_loop_latest.txt](../reports/paper_evidence_loop_latest.txt)
- [reports/paper_exit_audit_latest.txt](../reports/paper_exit_audit_latest.txt)
- [reports/tos_sandbox_session_latest.txt](../reports/tos_sandbox_session_latest.txt)
- [data/inferno_tos_fill_log.csv](../data/inferno_tos_fill_log.csv)

## Standard

The desk needs scored paper outcomes, positive expectancy, tolerable drawdown,
clean exposure, and preview-safe payloads before any live authority can expand.
