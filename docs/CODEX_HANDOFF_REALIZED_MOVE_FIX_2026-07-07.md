# Codex handoff — fix the realized-move data (do this FIRST)

- **Date:** 2026-07-07 (final handoff of the night)
- **From:** Claude (research lane) → **Codex**
- **Priority:** **#1, ahead of the sell-side wiring.** Until realized move is
  measured correctly, every backward number (buy AND sell) is untrustworthy, so
  there is nothing to wire toward yet.
- **Authority:** unchanged. Data-correctness only. No gate/risk/authority change.
- **Full diagnosis:** `docs/DATA_INTEGRITY_REALIZED_MOVE_2026-07-07.md`.

## The defect

`data/inferno_expected_move_ledger.json` `realizedAbsMovePct` is not a valid
per-event earnings move:

1. **Pseudo-replication.** 100 records = only **30 distinct realized values across
   13 names**. Names like KEYS/MRVL/VNET carry ONE realized value copied across
   5–9 rows — the same earnings event snapshotted at different pre-earnings times.
   Effective sample ≈ 30, not 100.
2. **Implausible magnitude.** 17 of 100 records show >40% "moves" (DELL 91%, HPE
   68%). Real single-name earnings-day reactions are ~5–15%. The realized-move
   window/method is wrong.

Quick repro:
```
python3 inferno_short_premium_study.py status   # -> VERDICT: data-unreliable... + banner
```

## The fix

1. **Recompute `realizedAbsMovePct` as the earnings-day reaction**, per distinct
   earnings event: `abs(close(T+1) / close(T-1) - 1) * 100` around the actual
   report datetime (or your agreed short window). Not a multi-week/cumulative move.
   Sanity-cap review: flag anything >40% for manual check before it lands.
2. **De-duplicate to one row per `eventId = ticker + earnings-date`.** Keep the
   entry snapshot you actually traded (or the last pre-earnings snapshot); collapse
   the repeated pre-earnings snapshots so each earnings event is ONE record.
3. **Backfill `impliedMovePct` from the same entry snapshot** so implied and
   realized are measured on the same event, then recompute `moveRatio`,
   `moveEdgePct`, `beatImpliedMove`, `outcomeR`.
4. **Add an upstream integrity guard** mirroring the one shipped in
   `inferno_short_premium_study.data_integrity()`: fail loud if
   replication > 1.5x, any realized > 40%, or any name has a frozen
   (single-value-across-many-rows) realized. Wire it into `inferno_doctor` so this
   can't silently return.

## Definition of done

- Expected-move ledger has one row per distinct earnings event; realized moves are
  plausible (≈5–15% typical, outliers verified).
- `python3 inferno_short_premium_study.py status` → verdict is no longer
  `data-unreliable-cannot-conclude-backward` (integrity passes).
- `inferno_doctor` flags realized-move corruption if it ever recurs.
- Full suite green; authority invariant clean; commit in your lane.

## Queue order after this

1. **(this) realized-move data fix** — unblocks all backward analysis.
2. Liquidity spread-primary gate (`CODEX_HANDOFF_LIQUIDITY_GATE_2026-07-07.md`) —
   in progress / mostly landed.
3. Short-premium defined-risk arm + wide universe
   (`CODEX_HANDOFF_SHORT_PREMIUM_2026-07-07.md`) — only meaningful once #1 makes
   the evidence trustworthy.

## Standing truth

Buy-side long premium is a KILL (theory + data). Sell-side is an unproven forward
hypothesis, NOT backward-supported (the support was corrupted). The only valid
evidence for either side is the forward, per-event, friction-real paper campaign —
which needs #1 done to mean anything.
