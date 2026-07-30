---
type: system-constraint
status: active
tags:
  - inferno
  - evidence
  - bottleneck
---

# Evidence Bottleneck

The binding promotion constraint is closed, scored paper evidence. Research artifacts can improve selection and learning, but they do not substitute for the 30-outcome gate.

The loop therefore tracks three evidence levels separately:

- Promotion evidence: scored paper outcomes.
- Fast-paper evidence: bounded research-only simulated tickets.
- Scenario evidence: underlying-price observations that are not paper fills.

The levels must never be conflated. Progress at a lower level can improve learning velocity but cannot grant live authority.

The evidence loop also distinguishes live/broker safety from permission to
mutate paper evidence. A halted authority manifest keeps live and broker flags
hard-false, yet denies the paper-cycle scope when critical inputs are stale.
That distinction is diagnostic only: a passing safety invariant never permits
the harvest to run while paper-cycle authority is withheld.

The paper variant scanner is part of the fast-paper evidence lane. It creates
research-only defined-risk candidates when the main funnel goes stagnant, then
hands them to the normal pricing and risk gates. Its output can increase paper
chances, but it is not operator approval, promotion evidence, a risk-constant
change, or broker authority.

The score threshold audit is the durable check against blaming stagnation on
strict gates without evidence. Its current role is diagnostic: catalog the
score, threshold, and sizing assumptions; keep scores as rank surfaces until
option-outcome calibration exists; and direct progress toward more closed,
scored paper outcomes rather than looser authority.

The paper-outcome completeness audit is the intake falsifier for this bottleneck.
It separately reports whether the canonical paperMoney fill log is absent,
schema-invalid, empty, status-ignored, closed but incomplete, or close-ready for
an operator-run ingest. A populated CSV is not evidence by itself: only an
immutable, matched fill record with the required execution facts can remove
provenance debt, and the audit never imports or alters a ticket.
The importer applies the same fail-closed checks, rejecting incomplete or
invalid closed rows before they can mutate a paper ticket.
The readiness audit calls a row close-ready only after that exact staged-ticket
identity check passes; column completeness alone is not operator work.
Doctor surfaces rejected and unmatched rows as intake debt, never as outcomes.
Closed evidence also requires timezone-aware, chronological execution times;
non-finite supplied P/L is ignored in favor of the validated execution-price
derivation.

On 2026-07-27, the canonical fill log contained two `planned` rows. These are
useful prefilled operator templates but count as zero accepted progress and
must never be described as paper fills. The completeness report now preserves
the raw status count, labels this state
`fill-log-stubbed-awaiting-operator-execution`, and emits a read-only work item
for each closed, lab-scorable result with missing provenance. Recovery requires
actual paperMoney order/fill history; it must never be inferred from a strike
plan, outcome estimate, shadow record, or cash movement.

The `inferno_paper_capture_template.py` worksheet reduces the same
transcription risk by pre-filling immutable staged-ticket identity facts while
leaving execution facts blank. It excludes expired staged tickets and reports
that exclusion explicitly; emitting it never stages, closes, scores, or
promotes a ticket. Its falsifier is simple: without an unexpired staged ticket
and operator-supplied paperMoney fill facts, it produces zero fillable rows and
zero promotion evidence.

Related: [[Loop Optimization Principles]] · [[Authority Boundary]]
