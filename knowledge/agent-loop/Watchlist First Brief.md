---
type: watchlist-research
updated: "2026-08-13"
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

An operator-provided TOS screenshot is evidence for the symbols visibly shown,
not proof that it contains every member of a named saved watchlist. Reconcile
the visible symbols into the canonical tracker only with the operator's
authorization, but do not overwrite the explicit personal-watchlist input or
claim complete synchronization until an end-of-list capture or export confirms
the full membership.

## Evidence

On 2026-08-10 the persisted four-symbol input was labelled
`tos-live-positions-2026-05-20`. It is both position-derived and stale, so the
brief did not silently present it as the current personal watchlist. The first
brief instead used the 146-name current tracker and its nine pre-existing edge
research priorities. It surfaced OTEX and TDC as research-first rows and kept
AVGO, ORCL, QCOM, and MRVL in monitor context with their existing caveats.

On 2026-08-13, the operator supplied an end-to-end capture of the named
`i keep a semi` watchlist: 186 source symbols, 185 canonical U.S. tracker
symbols, and one explicit external symbol (`EME:ASX`) held for mapping rather
than guessed. All 185 canonical symbols were reconciled to the Google Earnings
Tracker, including NBIS. A `TOS Pulse` tab now records the visible cadence
fields—last price, daily change, 52-week range, volume, RVOL, Pv52H, MOM,
ATR%, strength, and support/resistance—with an as-of date and source label.

The 2026-08-12 Schwab daily-candle refresh produced all six exact OHLCV formula
mirrors for 181/185 canonical symbols. `ASTK`, `GLDD`, `THR`, and `VMW` had no
daily history and remain explicit coverage exceptions, not zeros or scores.
The ingest cap now accepts the whole validated list, the CSV fallback reads
only a real ticker column, and a named full capture cannot be overwritten by a
different/default extractor run. These are provenance and research-data
improvements only; no authority, universe, gate, sizing, or live-trading state
changed.

On 2026-08-13, the complete 185-symbol price-history artifact was joined into
the research snapshot as `watchlistPulse` and copied into its `marketContext`.
The observed-only payload captures last, daily net and percent change, 52-week
range, volume, RVOL, Pv52H, momentum, ATR%, strength, support/resistance,
formula coverage, and source as-of time. The refresh measured 181 complete
six-mirror records and the same four transparent no-history exceptions. It
does not create a new score or feed existing readiness, priority, eligibility,
sizing, risk, or authority formulas; duplicated TOS and OHLCV metrics are
explicitly not double-counted.

The daily refresh now builds Schwab price history and the formula-metric
artifact before rebuilding the tracker snapshot. This avoids a one-run lag in
which the snapshot could have consumed yesterday's pulse while the refreshed
artifact was written later in the same loop. If Schwab authorization is
unavailable, the tracker refresh continues with the prior labelled artifact
and records the source-refresh failure as advisory rather than presenting it
as current data.

## Falsifier

This belief is false if the brief changes a score or gate, loses source
provenance, treats a stale position extract or partial screen capture as an
operator watchlist, implies a buy/sell/order instruction, or requires the
operator to maintain a ticket ledger to see current research priorities.
