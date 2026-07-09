# Pre-registration — defined-risk short-premium campaign

- **Registered:** 2026-07-07, before forward evidence. Research-only.
  `liveTradingAllowed=false`, `brokerSubmitAllowed=false` — unchanged.
- **Author:** Claude (research lane).
- **Supersedes direction of:** the buy-premium campaign
  (`docs/DECISIVE_MOVE_EDGE_KILL_2026-07-07.md` — KILL). This is the other side of
  the same measured variance risk premium.

## Why this, and the honest status

The desk's 100-record ledger shows realized earnings moves averaging 21.9% vs
32.5% implied. That is a negative edge for the premium *buyer* (killed) and a
structural tailwind for a defined-risk *seller*. The backward study
(`inferno_short_premium_study.py`) shows the seller's **center is positive**
(median +0.50R, 64% win, 9/13 names net-positive) but the **mean is negative**
(−0.16R at the conservative cap) because 2 of 18 names (DELL, HPE) carry ~300% of
the losses, and removing the best two names turns it negative with a CI that
crosses zero.

**Status: promising-but-unproven.** The failure mode is *undiversified tail on a
tiny universe*, not a negative center. This is the one lead whose honest next step
is a forward test rather than a kill.

## The decisive variable: diversification

Premium selling only works by spreading many uncorrelated event-bets so no single
blowup dominates. An 18-name backtest cannot answer this either way. The forward
campaign must trade a **wide universe** so a DELL-sized tail is one trade among
many, not 15% of the book.

## Pre-registered design

- **Structure:** defined-risk only — short strangle/iron condor with protective
  wings. No naked short vol, ever. Wings sized so max loss per event is bounded
  (target ≤ ~2–3R).
- **Universe:** ≥ **40 distinct names**, no name > ~4% of total risk. Breadth is
  the point; a narrow book fails by construction.
- **Entry:** pre-earnings, sell the implied move (short strikes near the implied
  breakevens). Record `impliedMovePct` and realized outcome per event.
- **Friction:** charge the full actual bid/ask on entry and on any close, from the
  real chain. No friction-blind records.
- **Event unit:** `eventId = ticker + earnings-date`; cluster all stats by name.

## CONFIRM (all, on forward friction-real evidence)

| Gate | Threshold |
|---|---|
| Distinct names | ≥ 40 |
| Distinct events | ≥ 60 |
| Mean net-R, **ex the two best names** | > +0.10R |
| Cluster-bootstrap 95% CI low (by name) | > 0 |
| Worst-2-name share of total loss | < ~40% (tail is diversified, not dominant) |
| Max single-event loss | ≤ wing cap (defined risk held) |

## KILL (any one)

1. ≥ 60 events and cluster CI on mean net-R crosses zero.
2. Mean net-R ex-two-best ≤ 0 at ≥ 60 events (edge still depends on a few names).
3. Worst-2-name share of loss ≥ ~40% even at ≥ 40 names (tail refuses to
   diversify — the strategy's own risk is uncontrollable here).
4. Time-box: 90 days (→ 2026-10-05) without reaching 40 names / 60 events.

## Honest caveats (binding)

- The backward center being positive is encouraging but the backward mean is
  negative; this is a *lead*, not an edge.
- Tighter wings flatter the backtest because the credit given up for protection is
  not modeled — only real chains price it. The forward test resolves this.
- Selling premium carries real tail risk; defined-risk caps it but also caps the
  edge, and the VRP may be too thin to survive protection + friction. That is
  exactly what the forward test measures.
- No authority/live change is contemplated regardless of outcome. This is paper
  evidence toward an honest yes/no.
