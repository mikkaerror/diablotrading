# Gate-Unlock Mission — get ONE candidate to stage (for Codex)

_Filed 2026-08-11 by Claude, from live diagnosis with the operator._

## The problem
Promotion gate stuck at **1/30**. Root cause is now precise: **no candidate ever
reaches `stage-in-paperMoney`, so the operator can never key a rep.** Approving
from the queue does nothing because the wall is the quality gate, not approval.

## Diagnosis (today's live slate)
Two structural starvation sources, both real:
1. **Illiquid universe.** The eligible list is heavy with small-caps / crypto
   miners (IREN, HIVE, CLSK, VNET, LUNR, DY, ENS). Their option chains carry
   wide ATM spreads (25–53%) and poor quote quality, so they fail the paper
   chain-quality / spread gate every time. They will essentially never stage.
2. **Wrong structure on the good names.** When a genuinely liquid name appears
   (today: **MRVL** Q85/institutional spread 9.75%; **IREN** Q84/usable spread
   6.41%), the engine generates a **STRADDLE**, which the long-vol premium
   hurdle blocks — instead of a **defined-risk spread**, which could pass.
   Example failures today: DY reward/risk 0.39 (< 0.50 floor); straddles held
   in auto-paper research, never `stage-in-paperMoney`.

## The target (success = one stageable ticket)
Produce **at least one candidate that clears the EXISTING paper gates** and
reaches `stage-in-paperMoney`, so `./inferno today` shows an operator-routable
ticket. Concretely: **a cap-fitting defined-risk spread on a clean-chain liquid
name** (start with MRVL, IREN) that satisfies, without any gate change:
- reward/risk **≥ 0.50** (debit-spread floor)
- ATM spread within the paper gate, quote quality above threshold
- premium hurdle satisfied (this is why defined-risk beats a straddle here)
- within the $500 ticket cap
- direction agrees with trend

## Hard constraints (do NOT cross)
- **Do NOT loosen any gate** — not the 0.50 floor, spread ceilings, premium
  hurdle, or promotion thresholds. The score audit is explicit: the problem is
  generation, not strict gates. Pass the gates; don't move them.
- Research-only. No authority, broker-submit, live-trading, risk-constant,
  ticket, or approval change. `liveTradingAllowed` / `brokerSubmitAllowed` stay
  False.
- **Do NOT change eligible-universe membership** (operator-gated). You MAY
  *recommend* the operator add liquid large-caps (tight-spread options) to the
  scan, since a small-cap-only universe structurally starves the gate — but
  surface it as a recommendation, don't edit the universe.

## Definition of done
`./inferno today` (or the paper director) shows ≥ 1 operator-routable /
stage-in-paperMoney candidate that passed the existing gates — a clean
defined-risk spread on a liquid name — so the operator can key their first
scored paper outcome. Add tests, run full unittest discovery, commit per the
hygiene rules.
