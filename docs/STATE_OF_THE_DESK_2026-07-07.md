# State of the Desk — 2026-07-07 (supersedes 2026-07-06)

One page. Read this cold and you know where the desk stands and what to do next.
Research-only throughout. `liveTradingAllowed=false`, `brokerSubmitAllowed=false`
— unchanged, not in question.

## Today's arc (the honest throughline)

The desk kept asking "why can't we stage the straddle?" Chasing it end to end
produced four findings, each deeper than the last:

1. **Liquidity gate was miscalibrated** — flagged Google's options "thin" because
   it scored raw volume over spread. Fixed (spread-primary), acceptance-tested.
2. **The straddle can never stage anyway** — its edge screen needs a
   `forecastRealizedMovePct` that **no model produces** (0 non-null in all data), so
   it correctly blocks 100% of straddles. The one live event is a vertical because
   verticals bypass that gate.
3. **Buy-premium is a KILL from data** — realized moves run ~10 pts *under* implied
   (variance risk premium against the buyer); the only positive cohort was 127%
   DELL/HPE and died on declustering.
4. **The realized-move data itself is corrupted** — 100 "records" = 30 distinct
   values across 13 names (same event resampled), with 17 implausible >40% "moves."
   This **retracts the sell-side backward support** found earlier in the day.

**Throughline: the measurement, not the market, has been the problem — twice.**
No strategy (buy or sell) can be judged until realized move is measured correctly.

## Where each thesis stands

- **Buy premium (long straddle/strangle):** KILL. Theory + the fact that even
  generous/corrupt data couldn't clear it. Do not weaken gates to revive it.
- **Sell premium (defined-risk):** unproven *forward hypothesis only*. VRP theory
  favors it; backward "support" was corrupted data. Pre-registered, not promising.
- **Directional/vertical:** the only family that stages today (bypasses the vol
  hurdle), but replay shows it underperforming and the one live vertical lost.

## Automation (running)

- Native Mac service `nightly_optimize.sh` refreshes data (install:
  `python3 install_inferno_nightly_optimize_service.py`).
- Daily 6pm verdict monitor scores BOTH sides vs pre-registered gates, logs
  `data/campaign_verdict_log.csv`, flags stale data, and now surfaces the
  data-integrity banner instead of false-precise numbers.

## Priority queue for Codex (in order)

| # | Action | Handoff |
|---|---|---|
| 1 | **Fix realized-move data** (recompute earnings-day move, de-dup to one row/event, add integrity guard to doctor) | CODEX_HANDOFF_REALIZED_MOVE_FIX_2026-07-07 |
| 2 | Liquidity spread-primary gate (mostly landed) | CODEX_HANDOFF_LIQUIDITY_GATE_2026-07-07 |
| 3 | Defined-risk short-premium arm + wide (≥40-name) universe | CODEX_HANDOFF_SHORT_PREMIUM_2026-07-07 |

#1 gates everything: until realized move is clean, no backward number (or forward
score) means anything.

## Follow-ups / loose ends

- `inferno_short_premium_study.py` is standalone; wiring it into `inferno_doctor`
  + `inferno_model_command_center` (Codex's lane) is optional polish.
- Operator-only, still open: `python3 inferno_capital_scaling.py revoke` (stray
  ack); Schwab weekly OAuth re-consent for fresh data.
- 127 uncommitted files (source/tests/docs; `data/` is gitignored). Large but real
  two-agent day — commit deliberately, ideally split Codex source edits from the
  research docs.

## The honest bottom line

Nothing here manufactured an edge — but the day was a win: every false edge
dissolved on paper at zero dollars, and the instrument is now honest enough that
when it next says "promote," the number will be true. The single highest-value
next action is not a strategy — it's clean realized-move data (queue #1).
