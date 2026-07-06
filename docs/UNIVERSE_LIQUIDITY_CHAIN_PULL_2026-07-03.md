# Decision Memo — The funnel is illiquid because chain-pull ignores the priority slate

- **Date:** 2026-07-03
- **Author:** Claude (research lane)
- **Stage:** research-only — proposal. No code edited here.
- **Authority:** unchanged. `liveTradingAllowed=false`, `brokerSubmitAllowed=false`.
  This is a data-coverage change (which names get option chains pulled), not a
  risk/authority change. Codex ops lane.
- **For:** the Claude/Codex sync. Operator asked what's holding the desk back
  after the drawdown/cap layer.

## TL;DR

Every "no viable paper tests / thin liquidity" verdict is grading the **wrong
names.** The daily Schwab option-chain pull (`SCHWAB_OPTIONS_SYMBOL_LIMIT = 12`)
is built from the **execution queue + approval queue + a manual watchlist** —
i.e. the positions you already hold plus a hand-kept list. It **does not include
the daily priority/conviction slate.** So the desk pulls chains for
`CCI, AZZ, AEHR, BMI, TXN, IREN, HIVE, TE, CLSK` (held miners + watchlist) while
its own **top-priority candidates get no chain at all**:

- Top-15 by priority today: `OTEX, LUNR, CRWV, TPC, CWEN, AVGO, ASTS, KEYS, ORA,
  IRM, ESE, OKLO, ZBH, RKLB, CHKP`.
- Chains actually pulled: none of those. **AVGO (#6), KEYS, OTEX, LUNR — the
  liquid large-caps — are never evaluated.**

Result: credit-spread candidates only ever surface on the illiquid names the
desk happens to hold, the risk gate correctly rejects them, and the funnel
reports "nothing viable." It's a **selection bug, not a market-liquidity
reality.**

## Evidence it's selection, not illiquidity

- The held miners are *not* thin — IREN/TE carry heavy option flow (top-contract
  OI 17k–100k, volume 9k+). So "illiquid universe" is false for them.
- A genuinely liquid large-cap, TXN, scored ATM-liquidity **11/100 ("poor")**
  while miner TE scored **50** — but that's because the desk is pricing
  off-cycle/OTM strikes on names it shouldn't be prioritizing, not because TXN
  options are thin. The right fix is to evaluate the *right* names, where the
  front-month ATM is deep.
- `inferno_schwab_daily_ops.default_symbol_universe()` source, verbatim intent:
  "execution/approval names first, then the manually maintained watchlist" — the
  priority slate is simply not in the list.

## The fix — include the priority slate in the chain-pull universe

`inferno_schwab_daily_ops.py :: default_symbol_universe(limit)`: blend the
top-priority daily slate into the symbol list, ahead of the manual watchlist.

Proposed order (dedup, then clamp to `limit`):
1. **Open live positions** (keep — you must monitor what you hold): TE, IREN,
   HIVE, CLSK.
2. **Top-N priority candidates** from `data/latest_snapshot.json` `rows`, sorted
   by `priority` desc, filtered to `setupRec != "Avoid"` and
   `daysUntilEarnings <= CANDIDATE_MAX_DAYS_UNTIL_EARNINGS`. **(new — this is the
   missing piece.)**
3. Execution/approval queue names.
4. Manual watchlist (fill remaining slots).

At `limit = 12` and 4 held names, that leaves ~8 slots for the best-ranked
candidates — which is exactly where liquid large-caps like AVGO/KEYS will land.

```python
def default_symbol_universe(limit=None):
    held      = symbols_from_positions(load_json_file(LIVE_ACCOUNT_SYNC_FILE))
    slate     = top_priority_slate(load_json_file(SNAPSHOT_FILE), n=8)  # NEW
    execution = symbols_from_payload(load_json_file(EXECUTION_QUEUE_FILE), ("items","readyTickers"))
    approval  = symbols_from_payload(load_json_file(APPROVAL_QUEUE_FILE), ("items",))
    watchlist = symbols_from_payload(load_json_file(WATCHLIST_INPUT_FILE), ("tickers","symbols","watchlist"))
    return unique_symbols(held + slate + execution + approval + watchlist, limit=limit)
```
`top_priority_slate` reads snapshot `rows`, drops `setupRec == "Avoid"` and
`daysUntilEarnings > 21`, sorts by `priority`, returns the top `n` tickers.

## Secondary (real, keep as-is)

- Small caps (AEHR, BMI) *are* genuinely wide (ATM spread 37–78%). Correct to
  block those — they're evidence-quality rejects, not selection errors.
- The `atmSpreadPct` gate measures spread as a % of premium, which structurally
  penalizes cheap OTM legs (what credit spreads use). See the earlier
  spread/liquidity consistency finding in `score_threshold_audit`. Worth a
  companion pass, but the chain-pull selection above is the higher-leverage fix.

## Why this matters for readiness

Combined with the paper/live decouple, this is the other half of getting real
paper evidence: the decouple lets the simulator run during the drawdown; **this
change makes it run on tradeable names.** Evidence gathered on liquid large-caps
is worth something; evidence on 60%-spread miners is not. Both are needed to
move off 1/30 toward an honest edge test.

## Acceptance

- After the change, the daily chain pull includes the top priority-slate names
  (e.g. AVGO/KEYS/OTEX today), verifiable in `data/inferno_schwab_options.json`
  `rows`.
- `strategy_alternative_pricing` begins surfacing credit-spread candidates on
  those names, with real ATM-liquidity scores (not the miner-only set).
- No authority change; `liveTradingAllowed`/`brokerSubmitAllowed` stay false.
