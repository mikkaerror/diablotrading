---
type: agent-loop-operations
updated: "2026-08-09"
research_only: true
live_trading_allowed: false
tags:
  - inferno
  - capital-readiness
  - authority
  - reporting
  - safety
---

# Capital Review Boundary

Links: [[Authority Boundary]] · [[Automation Cadence]] · [[Loop Optimization Principles]]

## Belief

Capital readiness can make a human review path eligible without approving a
candidate, a paper row, a broker preview, or an order. A planning amount is a
scenario input, not verified deployable capital or order authority.

## Contract

Capital readiness and the capital launch check preserve the legacy
`manualDeploymentAllowed` field for report compatibility, but publish
`manualReviewEligible` and `orderAuthorization: none` for human readers. The
rendered reports must state that a candidate, a planning amount, and a review
verdict never authorize a broker submission.

The check remains research-only: it does not change risk constants, candidates,
approval state, tickets, broker state, eligible universe, or authority.

## Evidence

On 2026-08-09, a $1,000 operator-argument scenario returned
`manual-ready-with-warnings`, while current data showed no stageable candidate,
29 paper outcomes still needed for automation promotion, cash attribution under
review, and auto live trading false. The prior phrase “Manual deployment
allowed” could be read as order permission despite those facts.

## Falsifier

This contract is failing if a readiness report calls review eligibility order
permission, omits `orderAuthorization: none`, treats planning cash as confirmed
cash, or causes any candidate, ticket, broker preview, risk setting, or
authority state to change.
