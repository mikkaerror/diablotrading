# Decision Memo — The promotion gate's win-rate floor is payoff-blind

- **Date:** 2026-06-26
- **Author:** Claude (research lane)
- **Stage:** research-only — decision memo and implemented calibration
- **Authority:** unchanged. `liveTradingAllowed=false`, `brokerSubmitAllowed=false`,
  no risk constant edited, no approval, no broker action. A risk-gate change
  requires explicit operator approval and Codex-lane implementation.
- **For:** the Claude/Codex sync on next steps after commit `db25fbb`.
- **Implementation status:** operator chose Option A on 2026-06-27. Codex
  implemented payoff-implied breakeven + `0.03` margin in
  `inferno_strategy_lab.py`, mirrored it in `inferno_promotion_gap.py`, and
  updated the threshold-sensitivity / score-threshold diagnostics. This remains
  paper-evidence-only; no broker authority or live submit flag changed.

## TL;DR

The promotion gate requires `win-rate Wilson lower bound ≥ 0.42` as a hard
blocker (`inferno_strategy_lab.verdict_for_metrics`). That floor is **payoff-blind**:
it assumes every admissible strategy wins ~like a coinflip. It is the same
assumption already fixed in the advisory `inferno_evidence_strength` scalar this
week — but here it lives in the *binding* gate.

Consequence: the desk's dominant strategy family (long premium — straddles and
debit spreads, the "premium-buy-monoculture") is **structurally unpromotable no
matter how profitable it is**, because convex payoffs win well under 42% by
design. This is a meaningful contributor to "promotion sensitivity promotes
nothing" — it is a gate-specification problem, not only a data problem.

**Recommendation:** replace the fixed `0.42` win-rate floor with a payoff-implied
breakeven anchor (Option A), or drop the win-rate floor and let profit-factor +
expectancy-lower-bound carry the decision (Option B). Either is a **calibration
fix, not a loosening** — see the proof below.

## The problem, precisely

`verdict_for_metrics` blocks promotion unless ALL of these clear:

| Gate | Threshold | Source constant |
|---|---|---|
| scored count | ≥ 30 | `MIN_SCORED_TRADES_FOR_PROMOTION` |
| win-rate Wilson lower | ≥ 0.42 | `MIN_WIN_RATE_LOWER_BOUND` |
| expectancy lower bound | > 0.0 | `MIN_EXPECTANCY_LOWER_BOUND` |
| profit factor | ≥ 1.25 | `MIN_PROFIT_FACTOR` |
| max drawdown | ≥ −6.0 R | `MAX_DRAWDOWN_RISK_UNITS` |
| false-positive rate | ≤ 0.45 | `MAX_FALSE_POSITIVE_RATE` |

The win-rate floor is independent of payoff ratio. But profitability is already
fully captured by the expectancy and profit-factor gates:

> With win rate `p` and payoff `b` (avg win / avg loss, in R):
> expectancy `E = p·b − (1 − p)` and profit factor `PF = p·b / (1 − p)`.
> `E > 0  ⟺  PF > 1`. So `PF ≥ 1.25` *already* certifies positive expectancy.

The win-rate floor therefore adds **no profitability protection**. It only adds a
constraint on *how* a strategy is allowed to make money — penalizing low-win-rate,
high-payoff structures even when their expectancy and profit factor are decisively
positive.

## Evidence — the floor is unreachable for convex payoffs

A genuinely profitable long-premium strategy: true win rate 45%, winners 2.5× losers
→ profit factor **2.05**, expectancy **+0.57R**. Wilson lower bound on its win rate
(computed with the repo's own `wilson_lower_bound`):

| n | Wilson lower | clears 0.42? |
|---|---|---|
| 30 | 0.302 | no |
| 60 | 0.331 | no |
| 100 | 0.356 | no |
| 200 | 0.383 | no |
| 400 | 0.402 | no |

It never clears 0.42 — through 400 trades — while passing the profit-factor and
expectancy gates immediately. Even the *symmetric* strategy the floor was designed
for (55% win, 1:1) needs n ≥ 60 just to clear the win-rate floor, which already
exceeds the 30-sample count gate. **The count gate (30) and the win-rate floor
(60–400+) encode contradictory definitions of "enough evidence."**

## The fix is not a loosening

### Option A (recommended) — payoff-implied breakeven anchor

Require the Wilson lower bound to clear the strategy's own breakeven win rate plus
a margin, instead of a fixed 0.42:

```
breakeven = avg_loss / (avg_win + avg_loss)        # = 1 / (1 + b)
require: win_rate_wilson_lower ≥ breakeven + MARGIN
```

This reuses the exact `empirical_breakeven` helper already shipped in
`inferno_evidence_strength.py`, so the gate and the advisory scalar finally agree.

**Symmetric strategies become stricter, not looser** (b = 1 → breakeven 0.50):

| margin | required Wilson lower | stricter than old 0.42? |
|---|---|---|
| 0.00 | 0.500 | yes |
| 0.03 | 0.530 | yes |
| 0.05 | 0.550 | yes |

**Convex strategies become fairly evaluated** (45% / b = 2.5 → breakeven 0.286):

| n | Wilson lower | margin 0.00 | margin 0.03 | margin 0.05 |
|---|---|---|---|---|
| 30 | 0.302 | clears | no | no |
| 60 | 0.331 | clears | clears | no |
| 100 | 0.356 | clears | clears | clears |

The margin sets how much evidence a convex edge must show: `0.03` is a reasonable
default (clears around n=60, in line with the count gate's spirit). The point: a
profitable convex strategy can now clear the win-rate component on realistic
evidence, while a coinflip strategy faces a *higher* bar than today.

### Option B (simpler) — drop the win-rate floor

Remove `MIN_WIN_RATE_LOWER_BOUND` from the blocker set and rely on
`MIN_PROFIT_FACTOR (1.25)` + `MIN_EXPECTANCY_LOWER_BOUND (>0)` + scored count +
drawdown + false-positive rate. Since `PF ≥ 1.25 ⟹ E > 0`, these already encode
conservative, payoff-aware profitability. This is the cleanest option but removes
a familiar guard; Option A keeps a win-rate guard while making it correct.

## Implementation notes for Codex (when/if operator approves)

- File: `inferno_strategy_lab.py` — `verdict_for_metrics`, constant
  `MIN_WIN_RATE_LOWER_BOUND`.
- Option A needs the per-strategy payoff ratio (or avg win / avg loss in R) on the
  strategy metrics dict so breakeven can be computed; reuse
  `inferno_evidence_strength.empirical_breakeven`.
- Mirror the change in `inferno_promotion_gap.py` (`trades_to_winrate_floor`,
  `analyze_strategy`) so the "what's left to do" projection uses the same anchor.
- Keep `MIN_SCORED_TRADES_FOR_PROMOTION = 30`; the count gate is fine, it's the
  win-rate floor that needs the anchor.
- `inferno_math_config.MIN_WILSON_LOWER_FOR_EDGE (0.42)` is the same number used
  elsewhere; decide whether it, too, should become a margin-over-breakeven.
- Tests: add a convex-payoff strategy that passes PF/expectancy and now also clears
  the anchored win-rate gate, plus a coinflip strategy that must clear ≥0.50.

## Secondary findings to fold into the same review

1. **R-unit risk limits vs the dollar account.** `MAX_DRAWDOWN_RISK_UNITS = −6.0`
   and 3 daily risk units: at a $500 ticket (1R) and ~$1,477 NLV, −6R ≈ −$3,000 ≈
   −2× the account. The cooldown gate permits an account-threatening drawdown
   before firing. Same root as the $500-cap-vs-$25-account-model gap. Reconcile the
   R-unit policy with dollar reality.
2. **Readiness gate selectivity.** `readiness ≥ 72` sits at ~the 47th percentile of
   the current 146-name universe (median 74.5) — it admits the top ~53%, while
   `inferno_math_config` default `OPERATOR_LEVEL` targets the top 20%. The "live
   quality / killer setup" framing implies far more selectivity than 72 delivers.
   Decide whether the gate should be a percentile target, not a fixed number.
3. **Constant drift (already guarded).** The shipped drift guard flags
   `MAX_DAILY_RISK_UNITS` (3 files) and `MAX_KELLY_FRACTION` (2 files), aligned
   today. Single-sourcing them from `inferno_math_config` is the clean follow-up.
4. **Kelly small-sample (minor).** `MIN_KELLY_SAMPLES = 8` lets a variance-based
   Kelly compute below the 30 the gate needs, and `μ/σ²` assumes near-Gaussian
   returns that truncated/convex option P&L violates. Well-mitigated; note, not
   alarm.

## Operator decision

1. **Chosen:** Option A — payoff-implied breakeven anchor.
2. **Margin:** `0.03`.
3. **Not changed:** `MIN_WILSON_LOWER_FOR_EDGE (0.42)` in `math_config`; that
   remains a separate follow-up decision if the desk wants the broader math
   edge helper to move from fixed floor to margin-over-breakeven.

The implemented change calibrates the promotion win-rate gate. It does not
approve any ticket, change risk constants, modify the eligible universe, or
alter broker authority.
