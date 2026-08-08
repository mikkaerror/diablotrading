# Promotion Gate — Bottleneck Analysis & Optimization Backlog
_Read-only synthesis of the desk's own diagnostics · 2026-08-07_

## One-sentence diagnosis
The gate isn't stuck because the gates are too strict — it's stuck because the
candidate **engine mass-produces a killed strategy family** (long-premium
straddles) on **illiquid names**, so ~**85 of 92** paper attempts die at the
quality gates before they can ever be staged.

## Evidence — three independent diagnostics agree
1. **Funnel: premium-buy monoculture.** Family distribution 107 premium-buy vs
   ~0 premium-sell; **70 of 146** setups are Straddles. Verdict literally reads
   `premium-buy-monoculture`. And the buy side is a standing, data-supported
   **KILL** (`docs/DECISIVE_MOVE_EDGE_KILL`).
2. **Blocker swarm: all 12 current candidates hard-blocked.** Lane hits —
   `premium_hurdle` 10/12, `strike_construction` 7/12, `liquidity` 6/12,
   `capital_fit` 5/12; every one routed to `alternative_structure`.
3. **Score/threshold audit (P1 findings):**
   - "Long-vol setups are not currently earning the move they require."
   - "**Loosening promotion thresholds would NOT solve the problem** — the
     account is not stagnant because gates are too strict; production lacks
     scored outcomes, and shadow replay fails expectancy/drawdown even on loose
     profiles."
   - Score surfaces are non-monotonic (rank filters only, not odds/sizing).
4. **Lineage:** operator paper ledger 92 rows → **1 qualified, 85 blocked,
   6 rejected.** Fast sims (72) and shadow (420) closes earn **no** promotion
   credit.

## Ranked optimization backlog (by leverage on scored-outcome throughput)
1. **[Highest] Rebalance generation off the killed monoculture toward the
   short-premium lead + defined-risk structures.** The engine floods the funnel
   with straddles (dead edge) while the one promising family
   (short-premium-defined — e.g. ORCL, score 81) is barely produced. Point
   generation at families that (a) have a plausible edge and (b) can pass the
   quality gates. _Owner: Codex strategy lane + operator (which families to
   scan)._
2. **Auto-execute the cap-fitting fallback the blocker swarm already
   recommends** (5-wide debit spread / 1-wide credit spread / single long leg)
   so cap-busting straddles convert into stageable defined-risk tickets instead
   of dying. Today it only *suggests* the fallback. _Owner: Codex (alt pricing /
   strike construction)._
3. **Liquidity pre-filter before pricing.** 6/12 die on wide ATM spreads
   (illiquid small-caps: USAR, ASTS, RKLB…). Filter to liquid names before
   spending the pricing budget — fewer chain-quality blocks, more usable
   candidates. _Owner: Codex (scan pre-filter — not a universe edit)._
4. **Calibrate scores by bucket; keep them as rank filters, not odds.** 4
   monotonic violations in scenarioScore. Guardrail, not a throughput lever.
   _Owner: Codex (score_calibration)._

## Explicitly NOT the fix
**Do not loosen promotion thresholds or quality gates.** The desk's own audit is
emphatic: the pipeline lacks clean candidates, not lenient gates — loosening
would manufacture junk evidence and set the real goal back. This is the
temptation to resist when the pressure is to "go faster."

## What this means for getting to the money
The fastest *legitimate* route to the first real scored outcomes is fixing
**generation** (items 1–2), not waiting for a straddle to randomly clear the
bar. That's Codex-lane engine work plus your call on which families to scan —
a clean, high-leverage task to hand a Codex session.
