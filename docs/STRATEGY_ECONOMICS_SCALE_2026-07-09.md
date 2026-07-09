# Strategy economics — is it worth it at this scale? (the juice-vs-squeeze answer)

- **Date:** 2026-07-09
- **Author:** Claude (research lane), patched by Codex for current pricing/math
  hygiene. Research-only. Illustrative model (`inferno_strategy_economics.py`),
  not a promise. No authority/gate/risk change.
- **Question:** even if the sell-side edge proves real, what does it EARN at an
  ~$1,100 account, and is that worth the data cost and the risk?

## The finding (decisive)

Monte Carlo over a defined-risk short-premium book, honest inputs (5%/event risk,
50 selected events/yr, 64% win, -3R tail cap), swept across edge scenarios.
Codex corrected one modeling issue: with a +1R credit cap, the old +0.20R
"optimistic" case was not feasible under the 64% win / -3R loss-tail assumptions.
The top case below is the best feasible +0.10R edge.

| Scenario | Mean annual P&L @ $1,100 | Prob losing year | Mean max drawdown |
|---|---|---|---|
| pessimistic (-0.10R) | **-$277** | 72% | -$638 |
| breakeven (0.00R) | -$2 | 49% | -$547 |
| thin edge (+0.05R) | **+$136** | 39% | -$514 |
| best feasible (+0.10R) | **+$273** | 29% | -$486 |

- **Even the best feasible case earns +$273/yr while data costs about $1,188/yr** -
  the subscription costs ~4.4x what the strategy makes. Buying data at this size is a
  guaranteed net loss regardless of whether the edge is real.
- Every scenario carries a ~30-70% chance of a losing year and a typical drawdown
  near **half the account**.
- Break-even account size *just to cover the data cost*: ~$4,752 (best feasible)
  to ~$9,504 (thin edge); never, without an edge.

## Why small accounts are even worse than the table shows

At roughly $55 risk/event, the bid/ask friction on a four-leg condor ($10-30) is a large
fraction of the risk. Friction is roughly fixed per contract, so at tiny size the
*rate* of return is worse, pushing the real per-event edge toward the
pessimistic/negative column. Small size earns less AND at a worse rate.

## What this means

- **The free signal test is still worth running** — it's $0 and answers "is there
  an edge at all." Do that.
- **The economic decision is already made: do not pay for data at ~$1,100.** Even a
  real, well-selected edge produces tens of dollars a year here, dwarfed by both
  the data cost and the drawdowns.
- This strategy becomes *dollars that matter* only at a much larger account
  (~$25–50k+) AND only if the edge proves real. At the current scale it is a
  research pursuit, not an income source — and it cannot be made into one by
  working harder on the code.

## Honest bottom line

The machine is excellent and the science question is worth closing for free. But
the money question has a clear answer at this account size: this is not the thing
that changes your finances, and spending on data to chase it would lose money in
every scenario modeled. Scale the account elsewhere first; let this stay a
zero-cost research pursuit until it's both proven and worth the squeeze.

## Pricing sources checked

- Market Chameleon subscription compare, accessed 2026-07-09:
  https://marketchameleon.com/Subscription/Compare
- ORATS Data API page, accessed 2026-07-09:
  https://orats.com/data-api

Pricing can change; reverify manually before any spend.
