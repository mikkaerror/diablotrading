# Archive Decisions Without Rewriting History

Date: 2026-09-28
Owner: codex
Related: [[Research Measurement Requires Provenance]]

Belief: a desk learns from immutable decisions, passes and observed outcomes,
not repeated retellings of the same simulation. An unexplained pass is missing
rationale, not a guessed strategy judgment.

Implementation: `./inferno archive` retains compressed exact source snapshots,
append-only record versions and retrospective annotations in a private local
SQLite archive. Captures have separate source-claimed and observed timestamps.
Same contracts across dates/lanes share an exposure key without granting
independent-event or execution status. Failed/rejected/no-trade records remain.

Durable rule: never backfill a historical reason or entry feature from today's
knowledge. Never sum duplicated source observations as independent P/L. A
simulation, an approval and a reconciled fill are different evidence classes.
Retain permanent core records; apply explicit relevance filters for each study.

Verification: unchanged captures add no new source snapshot or record version;
corrections/reversions preserve prior versions; interrupted ingestion recovers
without replay; concurrent writers serialize; backup restores with intact hashes.
Source count and archive integrity are bookkeeping metrics, not trading progress.

Falsifier: reconstructing a past decision from the archive with different source
bytes/reasons than were captured, losing a version on retry, or changing an
operator ticket during capture would invalidate the implementation contract.

Limitations: initial imports cannot recover overwritten history. Missing rationale
and absent broker evidence stay unknown. Local hashes are not external custody;
off-device backup and cloud/local ledger ownership remain explicit decisions.
The archive does not suppress new cross-day simulation entries at their producer.

Reference: [Decision archive](../../docs/DECISION_ARCHIVE.md).
