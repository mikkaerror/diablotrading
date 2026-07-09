# Trade-logic pre-registration — entry, structure, exit, friction

- **Date:** 2026-07-07
- **Author:** Claude (research lane). Research-only. Feeds the campaign in
  `docs/CAMPAIGN_KILL_GATES_2026-07-06.md`. No authority/risk change.
- **Purpose:** decide, *before* the campaign runs, exactly which version of the
  pre-earnings long-premium trade it tests — so we learn something instead of
  baking in unexamined defaults. Grounded in the 150-record replay
  (`data/inferno_dte_policy_analysis.json`), with its limits stated honestly.

## What the replay shows (caveated)

All figures are **friction-blind and correlated** — see caveats — so treat as
directional, not proof.

**Entry DTE** (net-R by entry bucket): 7–14 DTE is the only clearly positive
bucket (mean +0.83, n=41). 0–6 and 15–21 are mean-positive but median-negative
(a few winners carry them). 22–50 DTE is consistently negative (mean −0.4 to
−0.6). → **Entry window: 7–14 DTE primary.**

**Structure:** Long Straddle mean +0.33 (n=100, win 37%) vs Vertical Debit
mean −0.39 (n=50, win 38%). In this data straddles beat verticals — the opposite
of the "maybe verticals are the edge" hope, and the one live scored event so far
(a vertical) was a loss. → **Straddle primary arm; vertical a comparison arm,
not the lead.**

**Exit:** every record exits at 0–6 DTE — i.e. the desk's replay only ever
**holds through earnings to near-expiration.** There is **zero data** on the
alternative: exit the day before earnings to sell the IV ramp and avoid the
post-print IV crush + gamma. This is the single biggest unexamined lever in the
whole strategy and we have no evidence either way. → **the campaign must test
both exit rules head-to-head.**

**Friction:** confirmed friction-blind — `frictionRealized=False`,
`estimatedFrictionDollars=0.00`, grossR==netR on all 150 rows. So every positive
number above is a *gross* number.

## The two things the replay cannot tell us (and the campaign must)

1. **Real friction.** A straddle held to expiration crosses the spread once
   (~0.07–0.10R at a 15% ATM spread — modest). A straddle exited before earnings
   crosses **twice**, the second time into a wider near-event spread — potentially
   0.2–0.4R. Friction is small for hold-through and large for exit-before. This
   interacts directly with the liquidity gate: charge the *actual* per-trade
   spread from the chain (the fixed gate enables this).
2. **Exit timing.** Hold-through eats the IV crush but captures the realized
   move; exit-before banks the IV ramp but forgoes the move. Which wins is an
   empirical question we have never tested.

## Pre-registered campaign arms (2×2, plus a structure comparison)

| Arm | Entry | Structure | Exit |
|---|---|---|---|
| A (primary) | 7–14 DTE | Long straddle | **Hold through** to ~1–2 DTE |
| B (primary) | 7–14 DTE | Long straddle | **Exit day before earnings** (sell the ramp) |
| C (compare) | 7–14 DTE | Vertical debit | Hold through |
| D (compare) | 7–14 DTE | Vertical debit | Exit day before earnings |

Every arm charges the **full actual ATM spread** as friction, on every crossing
(once for hold-through, twice for exit-before). Distinct-event cap + clustering
(already shipped) keep the evidence independent. Each arm is scored separately
against the kill/confirm gates; ≥30 distinct events needed *per arm* before that
arm gets a verdict — or, if event supply is thin, the straddle arms (A,B) get
priority and verticals are dropped to a smaller descriptive sample.

## Honest caveats (binding on interpretation)

- **Correlated sample:** 150 records ≈ 18 tickers; the 7–14 straddle result is
  ~7 names, and its clustered 95% CI already crosses zero (−0.18, +2.40). The
  replay motivates the *design*; it does not establish an edge.
- **Friction-blind replay** overstates every arm; hold-through least,
  exit-before most.
- **Survivorship / selection** in how these 150 tickets were chosen is unknown;
  the campaign's pre-registered universe + liquidity gate fixes this going
  forward.
- The honest prior remains **no durable edge**. The value of pre-registering the
  arms is that when an arm returns a number, it will be the *right* number for a
  *defined* trade — and "exit-before beats hold-through" (or the reverse) is a
  genuinely useful thing to learn even if neither clears the promotion bar.

## Handoff

- Codex (shared paper-loop lane): stamp each paper ticket with `arm ∈ {A,B,C,D}`
  and its `exitRule`, and ensure the paper fill model charges actual per-crossing
  spread. Pairs with the liquidity-gate handoff
  (`docs/CODEX_HANDOFF_LIQUIDITY_GATE_2026-07-07.md`).
- The daily verdict monitor already scores per-strategy; extend its evidence
  extraction to split by `arm` when the field exists.
