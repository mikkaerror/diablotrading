# Mission

The North Star for the desk. Read once a month. Stay honest.

## What we are actually trying to do

Compound a small bankroll into a large one through disciplined,
defined-risk options trades, sized so a single bad week never threatens
the account.

We are **not** trying to:

- Catch the next NVDA in one trade.
- Make life-changing money in a quarter.
- Be right more often than the market.

We **are** trying to:

- Survive long enough for compounding to do its work.
- Take only trades the math has filtered.
- Cap losses at known dollar amounts on every position.
- Add to the bankroll over time (cash deposits compound too).

## The honest arithmetic of compounding

The desk starts from the operator's current deployable bankroll. The exact
number lives in local artifacts, not public docs. What matters here is the
shape of the compounding curve and the discipline required to stay alive long
enough for it to matter.

For a simple $1,000 reference bankroll, monthly compounding looks like this:

| Monthly | 1 year   | 3 years  | 5 years   | 10 years    |
|--------:|---------:|---------:|----------:|------------:|
| 2%      | $1,268   | $2,039   | $3,281    | $10,765     |
| 3%      | $1,426   | $2,898   | $5,891    | $34,711     |
| 5%      | $1,796   | $5,792   | $18,679   | $348,912    |
| 8%      | $2,518   | $15,965  | $101,257  | $10.3 M     |

Two observations the operator should internalise:

1. **The gap between 3% and 5% monthly is a 6x difference over 5 years.**
   That gap is risk management. Not signal selection — risk management.
   A trader who picks great signals but takes a 40% drawdown ends up
   *below* a trader who picks decent signals and never exceeds 10%.

2. **The gap between 5% and 8% is real but fragile.** 8% monthly
   requires aggressive sizing. Aggressive sizing requires you to be
   right about edge size. The desk's math is not yet confident that any
   edge is real — so we size as if 5% is the upper bound, not 8%.

The fast path to higher numbers is **adding to the bankroll**: a single
$1,000 deposit at month 12 has the same long-run effect as a year of
above-target returns.

## The four phases (where we are; where we're going)

| Phase | State                                  | Authority                | Today |
|-------|----------------------------------------|--------------------------|:-----:|
| 1     | Paper bootstrap — no live trades       | paper-evidence-only      | ←     |
| 2     | Paper-evidence promotion math earned   | paper-evidence-promotable|       |
| 3     | Live read-only with operator approval  | live-readonly + manual   |       |
| 4     | Broker-assisted live with hard caps    | broker-submit-allowed    |       |

We are in Phase 1. The authority manifest in `data/inferno_authority_manifest.json`
will only flip to Phase 2 when every gate in `docs/MATH.md` § 10 clears
simultaneously. The desk does not negotiate that flip. Neither does the
operator.

### What unlocks Phase 2

- At least 30 closed paper outcomes per active strategy.
- Wilson lower bound on win rate ≥ 0.42.
- Bootstrap expectancy lower bound > 0.
- Devil's advocate verdict: edge-holds (p < 0.05).
- Evidence strength composite ≥ 0.70.
- Walk-forward verdict: survives.
- Math invariant verifier: clean.

Until those line up, every trade is *manual*: the operator clicks submit
on what their own discretion approves. The desk filters and sizes; it
doesn't decide.

### The bridge to Phase 2

The promotion gates above require ~30 closed paper outcomes per
strategy. The strict live filter rarely clears anything on a given day,
so `inferno_paper_bootstrap` seeds the paper ledger at *relaxed* gating
(default 3-of-5 conviction gates cleared, paper-only at $50 notional)
so the math has something to learn from. Bootstrap outcomes feed shadow
evidence but **never count toward live promotion math** until manually
reclassified. The bootstrap proposals appear in the daily email
whenever the live filter blanks out — that's the desk telling you "no
live trade today, but here's research work that moves us closer to
Phase 2."

## Entry framework (the five conviction gates)

For any name to be considered, all five must pass:

| Gate | Threshold |
|---|---|
| Readiness% | ≥ 72 |
| Confidence | ≥ 2 of 3 |
| Days until earnings | ≤ 21 |
| Setup Rec | not in `Avoid` |
| Signal Trigger | must be present |

If fewer than 3 names clear all five gates, **do not trade**. Cash is a
position. There is no penalty for a flat day.

## Exit framework (this is where most retail accounts die)

Every entry needs a written exit *before* you click submit. The desk's
default rules — written so they fit on an index card:

### Rule 1 — Defined-risk strategies only (Phase 1)

Until Phase 3, take only debit spreads or vertical spreads. Your
maximum loss equals the premium you paid. No naked options. No
undefined-risk credit spreads outside the strategy lab's whitelist.

### Rule 2 — Profit-take at 1.5R

When the position is worth 1.5x the premium you paid, sell. Don't wait
for 2R. Don't wait for "the chart looks like it can run." Take the 1.5R.
This rule alone is worth more than picking the right ticker.

### Rule 3 — Time-stop at 50% of original DTE

If the position has not hit 1.5R by the time half its days-to-expiry
have elapsed, close it at market. Theta accelerates exponentially
toward expiry; staying long premium past the half-life is asymmetric
*against* you.

### Rule 4 — Catalyst exit before binary events

If the trade was entered for an earnings catalyst, **close the position
at the close the day before earnings** unless your specific thesis is to
hold through. IV crush and binary post-earnings moves are gambling, not
edge.

### Rule 5 — Hard daily loss limit

If three positions hit max loss in a single day, **stop trading for the
day**. Walk away from the desk. The math says this kind of cluster is
either bad luck or a regime shift — either way, more trades won't fix it.

## Position sizing (calibrated to the current bankroll)

The desk reads your live TOS cash automatically (from
`data/inferno_live_account_sync.json`). Sizing is computed from local cash,
not from a hard-coded public value:

| Tickets | $ each | Notes                          |
|--------:|-------:|--------------------------------|
| 3       | cash / 3 | Must stay below single-ticket cap. |
| 4       | cash / 4 | Usually closest to quarter-Kelly ceiling. |
| 5       | cash / 5 | Default even-split slate. |

Hard caps that can never be exceeded:

- **$500 per single ticket** (`MAX_SINGLE_TICKET_DOLLARS`)
- **$1,500 per day** (`MAX_DAILY_TICKET_DOLLARS`)
- **5 open tickets** (`MAX_OPEN_PAPER_TICKETS`)
- **25% of bankroll on one strategy** (quarter-Kelly)
- **3 R-units of risk per day** (`MAX_DAILY_RISK_UNITS`)

When the bankroll grows past $5,000, revisit these. The dollar caps were
calibrated for the current account size.

## Milestones (operator-facing)

These are the only numbers worth checking each month. They tell you
whether the system is working as designed, not whether you got lucky on
any one ticker.

| Milestone | Target |
|---|---|
| Closed paper outcomes (cumulative) | +6 / month |
| Max drawdown in any 30-day window | ≤ 15% |
| Win rate Wilson lower bound | trending up |
| Devil's-advocate p-value | trending down |
| Evidence strength composite | trending up |
| Bankroll | +3-5% / month after deposits |

If any of these regresses two months in a row, **stop trading and
investigate**. Something in the loop has broken — usually one of:
calibration drift, sizing creep, missed exits, undisciplined entries.

## What ambitious compounding actually means

It means **decades of disciplined compounding, never blowing up**.

The math is unforgiving but fair: small changes in monthly return create huge
differences over long time horizons, but only if drawdowns stay survivable. The
difference between an okay outcome and an extraordinary outcome is *time in the
market without ruin*.

The desk's whole job is to keep you in the market without ruin.

Every safety rail, every adversarial test, every conviction gate, every
exit rule, every drawdown cap exists for the same reason: **so you are
still trading in year 20**.

## Single paragraph for when you're about to break a rule

> A bad trade isn't a single bad position — it's the trade that breaks
> the discipline you spent a year building. The next undisciplined
> trade isn't worth the optionality it costs you. Walk away from the
> desk. The market is open tomorrow.
