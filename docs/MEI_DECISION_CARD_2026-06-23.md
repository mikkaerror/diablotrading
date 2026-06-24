# MEI Decision Card — 2026-06-23

**Stage:** research-only · operator-facing
**Trade window:** earnings today (dte_earn=0)
**Promotable:** N/A — this is a paper candidate, not a live order

Built as a template the desk can use for any future high-readiness candidate
that the discipline doc and the desk's own evidence ledger flag at the same
time. Surfaces the verdict so the operator decides on data, not on screen
score alone.

---

## What the screen says

| Field | Value |
|---|---|
| Ticker | MEI |
| Readiness | **90** (highest we've seen) |
| Setup | **Straddle** (Long Straddle) |
| Underlying price | $13.40 |
| Source price (when plan built) | $14.12 (−5.10% drift) |
| Days to earnings | **0** |
| IV Rank | 33.65 |
| IV Rank change | +17.18 (rapid pre-earnings IV climb) |
| Implied move (ATM) | **23.32%** |
| ATM bid-ask spread | 17.73% ("poor" quality) |
| ATM liquidity score | 26 / 100 |
| Quality flags | no-liquid-contracts, thin-atm-liquidity |
| Trend / Trigger | Bullish / Confirmed |
| Alignment | 36.4 ("Fragile") |
| Strength | 45.11 ("neutral") |
| Strike plan | empty (not yet priced) |

## What the discipline doc says

Five filters the deep-dive proposed (BACKLOG #14). MEI's score against each:

| Filter | MEI | Pass? |
|---|---|---|
| Implied move ≤ 20% | 23.32% | **FAIL** |
| ATM bid-ask ≤ 30% | 17.73% | pass |
| Max loss ≤ 25% of NLV | not priced yet | unknown |
| If within 7d earnings, implied in 10-20% sweet spot | 0d earnings, implied 23% | **FAIL** |
| R/R ≥ 0.5 | not priced yet | unknown |

Two of three computable filters fail. The two unknowns can't be evaluated
until the strike plan is built.

## What the desk's own ledger says

The 96-observation expected-move ledger, bucketed by implied-move band:

| Implied move bucket | n | Beat rate | Mean R |
|---|---|---|---|
| 0-10% | 3 | 67% | +0.34 |
| **10-20%** (sweet spot) | 40 | 52% | **+0.95** |
| **20-30% (MEI sits here)** | **34** | **21%** | **-0.28** |
| 30-50% | 7 | 0% | +0.13 |
| 50%+ | 12 | 0% | -0.15 |

Sub-$30 stocks specifically in the 20-30% bucket: n=5, beat rate **0/5**,
mean R **-0.385**. Five-for-five losers in the desk's evidence for the
combination that MEI represents (cheap stock, implied move 20-30%, long
vol).

From codex's DTE-policy cohort analysis, LONG_STRADDLE entries by DTE band:

| Entry DTE | n | Win rate | Net R |
|---|---|---|---|
| 0-6 | 7 | 43% | +0.51 |
| **7-14** | **36** | **56%** | **+0.86** ← only meaningfully positive |
| 15-21 | 21 | 33% | +0.44 |
| 22-35 | 27 | 7% | -0.41 |

The 7-14 DTE entry window is the desk's actual edge. MEI's option
expiration isn't in the strike plan yet, but with earnings today, the
typical play is to buy the front-week or front-month — which would land at
~7 DTE if the operator picks the nearest weekly, or ~30 DTE if monthly.

## What the academic literature says

[de Silva, Smith & So 2024 "Losing is Optional"](https://www.timdesilva.me/files/papers/losing_optional.pdf): retail traders
buying options before high-volatility earnings announcements **lose
10-14% on average** — the worst-performing retail behavior in their
dataset. MEI is 0 days from earnings: directly in this bucket.

[Bryzgalova et al. 2023 "Retail Trading in Options"](https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13285): retail
bid-ask spreads average 12.6%. MEI's 17.73% is 1.4× that — the friction
alone takes a meaningful chunk of any edge.

Post-earnings IV crush: 30-60% magnitude on large-cap equities (small-cap
like MEI can be wider). A long straddle held through the print needs the
realized move to substantially exceed the implied move (23.32% here) to
overcome the crush.

## Honest summary

**The strongest evidence (n=34 in the desk's own ledger) says this exact
combination has 21% win rate and loses 28 cents per dollar of debit.**

The strongest *positive* signal — the 90 readiness score — is a composite
that doesn't appear to weight implied-move-vs-evidence-sweet-spot. The
cap-fit audit shipped today (BACKLOG #2) showed the strategy lab routinely
proposes straddles when the cap-fit fallback to verticals would be safer;
codex's `inferno_paper_blocker_swarm` is being built to address this.
Until that lands, the readiness score should be treated as one input, not
the answer.

## Three options the operator has

**A) Reject MEI.** Statistical evidence: 21% historical win rate at this
implied-move band. Documented retail loss of 10-14% on 0-DTE earnings
options. Strike plan still empty. Defensible on data alone.

**B) Approve MEI.** Requires articulating in the journal prompt why this
trade clears the evidence-supported sweet spot when 34 prior observations
of the same setup did not. Acceptable answers include: "I have a thesis
on the realized move that exceeds 23% for reason X" or "I want to
generate evidence in this specific bucket." Not acceptable: "the
readiness is 90."

**C) Skip MEI.** Defers without committing. The candidate reappears
tomorrow if it's still valid. With earnings today, skipping is
effectively a soft reject — the trade window closes by end of session.

## The decision-card pattern (for future use)

This document is a template. For any future candidate that triggers a
deep-dive flag against a high screen score, the same five sections work:

1. What the screen says (raw fields)
2. What the discipline doc filters say (pass/fail per rule)
3. What the desk's own ledger says (matched cohort)
4. What the academic literature says (retail base rates)
5. Three operator options (reject / approve / skip with rationale)

The point of the card isn't to dictate the decision. It's to ensure the
decision is informed by the same four data sources every time. The
journal prompt at approve-time captures the rationale; the friction-
telemetry column captures how long the decision took. Over time, the
pattern produces a learnable record.
