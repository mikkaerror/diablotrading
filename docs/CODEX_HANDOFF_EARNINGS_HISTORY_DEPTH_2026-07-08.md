# Codex handoff — build per-name earnings history depth (the new bottleneck)

- **Date:** 2026-07-08
- **From:** Claude (research lane) → **Codex**
- **Authority:** unchanged. Research/data only. No gate/risk/authority change.
- **Read first:** `docs/STRATEGY_DEEP_DIVE_2026-07-08.md` (why selection is the whole
  edge) and `reports/earnings_richness_signal_latest.txt` (the signal harness).

## Thank you + what your fix revealed

`43ce154 expected-move: repair realized event moves` fixed the corrupted realized
column — integrity now passes (14 records = 14 distinct values, replication 1.0,
0 implausible). That was queue #1. It immediately exposed the real constraint:

**The clean ledger is 13 names with ~1 earnings event each (12 names have 1 event,
1 has 2, ZERO have ≥4).** The strategy deep dive + the literature (Liu, AFA) are
clear that the *entire* sell-side edge lives in ranking names ex-ante by earnings
richness. You cannot rank or validate a per-name signal on one observation per
name. So the signal harness (`inferno_earnings_richness_signal.py`) correctly
returns `insufficient-history-for-oos-test` and will keep doing so until depth
exists.

## The ask: backfill per-name earnings history

For each name in the campaign universe, assemble a history of past earnings events
with, per event:

- `earningsDate`
- `impliedMovePct` at entry (the pre-earnings ATM straddle-implied move)
- `realizedAbsMovePct` (earnings-day reaction: `abs(close(T+1)/close(T-1) - 1)`)
- derived `moveRatio`, `richness = 1 - moveRatio`

Target **≥ 8 past earnings per name** (≈2 years) so the walk-forward out-of-sample
test has real power.

### The hard part (flag early)

- **Realized** history is easy: historical daily prices around each past earnings
  date (Schwab price history or any EOD source).
- **Implied** history is the catch: you need the pre-earnings ATM implied move at
  each *past* earnings, which requires historical option prices/IV. Schwab's API
  may not provide deep historical option chains. Options:
  1. A historical earnings implied-move data source (e.g. ORATS or similar) —
     likely the cleanest, possibly paid. **Surface the cost/decision to the
     operator before committing spend.**
  2. Approximate historical implied from historical underlying IV term structure if
     available.
  3. If neither is feasible, accumulate forward only (slow: ~2 years of live paper
     to reach depth) and say so plainly.

## Definition of done

- `data/inferno_expected_move_ledger.json` (or a new history file the signal reads)
  contains ≥8 clean events for a meaningful set of names, integrity passing.
- `python3 inferno_earnings_richness_signal.py status` reports a real verdict
  (`signal-predictive-out-of-sample` or `signal-not-predictive`) instead of
  `insufficient-history-for-oos-test`.
- If historical implied can't be sourced, a short note to the operator stating that
  and the forward-only timeline.

## Why this is the gate

Everything else is ready: buy-side KILL is settled; the short-premium defined-risk
arm is wired; the liquidity gate is spread-primary; the pre-registration and kill
gates are dated; the daily monitor scores both sides. The one missing input is
**history depth to build the selection signal** — without it, even a perfectly-run
forward campaign is selling a roughly-coinflip set of names (Liu: naive selling
≈ wash). With it, the campaign can sell only the richly-priced names, which is the
only version with a documented edge.

## Operator note (surface, don't decide)

Sourcing historical earnings implied-move data may cost money. Given the account
size, that is a real cost/benefit call for the operator — present it, don't commit
spend unilaterally.
