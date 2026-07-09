# Ship-ready spec — Auto-approve paper tickets, capped by distinct event

**Status as of 2026-07-09:** historical / superseded. The distinct-event
measurement idea survived, but unattended agents must not approve, reject, stage,
close, or promote paper tickets for the operator. Keep this memo only as lineage
for the event-cap work; do not implement the autonomous paper-ticket authority
described below.

- **Date:** 2026-07-06
- **Author:** Claude (research lane)
- **Stage:** research-only spec. Paper (simulated) only. No real dollar, no live
  order. `liveTradingAllowed=false`, `brokerSubmitAllowed=false` — untouched.
- **For:** Codex. This is the highest-leverage automation left: it lets the
  evidence campaign accrue **independent-event** outcomes on autopilot, and it
  implements the clustering fix (`EVIDENCE_OVERCOUNT_CLUSTERING_2026-07-06.md`) at
  the point of intake.

## Why

Two facts from today:
1. Auto-approval already exists — `AUTO_PAPER_SELECTION_ENABLED=on`; the paper
   director auto-stages gate-passing candidates as `auto-paper-selected`
   (`inferno_paper_test_director.py` line ~290). The human is *not* the gate.
2. But the evidence base is **over-counted**: 150 outcomes = 18 names (8×/name),
   which inflates every CI and fakes edges. Cranking auto-approval *up* without a
   guard would just mass-produce 30 correlated tickets on 5 names — fast garbage.

So the fix is not "automate approvals" (done) — it is **"auto-approve, but never
stack correlated repeats on the same event."** That makes autonomous evidence
*honest*.

## The unit: an "event"

Define `event_id = ticker + "|" + earnings_date` (earnings date from the
candidate's `trackerContext.nextEarnings`; fall back to `ticker + option
expiration` if earnings date is missing). All correlated repeats — same name,
same earnings — share one `event_id`.

## The change — `inferno_paper_test_director.py`

At the auto-select branch (currently ~line 285–291):

```python
if (
    risk_verdict.get("passed") is True
    and strike_item.get("approvalStatus") != "approved"
    and not non_approval_reasons
):
    ev = event_id(candidate)                     # NEW
    n_ev = event_ticket_count(ev, ledger_items)  # NEW: open + scored tickets on this event
    if AUTO_PAPER_SELECTION_ENABLED and n_ev < MAX_PAPER_TICKETS_PER_EVENT:
        candidate["category"] = "auto-paper-selected"
    elif AUTO_PAPER_SELECTION_ENABLED:
        candidate["category"] = "event-capped"   # NEW: already enough on this event
        candidate["eventCapReason"] = f"{n_ev} tickets already on {ev} (cap {MAX_PAPER_TICKETS_PER_EVENT})"
    else:
        candidate["category"] = "approval-only"
    candidate["eventId"] = ev
    return candidate
```

- `event_id(candidate)` — helper as defined above.
- `event_ticket_count(ev, ledger_items)` — count paper tickets (open **and**
  closed/scored) whose `eventId == ev`. Requires stamping `eventId` on every
  staged ticket (do it at stage time so the count is durable).
- `event-capped` is a *new, benign* category: the candidate passed all gates, we
  just don't need another correlated observation of the same event. It is not a
  block; it's diversity control. Surface it, don't alarm on it.

## New config — `inferno_config.py`

```python
# Max paper tickets per distinct (ticker x earnings) event. Prevents the loop
# from manufacturing correlated pseudo-evidence; keeps auto-gathered outcomes
# independent so the promotion gate's distinct-event count means something.
MAX_PAPER_TICKETS_PER_EVENT = int(os.environ.get("INFERNO_MAX_PAPER_TICKETS_PER_EVENT", "2"))
```

Default 2 (allows e.g. a straddle + a strangle per event for the structure-family
arm, without stacking six ACN repeats). Env-overridable.

## Prioritise NEW events

When the director ranks the auto-paper slate for staging, **sort events with zero
existing tickets ahead of events that already have one.** One line in the sort
key: prefer `n_ev == 0`, then existing rank. This makes the loop spend its daily
staging budget widening coverage (new names/earnings) rather than deepening a few.

## Interaction with existing guards (keep all of them)

- `same_ticker_open` (risk policy) still applies — no two *open* tickets on one
  ticker at once.
- `MAX_OPEN_PAPER_TICKETS` still applies.
- All quote/liquidity/spread/cap gates (paper mode) still apply.
- The event cap is *additional* and only affects auto-selection, not the risk
  verdict.

## Pairs with the promotion gate (clustering memo)

Once tickets carry `eventId`:
- The promotion gate should require **≥ N distinct `eventId`s** (e.g. 20–25), not
  30 raw trades.
- Bootstrap CIs should cluster on `eventId`.
Same field powers both intake diversity and honest promotion counting.

## Acceptance tests

1. First gate-passing candidate for a fresh `event_id` → `auto-paper-selected`.
2. After `MAX_PAPER_TICKETS_PER_EVENT` tickets exist on an event, the next
   candidate for that event → `event-capped` (not auto-staged), with reason.
3. A candidate on a **new** event auto-selects even when other events are capped.
4. Staging budget prefers zero-ticket events over one-ticket events.
5. Authority invariant: `liveTradingAllowed`/`brokerSubmitAllowed` stay false; no
   live path touched.

## What this unlocks

With the decouple (paper runs during drawdown) + priority-slate chain-pull
(liquid names) + this (auto-approve, one/event, prioritise new events), the
campaign accrues **distinct-event** paper evidence **autonomously** — the exact
thing that has been impossible. And because it's event-capped, hitting "30" will
mean 30 independent bets, not 5 names × repeats. Honest evidence, on autopilot,
no real money.
