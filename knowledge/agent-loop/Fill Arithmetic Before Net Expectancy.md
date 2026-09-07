---
type: operating-belief
status: implemented
date: 2026-09-07
scope: paper-fill-economics
---
# Fill arithmetic before net expectancy

Belief: agreement between a fill CSV and its imported copies does not prove
that reported P/L follows from prices and quantity. Blank fees cannot support
net-return claims.

Rule: independently calculate the standard-position gross P/L, reconcile any
supplied P/L to its declared gross/net basis, and subtract explicitly supplied
total round-trip fees once. Missing costs remain unknown; contradictory or
nonfinite data is rejected. No paper record is repaired by the audit.

Evidence: fixtures with a consistent but false $9,999 P/L are excluded; $30
gross less $35 total fees is scored as a $5 net loss. Existing DELL remains
$30 gross, fees unknown, with no additional qualified outcome.

Falsifier: false arithmetic is admitted, absent fees become zero, fees are
multiplied again, or a cost edit retains valid imported provenance.

Durable isolation lesson: initializing an intake-specific CSV must not call a
helper bound to global sandbox files. A discovered blank-column schema side
effect was restored byte-for-byte and is covered by a path-isolation test.

Cost and progress: test duration is not monetary cost. This repair improves
evidence integrity but creates zero accepted paper outcomes. Independent
execution and cost-source verification remains unestablished.

See [[PAPER_FILL_ECONOMICS_2026-09-07]],
[[PAPER_OUTCOME_QUALIFICATION_2026-09-07]], and
[[Process Trust Before Throughput]].

Validation: 89 focused and 2,083 full tests pass; math12 clean; doctor retains
11 attention items. A later existing schema writer re-added the two empty
optional columns; original CSV cells remain identical and five other protected
files match pre-run hashes. The lab still reports one unknown-fee observation,
zero net-of-reported-fee observations, and zero independent verification.
