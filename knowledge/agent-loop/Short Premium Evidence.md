---
type: agent-loop-belief
updated: "2026-07-14"
status: active
research_only: true
live_trading_allowed: false
tags:
  - inferno
  - agent-loop
  - short-premium
  - evidence
---

# Short Premium Evidence

Links: [[Loop Beliefs]] · [[Evidence Bottleneck]] · [[Authority Boundary]]

## Current belief

The short-premium thesis has no usable backward realized/implied move pairs in
the current expected-move ledger and no closed forward
`SHORT_PREMIUM_DEFINED` records. The honest verdict is
`insufficient-realized-move-data`; no edge claim is supported.

## Measured evidence

- Usable backward observations: 0.
- Forward campaign: 0 / 60 distinct events and 0 / 40 distinct names.
- The 2026-07-14 unified sync originally crashed the study on a partial row,
  then on the resulting empty observation set.
- The repaired producer skips partial or invalid ratios, publishes blank
  backward metrics, writes strict JSON atomically, and remains visible in the
  doctor and command-center report map.

## Durable rule

Missing or invalid realized-move inputs are excluded, never imputed. An empty
observation set must publish an explicit insufficient-data artifact rather than
crash, reuse stale output, or calculate a synthetic edge.

## Falsifier

This belief is falsified when reviewed source data provides at least one valid
realized/implied move pair or the forward paper campaign records a closed,
friction-accounted `SHORT_PREMIUM_DEFINED` event. Any edge claim still requires
the preregistered breadth, clustered confidence, and tail-concentration gates.

This note cannot change paper staging, promotion, risk constants, broker submit,
or live-trading authority.
