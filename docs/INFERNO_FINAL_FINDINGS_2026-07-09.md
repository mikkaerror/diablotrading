# Inferno — Final Findings & Decision (capstone)

- **Date:** 2026-07-09
- **Author:** Claude (research lane). Research-only throughout.
  `liveTradingAllowed=false`, `brokerSubmitAllowed=false` — never changed.
- **Purpose:** one page that closes the multi-day investigation. Read this and you
  know what's true, what's decided, and what's left.

## What we set out to answer

Does the Inferno desk's strategy — pre-earnings options on single names — have a
real, capturable edge worth pursuing at this account?

## What we found (in order of discovery)

1. **Buying pre-earnings premium (long straddle) is a KILL.** The desk's data and
   the published literature agree: implied moves are pre-inflated, realized comes
   in ~10 points lower on average, and long straddles only win when implied is
   *low* vs history (the exception). The desk's own edge screen correctly blocks
   it — and could never stage it anyway, because it requires a realized-move
   forecast the desk never computed.
2. **The measurement, not the market, was the recurring problem.** Twice an
   "edge" dissolved under scrutiny: first over-counted correlated trades, then a
   corrupted realized-move column (100 "records" collapsed to ~14 real events,
   with implausible >40% earnings moves). Codex has since repaired the data.
3. **Selling premium is the right direction but a thin, selection-dependent,
   shrinking edge.** The variance risk premium is real, but the single-name
   *earnings* piece is near a wash unless you rank names ex-ante by richness
   (Liu, AFA: +0.39% rich vs −0.17% cheap), and it's been declining. Built the
   ranking signal + an out-of-sample validator (`inferno_earnings_richness_signal`).
4. **We can't yet test the signal:** the clean data has ~1 earnings event per name;
   ranking needs ~8. Getting depth needs historical *implied* earnings moves —
   the paid input.
5. **The decisive finding — economics at scale.** Even if the edge is real and you
   select well, at ~$1,100 the best feasible case earns **~$273/yr while the data
   costs ~$1,188/yr**, with a ~30% chance of a losing year and drawdowns near half
   the account. The strategy cannot pay for its own data until roughly a
   **$5k–10k** account, and doesn't produce *meaningful* income until **$25–50k+**
   — and only then if the edge proves real.

## The decision (already determinable)

- **Do the free thing:** if you want scientific closure, use a data provider's free
  trial to backfill ~8 quarters × 20–30 names, run the importer, run the signal.
  It answers "is there any edge" for $0. (Flow is one command each; tooling built
  and tested.)
- **Do not spend on data at this account size.** Every modeled scenario loses money
  net of the subscription. This is arithmetic, not pessimism.
- **Do not expect this to change your finances.** At the current scale it is a
  research pursuit with a real-but-tiny ceiling, not an income source, and no
  amount of additional code changes that.

## What would change the answer

Only two things, and neither is more engineering: (a) a **materially larger
account** (~$25k+), and (b) the **signal proving predictive out-of-sample** on real
purchased data. Until both hold, the honest expected value of further investment
here — money or hours — is negative.

## State of the machine (complete)

Buy-side kill: settled. Data integrity: fixed + guarded. Liquidity gate:
spread-primary. Short-premium arm: wired, defined-risk, friction-real. Selection
signal + validator: built. History importer: built. Economics model: built. Daily
monitor + Schwab OAuth early-warning reminder: automated. Everything is research-only;
no authority or risk constant was ever touched.

## The honest bottom line

This was a successful investigation, just not a lucrative one. It converted a
hopeful, unexamined strategy into a precise map: one dead branch, one thin branch
that's only worth money at 20–50x the current account, and a machine honest enough
to say so for free. The desk's highest-value output was never a trade — it was
keeping real dollars out of a strategy that, at this scale, loses in every
scenario. The next move that actually improves your situation is not in this repo.

## References

- `docs/STRATEGY_DEEP_DIVE_2026-07-08.md`
- `docs/STRATEGY_ECONOMICS_SCALE_2026-07-09.md`
- `docs/DATA_INTEGRITY_REALIZED_MOVE_2026-07-07.md`
- `docs/EVIDENCE_OVERCOUNT_CLUSTERING_2026-07-06.md`
- Market Chameleon subscription compare, accessed 2026-07-09:
  https://marketchameleon.com/Subscription/Compare
- ORATS Data API page, accessed 2026-07-09:
  https://orats.com/data-api
