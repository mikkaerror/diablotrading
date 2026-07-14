---
type: agent-loop-operations
updated: "2026-07-14"
research_only: true
live_trading_allowed: false
tags:
  - inferno
  - agent-loop
  - operations
  - storage
---

# Storage Hygiene

Links: [[Loop Optimization Principles]] · [[Authority Boundary]] · [[Current Loop State]]

## Durable rule

Unattended housekeeping may bound runtime log growth, but it must not delete or
compact paper ledgers, cycle evidence, market-data snapshots, broker exports, or
other evaluator inputs. Rebuildable caches and Git maintenance require an
explicit housekeeping invocation.

Canonical ledgers must keep decision evidence without duplicating raw provider
payloads. Paper entries retain their selected legs, quote-quality metrics, and
source provenance, while full Schwab contract arrays remain in the dedicated
source artifact. Existing ledger history is never rewritten by housekeeping.

## Measured baseline

- Repository size before cleanup: 172 MB; after normal Git packing and cache
  cleanup: 98 MB.
- `.git` before cleanup: 69 MB with 8,197 loose objects and 26 temporary
  fragments; after `git gc`: 4.8 MB with no loose-object garbage.
- External Inferno logs before trimming: 7.3 MB / 145,295 lines; after trimming
  to the configured 500-line cap: 292 KB / 5,195 lines.
- The 90-cycle journal and durable paper ledgers were preserved.
- A 2026-07-14 audit found 12.4 MB of raw Schwab contract arrays copied into 25
  historical paper entries. The producer now omits those arrays from new
  entries while retaining compact evaluator inputs; historical evidence stays
  byte-for-byte untouched.

## Falsifier

This policy is failing if nightly housekeeping changes any canonical evidence
artifact, if an operator loses data needed to reproduce an evaluator result, or
if external runtime logs again grow materially beyond their configured cap after
a successful nightly run.

Housekeeping changes storage operations only. They cannot change authority,
risk constants, the eligible universe, broker state, or paper-ticket decisions.
