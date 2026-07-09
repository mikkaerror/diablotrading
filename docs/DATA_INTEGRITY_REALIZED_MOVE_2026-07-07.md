# Data-integrity finding — the realized-move column is corrupted (retracts the sell-side backward support)

- **Date:** 2026-07-07
- **Author:** Claude (research lane). Research-only. No authority/gate/risk change.
- **Severity:** high. Invalidates every realized-vs-implied conclusion drawn from
  `data/inferno_expected_move_ledger.json`, **including the sell-side lead written
  earlier today.** Honesty requires walking that back.

## What happened

Investigating whether "over-moving" is a persistent, exploitable name trait (which
would make the sell side workable), I found a split-half persistence correlation of
**0.962** — implausibly clean. Interrogating it exposed the cause: the ledger's
`realizedAbsMovePct` is not a valid per-event earnings move.

## Two concrete defects

1. **Pseudo-replication.** The "100 records" contain only **30 distinct realized
   values across 13 names**. Several names carry one realized value repeated across
   many records (KEYS, MRVL, VNET: a single value across 5–9 rows). These are
   snapshots of the *same* earnings event at different pre-earnings times, not
   independent events. Effective sample ≈ 30, not 100. The 0.962 "persistence" is
   an artifact of the same number repeated within a name.
2. **Implausible magnitudes.** **17 of 100 records show >40% "earnings moves"**
   (DELL 91%, HPE 68%). Real single-name earnings-day reactions are ~5–15%. A 91%
   value means the realized-move window/method is wrong (measuring a multi-week or
   cumulative move, or a mis-scaled field), not a one-event reaction.

## What it invalidates

- The **sell-side "positive center"** (median +0.50R, 64% win, 9/13 names
  positive) came from `1 - moveRatio`, and `moveRatio` inherits the broken realized
  column. **That lead is not backward-supported.** I retract the "promising"
  framing; the pre-registration stands only as a *forward* hypothesis.
- The **buy-side numbers** (realized 21.9% vs implied 32.5%) are unreliable in
  magnitude. The buy-side KILL still holds on *theory* (buying overpriced
  pre-earnings premium is structurally negative) and on the fact that even this
  generous/corrupt data couldn't make buying clear the bar — but do not cite the
  specific figures.
- Any module reading this ledger (expected-move verdict, DTE replay netR) is
  suspect for the same reason.

## What still stands

- The **variance-risk-premium theory** (sellers are paid, buyers pay) is
  independent of this ledger.
- The **only trustworthy evidence is forward**: per-event, earnings-day realized
  move, real chain prices, friction charged. This is exactly what the paper
  campaign is designed to gather — and now clearly the *only* valid path for either
  side.

## Fixes

1. **Root cause (Codex / data lane):** correct `realizedAbsMovePct` to the
   earnings-day (or defined short window) reaction, computed once per distinct
   earnings event; de-duplicate the ledger to one row per `eventId`.
2. **Guardrail (shipped, this session):** `inferno_short_premium_study.py` now runs
   a `data_integrity()` check and returns
   `verdict = "data-unreliable-cannot-conclude-backward"` with a prominent banner
   when replication > 1.5x, any >40% magnitude, or frozen realized values appear.
   The daily monitor will surface the banner instead of false-precise numbers.
3. **Broader:** apply the same integrity check upstream wherever realized move is
   consumed.

## The honest lesson

Twice now the desk's "edge" dissolved under scrutiny — first over-counted
correlated trades, now a corrupted realized-move column feeding both the kill and
the pivot. The pattern is the throughline of this whole engagement: **the
measurement, not the market, has been the problem.** No strategy — buy or sell —
can be judged until realized move is measured correctly, one clean value per event.
The forward paper test is the only instrument that does that.
