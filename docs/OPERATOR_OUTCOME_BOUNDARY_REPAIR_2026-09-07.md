# Operator outcome boundary repair — 2026-09-07

First repair from the end-to-end process review: background research must not
close operator paper tickets. Historical evidence qualification is next.

## Before and after

- Expiration review previously fetched the latest underlying quote and rewrote
  open paper outcomes as closed, including on expiration day. It now queues
  post-expiration operator review, makes no quote request and never saves the
  ledger. Pure payoff helpers remain available to isolated shadow research.
- The morning pipeline and downloads watcher called fill ingestion without an
  operator action; the strike-cycle shell invoked `ingest`. These now preview
  proposed changes. Preview counts cannot claim imported rows or accepted
  progress and cannot advance ledger timestamps, rewrite the CSV, or replace
  the last actual ingest report.
- Compatibility matters: old deployed shell calls to `ingest` also preview.
  The application needs `operator_requested=True`, or the dedicated operator
  CLI needs `ingest --operator-requested`, to apply reviewed fills. Status with
  a missing report cannot silently import. This flag is an application routing
  boundary, not authentication against a malicious caller.
- The existing `run_inferno_tos_fill_ingest.sh` operator wrapper opts in.
  `record-fill` opts in only for the selected ticket, avoiding unrelated CSV
  closures during a single-ticket action. Do not put these operator routes in
  scheduled jobs. Direct legacy Python `ingest` instructions now preview;
  operators can use the dedicated wrapper after reviewing their evidence.

## Validation and remaining scope

Regression fixtures include a valid closed CSV row, an expired open ticket,
existing historical outcomes, missing status reports, an old-style CLI call,
and a second unrelated ticket. The expected measurable delta is one proposed
closure with zero applied changes in unattended mode, versus one applied
closure in explicit operator tests. All writes in these tests use temporary
fixtures or mocked persistence.

Validation completed: 83 focused tests and 2,033 full-suite tests passed.
All 12 math invariants and secret hygiene passed; `git diff --check` is clean.
Doctor retains 11 attention items. A real-file read-only smoke check preserved
SHA-256 hashes of the paper ledger, fill CSV and last actual ingest report.
The manual run trace records zero promotion progress and unknown monetary cost.

No production paper ticket, risk constant, eligible universe, or broker
permission is changed. This is boundary correctness, not new promotion evidence
or demonstrated trading edge. Schedule drift and morning dependencies remain
separate work; no schedule was reinstalled during this repair.

Historical MOD/IREN intrinsic estimates still need separation from recorded
executions. DELL is not proven synthetic: sandbox seeding creates blank fill
stubs, and the seed note survives later data entry. Qualification must check
execution sources rather than reject a record solely for template provenance.

Suggested Claude task: audit refresh completion dependencies, the 07:30 brief
versus 07:35 refresh, holiday behavior and deployed-script drift. Coordinate
before editing shared orchestration; leave outcome reviewer, fill importer,
record-fill and promotion-evidence qualification to Codex. Preserve paper and
broker boundaries and report actual source timestamps.
