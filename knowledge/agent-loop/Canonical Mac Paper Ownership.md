# Canonical Mac Paper Ownership

D5/D6 explicitly authorize Mac ownership and a $2,000 paper single-ticket budget. Live caps, daily budget, open-ticket limits, liquidity/freshness gates and broker flags are unchanged.

The frozen 2026-09-30 archive contains 105 Mac rows and 496 cloud rows with SHA-256 hashes and GCS generations. Reconciliation is deterministic and read-only: 88 Mac-only, 7 refresh duplicates, 10 conflicts, 479 cloud-only. Keep the Mac ledger unchanged; quarantine all cloud observations with original identity and provenance. Neither an intrinsic close nor a cloud-only row gains fill credit. Conflicts remain for human review rather than automatic status selection.

The Mac runs the existing strike cycle after dawn and before the delegate. A second cycle after the delegate stages newly approved tickets before the Editor/cards. Only the existing delegate/operator can approve. Per-input receipts suppress duplicate cycles. Local mutations share a reentrant process/file lock. Ownership state pins the canonical root, host and acknowledgement hash; cloud paths reject paper/approval/fill mutation before side effects.

Cloud jobs restore one complete hash-verified canonical snapshot or stop. They never publish protected state or send approval/strike emails. Immutable snapshot files precede a generation-checked current pointer. Publication rechecks input hashes to reject mixed snapshots. Restore validation finishes before replacing any files. Cloud-only legacy objects remain archived and are not the canonical source.

The lifecycle test uses temporary files only and the real risk, approval, staging, fill-ingest and lineage functions. It proves one-host consistency, not broker fills or trading edge. Source hashes and the real 1/30 count must stay unchanged through cutover. Rollback must not restore an old mutable ledger over later operator decisions.
