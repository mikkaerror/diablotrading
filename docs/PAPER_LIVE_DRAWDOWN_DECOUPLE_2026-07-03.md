# Decision Memo — Decouple paper staging from the live drawdown pause

- **Date:** 2026-07-03
- **Author:** Claude (research lane)
- **Stage:** implemented 2026-07-03 in the Codex lane; research-only behavior.
- **Authority:** unchanged. `liveTradingAllowed=false`, `brokerSubmitAllowed=false`.
  Nothing in this proposal enables live trading, a broker order, or moves any
  real dollar. It concerns *simulated* paper staging only.
- **For:** the Claude/Codex sync. Operator (Mikka) asked why paper evidence is
  stuck at 1/30 and authorized exploring the fix.

## TL;DR

**Implementation status:** shipped. `inferno_risk_policy.evaluate_strike_item`
now has `mode="live" | "paper"`. Live mode remains drawdown-scaled and can stay
at `$0`; paper mode uses `PAPER_TICKET_BUDGET_DOLLARS` / `PAPER_DAILY_BUDGET_DOLLARS`
from `inferno_config.py`, defaulting to `$500` / `$1500`. Paper staging,
strategy-alternative pricing, strike-plan paper annotations, and shadow evidence
now pass `mode="paper"`. The `accept --floor X` ack bug in
`inferno_capital_scaling.py` is also fixed.

The desk is at **1 of 30** scored paper outcomes and not moving. On
2026-07-03 I traced why: the account is **~53% below its peak** ($1,686 → ~$788),
which puts the drawdown protocol at level **"pause"** (`capMultiplier = 0`,
`newEntriesAllowed = false`). The effective single-ticket cap is

```
effectiveCap = min(ackedCap, MAX_SINGLE_TICKET_DOLLARS) × drawdown_multiplier
```

so the multiplier of **0** forces `effectiveCap = $0` — and the risk gate
(`inferno_risk_policy`, the `max loss $X exceeds single-ticket cap $0.00` block)
then rejects **every** candidate. Raising the cap does nothing: the drawdown
multiplier zeroes it afterward. That is correct and protective **for live
capital**.

The problem: **the same gate governs paper (simulated) staging.** So a drawdown
pause — whose entire purpose is to stop risking *real* money when the account is
underwater — is also blocking the collection of *simulated* evidence, which
risks **zero** real dollars and is exactly what the desk needs to escape 1/30.

**Proposal:** decouple. The drawdown pause and the evidence-adjusted-$0 live
authority should gate **live** sizing only. **Paper** staging should use a fixed
paper budget and ignore both. Live stays fully paused; paper flows.

## Why this is a category error, not a safety relaxation

- The drawdown protocol exists to protect **real capital**. Paper tickets are
  simulated — they cannot lose a real dollar.
- Blocking paper during a drawdown **protects nothing** and **starves the one
  thing that ever ends the drawdown-of-progress**: closed, scored paper
  outcomes. The desk needs evidence *most* when it's doing worst.
- This is the opposite of loosening a real-money guard. Live risk stays exactly
  as locked as it is today. We are only letting the *simulator* run.

## The mechanism (grounded)

- `inferno_capital_scaling.current_recommended_cap()` computes `effectiveCap`
  and multiplies by `drawdownState.capMultiplier` (0 at level "pause").
- `inferno_risk_policy` reads that single `effectiveCap` via
  `current_single_ticket_cap()` and blocks any ticket whose max loss exceeds it
  (the `effectiveSingleTicketCap` / `effectiveSingleTicketCapSource` metrics).
- Every paper staging path — `inferno_strategy_alternative_pricing`,
  `inferno_paper_test_director`, `inferno_fast_paper_cohort` — runs candidates
  through that same gate, so all inherit the live $0 cap.
- A paper budget already exists and is *not* used by this gate:
  `inferno_paper_bootstrap.BOOTSTRAP_TICKET_DOLLARS = $50`.

## Proposal — a `mode` on the risk gate

Thread a `mode: "paper" | "live"` (or `is_paper: bool`) through the risk
verdict:

- **Paper mode:** cap = a fixed **paper budget** (start at
  `BOOTSTRAP_TICKET_DOLLARS`, or a small operator-set paper cap up to ~$500).
  **Skip** the drawdown `capMultiplier` and the evidence-adjusted-$0 live
  authority. Keep the *paper-hygiene* gates: `MAX_OPEN_PAPER_TICKETS = 5`,
  same-ticker-open guard, quote-quality / liquidity / spread gates, source-price
  divergence. Those are about evidence *quality*, not real-money risk, and
  should stay.
- **Live mode:** unchanged. Full drawdown pause + evidence-adjusted-$0 +
  scaling ack. Live remains paused at ~53% drawdown, exactly as now.

## What stays locked (non-negotiable)

- `liveTradingAllowed` / `brokerSubmitAllowed` remain **false**.
- The live drawdown pause is **fully preserved** — this changes nothing about
  when the desk may risk real money.
- No broker order, no real dollar, ever, from this change. Paper = simulated.

## Ready-to-ship spec (operator approved 2026-07-03)

Operator has approved shipping this. Decisions are made inline below so Codex is
unblocked. Scope is Codex's risk lane; keep it research-only (no authority flags,
no broker).

### 1. New constant — `inferno_config.py`
```python
# Paper (simulated) per-ticket budget. Independent of the live drawdown pause
# because paper risks $0 real dollars. Sized to let defined-risk credit spreads
# stage as evidence (their max loss runs ~$120–450).
PAPER_TICKET_BUDGET_DOLLARS = float(os.environ.get("INFERNO_PAPER_TICKET_BUDGET", "500"))
PAPER_DAILY_BUDGET_DOLLARS  = float(os.environ.get("INFERNO_PAPER_DAILY_BUDGET", "1500"))
```
Decision: **paper budget = $500** (operator-chosen, so the credit spreads the
scorer already prefers can actually stage). Env-overridable.

### 2. Gate change — `inferno_risk_policy.py :: evaluate_strike_item`
Current signature (line ~407): `def evaluate_strike_item(item, ..., ) -> RiskVerdict`.
Add `mode: str = "live"` (keep default `"live"` so nothing else changes).

Inside, at the single-ticket cap block (lines ~436–444):
```python
if mode == "paper":
    effective_cap = PAPER_TICKET_BUDGET_DOLLARS          # drawdown-independent
    cap_source = "paper-budget"
    daily_cap = PAPER_DAILY_BUDGET_DOLLARS
else:
    cap_info = current_single_ticket_cap()               # live: unchanged
    effective_cap = cap_info["effectiveCap"]             # still 0 during pause
    cap_source = cap_info.get("source") or "config-default"
    daily_cap = MAX_DAILY_TICKET_DOLLARS
if loss > effective_cap:
    blocks.append(f"max loss ${loss:.2f} exceeds single-ticket cap ${effective_cap:.2f} ({cap_source})")
if projected_loss > daily_cap:
    blocks.append(f"projected daily max loss ${projected_loss:.2f} exceeds cap ${daily_cap:.2f}")
```
Everything else in the function is **unchanged and applies in both modes**:
`MAX_OPEN_PAPER_TICKETS`, same-ticker-open guard, `visible_quote_blocks`,
Schwab liquidity/quote/spread blocks, `MAX_UNDERLYING_SOURCE_DIVERGENCE_PCT`,
the `debit/credit reward-risk` floors, and the `unexpected liveTradingAllowed`
tripwire. Those are evidence-quality / integrity gates, not real-money risk.

### 3. Call sites — pass `mode="paper"`
Both current importers of `evaluate_strike_item` are paper-staging paths:
- `inferno_strategy_alternative_pricing.py` (line 29 import) → its
  paper-risk/combined evaluation call → `mode="paper"`.
- `inferno_paper_execution.py` (line 17 import) → `mode="paper"`.
Grep for any other `evaluate_strike_item(` call before shipping; anything that
represents *live* staging keeps the default `mode="live"`.

### 4. Acceptance tests (`tests/test_inferno_risk_policy.py`)
1. FCX-style put-credit item, max loss $127, **during a drawdown-pause**
   (`capMultiplier=0`): `evaluate_strike_item(item, mode="paper")` → **no cap
   block** (the `single-ticket cap` string is absent). Liquidity blocks may
   still apply — assert specifically on the cap block, not `passed`.
2. Same item, `mode="live"` → cap block **present** (`$0.00`).
3. Paper item with max loss $600 (> $500 budget), `mode="paper"` → cap block
   present at `$500.00 (paper-budget)`.
4. `mode="paper"` still enforces `MAX_OPEN_PAPER_TICKETS` and the same-ticker
   guard.
5. Authority invariant: no code path sets `liveTradingAllowed` /
   `brokerSubmitAllowed`; both remain false.

### 5. Wiring / surfacing
- No change to the drawdown protocol, capital-scaling, or authority controller.
- The command-center / dashboard "would trade" panel will start showing paper
  candidates that pass on everything except liquidity — that's the intended,
  honest signal that the systemic $0 wall is gone.

## Honest caveat — this alone will not produce tickets today

Even with paper decoupled, the current priceable names (CCI, FCX, TXN, AEHR)
still fail the **liquidity/quote-quality** gates — thin ATM liquidity, poor
quote scores, wide/untradeable spreads. Those gates are about evidence quality
and should stay. So this change removes the *systemic* $0-cap wall that blocks
everything, but the desk still needs cleaner, more liquid candidate names to
actually accrue outcomes. Both are required to move off 1/30; this is the
necessary structural half.

## Two related items found on 2026-07-03

1. **Ack floor bug.** `inferno_capital_scaling.py accept --floor X` records
   `acceptedCap` using the *default* floor ($25), not `X`, so a `--floor 500`
   ack mismatches the live recommendation (>20% tolerance → `needsFreshAck`) and
   silently drops the cap. Low priority next to the pause, but it means the ack
   CLI doesn't do what its flags say.
2. **This memo's core issue** — drawdown pause applied to paper — is the real
   reason paper is stuck, and the higher-value fix.

## Decisions (made 2026-07-03 — cleared to ship)

1. Paper/live decouple: **approved.**
2. Paper budget: **$500** (env `INFERNO_PAPER_TICKET_BUDGET`), daily **$1500**.
3. Also fix the ack-floor bug in passing (§ "related items"): `accept --floor X`
   must record `acceptedCap` using `X`, not the default $25 — one-line fix in the
   accept path so the CLI matches its flags. Not required for the decouple, but
   cheap while in this file.

Guardrails that do **not** move: `liveTradingAllowed=false`,
`brokerSubmitAllowed=false`, the drawdown pause on **live** capital, and every
quote/liquidity/integrity gate. This ships the simulator, nothing else.
