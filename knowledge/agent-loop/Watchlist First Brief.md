---
type: watchlist-research
updated: "2026-08-10"
research_only: true
live_trading_allowed: false
tags:
  - inferno
  - watchlist
  - usability
  - research-only
  - authority-boundary
---

# Watchlist-First Brief

Links: [[Authority Boundary]] · [[Artifact Lifecycle]] · [[Wealth Objective Boundary]]

## Belief

A small, source-labelled view of the current tracker is more useful for daily
research than asking the operator to navigate paper-ticket machinery. Simpler
presentation must not turn research ranks into an order or conceal stale
watchlist provenance.

## Contract

`./inferno watchlist` builds `reports/watchlist_brief_latest.txt` from the
existing edge-research and conviction artifacts. It displays a compact
research-first list plus monitor context. It introduces no score, gate, sizing,
ticket, approval, or authority path.

If `data/inferno_watchlist_input.json` is fresh and operator-labelled, the
brief narrows to that explicit list. A position-derived or dated-out input is
shown as a warning and the current full tracker remains the source instead.

## Evidence

On 2026-08-10 the persisted four-symbol input was labelled
`tos-live-positions-2026-05-20`. It is both position-derived and stale, so the
brief did not silently present it as the current personal watchlist. The first
brief instead used the 146-name current tracker and its nine pre-existing edge
research priorities. It surfaced OTEX and TDC as research-first rows and kept
AVGO, ORCL, QCOM, and MRVL in monitor context with their existing caveats.

## Falsifier

This belief is false if the brief changes a score or gate, loses source
provenance, treats a stale position extract as an operator watchlist, implies a
buy/sell/order instruction, or requires the operator to maintain a ticket
ledger to see current research priorities.
