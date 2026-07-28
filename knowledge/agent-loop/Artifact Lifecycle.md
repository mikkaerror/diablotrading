---
type: agent-loop-operations
updated: "2026-07-26"
research_only: true
live_trading_allowed: false
tags:
  - inferno
  - agent-loop
  - artifact-lifecycle
  - provenance
---

# Artifact Lifecycle

Links: [[Storage Hygiene]] · [[Loop Optimization Principles]] · [[Authority Boundary]]

## Belief

For mutable research evidence, creation, successful recomputation, failed
attempts, and source-data age are separate facts. Filesystem mtime and a legacy
`generatedAt` value cannot establish current evidence by themselves.

## Contract

The shared lifecycle helper preserves legacy `generatedAt` as creation-time
compatibility data and adds `createdAt`, `updatedAt`, `lastSuccessfulAt`,
`lastAttemptAt`, `sourceDataAsOf`, `producer`, `freshnessPolicy`, and
`lifecycleStatus`.

A successful recomputation advances `updatedAt`, `lastSuccessfulAt`, and
`lastAttemptAt`. A failure advances only `lastAttemptAt`, records
`lastFailure`, and changes `lifecycleStatus` to `failed`; it must never advance
successful evidence freshness or replace the last valid source-as-of time.

## Evidence

On 2026-07-26, the shadow-evidence and paper-execution ledgers had been
rewritten that morning while retaining `generatedAt` values from 2026-05-12 and
2026-04-22 respectively. The lifecycle contract was added to make that state
observable without rewriting historical records or changing any paper ticket,
risk setting, universe, or authority.

## Falsifier

The contract is failing if a failed ledger refresh advances
`lastSuccessfulAt`, if a dashboard treats `generatedAt` as a mutable ledger's
freshness timestamp, or if a source timestamp is absent while the artifact is
called current.
