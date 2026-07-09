# State of the Desk + Implementation Queue — 2026-07-06

**Status as of 2026-07-09:** historical / superseded by
`STATE_OF_THE_DESK_2026-07-07.md` and later operator-owned paper workflow work.
References to auto-approval or autonomous paper ticket gathering are no longer
current authority. Unattended agents must not stage, approve, reject, close, or
promote paper tickets.

One page. Read this cold and you know where the desk stands and what to do next.
Everything here is research-only. `liveTradingAllowed=false`,
`brokerSubmitAllowed=false` — unchanged and not in question.

## Where the desk stands (honest)

- **No proven edge. 1 of 30 scored.** The desk has never promoted a strategy.
- **The one lead — 7–14 DTE pre-earnings straddle — was DOWNGRADED.** It looked
  robust (+0.87R, LB +0.32) but that treated 39 correlated trades as independent.
  Clustered by name (only 7 names; DELL + HPE carried it), the honest 95% CI is
  **[−0.18, +2.40]** — crosses zero. Matched on shared names it *reversed*. It is
  now a **weak, unproven lead**, not an edge.
- **The real finding is systemic: the desk over-counts evidence.** 150 outcomes =
  **18 tickers** (8×/name). Correlated repeats inflate every CI and let the
  30-trade promotion gate be cleared by ~5 names. This is very likely *why the
  desk keeps surfacing edges that dissolve.*
- **Account:** ~$788, ~53% below peak → the live drawdown protocol is at "pause"
  (correctly blocking new *live* risk). Money is not the binding constraint;
  evidence + honest measurement are.

## Shipped & verified this cycle (working)

- ✅ **Payoff-aware win-rate promotion floor** (Codex, committed).
- ✅ **Paper/live drawdown decouple** — verified: a $127 ticket **passes in paper,
  blocked in live** during the pause. Paper evidence can flow while live stays
  paused.
- ✅ **Chain-pull priority slate** — verified: now surfaces liquid large-caps
  (GOOG/ASML/TXN/FCX), not just held miners.
- Result: funnel flipped `priced-risk-blocked → priced-risk-pass`. The systemic
  $0 wall is gone. The decouple + chain-pull bundle is committed and pushed as
  `825464a`.

## Implementation queue (do in this order)

| # | Action | Where | Memo |
|---|---|---|---|
| 1 | Commit + push the decouple + chain-pull (working tree) | git | — |
| 2 | Set `INFERNO_PAPER_TICKET_BUDGET=2000` for the straddle arm (env, no code) — $500 blocks large-cap straddles | env | CAMPAIGN_PLAN |
| 3 | **Auto-approve paper + distinct-event cap** — the automation unlock; stamps `eventId` | `paper_test_director`, `config` | AUTO_APPROVE_PAPER_EVENT_CAP |
| 4 | **Evidence clustering fix** — promotion gate counts distinct events; cluster-bootstrap CIs (same `eventId`) | `strategy_lab`, `evidence_strength`, `promotion_gap`, `math_config` | EVIDENCE_OVERCOUNT_CLUSTERING |
| 5 | **Run the campaign** — 0–21 DTE window, structure-family arm (straddle/strangle/single-long/vertical), real friction, ≥30 **distinct events** across ≥2–3 cycles, pre-registered kill gates | — | CAMPAIGN_PLAN |
| 6 | Housekeeping: `revoke` the stray capital-scaling ack; single-source `MAX_DAILY_RISK_UNITS` + `MAX_KELLY_FRACTION`; readiness-gate selectivity; ack-floor bug | various | — |

Items 3+4 share one field (`eventId = ticker + earnings-date`) — build them
together. Together with 1+2 they make the campaign gather **honest, independent**
evidence **autonomously**.

## Codex execution update - 2026-07-06 12:54 MT

- Queue item 1: done. Commit `825464a` pushed to `origin/main`.
- Queue item 2: done as launchd env: `INFERNO_PAPER_TICKET_BUDGET=2000` and
  `INFERNO_PAPER_DAILY_BUDGET=6000`.
- Queue items 3-4: implemented and tested. Paper records now carry `eventId`;
  auto paper selection is capped per event; promotion/evidence math now counts
  distinct events and uses cluster bootstrap CIs.
- Queue item 5: attempted. The cycle produced 0 stageable paper tickets. The
  $2000 paper cap removes part of the size blocker, but current names still fail
  quote quality, liquidity, source-price divergence, reward/risk, or residual
  cap checks.
- Queue item 6: partially done. Risk/Kelly defaults are single-sourced through
  `inferno_math_config`; ack-floor was already fixed. The stale capital-scaling
  ack still exists and requires explicit operator revoke. Readiness selectivity
  remains diagnostic-only, not a gate change.
- Verification: full unittest suite 1456/1456 OK; `git diff --check` clean;
  `inferno_math_verify.py` clean; `inferno_secret_hygiene.py` healthy;
  `./inferno doctor` healthy; production-code live-submit invariant clean.

## The memos (index)

1. `PROMOTION_GATE_WINRATE_FLOOR_2026-06-26.md` — payoff-aware win-rate floor (shipped).
2. `PAPER_LIVE_DRAWDOWN_DECOUPLE_2026-07-03.md` — paper runs during drawdown (shipped).
3. `UNIVERSE_LIQUIDITY_CHAIN_PULL_2026-07-03.md` — chains cover the priority slate (shipped).
4. `CANDIDATE_EDGE_7_14_DTE_STRADDLE_2026-07-03.md` — the lead (now downgraded — read with the clustering memo).
5. `EVIDENCE_OVERCOUNT_CLUSTERING_2026-07-06.md` — **the important one**: count events, not trades.
6. `AUTO_APPROVE_PAPER_EVENT_CAP_2026-07-06.md` — auto-gather distinct-event evidence.
7. `CAMPAIGN_PLAN_PROVE_OR_KILL_2026-07-03.md` — the test design + decision gates.

## The honest bottom line

None of this manufactures an edge — it manufactures the **ability to find one
honestly, on autopilot, without risking a dollar or fooling ourselves with
correlated repeats.** The prior, given everything seen, is that most candidates
(including the straddle) will *fail* honest distinct-event testing. That is a
fine outcome: the pre-registered kill gates make "no edge here" a clean, cheap
answer instead of an endless drift. The win of this cycle is not a strategy — it
is that **when the desk next says "promote," the number will finally be true.**
