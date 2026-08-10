---
type: agent-loop-operations
updated: "2026-08-09"
research_only: true
live_trading_allowed: false
tags:
  - inferno
  - agent-loop
  - action-pulse
  - freshness
  - provenance
---

# Pulse Freshness

Links: [[Automation Cadence]] · [[Authority Boundary]] · [[Artifact Lifecycle]]

## Belief

A quick action pulse is useful only when it distinguishes its current
lightweight checks from daily-loop prose reused from an earlier artifact.
Saved prose is context, not a current gate result, candidate promotion, ticket
stage, or order authorization.

## Contract

Fast mode skips heavy maintenance and loads the saved daily-loop artifact. Its
payload and rendered memo label that narrative `saved-artifact` and preserve
its source timestamp. A non-fast build labels the prose `fresh-build`.

The saved-artifact renderer also normalizes obsolete `decide-today` and
`approve/reject` wording to the review-only boundary. Current gates—not saved
prose—remain the authority source.

The pulse continues to show the independently refreshed research-review queue
and freshness panel. Those checks take precedence over the narrative. The
change does not alter scheduler cadence, native TOS export, quality or
promotion gates, risk constants, universe, paper tickets, broker submission,
or order authority.

## Evidence

On 2026-08-09, `./inferno action-pulse` was verified to select the fast path
by default. That path intentionally reuses a daily-loop artifact while the
read-only Schwab and capital checks may be newer. The renderer now exposes the
saved-versus-fresh provenance and timestamp before displaying the prose.

## Falsifier

This belief is false if a fast pulse presents saved daily-loop prose as fresh,
omits its provenance, lets narrative outweigh current gates, invokes the full
desktop path automatically, or permits a queue or narrative to stage or
approve an order.
