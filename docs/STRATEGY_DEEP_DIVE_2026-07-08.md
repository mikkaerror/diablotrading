# Strategy Deep Dive — pre-earnings options, grounded in outside evidence

- **Date:** 2026-07-08
- **Author:** Claude (research lane). Research-only. No authority/gate/risk change.
- **Purpose:** step outside the desk's own (small, and partly corrupted) data and
  ask the harder question: does the strategy family the desk is built around have a
  *documented, durable, retail-capturable* edge? Grounded in the academic and
  practitioner literature, cross-checked against what the desk found.

## The one-paragraph verdict

The external evidence lines up almost exactly with what the desk discovered on its
own. **Buying pre-earnings premium is structurally a loser** — the literature is
clear that implied moves are pre-inflated and long straddles only win when implied
is *low* relative to a stock's historical earnings move, which is the exception.
**Selling pre-earnings premium has a real but thin, selection-dependent, and
shrinking edge** — the broad variance risk premium is robustly positive, but the
*single-name earnings-jump* premium (what an earnings short actually harvests) is
close to a wash on average and only turns profitable when you can *rank names
ex-ante* by their risk premium. And at a **small retail account, option bid/ask
spreads of 5–10% dwarf an edge measured in tenths of a percent.** The throughline:
the edge, to the extent it exists, lives entirely in *name selection* and *cost
control* — the two things the desk does not yet have.

## 1. Buying premium into earnings — the literature confirms the KILL

- The key predictor of earnings-straddle returns is the gap between a stock's
  **historical realized earnings move** and the **current implied move**. Long
  straddles profit only when implied is *low* relative to history; when implied
  exceeds history (the usual case), the short side wins. (ORATS; TradeStation.)
- Pre-earnings IV is already elevated because the market knows the event is coming
  and prices it aggressively — so a long straddle needs the stock to move *more
  than an already-inflated implied move*. (moomoo; Fidelity.)
- This is exactly the desk's finding (realized 21.9% vs implied 32.5%, move edge
  −10.6%) and exactly why the buy-side hurdle correctly blocks it. **The KILL is
  consistent with two decades of published evidence, not just our sample.**

## 2. Selling premium into earnings — real edge, but not a free lunch

- The **broad variance risk premium is pervasive and robust**: implied vol exceeds
  realized by ~2–4 vol points on the SPX at 30 days, across assets and decades.
  This is the structural tailwind that makes *selling* the right side in general.
  (AlphaArchitect; AEA.)
- **But two critical qualifiers for earnings specifically:**
  1. **It is selection-dependent.** Liu (AFA, *Earnings Announcements: Ex-ante
     Risk Premia*): selling straddles on the announcement earns **+0.39% for names
     with above-median ex-ante risk premia vs −0.17% for below-median** — a
     statistically significant 0.56% spread. Read carefully: *naive* earnings
     selling is roughly a wash; the profit lives entirely in *ranking names ex-ante*
     and selling only the richly-priced ones. The single-name earnings *jump*
     premium is not the same free structural gift as the index diffusive VRP.
  2. **It is shrinking.** A 2025 Chicago Fed working paper documents *The Decline
     of the Variance Risk Premium* — falling trading frictions have compressed the
     overpricing that made selling profitable. The edge is thinner today than in
     the backtests.
- Net: the sell side is the right *direction* (matches theory and the desk's own
  data-before-corruption), but its realistic edge is **small, requires an ex-ante
  selection signal, and is decaying** — and it still carries the earnings *jump
  tail* (a 15% move when 5% was priced overwhelms the crush benefit), which is
  precisely the DELL/HPE problem the desk saw.

## 3. The retail-scale problem — friction likely exceeds the edge

This is the part the desk has under-weighted and the literature makes stark:

- Typical option **bid/ask spreads run 5–10%+** of the option price. (Unusual
  Whales; SteadyOptions.)
- In the definitive retail study (Bogousslavsky & Muravyev, *An Anatomy of Retail
  Option Trading*), **the average retail option trade earns −0.9%**, small
  *relative to* the 5–10% spread — i.e., execution cost, not strategy, dominates
  outcomes. Retail only survives by using **limit orders** to avoid crossing the
  spread.
- Put the numbers together: an earnings-selling edge of **~0.4% per event** (and
  only for well-selected names) against a **5–10% round-trip spread** means the
  edge is invisible unless you (a) trade only the tightest-spread names, (b) always
  work limit orders, and (c) hold to expiration to avoid a second crossing. On a
  **~$800 account**, position sizing also forces you into cheaper, often
  wider-spread names — the worst quadrant.
- Defined-risk wings (needed to cap the earnings tail) cost premium too, cutting
  the already-thin net edge further.

## 4. What would actually have to be true (the honest path)

If the sell side is to be more than a hope, all of these must hold together:

1. **An ex-ante selection signal** that ranks names by earnings richness —
   essentially the desk's missing `forecastRealizedMovePct`, but framed correctly:
   *history of realized-vs-implied earnings moves per name* (the exact variable the
   literature says carries the edge). This is the single highest-value thing to
   build, and it doubles as the fix for the corrupted realized-move data.
2. **Tight-spread universe only.** Restrict to names whose ATM earnings spread is
   genuinely narrow (mega-caps, high-volume single names). This is what the
   liquidity-gate work already moves toward; here it becomes an *edge* requirement,
   not just a quality filter.
3. **Limit-order fills, held to expiration**, so friction is one narrow crossing,
   not two wide ones. The paper model must charge realistic (not mid) fills or it
   will overstate everything.
4. **Wide diversification** (≥40 names) so the jump tail is one trade among many —
   the pre-registered short-premium design already encodes this.
5. **Small, Kelly-fractional sizing** given the fat tail; never scale into it.

If those five hold and the forward paper test *still* shows a positive,
declustered, friction-real edge — that is a real, if modest, strategy. If any one
fails, the honest expectation is breakeven-to-negative after costs.

## 5. Strategic assessment and decision tree

- **The desk has been fishing in a pond with a real but small and shrinking fish,
  using gear (naive entry, wide-spread names, no selection signal) that can't catch
  it, on a boat (\$800, high friction) that makes the catch barely worth the fuel.**
  That is not a failure of effort — it is a precise diagnosis.
- **Decision tree:**
  - If you want to keep pursuing this: the *only* high-value build is the **ex-ante
    earnings realized-vs-implied selection signal** (§4.1). Everything else
    (liquidity gate, short-premium wiring, diversification) is already in motion and
    is necessary but not sufficient without it. Build the signal, run the
    pre-registered forward test, honor the kill gates.
  - If the selection signal can't be built or doesn't rank names out-of-sample:
    the honest read is that **retail single-name earnings vol has no edge you can
    capture net of friction**, and the effort is better spent elsewhere.
  - Either way, the account is too small for this to be the thing that changes your
    finances in the near term; treat it as a research pursuit with a real but capped
    upside, not a fix.

## 6. The honest bottom line

Nothing here is the answer you were hoping for, but it is the truth the outside
evidence supports: the buy side is dead (confirmed by the literature), the sell
side is real-but-thin-and-selection-dependent (confirmed by the literature), and
retail friction is the silent tax that decides whether any of it survives. The one
build that could tip it from "hope" to "edge" is a per-name ex-ante
realized-vs-implied earnings signal — which is also, not coincidentally, the fix
for the corrupted data. That is where the next real work is, if you choose to do
it.

## Sources

- ORATS University — Volatility around earnings: https://orats.com/university/volatility-around-earnings
- TradeStation — Straddle Opportunities for Earnings: https://www.tradestation.com/learn/options-education-center/straddle-opportunities-for-earnings/
- moomoo — Why Pre-Earnings Volatility Attracts Option Traders: https://www.moomoo.com/us/learn/detail-why-pre-earnings-volatility-attracts-option-traders-117911-250476039
- Alpha Architect — The Variance Risk Premium is Pervasive: https://alphaarchitect.com/the-variance-risk-premium-is-pervasive/
- Hong Liu et al. — Earnings Announcements: Ex-ante Risk Premia (AFA): https://afajof.org/management/viewp.php?n=55300
- Chicago Fed — The Decline of the Variance Risk Premium (2025): https://www.chicagofed.org/-/media/publications/working-papers/2025/wp2025-17.pdf
- Chen et al. — Anticipating jumps: Decomposition of straddle price (ScienceDirect): https://www.sciencedirect.com/science/article/abs/pii/S0378426622003351
- Khan & Khan — 17-Year Backtest of Straddles around S&P 500 Earnings (SSRN 4832160): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4832160
- Bogousslavsky & Muravyev — An Anatomy of Retail Option Trading: https://www.lsu.edu/business/files/event-files/2025-finance-mardi-gras/retail_option_trading_v2.pdf
- Unusual Whales — The bid/ask spread and how it affects options traders: https://unusualwhales.com/information/the-bid-ask-spread-and-how-it-affects-options-buyers-and-sellers
