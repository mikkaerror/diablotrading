# Thinkorswim Automation Path

The end game is not "let a dashboard fling orders into the void."

The end game is:

- the desk finds the right names
- the desk proves it has edge
- the desk stages clean execution intents
- the broker surface executes only what has earned approval

## Best Mental Model

Treat thinkorswim as the execution cockpit.

Treat inferno as the conviction engine and control plane.

That means:

- inferno decides what deserves attention
- inferno decides what is approved
- inferno decides the risk budget
- thinkorswim is where the order is actually staged, supervised, and eventually submitted

## Low-Performance Mode

TOS does not need to stay open all day. Keep it closed while the desk runs
tracker updates, daily math, paper-evidence checks, and email briefs. The local
automation defaults below prevent background jobs from foregrounding or
reopening the broker:

```bash
TOS_EXPORT_AUTOMATION_ENABLED=0
TOS_BACKGROUND_EXPORT_ALLOWED=0
```

Open TOS only for supervised export capture or manual order staging. If a report
mentions `tos-closed-low-power`, that is an intentional safe state, not a broker
failure.

## Safer Path To Automation

### Step 1: Human-supervised execution

- review the morning brief
- review the approval queue
- approve or reject names
- let the execution clerk stage the order intents
- manually place or confirm the order in thinkorswim

### Step 2: Conditional and bracket workflow

- use thinkorswim for defined order logic
- keep the inferno desk responsible for eligibility and sizing
- keep a human in the loop

### Step 3: Paper execution adapter

- mirror approved names into a paper execution log
- compare intended trade with realized outcome
- study slippage, timing, and false positives

### Step 4: Broker API lane

- integrate only after paper evidence is strong
- keep approval, risk caps, and audit logs mandatory
- do not give the broker adapter authority to invent trades

## What Has To Be True Before Real Automation

- morning runs are reliable
- false positives are measurable
- approval flow is stable
- risk-unit budgets are enforced
- duplicate runs are impossible
- every execution intent is auditable

## What The Bot Should Never Be Allowed To Do

- place a live trade from a stale snapshot
- exceed the daily risk-unit cap
- bypass manual approval
- trade a setup outside the allowed broker lane
- keep firing if logs or health checks are broken

## Practical Rule

If the desk cannot explain the trade in one sentence and one risk limit, the bot should not be allowed to touch it.
