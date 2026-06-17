# Trading Day Checklist

The one page you reread every morning before clicking submit on anything.

## Mindset

- The desk's automation does not place trades. You do.
- The math's job is to *filter* and *size*, not to authorise.
- Five names with conviction beat fifteen with hope.
- If a ticket fails any gate below, skip it. There's always tomorrow.

## Step 1 — See the state (3 minutes)

You do not need thinkorswim open for Steps 1–5. Keep the broker closed if the
Mac is slow; the desk should still run the tracker, math, paper evidence, and
briefing stack in low-performance mode.

```bash
cd "<repo-root>"
python3 inferno_doctor.py
python3 inferno_brain_console.py
cat reports/morning_brief_latest.txt
cat reports/approval_cadence_latest.txt
```

If `inferno_doctor.py` says anything other than healthy, stop. Fix the
desk first; you can't trust a slate you can't see.

## Step 2 — Filter today's slate (5 minutes)

For every candidate name on the morning brief, apply these five gates.
A name has to clear **all five** to be considered.

| Gate | Threshold | Source |
|---|---|---|
| Readiness% | ≥ 72 | computed 0-100 field |
| Confidence | ≥ 2 of 3 | sheet column |
| Days until earnings | ≤ 21 | sheet column |
| Setup Rec | not in `Avoid` | sheet column |
| Signal Trigger | present | sheet column |

(These are encoded in `frontend/modules/dataProcessor.js → convictionConfig`.
If you change them there, the dashboard re-filters live.)

Pick **3–5 names** that clear all five gates. If fewer than 3 clear, take fewer
or skip the day entirely. The market's open tomorrow.

## Step 3 — Size each ticket (1 minute)

Use the guardrails printed by the latest capital readiness report. The options
budget is dynamic; do not infer it from a fixed percentage.

```
ticket_size = printed_max_options_risk / candidates_today
ticket_size = min(ticket_size, printed_max_starter_ticket)
```

Never exceed the printed starter-ticket cap regardless of conviction.
Never exceed the printed max options risk budget.

## Step 4 — Paper-stage before live (3 minutes)

```bash
./run_inferno_strike_cycle.sh
cat reports/strike_plan_latest.txt
cat reports/paper_test_director_latest.txt
```

The strike cycle picks strikes for approved or paper-auto tickets, then the
paper test director gives you a single memo with: stageable now / auto-paper
selected / approval only / hard-blocked. For paperMoney evidence, use only
**stageable** or **auto-paper-selected** names. Live trades still require
explicit manual confirmation.

## Step 5 — Read the broker preview (2 minutes)

```bash
./run_inferno_broker_preview.sh
cat reports/broker_preview_latest.txt
```

This is the offline order ticket. It shows the contracts, strikes, debit
or credit, max loss, and reward/risk. **Read every line.** If max loss
exceeds your per-ticket cap or reward/risk is below
`MIN_DEBIT_SPREAD_REWARD_RISK = 0.50`, skip.

## Step 6 — Place the trade in thinkorswim

Open TOS only here, after the offline broker preview is clean. You. Manually.
With the exact strikes, debit/credit, and quantity from the broker preview.

- Use a **debit spread** or a **vertical** unless you have a specific
  reason to be naked.
- Place a **limit order** at the mid (or slightly worse if mid is illiquid).
- Set a stop or alert at your max-loss threshold.

The desk does not click submit. The Schwab API lane is read-only market data,
not order entry. The desk does not have permission to enter live orders.
**You do.**

### Write the exit before you click submit

Every entry needs a written exit. Open the TOS order ticket and set these
*before* you click submit — they're called working orders, and they
mechanise the discipline so you don't have to remember at 2pm:

1. **Profit-take limit at 1.5R** — sell-to-close GTC limit at
   `entry_debit × 1.5`. This is the rule that earns the most money.
2. **Time-stop alert at 50% of original DTE** — set a price alert (not
   an order) on that date so you remember to close it manually if the
   profit-take hasn't filled.
3. **Catalyst exit** — if the entry is earnings-driven, note the
   earnings date in your phone and close the position the day before
   regardless of P&L. IV crush is not edge.
4. **Hard daily loss limit** — if three positions hit max loss in one
   day, stop trading for the rest of the day. Cluster losses signal a
   regime shift; more trades don't fix it.

The full exit framework lives in [`MISSION.md`](MISSION.md#exit-framework-this-is-where-most-retail-accounts-die).
Reread it monthly.

## Step 7 — Log the ticket back

```bash
./run_inferno_tos_fill_ingest.sh
```

This pulls your fills back into the paper ledger so the math can learn
from outcomes you actually took. Without this step, the desk has no
feedback loop, and the Wilson / Bayesian / Kelly modules never improve.

## What "the timing is right" actually means

The five conviction gates are the timing. If a ticket clears all five
*and* its strike-plan max-loss is under your per-ticket cap *and* its
reward/risk clears 0.5, the timing is right. If any gate fails, the
timing is wrong — even if the chart looks good.

## What to do when nothing clears

Cash is a position. Skip the day. Reread the morning brief tomorrow.
There is no penalty for not trading. There is a large penalty for
trading without conviction.

## End-of-session housekeeping

```bash
./run_inferno_paper_evidence_loop.sh
./run_inferno_paper_exit_auditor.sh
python3 inferno_outcome_reviewer.py
```

These close the feedback loop so tomorrow's math sees today's outcomes.

## The single sentence

> Filter to 3–5 conviction-gate passers; size each at $210–$262; cap any
> one ticket at $500; cap the day at $1,500; click submit yourself; log
> the fills back.
