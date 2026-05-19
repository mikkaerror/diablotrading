# Account Blow-Up Case Studies

Six well-documented blow-ups, picked because each one teaches a
specific rule. The point is not to recite the war stories — the point
is to convert each one into a guardrail the desk enforces in code or
in a pre-commit clause.

When a future feature ever weakens one of these guardrails, that
feature should be rewritten or rejected.

## Reading guide

Each case has four fields:

| Field | Meaning |
|---|---|
| **The trade** | What was actually on, in the language a peer would use |
| **The error** | The specific decision-shape that killed the account |
| **The frequency** | How often something like this happens in the broader literature — calibrates whether we're worrying about a tail or a mode |
| **Our rule** | The one-line guardrail derived from the case |

The case studies are not romanticised. Most of these people were
extremely smart and well-resourced. Smart + well-resourced does not
beat ruin math.

---

## 1. Victor Niederhoffer — 1997 (and again 2007)

- **The trade.** Naked short S&P 500 index puts, sized large.
  Niederhoffer was selling premium based on the heuristic that the
  market had never moved the way it would need to move for him to
  lose catastrophically.
- **The error.** Bet-the-fund on a "this hasn't happened before"
  prior. When the Asian-crisis contagion hit in October 1997 and
  the Dow fell 7.4% in a single session, the naked-put position
  was margin-called immediately. Loss: ~$100M+, fund closed.
  Repeated the same shape of error in 2007 with a different
  trigger, and blew up a *second* time.
- **The frequency.** Naked-short-vol blow-ups are not rare events
  in the options literature — they show up roughly every business
  cycle (1987, 1998, 2008, 2018, 2020 are the canonical episodes).
  Treat naked short premium as "your bankroll is a margin requirement
  the market can call any day."
- **Our rule.** **No naked short premium. Ever.** Banned setups in
  `inferno_operator_briefing` and reinforced by the blow-up
  guardrails module. The constraint applies whether or not the
  trade looks attractive on prior data — the past is not a sample
  from the future tail.

Source: [The Blow-Up Artist (FutureBlind synthesis)](https://futureblind.com/2007/10/09/the-blow-up-artist/);
[Steady Options recap](https://steadyoptions.com/articles/how-victor-niederhoffer-blew-up-twice-r124/).

---

## 2. James Cordier / OptionSellers.com — November 2018

- **The trade.** Naked short calls on natural gas futures (and
  short puts on crude oil) inside a managed-futures fund.
- **The error.** A pure short-volatility book with no defined
  maximum loss per ticket. When natural gas futures surged ~20% in
  a single session on November 14, 2018, the position margin call
  not only zeroed customer accounts — many ended up *owing* the
  broker. The promotional copy on optionsellers.com framed naked
  short calls as a low-risk income strategy. There is no version
  of an undefined-loss position that is a low-risk income strategy.
- **The frequency.** This is the same shape as Niederhoffer with
  a different underlying and 21 years later. Pattern: low-recent-
  vol regime + naked short-vol position + sudden spike. The
  pattern reliably reproduces.
- **Our rule.** **Every position must have a defined maximum loss
  knowable at trade open.** Long premium has this property by
  default (you cannot lose more than the debit). Verticals have
  it (the long leg caps the loss). Naked shorts do not — they are
  banned.

Source: [Early Retirement Now write-up](https://earlyretirementnow.com/2018/12/18/the-optionsellers-debacle/);
[Steady Options recap](https://steadyoptions.com/articles/james-cordier-another-options-selling-firm-goes-bust-r429/).

---

## 3. Long-Term Capital Management — August 1998

- **The trade.** Convergence trades across global fixed income —
  pairs that *should* mean-revert if pricing relationships hold.
  Carried at ~25:1 balance-sheet leverage on $4.8B of equity.
- **The error.** Two errors stacked. First, leverage that was
  fine in normal-correlation regimes was lethal when correlations
  spiked to 1 across the book. Second, the LTCM positions were
  *crowded* — other major dealers held lookalike books, so when
  LTCM had to delever, the cover bid wasn't there. Russia's August
  1998 default was the trigger but the *shape* of the loss was
  determined by the structure of the book, not the trigger.
- **The frequency.** "Diversified" book whose pieces become
  perfectly correlated in stress is the modal hedge-fund failure
  mode of the last 30 years. Risk-parity 2020, the August 2007
  quant quake, the 2022 60/40 collapse — all the same shape at
  different scales.
- **Our rule.** **Slate concentration caps are absolute, not
  advisory.** The conviction audit already flags
  sector-concentration disagreements; the blow-up guardrails
  enforce a hard cap on (a) tickets in one sector, (b) tickets in
  one setup, and (c) tickets in one underlying.

Source: [President's Working Group LTCM report](https://www.sechistorical.org/collection/papers/1990/1999_0401_LTCMReport-1.pdf);
[Berkeley lessons summary](https://eml.berkeley.edu/~webfac/craine/e137_f03/137lessons.pdf).

---

## 4. Karen "the Supertrader" Bruton — 2014–2016

- **The trade.** Selling strangles on the S&P 500 index, rolling
  losers forward at ~56 DTE rather than realising them.
- **The error.** Two errors. First, the underlying strategy was
  another naked-short-vol book — same shape as Niederhoffer and
  Cordier, smaller until it wasn't. Second — and this is the more
  subtle one — when losses started arriving, the strategy was to
  *avoid realising them* by rolling forward into longer-dated
  losing positions, which produced reported "profits" while the
  liability stacked. The SEC charged her with fraud in 2016 for
  the resulting misreporting; the trading approach itself was
  ruinous before any fraud charge attached.
- **The frequency.** The "roll the loser forward" antipattern is
  one of the most common operator-level account-killers. It maps
  directly to the disposition effect (Shefrin & Statman 1985):
  selling winners early, riding losers long.
- **Our rule.** **No rolling losers forward to avoid realising
  loss.** The pre-commit falsification triggers in the audit
  already enforce "decide every exit before sizing" and "do not
  roll into PEAD horizon" — both forms of the same discipline.
  The blow-up guardrails reinforce: a losing ticket is *closed*,
  not rolled.

Source: [Macro Ops case write-up](https://macro-ops.com/karen-the-supertrader-goes-rogue/);
[TheStreet on SEC charges](https://www.thestreet.com/investing/karen-the-supertrader-s-winning-strategy-relied-on-fraud-sec-alleges-13593247).

---

## 5. Bill Hwang / Archegos — March 2021

- **The trade.** Concentrated, levered long positions in a small
  number of US- and China-listed equities, expressed through total
  return swaps with multiple prime brokers. ~$100B+ economic
  exposure on roughly $1.5–36B of equity at peak.
- **The error.** Three errors stacked. First, concentration: the
  book was dominated by a handful of names. Second, leverage that
  amplified that concentration via swap structures. Third, the
  *same* concentrated exposure was carried at multiple prime
  brokers without each broker seeing the full picture, so the
  effective leverage was hidden. When the largest positions started
  declining, the margin spiral was unrecoverable inside 48 hours.
- **The frequency.** Concentrated-and-leveraged blow-ups are the
  most spectacular and the most preventable. The math of
  concentration + leverage is unambiguous: a single position large
  enough to break the account requires only that *one* of its risks
  realise to ruin the trader. Diversification is the cheap defense.
- **Our rule.** **Hard cap per-ticket as a fraction of bankroll;
  hard cap per-day total risk.** Sizing capped at quarter-Kelly,
  per-ticket dollar cap, daily-total cap. The blow-up guardrails
  fail loud the moment a sizing call would push past any of these.

Source: [SEC press release on Archegos charges](https://www.sec.gov/newsroom/press-releases/2022-70);
[Wikipedia summary](https://en.wikipedia.org/wiki/Bill_Hwang).

---

## 6. Amaranth Advisors — September 2006 (mentioned, not detailed)

A single energy trader — Brian Hunter — concentrated ~$5B in
natural-gas calendar spreads. Lost ~$6.5B (more than 65% of the
fund) in a week when the spread moved against him. Same shape as
Archegos at smaller scale: concentration eats the diversification
benefit before the concentration's first bad week.

**Our rule.** Same as Archegos — concentration caps are absolute.

---

## What these six teach, in one sentence each

1. **Niederhoffer.** Do not sell what can pay infinitely.
2. **Cordier.** Maximum loss must be knowable at trade open.
3. **LTCM.** Correlation is 1 in the regime you care about.
4. **Karen.** Close losers; do not roll them.
5. **Hwang.** Concentration plus leverage is unrecoverable in one bad day.
6. **Amaranth.** Same rule, repeated.

## What they do not teach

None of these blow-ups happened because the operator could not
predict the market. They happened because the operator did not
constrain the *shape* of the bet. The desk's job is to constrain
the shape — direction, size, correlation, defined loss — *before*
worrying about whether the prediction is right.

When a trade-conviction audit fires only soft bear bullets but the
trade still violates one of the six rules above, the rule wins. The
blow-up guardrails module exists precisely to make that override
mechanical.
