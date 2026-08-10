# Promotion Gate — Operator Playbook

_State as of 2026-08-06. The gate is the desk's single binding constraint._

## Where it stands
- **Scored paper outcomes: 1 of 30** (need 29 more, plus the distinct-events condition).
- Pipeline health is **green**: Schwab authorized, account locked to 8499, quote-coverage
  module live, so candidates now actually **price** (`alt pricing = priced-risk-pass`).
  The plumbing that was broken is fixed.

## Why nothing is stageable right now (the honest reason)
Not a workflow or routing gap — the current slate is **legitimately all-blocked on trade
quality**, and the desk is correctly refusing to stage sub-threshold trades:

| Candidate | Strategy | Block reason |
|-----------|----------|--------------|
| CRWV | CALL_DEBIT_SPREAD | reward/risk 0.25 < 0.50 debit-spread floor |
| CRWV | PUT_DEBIT_SPREAD | reward/risk 0.05 < floor; bearish spread vs bullish trend |
| USAR / MP | — | wide ATM spread / poor Schwab chain quality / premium hurdle |
| 1 research-selected | — | decision card incomplete / long-vol premium hurdle has no positive forecast edge |

**There is no candidate good enough to route. Do not force one.**

## The quality bar a candidate must clear to become routable
From `classify_candidate` in `inferno_paper_test_director.py`, a candidate reaches
`stageable-now` / `approval-only` (i.e. operator-routable) only when ALL hold:
1. `effective_item.ok == True` (constructed + priced)
2. `risk_verdict.passed == True`
3. `decisionCard.paperComparisonAllowed == True` (card complete; any long-vol premium
   hurdle has positive forecast edge)
4. reward/risk **≥ 0.50** (debit-spread floor)
5. no direction conflict (e.g. not a bearish spread in a bullish trend)
6. within the ticket cap

## The loop that actually moves the gate (1 → 2)
When a session surfaces a candidate that clears the bar:
1. Run the session cycle: `./inferno sync` (or `./inferno strike-cycle`).
2. `./inferno today` — a qualifying candidate shows up as approval-only / auto-paper.
3. Approve it (`y`). It stages as a paper ticket.
4. Key that exact order into **thinkorswim paperMoney** yourself; record the real fills.
   (Desk never stages/fills for you.)
5. Enter the fills in `reports/paper_capture_template_latest.csv` and import the CSV.
6. Close it when done → strategy lab scores it → **gap drops by one**.

## Does NOT move the gate
- The 5 fast-paper sims (`promotion credit OFF`, research-only).
- Shadow closes (quarantined from promotion credit).
- Forcing any sub-threshold or wrong-direction trade.

## Small cleanup worth doing
- One stale staged ticket lingers: `MOD CALL_DEBIT_SPREAD exp 2026-06-18` (expired,
  not fillable). Clear it via `./inferno today` / the approval queue so the capture
  template isn't cluttered. (Operator action — the desk won't close tickets for you.)

## Bottom line
The gate is not blocked by anything you can fix tonight. It moves one outcome at a time,
each time the daily cycle produces a genuinely stageable setup and you run it through
paperMoney. The right cadence is: run the cycle each session, check `./inferno today`,
and act only when a candidate clears the bar above.
