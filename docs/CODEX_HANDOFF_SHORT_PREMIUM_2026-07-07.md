# Codex handoff — wire the defined-risk short-premium arm into the paper funnel

- **Date:** 2026-07-07
- **From:** Claude (research lane) → **Codex** (owns capital/risk/strategy + shared
  paper loop)
- **Authority:** unchanged. Paper evidence only. `liveTradingAllowed=false`,
  `brokerSubmitAllowed=false`. No live submit, no risk-constant edit without
  operator ack.
- **Read first:** `docs/SHORT_PREMIUM_PREREG_2026-07-07.md` (the dated
  pre-registration) and `reports/short_premium_study_latest.txt` (the backward
  study). Context: `docs/DECISIVE_MOVE_EDGE_KILL_2026-07-07.md` (buy side is a
  KILL; this is the other side of the same VRP).

## Why

The buy-premium program is dead on the desk's own data. The short (sell-premium)
side has a positive center (median +0.50R, 64% win, 9/13 names positive) but a
negative mean driven by 2 tail names on an 18-name sample. The open question is
strictly whether a **wide, diversified universe** tames the tail. We can only
answer it forward, with real chains. This handoff makes that evidence flow.

## What to build (paper loop, defined-risk only)

1. **New structure family: `SHORT_PREMIUM_DEFINED` (iron condor / short strangle
   with protective wings).** Never naked. Wings sized so per-event max loss is
   bounded (target ≤ ~2–3R). This is the inverse of the long-vol path; reuse the
   strike-selector plumbing but sell the implied-move strikes and buy wings.
2. **Route it through the existing credit-spread machinery.** The
   `MIN_CREDIT_SPREAD_CREDIT_RISK` gate already exists — the short arm is a credit
   structure, so this is the correct gate (unlike the long straddle, which was
   wrongly gated by it). Confirm the credit/risk floor is sane for condors.
3. **Bypass the long-vol hurdle for this family.** `long_vol_hurdle` /
   `forecastRealizedMovePct` applies to premium *buying* and must NOT gate the
   short arm (its edge is the VRP, not a realized-move forecast). Ensure
   `is_long_vol()` is False for `SHORT_PREMIUM_DEFINED` so it isn't blocked for a
   missing forecast.
4. **Wide universe.** Point the short-arm scanner at ≥ 40 distinct pre-earnings
   names, no name > ~4% of total risk. Breadth is the whole experiment.
5. **Friction-real fills.** Charge the full actual bid/ask on entry and close from
   the chain — on both the short strikes and the wings. No friction-blind records
   (the backward ledger was friction-blind; the forward test must not be).
6. **Stamp evidence:** `arm="SHORT_PREMIUM_DEFINED"`, `eventId=ticker+earnings-date`,
   record `impliedMovePct`, realized move, credit collected, wing cost, per-event R.

## Definition of done

- The paper director can stage `SHORT_PREMIUM_DEFINED` tickets on a ≥40-name
  pre-earnings universe, defined-risk, friction-charged, event-stamped.
- These tickets are NOT blocked by `long-vol-premium-hurdle`.
- The daily monitor's `inferno_short_premium_study.py` picks up forward records and
  scores them against `docs/SHORT_PREMIUM_PREREG_2026-07-07.md`.
- Full suite green; authority invariant clean; you commit in your lane.

## Boundary reminder

This is paper evidence toward an honest yes/no. No promotion, no live authority,
no risk-constant change flows from shipping this. The pre-registered kill gates
make "no edge, even selling" a clean, cheap answer if that's the truth.
