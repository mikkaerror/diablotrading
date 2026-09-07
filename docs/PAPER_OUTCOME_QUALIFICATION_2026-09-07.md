# Paper outcome source qualification — 2026-09-07

The strategy lab now admits recorded paper fills only when they reconcile to
the saved fill source. A numeric closed outcome alone cannot count toward its
30-observation sample. This changes evidence admission, not ticket state or
risk policy. Statistical thresholds and live/broker restrictions are unchanged.

## Measured result on the same saved evidence

| Record | Before | After | Reason |
| --- | --- | --- | --- |
| MOD | Counted | Intrinsic estimate; excluded from lab sample | No recorded execution or closed source row |
| IREN | Counted | Intrinsic estimate; excluded from lab sample | No recorded execution or closed source row |
| DELL | Counted on planned risk | Source-reconciled recorded paper fill | Closed CSV row, imported fingerprint and execution fields match |

The source-reconciled sample is **1/30**, with **29 remaining**. Three numeric
historical outcomes remain visible as reported data. Independently verified
broker executions remain **0 established by this workflow**. Do not describe
one source-reconciled fill as one independently verified broker execution.

DELL's reported $30 P/L now uses its actual $1.80 debit and one strategy unit:
$180 risk, or 0.166667 R. The old denominator was the $320 planned debit,
producing 0.09375 R. Prices and quantities reconcile; costs are unverified,
so neither this value nor the reported P/L is represented as verified net profit.
Sandbox-seeded notes establish blank-template origin, not synthetic prices.

## Admission and source contract

`inferno_paper_provenance` reads the canonical fill CSV without invoking the
importer or changing its schema. Rows and SHA-256 hash come from the same byte
snapshot. Missing, malformed or duplicate-header sources fail closed.

Admission requires staged/closed paper status, a closed paper-fill-log
execution, a valid closed source row with matching ticket/ticker/strategy and
expiration, an imported row fingerprint, and matching entry/exit prices,
contracts, environment, timestamps and reported P/L. Fill-adjusted positive
finite risk supplies the denominator. Invalid numbers and explicit synthetic
or proxy evidence types are excluded. Identical exports are deduplicated;
conflicting closes and duplicate ticket identities cannot increase the sample.
Closes are sorted by timezone-aware execution time for drawdown calculations.

This is consistency with an operator-reported source, not authentication or
independent broker evidence. Full contract identities, original broker fills,
fees and settlement details still require a stronger source chain. The current
CSV is mutable: a missing or changed source withholds qualification rather than
silently inferring it from an old report. Durable source archival remains a
useful follow-up; no historical ticket is rewritten to manufacture provenance.

## Consumers

The strategy lab, promotion lineage and outcome-completeness report use the
same reconciliation contract. Legacy numeric rows stay visible in a separate
reported count. The paper evidence-loop gap, velocity builder and automated
progress evaluator now consume source-qualified counts rather than raw numeric
outcome volume. Historical performance analytics remain descriptive reported
ledger statistics; they are not independent execution verification.

Shadow replay cannot bypass the paper source gate by renaming status. Its
numeric observations remain visible as descriptive shadow count/mean R, while
the nested paper lab excludes them. No shadow or fast-simulation record gains
promotion credit.

Velocity uses source-reconciled execution close dates, excluding future dates.
The one-fill rate is too thin to forecast operational capacity; its unchanged
linear clearance calculation is a sample-throughput scenario, not a promise
of promotion or profitable edge. The separate Claude scheduling work owns
refresh completion dependencies and deployed script drift.

## Verification

Focused cases cover source and ledger tampering, invalid numbers, missing
sources/import keys, explicit synthetic records, innocuous seed notes,
conflicting exports, duplicate IDs across strategies, timezone ordering,
fill-adjusted risk, stale lab agreement, and raw growth failing to earn loop
progress credit. Statistical gate tests now supply explicit recorded-fill
fixtures instead of silently treating bare P/L as execution.

A real-file smoke check rebuilt the lab, lineage, completeness and velocity
reports while preserving SHA-256 hashes of the paper ledger, fill CSV and last
actual ingest report. This repair records zero new promotion progress and no
production ticket mutations; monetary run cost is unavailable.

Completed validation: 98 focused tests and 2,048 full-suite tests passed.
Math verification checked 12 artifacts without violations; secret hygiene and
`git diff --check` passed. Doctor retains 11 attention items. Central command
now reports a sample gap of 29 with live/broker submission still disabled.
