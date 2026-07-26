# Basket system — operating decisions and hard-won facts

**Date:** 2026-07-20
**Status:** binding for the basket lane. Read before changing sizing, momentum,
or the weekly task.

This file exists because several of these were derived WRONG at least once
tonight, at real cost. If you are a future session, trust this over your priors.

---

## 1. Momentum comes from Schwab, NOT from FMP `quote-change`

The FMP `quote-change` endpoint is **plan-limited**. It serves a couple of
mega-caps (NVDA, AMD) and returns `ACCESS DENIED ... requires a higher plan` for
almost everything else — **including on a single isolated call**.

How this was mis-diagnosed twice:
1. First conclusion: "the plan whitelists symbols." Drawn from a parallel burst
   of 10 calls where 2 succeeded.
2. Second conclusion (a "correction"): "no, it's rate limiting from parallelism."
   Drawn from the fact that a fresh 27-name momentum artifact existed.
3. Correct conclusion: a **single isolated call for RBC was still denied**, so it
   is a genuine plan limit. The fresh artifact existed because it came from
   **Schwab**, not FMP.

**The test that distinguishes throttling from a plan limit is one isolated call.**
Run that before concluding anything about this API.

Momentum is produced by `inferno_ai_basket_refresh.py`, which pulls Schwab price
history and writes `data/ai_basket_momentum.json`:

```
python3 inferno_ai_basket_refresh.py run      # Coverage: 30/30 | published=True
```

`batch-quote` is NOT affected and works for all names. Use it freely.

Consequence: momentum depends on a live Schwab OAuth token, which the Sunday
`schwab-weekly-reauth` task keeps alive. If that lapses, the weekly review now
fails closed and says so, rather than serving stale numbers.

## 2. A partial run may never replace a complete signal set

**Incident (2026-07-20):** a loop over the plan-limited `quote-change` endpoint
produced a 3-record file. Saving it silently destroyed a good 27-name momentum
artifact. Composite tags, sizing, and the weekly email then ran on the wreckage
without any error surfacing.

`inferno_ai_basket_momentum.save()` now refuses to shrink coverage and returns
`{"written": False, "reason": ...}`. Coverage may grow or hold; it may not shrink
by accident. Pass `allow_shrink=True` only if the universe genuinely got smaller.

This mirrors the publication contract already in `inferno_ai_basket_refresh.py`.
Apply the same rule to any new artifact that downstream modules trust.

## 3. Sizing is shaped by the actual account, not by percentages

Percentage caps written for a large book are nonsense on a small one. At a
$706 NLV an 8% cap means no position may exceed $56, which **mathematically
forces 13+ holdings** of ~$28 each — a portfolio nobody can run.

`account_shape()` therefore:
- derives a position count from NLV (`nlv // $100`, clamped 3–20)
- **relaxes** the single-name cap if the original would mandate more positions
  than that. Concentration is correct for a small account, not a violation.
- raises the dust threshold to half of equal weight
- leaves large accounts untouched (a $500k book keeps the 8% cap)

Always pass `nlv`. Without it the output is theatre.

## 4. REDUCE is not fundable

`REDUCE` means *rolling over* (below the 50-day, or fading). It is a
trim-toward-zero label, **not a small allocation.**

Before this rule, 23 of 30 names were REDUCE while sizing still deployed 79% of
the book across 25 names — the model saying "reduce almost everything" and the
allocator saying "stay fully invested." Only `LEADER` (1.00) and `HOLD` (0.70)
receive capital; `REDUCE` and `AVOID` are 0.00.

The consequence is intended: **in a rolling-over tape the book goes majority
cash.** That is the momentum lane working, not a bug. See
`docs/MOMENTUM_VS_BUYLOW_VERDICT_2026-07-15.md`.

## 5. Operator long-term holds are excluded from exit logic

Positions flagged `operatorLongTermHold` (currently TE, IREN, HIVE, CLSK) never
produce EXIT or TRIM. Enforced in `inferno_basket_holdings_join.py`, pinned by
tests, and restated in the scheduled-task prompt so even the summarising step is
bound by it.

Their trend state is still **displayed**. Respecting a hold decision means not
nagging; it does not mean hiding data. The awareness line carries no
recommendation.

## 6. Watchlist and portfolio are two different things

- **Watchlist** = `research/ai_basket_universe.json`, 30 names. Candidates.
- **Portfolio** = `data/inferno_live_position_review.json`. What is actually owned.

As of 2026-07-20 the overlap is **zero**: the book is TE/IREN/HIVE/CLSK
(~$706 NLV) and none are on the watchlist. Do not describe the watchlist as
"the portfolio" — that error caused sizing to be built against a book that does
not exist.

## 7. Three copies of the ticker list existed, and drifted

The universe contract, the tracker artifact (standalone HTML, cannot import
Python), and the scheduled-task prompt each held their own list. The artifact
had 30 names while the contract had 27 for weeks, so the bearings sleeve was
visible in the tracker and invisible to every engine.

Fixed: the task prompt now READS the contract, and
`tests/test_inferno_basket_artifact_sync.py` fails if the artifact drifts from
it. Never hardcode a fourth copy.

## 8. Git runs host-side only

The agent sandbox can create files but not delete them. Git writes `index.lock`
on any operation that touches the index — **including read-only ones like
`git status`** — and expects to remove it immediately. It cannot, so every git
command from the sandbox poisons the next one.

Commits happen on the operator's machine via `./commit_basket.sh`, which clears
stale locks, runs the suite, and refuses to commit a red suite. The agent does
research, code, and file writes; the operator runs git.

## 9. The number stack, and what feeds what

Added 2026-07-21. The layers, bottom to top — each one consumes the one below:

1. **quotes** → trend state per name (vs 50-/200-day, distance from high)
2. **momentum** (Schwab) → 3M/6M blend + a single `direction` field
3. **composite** → 0-100 RS + LEADER / HOLD / REDUCE / AVOID
4. **vs-benchmark** → relative strength vs SMH, per-category rollup, factor concentration
5. **regime** (`inferno_ai_basket_regime.py`) → ONE 0-100 score + label from
   breadth-200 (30%), breadth-50 (25%), leader fraction (20%), beating-sector
   (15%), basket-beats-benchmark (10%)
6. **sizing** → account-shaped target weights, **throttled by the regime**
7. **holdings join** → the live book vs the watchlist
8. **signal history** → every run appended to `data/ai_basket_signal_history.csv`,
   with week-over-week deltas

`direction` is mutually exclusive (fading wins over accelerating when both hold),
because reporting a name as simultaneously accelerating AND fading is useless.

### The regime throttle

A weak regime caps total deployment: RISK-ON 100% / CONSTRUCTIVE 85% /
NEUTRAL 70% / CAUTION 50% / RISK-OFF 30%. It exists to catch the one failure the
tag logic alone cannot: a **narrow rally**, where a few names still qualify as
leaders while breadth underneath has collapsed. Sizing would commit fully to
those few; the regime sees the thin breadth and trims.

It only ever REDUCES deployment — a strong regime never forces a cash-heavy book
to invest. Pinned by tests. It is dormant whenever sizing is already conservative
(as on 2026-07-21: 36% invested, well under the CAUTION cap).

## 10. Email: crossings vs the full digest

`--send` emails trend crossings and fires ONLY when something crosses. For weeks
that produced silence, and the regime / sizing / portfolio layers never reached
the inbox at all.

`--email` sends the FULL digest every run, with the regime read in the subject
(`[Basket] Weekly review — CAUTION (39/100)`). The weekly task uses both.

## 11. Universe changes require explicit operator approval

Adding or removing tickers changes what the engines are eligible to act on.
Codex had deliberately guarded the universe at 27 with `assertNotIn` tests. The
widening to 30 was done **with explicit operator approval on 2026-07-20** and
logged as a `LANE-CROSS` note in `coordination/model_notes.jsonl`.

Do not widen or shrink the universe by inference. Ask.

---

**Boundary, unchanged:** everything in this lane is research-only. No module
places a trade, sizes anything for real, or touches `liveTradingAllowed` /
`brokerSubmitAllowed`. Not financial advice.
