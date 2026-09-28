# Decision and evidence archive

The archive preserves what the desk recorded, including why a proposal was
blocked or passed over, and what changed afterward. It is an observation system,
not a decision maker, trading journal inferred from prices, or promotion gate.

## Daily use

```bash
./inferno archive run
./inferno archive history --ticker DY --limit 20
./inferno archive history --ticker DY --before 1234 --limit 20
./inferno archive show --record-id 1234
./inferno archive verify
./inferno archive status
```

`run` sweeps current saved sources and recovers pending captures. It never
refreshes broker data or approves, rejects or closes a ticket. `history` returns
version IDs, recorded reasons, source lane, capture time and contract grouping;
`--before` pages backward through those IDs. `show` exposes the full archived
source record, its source-file SHA-256, row index, code receipt and later notes.
An approval state is not evidence of execution.

In the existing `./inferno today` prompt, a pass reason can be recorded in the
same response: `s Awaiting a fresh quote` or `n Thesis invalidated`. There is no
extra prompt. Bare letters still work; an omitted rationale stays unknown.
The existing approve workflow and decision permissions are unchanged.

## What is recorded

| Source | Meaning retained |
|---|---|
| Paper execution ledger | Saved ticket state, gates, construction, entry context, fills/outcomes as reported |
| Shadow evidence | Hypothetical structures and outcomes; never verified executions |
| Fast simulation ledger | Separate simulated entry/exit experiments |
| Scenario evidence | Underlying-price research observations, not option trades |
| Approval queue | Recorded approval state and decision timestamps; no decision action |
| Strike plan | Priced or blocked proposals, source quotes, risk checks and research context |
| Operator decision CSV | Exact recorded approve/skip/reject text and any supplied rationale |

The JSON persistence helper observes only these named evidence files, passing
the exact bytes written instead of rereading a potentially replaced file.
Strike-plan and server queue saves use that helper. The existing operator CSV
logger is captured after writing. Writers outside these helpers, including the
Claude-owned delegated CSV logger, are caught by the daily sweep; approval queue
state still passes through the JSON hook. No approval/delegation rules change.

A source record keeps everything it actually contains: thesis/research notes,
entry scores, market and quote context, gate reasons, intended structure,
risk inputs, exit rules and outcomes. **Missing fields stay missing.** We cannot
recover a rationale never recorded, a quote already overwritten before capture,
or a broker execution absent from source data. The current decision CSV has no
durable ticket ID; we do not invent joins from ticker alone. Source records in
different lanes stay distinguishable.

## Time, identity and corrections

- `sourceClaimedAt` is the timestamp the producer recorded. `capturedAt` is when
  the archive observed it. Initial history is labeled `saved-state-observation`,
  not reconstructed prediction-time knowledge.
- Every changed source file is retained as an exact compressed snapshot. Its
  SHA-256 identifies its bytes. Identical source bytes are stored once.
- Unchanged record content adds no new version. Outer refresh timestamps alone
  do not count as new decisions; their source snapshots still remain available.
  Nested quote/source timestamps are meaningful evidence and are retained.
- Changed reasons, prices, outcomes or source context append a new version.
  Corrections never overwrite the old account, including a later reversion to
  an earlier value. A missing record in a later source is not an inferred close.
- Contract grouping uses ticker, strategy, expiration and sorted leg symbols,
  directions and reported quantities, **without the trade date**. Missing
  contract identity falls back to source-record identity rather than a guess.
  These are exposure groups, not independent events or counts of executions.
- Cross-day or cross-lane copies remain auditable source observations under the
  same contract group. The archive does not add their P/L together, feed a
  promotion counter, or silently delete historical repeats.

For a later explanation or correction, append a dated annotation:

```bash
./inferno archive annotate --record-id 1234 --author operator \
  --reason 'Later clarification: the planned holding period was two sessions.'
```

Annotations are visibly retrospective. They never replace the original reason,
change a ticket decision, or turn hindsight into an entry-time feature. Author
text is a recorded attribution, not authenticated identity.

## Retention and relevance

**Retain core records permanently by default:** decisions and passes, original
reasons, subsequent corrections, source snapshots, outcomes and code receipts.
There is no automatic deletion or rolling window. Compression and content
hashing avoid retaining multiple byte-identical source blobs. Existing log and
dated-report housekeeping patterns do not target `data/decision_archive/`.

Age alone does not make a trade useless. For a new study, select records by the
same strategy version, instrument, horizon, execution/cost basis, source quality
and applicable market conditions. Show older/incompatible samples separately.
A current research window is a filter over history, not a reason to erase it.
A retrospective import never becomes forward validation merely by waiting.

Failed trades, rejected proposals and no-trades remain in the archive. They
support evaluation of missed opportunities and discipline, provided later
outcomes are collected under a predeclared comparison. No-trades have unknown
counterfactual P/L until that evaluation exists. Many small trades do not by
themselves establish positive expectancy; risk budgets and authority remain
unchanged while the desk collects evidence.

This is an engineering retention policy for the local research desk, not a claim
of regulatory recordkeeping compliance or immutable external custody.

## Durability, recovery and backup

Private state lives in `data/decision_archive/archive.sqlite3`, outside Git.
SQLite transactions serialize concurrent writers. Tables reject updates and
deletes; source blobs are compressed, hash-checked, and linked through snapshot
hashes. Source-record hashes and source-row linkage are verified as well.
This detects inconsistency; a filesystem owner could rewrite the whole archive.

Before ingestion, each capture is durably spooled under `pending/`. A database
failure leaves the exact captured bytes for recovery by the next `run`.
Capture receipts prevent replay after a crash between database commit and spool
cleanup. Failure to archive never repeats or reverses the original decision.
Warnings go to stderr and a local failure journal; pending captures, incomplete
spool files, parse errors and capture failure history appear in archive health.
Disk failure can prevent both the primary record and its backup—local durability
is not off-device recovery. Do not delete pending or failure evidence to make a
health report green.

Create a new consistent backup with SQLite's backup API, not a copy of a live DB:

```bash
./inferno archive backup --destination _backups/decision_archive/2026-09-28.sqlite3
```

The command refuses overwrite, checks SQLite integrity and prints the backup
hash. Recovery: stop archive writers, preserve the damaged/current directory,
place the recovery copy at `data/decision_archive/archive.sqlite3`, retain any
pending captures, and run `verify` before resuming. A restore round trip is
covered by tests. Off-device encrypted backup still needs an operator-selected
destination; no new cloud upload or ledger migration is performed here.

Cloud and local archives are separate stores. Copying this DB over another
host's DB would lose history. The pending canonical-ledger ownership decision
remains separate; do not claim a cloud merge or universal broker record.

## Operations

`reports/decision_archive_latest.txt` and `data/inferno_decision_archive.json`
provide archive health, source/version counts, missing rationale and integrity.
Doctor and command center surface the report. The existing daily refresh sweeps
the archive before its command-center handoff; immediate hooks capture supported
writes between sweeps. No new email or separate scheduled job is introduced.

The archive makes repeated work visible and avoids duplicate archive versions.
It does not yet stop legacy simulation producers from creating cross-day rows.
Changing experiment generation and migrating performance consumers to shared
identities are separate, testable repairs; they must preserve existing outcomes
and distinguish deliberate entry/exit variants from redundant replays.
