---
date: 2026-09-10
researchOnly: true
promotable: false
---

# Metric semantics repair September 10

Operator authorized sequential implementation after the guardrail audit.
First priority implemented in `inferno_edge_research.py`: meaningful finite
positive P/E only, explicit forward/trailing/tracker source/status, fallback
only for absent values, and a consistent valid future earnings interval for
catalyst classification. Existing missing-P/E bucket and all weights/cutoffs
remain unchanged. The scoring fallback is not a valuation of the business.

Frozen full-universe impact: 183 rows, eight score reductions of 3.36 points,
zero lane changes, zero score increases. Missing metadata for 55 names remains
missing. Inputs, baseline source and comparison are under
`outputs/metric-semantics-2026-09-10/`. Regression cases include negative/zero/
nonfinite P/E, missing-value fallback, past/missing/invalid event offsets, and
valid zero-day and 21-day boundary values.

Original audit artifacts characterize the pre-repair implementation and remain
historical. No empirical edge, order authority, risk-policy change or paper
outcome was earned by this repair. Next priority is research-only industry
coverage without changing the eligible universe or legacy theme-score bonuses.
