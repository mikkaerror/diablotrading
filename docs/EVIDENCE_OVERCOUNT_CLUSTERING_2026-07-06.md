# Decision Memo — The desk over-counts evidence: it measures trades, not independent events

- **Date:** 2026-07-06
- **Author:** Claude (research lane)
- **Stage:** research-only. This *strengthens* the promotion gate (makes it more
  honest, i.e. harder). `liveTradingAllowed=false`, `brokerSubmitAllowed=false`.
- **For:** operator + Codex. This is the most important methodology finding in the
  project — it changes how every edge and every CI on the desk should be read.

## TL;DR

The desk's statistics treat every **trade** as an independent observation. They
are not. The 150 closed outcomes are only **18 distinct tickers** (8.3 trades per
name; CIEN 13×, ORCL 12×, ACN 12×, MOD 11×…). Repeated trades on the same name
around the same earnings share the same move, direction, and IV regime — they are
**highly correlated**. Counting them as independent:

1. **Inflates every bootstrap confidence interval** (evidence looks more robust
   than it is), and
2. **Weakens the 30-outcome promotion gate** — a strategy could "clear 30
   outcomes" with ~5 names × repeats, i.e. far fewer independent bets.

This is very likely **the core reason the desk keeps surfacing 'edges' that
aren't real.**

## The proof (it just happened to us)

The "7–14 DTE straddle edge" looked robust by-trade:
- n=39, mean **+0.87R**, bootstrap lower bound **+0.32** → looked like a real edge.

Re-run **clustering by name** (7 names, resample names not trades):
- median **+0.80R**, 95% CI **[−0.18, +2.40]** → **lower bound below zero.**

Two further tells confirmed the mirage:
- **Two names carried it:** DELL +4.45R and HPE +2.35R; the other five names
  (ACN, MRVL, ORCL, CIEN, PL) were near-zero or negative.
- **Matched test reversed it:** on the 3 names present in *both* the 7–14 and
  22–35 windows, 7–14 was *worse* in all three. The apparent DTE "gradient" was a
  name-selection artifact, not a timing effect.

So the exciting edge was ~2 lucky names in a small, correlated sample — noise
dressed as signal by a statistic that assumed independence.

## Why it happens (mechanism)

Bootstrap and Wilson intervals assume i.i.d. draws. Earnings-options outcomes are
**clustered by event**: N trades on ticker T around one earnings date are one bet
observed N times, not N bets. The effective sample size is closer to the number
of **distinct (ticker × earnings-date) events** than to the trade count. With
clustering, `SE ∝ 1/√(#events)`, not `1/√(#trades)` — so a bootstrap over trades
understates the true uncertainty by roughly `√(trades/events)` ≈ √8 ≈ **2.9×**.

## Where this bites (systemic)

Every place the desk gates a decision on a trade-count or a by-trade CI:
- **Promotion gate** (`inferno_strategy_lab`): `MIN_SCORED_TRADES_FOR_PROMOTION = 30`
  counts trades. Should count distinct events.
- **Evidence strength** (`inferno_evidence_strength`): sample-size + Wilson +
  bootstrap all by trade.
- **Win-rate / expectancy CIs** (`inferno_strategy_lab`, `inferno_promotion_gap`).
- **Score calibration**, **DTE cohorts**, **expected-move** — all by trade.
- **My own audit checks** — same caveat applies; note it.

## The fix

1. **Define an event id** on every outcome: `event = ticker + earnings-date`
   (or ticker + expiration if earnings-date is unavailable). Persist it on
   paper/shadow records.
2. **Count distinct events, not trades**, for the promotion gate. Concretely:
   `MIN_SCORED_TRADES_FOR_PROMOTION` becomes (or is joined by) a **distinct-event
   minimum** — e.g. ≥ 20–25 distinct earnings events. Surface both counts.
3. **Cluster-robust CIs everywhere a CI gates a decision:** resample events (with
   all their trades), not individual trades — the cluster/block bootstrap used
   above. Add a `cluster_bootstrap(records, key="event")` helper next to the
   existing bootstrap in `inferno_math_config` and route the gating modules
   through it.
4. **Cap per-event weight** in aggregate stats so one name (ACN 9×, AGX 10×)
   cannot dominate a cohort mean.

None of this is a loosening — it makes the evidence bar **harder and honest.**
It will (correctly) push promotion further out, because the desk has fewer
independent bets than it thought.

## Impact on the candidate edge and the campaign

- **Downgrade the 7–14 DTE straddle finding** from "robust edge" to "weak,
  unproven lead — not statistically distinguishable from no edge under honest
  clustering." Keep testing it (only forward data settles it), but with the
  prior that it will probably fail, and **on distinct events**.
- **The campaign must accrue distinct earnings events, not repeat-trades on a
  handful of names.** ≥30 *events* across ≥2–3 cycles, cluster-robust CIs, per-name
  weight caps. The `dashboard`/evidence panel should show distinct-event count.

## The honest meta-point

The desk built sophisticated statistics on top of a counting error that made
weak, correlated evidence look strong. Fixing this is worth more than any single
edge: it means that when the desk finally *does* say "promote," the number will
mean what it claims. Until then, treat every prior "edge" — including this one —
as unproven.
