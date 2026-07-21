# Basket vs SMH — does the stock-picking beat the ETF? (the decisive test)

- **Date:** 2026-07-13
- **Author:** Claude (research lane). Research-only, decision-support, not financial
  advice. Point-in-time snapshot (2026-07-13), equal-weight, trend-strength proxy.

## The question

~80% of the basket is the semiconductor factor (see PORTFOLIO_THESIS_AND_FRAMING).
So the honest test: does holding these 30 individual names — with their single-name
blow-up risk — actually beat just owning the semiconductor ETF (SMH), which gives
the same exposure, diversified, in one ticket?

## Method

Relative strength vs SMH = blend of (% above 200-day) and (distance from 52-week
high), each name minus SMH's. Positive = stronger trend / closer to high than the
sector. Trend-strength proxy, not literal trailing return; one-day snapshot;
equal-weight (actual position weights may differ).

## Result

Benchmark **SMH: +37% above 200-day, −12% off its 52-week high.**

- **Equal-weight basket average: +33% above 200-day, −25% off high — WEAKER than
  SMH on both.**
- **Only 11 of 30 names beat SMH.**
- The **leaders decisively beat the sector**: DELL (+44 RS), AMD (+28), FTNT (+21),
  STX (+16), WDC (+12), HPE (+10), MRVL (+8), TKR (+6), ARM, TXN, ANET.
- The **drags that pull the basket below SMH are the already-AVOID names**: ORCL
  (−58 RS), SMCI (−50), VNET (−45), OTEX (−41), MSFT (−33), plus AAOI/QCOM/AVGO.

## The decisive conclusion

1. **Holding the whole basket is strictly worse than just buying SMH** — lower
   relative strength AND concentrated single-name risk the ETF diversifies away.
   Do not passively hold all 30.
2. **Holding SMH is a reasonable, simple default** — it beats the average basket
   name, is diversified, and is one ticket.
3. **Holding the top-ranked names beats SMH** — the leaders are in stronger trends
   than the sector. The selection adds value *only if you concentrate in the
   leaders and cut the laggards.*

The names dragging the basket below the ETF are exactly the ones the composite
already tags **AVOID**. Had they been exited at their 200-day breaks (as the system
prescribes), the remaining basket would beat SMH. **The stock-picking is justified
only by using the discipline — not by holding everything.**

## What this means for the process

- This is the strongest validation yet of the tracker/alerts/composite: their entire
  job is to keep you in the ~third that beats the sector and out of the third that
  drags it below the ETF.
- It is also the clearest argument against the "hold everything and buy the dips"
  instinct: the dip names here (ORCL, SMCI, VNET) are precisely what's underperforming
  the ETF. Buying them would move the basket further *below* SMH.
- Honest fallback: if you won't actively rotate and cut, **just own SMH** — it beats
  a passively-held version of your own basket, with far less single-name risk.

## Caveats

- Trend-strength proxy and a single-day snapshot; a multi-window trailing-return
  version (needs per-name history) would firm it up but is unlikely to reverse the
  direction — the laggards are broken on every measure.
- Equal-weight; if your real weights already tilt to the leaders, your live basket
  may be closer to or above SMH. Worth checking against your actual positions.
