---
type: agent-loop-operations
updated: "2026-07-14"
research_only: true
live_trading_allowed: false
tags:
  - inferno
  - agent-loop
  - market-data
  - retries
---

# Market Data Retry Discipline

Links: [[Loop Optimization Principles]] · [[Storage Hygiene]] · [[Authority Boundary]]

## Durable rule

An empty market-data response and a raised transport exception are different
failure classes. Consecutive empty history responses receive one retry and are
then cached as an empty, schema-stable frame for the rest of the process.
Transport exceptions retain the full bounded retry budget.

The ticker-universe audit must also surface provider-skipped price symbols as
advisories even when an older sheet value still appears structurally valid.

## Evidence

The 2026-07-14 unified sync retried unsupported GLDD and THR history requests
four times per lookback period. Those identical empty responses produced no
accepted data and extended the dawn refresh. The bounded empty-result rule cuts
that work in half while preserving a retry for a transient empty response and
all four attempts for explicit exceptions.

## Falsifier

This rule is wrong if vendor telemetry shows that a third or fourth immediate
retry commonly recovers after two consecutive empty frames. In that case,
replace the fixed empty limit with measured provider-specific backoff rather
than silently widening retries for every symbol.

This optimization does not remove tickers, change the eligible universe, alter
risk policy, or create broker authority.
