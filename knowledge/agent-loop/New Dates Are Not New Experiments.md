# New Dates Are Not New Experiments

Date: 2026-09-28
Owner: codex
Related: [[Archive Decisions Without Rewriting History]]

Belief: changing a report date does not create a new independent observation.

Rule: one contract exposure per shadow hold-to-expiration protocol. Preserve
original entry economics and all legacy outcomes. Fast next-session experiments
remain a distinct protocol but must have new quote/economic inputs to re-enter.
Actual inserted rows, not shortlist size, determine accepted seeding progress.

Evidence: prior audit found 1,025 closed shadow rows for 452 contract structures,
including 85 extra rows sharing structure, entry price and source snapshot.

Falsifier: a replay of unchanged contract/input data increments experiment count,
or ingestion modifies an existing entry or outcome. Deterministic tests and the
frozen-source replay protect against both. No change to trading authority.
