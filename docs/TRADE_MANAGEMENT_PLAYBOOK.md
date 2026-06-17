# Inferno Trade-Management Playbook — Runners & Fixed Gains

**Stage:** research-only / playbook / operator-facing rules. No code in this doc auto-executes.
**Date:** 2026-05-25
**Reference NLV:** $5,000 (worked example). Rules scale linearly with NLV via the formula already wired in `inferno_capital_scaling.py`.
**Anchored to:** the `inferno_capital_scaling` recommender (1% / ticket, $25 floor, $2k ceiling, symmetric drawdown), the existing `inferno_paper_exit_auditor`, and the strategy generator's two output families (long-vol cap-aware variants vs defined-risk premium plays).

This document defines, in rules, what to do *after* the strategy generator hands you a ticket: when to scale out, when to let it run, when to cut, when to walk away on time. The goal is to make every closed outcome a *decision you made on purpose*, not a position that drifted into expiry.

---

## 1. Two lanes, one bankroll

The strategy generator already produces two structurally different trade types:

**Lane A — Runners** (long-vol, capped loss, uncapped or large-multiple upside)
- LONG_STRADDLE, LONG_STRANGLE, LONG_CALL, LONG_PUT
- Max loss = debit paid (defined when you enter)
- Max profit = "large" — typically 3-10× debit on a hit, but most cycles lose
- Empirical base rate: ~40% win rate, slightly negative expectancy at average prices

**Lane B — Fixed gains** (defined-risk premium, both sides capped)
- PUT_CREDIT_SPREAD, CALL_CREDIT_SPREAD, CALL_DEBIT_SPREAD, PUT_DEBIT_SPREAD, IRON_CONDOR
- Max loss = defined (width − credit, or debit paid)
- Max profit = defined (credit collected, or width − debit)
- Empirical base rate: ~60-75% win rate, modestly positive expectancy

These need different management because their P&L curves are different shapes. Treating them with one rulebook is the most common amateur mistake in this game.

---

## 2. Position sizing at $5,000 NLV (the worked example)

The formula already running:

| Field | Value at $5k NLV |
|---|---|
| Single-ticket cap | **$50** (1% of NLV, above the $25 floor — formula picks up cleanly) |
| Daily new-exposure cap | **$150** (3× single-ticket) |
| Max open positions | 5 |
| Max total open exposure | **$250** (5% of NLV) |

The structural reality at $50/ticket: the standard "$300 long straddle on a $100 stock" *does not fit*. The trades that fit cleanly at this bankroll are:

| Trade type | What fits at $50 max-loss |
|---|---|
| Long straddle / strangle | Underlyings priced $15-30, OR wide-strike strangles on $50-100 names where each leg is sub-$0.25 |
| Long single-leg call/put | Any underlying where the target option is < $0.50 debit per share |
| Credit spread ($1 wide) | Sell strike − buy adjacent dollar; collect ≥ $0.50 credit |
| Iron Condor (narrow) | $1 wings on each side, total max loss ≤ $50 |

This isn't a limitation of the desk — it's the truth about options structural minimums. At $5k NLV, the right operator stance is **"collect evidence with small positions, let NLV grow, the trades scale up as the account does."**

| NLV milestone | Single-ticket cap | What unlocks |
|---|---|---|
| $5,000 | $50 | Penny spreads, narrow ICs, sub-$0.50 single legs |
| $15,000 | $150 | Standard $1-2 wide credit spreads, small straddles ($1.50 debit) |
| $25,000 | $250 | $5-wide credit spreads, mid-debit straddles on $50-80 names |
| $50,000 | $500 | Full straddles on liquid $100-200 names — original cap target |
| $200,000 | $2,000 (ceiling) | Cap saturates; growth above this is in size of book, not per-trade |

---

## 3. Lane A — Runner management rules

A "runner" is a long-vol position that has gone right and is still in the trade. The job of these rules is to **bank the win without strangling the upside**. Long-vol's edge is in the fat right tail; cut too early and the strategy's expected value collapses.

### 3.1 Entry — when the desk lets you enter a long-vol ticket

All four must be true:
1. The strategy generator emits the position in the auto-paper slate (`paperAutoSelected: true`).
2. `riskVerdict.passed: true` (it fits the cap, the freshness check, the liquidity floor).
3. `paperOnly: true` and `liveTradingAllowed: false` — this is research evidence, not live capital, until the 30-outcome promotion gate clears.
4. Approval cleared by you (`python3 inferno_approval_queue.py approve <ticker>`).

### 3.2 The runner profit ladder

For every winning long-vol position, scale out in **three pieces**, not all at once:

| Trigger | Action | Position after |
|---|---|---|
| **+50% of debit** (e.g., $50 paid → $75 mark) | Close 50% of position | 50% remaining, ~+25% of debit banked |
| **+100% of debit** (2× — break-even on the loser) | Close another 25% | 25% remaining, ~+50% of debit banked, **trade is now fully de-risked** |
| **+200% of debit** OR ticker has moved through the further breakeven | Close the last 25% | Position flat, max realized win |

The third tranche is the "runner" — it's the chunk that pays for all the trades that didn't move. If you skip the third tranche, your expected value falls below break-even because you're cutting off the fat right tail.

### 3.3 The runner stop-loss

| Trigger | Action |
|---|---|
| Position at **−50% of debit** | Close immediately, no exceptions |
| Position is **flat (±10%)** at **T-3 days** | Close — theta will accelerate against you and the realized move hasn't arrived |
| Position has **not moved in either direction by T-2 days** | Close — option will decay to zero before any move arrives |
| **48 hours before expiry**, regardless of state | Close — gamma is too high to hold overnight |

### 3.4 Pre-event vs post-event exits

This is the call where most edge gets won or lost on long-vol earnings trades.

- **If the desk's selection edge is in pricing IV cheap → realized move expansion** (the typical edge story): **exit BEFORE the announcement.** You're buying the IV runup, not the binary outcome. The IV crush eats the gains otherwise.
- **If the desk's selection edge is in identifying a binary that will hugely overshoot consensus** (the "no, this stock is going to gap 20%" thesis): **hold through the announcement.** Accept the IV crush; bet on the realized move being so large that it overwhelms the crush.

Without 30+ closed outcomes you don't yet know which edge you have. **Default to pre-event exit** for the first 30 outcomes — it's the lower-variance way to collect the evidence that tells you which side your edge is on.

---

## 4. Lane B — Fixed-gain management rules

A "fixed gain" position has both sides capped. The job here is **not maximizing the win** (the max is fixed) — it's **maximizing the win rate × early-exit gamma**. You take what the market gives you fast and free up the cap slot.

### 4.1 Entry — same gate as Lane A

Same four gates as §3.1. The strategy generator already produces these as `PUT_CREDIT_SPREAD`, `CALL_DEBIT_SPREAD`, `IRON_CONDOR` etc. via the cap-aware variant search.

### 4.2 Profit-take rules per sub-type

**Credit spreads (PUT_CREDIT_SPREAD, CALL_CREDIT_SPREAD, IRON_CONDOR)** — the high-win-rate, capped-profit case:

| Trigger | Action |
|---|---|
| Position at **+50% of max profit** | Close. This is the canonical tastytrade rule for a reason: closing at 50% nearly doubles the trade's annualized return vs holding to expiry, and it free-rolls the spread's tail risk. |
| Position at **+25% of max profit** by **T-7 days** | Close — the remaining profit isn't worth the gamma risk in the last week. |
| **T-3 days** with any profit | Close — you've harvested 80% of what was on the table. |

**Debit spreads (CALL_DEBIT_SPREAD, PUT_DEBIT_SPREAD)** — the lower-win-rate, asymmetric case:

| Trigger | Action |
|---|---|
| Position at **+50% of max profit** | Close half. |
| Position at **+80% of max profit** | Close the rest — the last 20% requires the underlying to sit *exactly* at the long strike, which is unlikely. |
| **T-2 days** with any profit | Close. |

### 4.3 Stop-loss rules

| Trigger | Action |
|---|---|
| Position at **−100% of max profit** for a credit spread (i.e., loss = 2× the credit) | Close. Don't wait for max loss. |
| Position at **−50% of debit** for a debit spread | Close. |
| The underlying has **breached the short strike** of a credit spread and the spread is now at break-even or worse | Close — don't roll. Rolls are credit-only; if the roll requires a debit, you eat the loss and learn. |

### 4.4 No rolls in research mode

A "roll" (closing the current position and opening a new one further out in time or further OTM) **adds risk and obscures evidence**. Until the 30-outcome gate clears, every closed outcome should be a clean win or a clean loss. Don't add rolls to the evidence stream — they corrupt the per-strategy R-multiple distribution that the future per-family Kelly math (see `docs/POSITION_SIZING_RESEARCH.md` §5.1) needs.

After the promotion gate clears and you have evidence per family, rolls become an evaluable extension; not before.

---

## 5. Portfolio-level rules (cross-cutting)

These apply *across* all open positions, regardless of lane.

### 5.1 Concentration caps

| Rule | Limit at $5k NLV |
|---|---|
| Max % of open slots in any one strategy family | 60% (3 of 5 slots) |
| Max % of open slots sharing an earnings day | 40% (2 of 5 slots) |
| Max % of open slots in any one sector (XLK, XLF, XLV...) | 60% (3 of 5 slots) |
| Max % of open slots in any one underlying | 20% (1 of 5 slots) |

Why concentration matters: the 1% per-ticket cap assumes positions are independent. Two long straddles on two semiconductor names on the same earnings day are *not* independent — they share systematic vol exposure and sector beta. Concentration caps preserve the assumption the sizing math depends on.

### 5.2 Drawdown circuit-breakers

The cap shrinks symmetrically with NLV (the scaling module does this automatically). On top of that, when the desk has trailing drawdown from peak NLV:

| Trailing drawdown from peak NLV | Cap multiplier | Max open positions |
|---|---|---|
| < 10% | 1.0× (normal) | 5 |
| 10% – 20% | 0.5× (half-size) | 3 |
| 20% – 30% | 0.25× (quarter-size) | 2 |
| > 30% | **Pause new entries.** Continue managing open positions to exit; no new entries until NLV recovers above the 30% mark. |

This is the *stepped* tightening from `docs/POSITION_SIZING_RESEARCH.md` §4.4. Symmetric % scaling alone is gentle in a drawdown — the stepped multiplier forces aggressive de-risking when the strategy is bleeding.

### 5.3 Daily entry budget

Existing daily-cap rule applies: max $150 of new max-loss exposure per trading day at $5k NLV. With 1% per ticket, this is 3 new positions per day max.

If a fourth opportunity arrives that day, you wait — the constraint is not the number of opportunities, it's the desk's daily statistical-independence budget.

---

## 6. Connection back to the system

The trade-management rules above already have hooks in the existing code:

- **Entry gate** — already enforced by `inferno_risk_policy.evaluate_strike_ticket()` + the auto-paper slate.
- **Exit reconciliation** — `inferno_paper_exit_auditor.py` already flags open paper tickets by age and expiration window (`REVIEW_AFTER_OPEN_DAYS=2`, `OVERDUE_AFTER_OPEN_DAYS=4`). What it does NOT do yet is recommend exit *price triggers*; today's auditor is purely time-based.
- **Outcome scoring** — `inferno_paper_execution_ledger.json` records the outcome each closed paper trade produces. This is the input the future Kelly math and the per-family cap adjustments need.

### 6.1 The daily auditor — `inferno_trade_management.py`

The playbook is now enforced as a research-only auditor that walks each open paper position daily and emits a per-position **recommended action** ("trim 50% at +50% target hit", "cut at stop", "time stop in 3 days") based on the rules above. It outputs a report card the operator reads each morning alongside the doctor.

```
inferno_trade_management.py
  Input:   inferno_paper_execution_ledger.json (open positions)
           inferno_paper_mark_to_market.json (current marks)
  Output:  data/inferno_trade_management.json   (per-position actions)
           reports/trade_management_latest.txt (operator briefing)
  Verdicts per position:
      hold          — no action; trade is mid-cycle
      take-profit-1 — at +50% target; trim half
      take-profit-2 — at +100% / +50% of max profit; trim or close
      take-profit-3 — runner final; close
      stop-loss     — hit stop; close
      time-stop     — T-X days reached; close
      pre-event-exit — earnings tomorrow; close to avoid IV crush
  Stage:   research-only, promotable=False, liveTradingAllowed=False,
           brokerSubmitAllowed=False.
```

Run it after mark-to-market refresh:

```bash
./run_inferno_paper_mark_to_market.sh
./run_inferno_trade_management.sh
```

---

## 7. Bottom line — what to do at $5k NLV

1. **Trade small, trade often, log outcomes.** The 1% rule keeps you in the band where the evidence stream actually accumulates without ruin.
2. **Run two distinct rule sets** for runners (Lane A) and fixed gains (Lane B). They have different P&L curves; treating them the same destroys edge.
3. **Default to pre-event exit on long-vol** until enough closed outcomes exist to know which side of the IV-crush curve your edge is on.
4. **Take credit-spread profits at 50% of max** — non-negotiable for the high-win-rate lane.
5. **Hard concentration caps**: no more than 2 open positions sharing an earnings day, no more than 3 in any single strategy family, no more than 1 in any single underlying.
6. **Stepped drawdown circuit-breaker**: halve the cap after 10% DD, quarter after 20%, pause new entries past 30%.
7. **Don't roll.** Until 30 outcomes accrue. Rolls corrupt the evidence stream.
8. **Let the cap scale with the account** via `inferno_capital_scaling accept`. The trades grow as the bankroll grows; you don't update limits manually.

The honest meta-point: at $5k NLV the rules above are theoretical 90% of the time, because the structural minimums of options pricing don't fit 1% sizing cleanly. The first job at $5k is **collecting evidence with the small positions that do fit** — narrow credit spreads, sub-$0.50 single legs, micro iron condors. Once NLV crosses ~$15k the trade types open up, the playbook starts running at full resolution, and by $25-50k NLV you're operating the desk the way the strategy generator was designed for.

---

## Sources

- Sosnoff, T., et al. *tastytrade research mechanics videos.* Standard reference for the "close credit spreads at 50% of max profit" rule.
- Sinclair, E. (2013). *Volatility Trading.* Wiley. Pre-event vs post-event exit framework for long-vol around discrete events.
- Sinclair, E. (2020). *Positional Option Trading.* Wiley. Roll vs close decision discipline.
- Vince, R. (1990). *Portfolio Management Formulas.* Concentration / correlation haircut framework underpinning §5.
- Tharp, V. (2007). *Trade Your Way to Financial Freedom.* R-multiple methodology for outcome scoring.
- See also `docs/POSITION_SIZING_RESEARCH.md` for the position-sizing layer this playbook sits on top of.
