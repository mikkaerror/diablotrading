---
type: agent-loop-operations
updated: "2026-08-08"
research_only: true
live_trading_allowed: false
tags:
  - inferno
  - agent-loop
  - liquidity
  - premium-hurdle
  - provenance
---

# Liquidity / Premium Matrix

Links: [[Evidence Bottleneck]] · [[Short Premium Evidence]] · [[Authority Boundary]]

## Durable rule

Treat quoted structure variants, ticker exposures, and quote snapshots as
different denominators. Several alternative structures can share the same
underlying and source quote; they are not independent liquidity observations.
A missing quote or source premium record is **unobserved**, not a clean pass.
Source premium pressure describes the original long-vol candidate, not the
risk status of an alternative structure. An alternative premium block requires
its own pricing-risk evidence.

The matrix only joins existing pricing, blocker-swarm, and expected-move
evidence. It cannot introduce a threshold, loosen a quality or promotion gate,
or affect risk constants, universe membership, paper tickets, or broker state.

## Current observation

The 2026-08-07 local snapshot contains 66 pricing rows across 44 ticker
exposures but only 15 distinct ticker/quote observations. Of those rows, 30
are liquidity-blocked and 32 carry source premium pressure; 24 have both.
At ticker level the corresponding counts are 14, 10, and 8. No current row has
a structure-specific premium block, so the source-pressure count must not be
treated as an alternative-structure gate failure. Twenty-nine ticker exposures
have no quote evidence, so the report does not label them clear.

The 16 cap-fit fallback variants remain research-only. None has passed the
combined pricing and paper-risk gates.

## Falsifier

This belief fails if the matrix counts multiple variants sharing one
ticker/timestamp as separate quote observations, projects a source long-vol
premium hurdle into an alternative-structure block, displays a normalized
spread ratio as an unscaled percent, calls missing evidence clear, or creates
an authority-bearing field or action. Any failure requires a deterministic test
before the report can be trusted again.
