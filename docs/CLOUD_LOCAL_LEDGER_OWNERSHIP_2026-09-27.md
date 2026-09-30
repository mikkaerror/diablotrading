# Cloud/local ledger ownership — 2026-09-27

Status: implementation authorized by D5/D6 on 2026-09-30; frozen reconciliation complete, deployment verification in progress. The proposal below is retained as the migration design. See the operating-plan log and outputs/ledger-cutover-2026-09-30 for execution receipts.

## Recommendation

Use the **Mac operator desk as the canonical paper ledger and approval workflow
owner for now**. That is where `./inferno today`, reply ingestion, and the
source fill evidence are already reviewed. Cloud jobs should produce research,
quotes, reports, and separately namespaced shadow observations; the cloud should
consume a versioned read-only copy of canonical paper evidence for reporting.
Do not let both hosts overwrite the same mutable ledger or approval queue.

This requires an explicit reviewed cutover. Current cloud code still calls
`record_from_strike_plan`; this proposal does not disable it, move its schedules,
or imply it has already stopped. Until cutover, label every report with its
host, source revision and ledger identity, and treat the two ledgers as divergent.
Select one approval-email dispatcher and inbox owner at the same cutover. The
new local reservation lock does not coordinate two independent hosts.

A future cloud-owned ledger can be more available than a laptop, but it needs a
single transactional writer, durable operator-authenticated decision events,
immutable fill sources, versioned reads, restore-failure handling and tested
rollback first. A GCS file copied in and out by multiple jobs is not that service.
Availability alone is insufficient reason to move the operator evidence today.

## Observed evidence and uncertainty

| Observation | Basis | Implication |
|---|---|---|
| Local ledger has 105 rows: 96 paper-blocked, 6 paper-rejected, 3 paper-staged | Read-only inspection of `data/inferno_paper_execution_ledger.json` during this session | Total rows are not qualified outcomes or open trades |
| Local ledger lifecycle success is dated 2026-09-07; compatibility creation stamp is older | Same artifact, `updatedAt` and `lastSuccessfulAt` | Count is a saved snapshot, not proof of current execution |
| Latest local strategy report counts 1 source-reconciled scored trade | `reports/strategy_lab_latest.txt` | Do not turn ledger volume into promotion credit |
| Cloud has approximately 495 tickets and reports a $500 single-ticket cap | Operator handoff and Claude's 2026-09-28 UTC note | Not independently re-fetched in this session; overlap and image identity remain unverified |
| Local reports show a $2,000 paper cap from `paper-budget` | Session command-center/ticket-cap artifacts | This is existing local research policy, not live capital authority |

Relevant inspected source:

- `inferno_strike_selector.py`: strike evaluations explicitly pass `mode="paper"`.
- `inferno_risk_policy.py::evaluate_strike_item`: paper mode uses
  `PAPER_TICKET_BUDGET_DOLLARS`; live mode uses the separate live cap path.
- `inferno_config.py`: `INFERNO_PAPER_TICKET_BUDGET` defaults to `500`;
  `INFERNO_PAPER_DAILY_BUDGET` separately defaults to `1500`.
- `scripts/deploy_cloud_run_job.sh::write_env_file`: does not pass either
  paper-budget variable. Its new email-mode forwarding is delivery-only.
- `inferno_cloud_state.py`: restores/persists whole files without a merge or
  generation precondition. Its ledger object is under the configured bucket
  prefix, independent of an unconfigured Mac local file.

**The cap observation does not establish image drift.** Even the current paper
code yields a $500 cap if the cloud lacks the paper-budget environment override.
Check deployed immutable image digest/revision, the actual evaluator mode,
`effectiveSingleTicketCapSource`, and effective risk environment before deciding
whether code, configuration, or both explain the discrepancy. Read only the
needed non-secret configuration fields; never dump job secrets into reports.

## Paper-budget deployment proposal: operator ack required

Yes, the deployment script should eventually pass an **explicitly approved**
`INFERNO_PAPER_TICKET_BUDGET` so the effective policy is reproducible. It should
not silently inherit a workstation's override or hard-code $2,000 as a new cloud
default. Proposed operator question:

> Do you acknowledge applying the existing Mac paper-ticket budget of $2,000 to
> the designated cloud paper evaluator after verifying the deployed code and
> ledger ownership, with every other risk input unchanged?

This is a risk-policy question under CLAUDE.md §8, not a reporting fix. No ack
file was created, no environment was edited, and no paper-budget forwarding was
added. A later implementation should require the explicit approved value, record
its provenance and effective configuration, and reject an unacknowledged mismatch.
The separate paper daily budget, open-ticket limit, liquidity/freshness gates,
and live drawdown/capital rules remain unchanged. A $2,000 ticket ceiling does
not override a smaller remaining daily budget or make a candidate executable.

Before an ack, compare both caps against the **same frozen input and ledger** in
an isolated research run. Count only cap-block deltas, all-gates deltas, duplicate
exposure and daily-budget effects. Do not edit the evaluator to make candidates
pass. Neither the 105/495 count difference nor empty queues is evidence for
raising a limit. No cap-change impact estimate is claimed here.

## Reconciliation plan for operator review

1. Pause mutable paper/approval writers on both sides for a bounded maintenance
   window, after operator approval. Keep the failure auditor available. Capture
   immutable copies of both ledgers, queues, dispatch/inbox state, operator
   decisions, fill CSVs, import fingerprints, source attachments and relevant
   entry snapshots. Record SHA-256 hashes, UTC capture time, host, image digest,
   schema, lifecycle timestamps and GCS object generation. Never overwrite either
   source with the other before this archive exists.
2. Produce a dry-run crosswalk in a separate directory. Match exact ticket IDs
   first, including `mergedDuplicateTicketIds`; then compare semantic trade-date,
   ticker, event, strategy, expiration, ordered leg symbols/ratios and quantity.
   `planned_ticket_id` includes date/strategy/expiration/legs; different IDs may
   represent quote refreshes. Same ticker alone is never sufficient for merging.
3. Classify rows as identical, refresh-only duplicate, cloud-only, local-only,
   or conflicted. Preserve original IDs, entry-score snapshots, source timestamps
   and policy-version provenance. Do not average prices, sum duplicate P/L, reset
   pending age, select a status by newest timestamp, or reinterpret a historical
   block under today's risk budget. Conflicting fills, decisions, contract terms
   or lifecycle histories require a human disposition; missing evidence remains
   unknown. Preserve stale and rejected records as history.
4. Keep unverified cloud-only observations in an archive/research namespace until
   source reconciliation establishes their type and provenance. Never promote
   blocked, shadow or intrinsic-estimate rows into counted fill evidence. Re-run
   the existing fill economics, evidence lineage, completeness and strategy-lab
   checks on the proposed copy. Report before/after total rows, distinct events,
   duplicates, unresolved conflicts and qualified outcomes separately. A larger
   merged history is not permission to increase promotion credit.
5. Crosswalk approval requests separately. Reconcile only explicit human decisions
   with audit provenance; do not infer approval from a token, a sent email, a
   staged row or a broker preview. Preserve pending token/event identity and the
   union of daily email reservations. If two pending tokens conflict, present a
   proposed canonical mapping for review; do not silently accept both. Route old
   email replies only if their exact request is still live and unambiguous.
6. Present the manifest, conflict list, test results and proposed canonical copy
   to the operator. Apply only an explicitly authorized migration. Configure one
   writer/sender/inbox owner; use generation-checked snapshot publication and
   serialize writers. Failed restore must block mutation and approval delivery;
   it must not fall back to an empty ledger/history and overwrite the archive.
7. Verify a second reconciliation is a no-op, old pending replies still resolve,
   cloud/local report counts match the same snapshot hash, and all authority
   fields remain off. Keep rollback copies and validate later scheduled runs.
   Rollback must not erase human decisions made after cutover: replay reviewed
   audit events rather than blindly restoring an older file.

Acceptance requires zero unexplained row loss, explicit conflict dispositions,
unchanged protected risk/authority code, no invented fills or decisions, no
unreviewed increase in qualified evidence, and one active writer/sender. This is
a migration proposal, not authorization to approve, reject, close or promote a
paper ticket.

Related: [[EMAIL_CONSOLIDATION]], [[SYSTEM_MAP]], and CLAUDE.md §§2, 4, 8.
