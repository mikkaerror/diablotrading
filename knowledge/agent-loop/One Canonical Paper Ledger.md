# One Canonical Paper Ledger

Whole-file cloud restore/persist is not reconciliation. Independent Mac/cloud
ledgers can accumulate different blocked observations, decisions and outcomes.
Do not choose a winner by row count or latest filesystem timestamp.

Current proposal: retain the Mac operator ledger as canonical until a reviewed
single-writer cutover; archive cloud-only history and crosswalk immutable identity,
fill provenance and operator decisions. Local 105 rows versus cloud approximately
495 is a coverage discrepancy, not evidence of 390 missing qualified trades.
The cloud count is operator-reported, not independently fetched in this session.

A $500 cloud cap also does not prove stale code: the inspected current paper
budget defaults to $500, and deployment omits its override. Verify image, mode,
cap source and configuration separately. Forwarding the Mac's $2,000 override
requires operator risk-policy ack; it has not been implemented.

Evidence and migration acceptance criteria:
[[../../docs/CLOUD_LOCAL_LEDGER_OWNERSHIP_2026-09-27]]. Falsifier for the proposed
operating model: no way to preserve fill/decision provenance or reliably publish
versioned snapshots from the Mac. If that occurs, design a cloud transactional
writer for operator review instead of enabling dual writes.
