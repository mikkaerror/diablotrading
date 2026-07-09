# Decision brief — sourcing earnings history depth (priced)

- **Date:** 2026-07-08
- **Author:** Claude (research lane). Research-only. Operator decision; no spend
  committed. Given the account size, this is deliberately a *prove-before-you-pay*
  plan.

## What's needed and why

The sell-side edge lives entirely in ranking names ex-ante by earnings richness
(`docs/STRATEGY_DEEP_DIVE_2026-07-08.md`). The signal harness
(`inferno_earnings_richness_signal.py`) is built and validated, but the clean
ledger has ~1 earnings event per name — too thin to rank anything. It needs ~8
past earnings per name, each with **implied move at entry** and **realized
earnings-day move**. Realized is free (past prices); the paid part is historical
**implied** earnings moves.

## Priced options (verified 2026-07-08)

Codex recheck on 2026-07-09: ORATS still listed a Delayed Data API plan at
`$99/mo` on its pricing page. Market Chameleon blocked automated verification, so
verify its subscription terms manually in a normal browser before any spend.

| Source | Price | Fit | Trial |
|---|---|---|---|
| Market Chameleon **Earnings Trader** | **$79/mo** | Direct: historical earnings implied-vs-realized per name. Web UI (manual export). | 7-day free |
| Market Chameleon Total Access | $99/mo | Adds option screeners on top of the above. | 7-day free |
| ORATS Individual | $99/mo | EOD options history to 2007 + **API** (best for programmatic backfill). | 14-day / $29 |

Context: $79–99/mo is **~10–12% of a ~$800 account per month** — a large fixed
research cost relative to capital. Do not subscribe on spec.

## Recommended sequence (costs $0 to get the answer)

1. **Free trial** (Market Chameleon Earnings Trader, 7-day). No payment risk if
   cancelled in the window.
2. **Backfill a test sample:** ~8 quarters of implied + realized earnings moves for
   20–30 liquid, tight-spread names. Load into the ledger/event format.
3. **Run the signal:** `python3 inferno_earnings_richness_signal.py status`.
   - `signal-predictive-out-of-sample` → the ranking works; a subscription is now a
     justified research cost. Proceed to wire the signal into the campaign universe.
   - `signal-not-predictive` → the ex-ante ranking is noise on real data. That kills
     the sell-side pursuit for **$0** — a clean, cheap answer, exactly the point.
4. **Only then** decide on ongoing spend (and prefer ORATS API if you want the
   backfill automated into the desk rather than manual exports).

## The honest note

Even if the signal proves predictive, the account is too small for this to change
your finances soon; treat it as a research pursuit with real-but-capped upside. The
value of this plan is that it converts an open-ended "keep paying and hoping" into a
single, free, pre-registered test whose result decides whether any money is spent at
all.

## Sources

- ORATS pricing: https://orats.com/data-api
- Market Chameleon subscription compare: https://marketchameleon.com/Subscription/Compare
