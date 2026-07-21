# Verdict: are we a "buy-low" desk or a "buy-strength" desk?

**Date:** 2026-07-15
**Status:** research-only decision memo. Resolves the open lane question (#47).
**Author:** Claude (PM lane)

---

## The question

You framed the mission as "buy low, sell high, and buy cabins in the mountains."
That is the right *goal*. But it hides a mechanical fork that the whole monitor
depends on, and the two answers are opposite instructions:

- **Buy-low / mean-reversion:** add to names that have fallen, trim names that
  have run. Bet on reversion to a mean.
- **Buy-strength / momentum (trend-following):** hold and add to names in
  uptrends, cut names that break down. Bet on trend persistence.

The tracker, the composite score, the crossing alerts, and the vs-SMH column are
all currently built the **momentum** way (they reward strength, flag weakness).
Before we keep building on that foundation, we should prove it's the right one on
our own names — not assume it.

## The verdict

**We are a buy-strength / trend-following desk. Literal "buy-low, sell-high"
mean-reversion is the worst of the available approaches on this kind of basket,
and the evidence isn't close.**

Buying low still has a place — but only at the *thesis/accumulation* stage
(deciding what theme to own and starting a position when the story is early and
cheap). Once a position is on, it must be **managed by trend, not by dip-buying.**
Averaging down into names that are breaking down is the single fastest way to
turn this book into a crater.

## The evidence — NVDA, your flagship, 5 years (2021-07 → 2026-07)

Three philosophies run on the same monthly price series for the same name:

| Strategy | Total return | CAGR | Max drawdown | Return/vol |
|---|---:|---:|---:|---:|
| Buy & hold (never sell, ride the dips) | **+986%** | 61% | −63% | 1.22 |
| Trend-follow (hold only above ~200-day) | +599% | 48% | **−43%** | 1.13 |
| Buy-low / sell-high (mean-reversion) | **+21%** | 4% | −56% | 0.12 |

Read that bottom row again. Over a stretch where NVDA went up ~10x, the
"buy-low, sell-high" timing rule made **+21% total** — and *still* suffered a
−56% drawdown. It structurally sold the winner every time it made a new high
(sitting in cash through the biggest gains) and bought back into falling knives
during the busts. In a trending market, "sell your winners, buy your losers" is
a wealth-destruction machine.

### Robustness — it isn't one lucky rule

Trend-following holds up across every lookback window; mean-reversion fails in
every variant:

| Trend window | CAGR | Max drawdown | Return/vol | % of time invested |
|---|---:|---:|---:|---:|
| 6-month | 50% | −35% | 1.31 | 68% |
| 8-month | 48% | −51% | 1.14 | 77% |
| 10-month | 48% | −43% | 1.13 | 80% |
| 12-month | 52% | −54% | 1.18 | 87% |

Even the "compromise" — buy on a dip but only sell when the trend actually breaks
— lands at 31–33% CAGR: better than pure mean-reversion, still well short of
just holding or trend-following. Waiting in cash for dips costs more than it saves.

## Cross-sectional corroboration — the whole basket, right now

The single-name test is echoed across all 30 names in today's snapshot. The
names sitting **below** their 200-day are the ones that kept bleeding, not the
ones snapping back:

- **ORCL** −34% below its 200-day, −63% off its high — a "buy the dip" magnet
  that has only punished dip-buyers.
- **MSFT** below its 200-day; **VNET, SMCI, ARM** deeply below trend and still
  weak.
- The names **above** trend (STX, WDC, DELL, FTNT) are the ones beating the
  sector.

Weakness persisted; strength persisted. That is a momentum signature, not a
mean-reversion one. If reversion ruled this basket, the deep laggards would be
the leaders by now. They aren't.

## Why this basket especially punishes buy-low

Two structural features:

1. **Secular trend.** These are AI-capex compounders in an up-cycle. Trend
   persistence is strong; betting against it (selling strength) fights the
   dominant force.
2. **Fat left tails.** Individual names here routinely draw down 40–65% (NVDA
   −63%, SMCI −56% off high, ARM −38%). "Buy the dip" on a name that is *actually
   breaking* (accounting problem, lost socket, demand air-pocket) doesn't revert —
   it keeps going. The 200-day rule is what gets you out before −60% becomes −80%.

## What this means mechanically for the monitor (no rebuild needed)

The system is already pointed the right way; this memo confirms it and sharpens
the language:

- **Keep** the composite score, LEADER/REDUCE/AVOID tags, and the 200-/50-day
  crossing alerts. They are momentum-correct.
- **Interpretation rule to adopt:** an AVOID / below-200-day name is *not* a
  discount to add to — it's a signal to stand aside until it reclaims trend.
  "Cheap and falling" is a trap here; "strong and extended" is the norm to ride.
- **Where buy-low is allowed:** only at initiation of a *new* thematic position
  you don't yet own, when the whole theme (not a single broken name) is out of
  favor. That's value-minded *entry*, followed by trend-based *management*.
- **Re-entry, not bottom-picking:** the 200-day reclaim (the REENTRY alert) is
  the disciplined way to buy back a name that fell and healed — you catch the
  turn *after* it's confirmed, not by guessing the low.

## Reconciling with "buy low, sell high, buy cabins"

You don't have to abandon the instinct. The reconciliation:

- **Buy low = be early to the *theme*,** and start positions when the sector is
  hated, not when a single name is collapsing.
- **Sell high = trim into strength for *risk control / rebalancing*,** and exit
  fully when a name loses its trend — not because it merely went up.
- The cabins get bought by **letting winners run and cutting losers fast** — the
  asymmetry trend-following is built to capture — not by averaging down into
  −60% drawdowns hoping for a bounce.

## Limitations (stated honestly)

- The single-name backtest is **one name (NVDA), monthly granularity**, chosen
  because the data plan only serves deep history for a whitelisted subset. It is
  illustrative, not a full 30-name portfolio backtest. The direction, however, is
  corroborated by the all-30 cross-section and by the broad academic record
  (12-1 cross-sectional momentum and trend-following are among the most
  replicated return premia; naive short-horizon mean-reversion is not a reliable
  standalone equity edge, least of all in secular growth).
- Trend-following underperforms buy-and-hold on *raw* return because it sits out
  whipsaws and misses gap-up recoveries. The choice between "buy & hold" and
  "trend-follow" is a **drawdown-tolerance** decision, not a buy-low-vs-momentum
  one — both are strength-respecting. If you can stomach −60% without selling,
  buy-and-hold maximizes return; if you can't, trend-following is the disciplined
  version of the same bet.

## Bottom line

Lane locked: **buy strength, manage by trend, never average down into a broken
name.** Buy-low is reserved for early thematic entry, not position management.
The monitor already encodes this; keep building on it.
