---
type: agent-loop-principles
status: active
tags:
  - inferno
  - agent-loop
  - control-system
---

# Loop Optimization Principles

## Objective

Increase verified paper and research evidence per unit of time without widening authority.

## Fixed rules

1. Safety is a gate, not an optimization target.
2. Execution success and useful progress are separate measurements.
3. Only fixed-evaluator deltas can classify a run as productive.
4. Identical state inside the cooldown is duplicate work.
5. Store compact outcomes and lessons; retrieve only what the current blocker requires.
6. Keep evaluator, authority, and live-broker boundaries outside unattended code mutation.
7. Prefer small, reversible experiments with explicit keep/discard criteria.
8. Back off after repeated no-progress runs, but never let skipped checks extend the gate forever.
9. Consolidate traces into falsifiable beliefs; retire or challenge beliefs when evidence changes.
10. Use swarm-style decomposition only for independent research lanes with machine-readable finishes.
11. Keep swarm outcome reward separate from accepted progress unless the fixed evaluator records a real evidence delta.
12. Freshness gates follow market sessions: on weekends and market holidays, the latest regular session plus same-day infrastructure checks are the active cycle.

## Accepted progress

- A new scored paper outcome.
- A reduction in remaining promotion evidence.
- A newly verified paper candidate that is stageable, auto-paper-selected, or approval-only.
- A closed fast-paper research ticket.
- A closed scenario observation.
- A measured reduction in paper hard-blocked candidates.
- A measured reduction in the dominant blocker.

Artifact refreshes are maintenance. A safe run with none of these changes is a no-op.

## Paper blocker swarm

The paper blocker swarm maps blocked paper candidates across independent lanes:
operator action, data freshness, liquidity, strike construction,
premium/evidence hurdle, capital fit, alternative structure, and
concentration/process.

Its rewards are intentionally split:

- coverage reward: each lane classified the candidate instead of collapsing to one serial explanation.
- finish reward: each lane returned a completed verdict.
- outcome reward: always zero inside the swarm artifact.

Only the evidence goal loop can accept progress, and only when the fixed
evaluator observes candidate discovery, blocker reduction, closed exploratory
evidence, or scored paper outcomes.

Related: [[Evidence Bottleneck]] · [[Authority Boundary]] · [[Current Loop State]]

Wealth and emotional urgency never alter this control logic. See [[Wealth Objective Boundary]].
