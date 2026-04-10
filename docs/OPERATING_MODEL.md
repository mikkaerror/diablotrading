# Inferno Operating Model

This desk works best when we treat it like a small operating system with clear roles, not just a dashboard with a send button.

## North Star

Every morning we want one reliable result:

- fresh tracker values
- one ranked brief
- one review queue
- one clear path from conviction to action

That means the job of the system is not "look cool." The job is:

1. refresh data
2. verify health
3. rank opportunity
4. stage decisions
5. measure outcomes

## Current Roles

### Inferno Runner

Responsible for:

- running the BC/P/Q/R updater jobs
- repairing column `R` if the external ATR job breaks
- syncing `U:Y` score formulas
- reading the sheet
- rebuilding the snapshot and brief
- sending the email

Main file:

- [morning_inferno_pipeline.py](/Users/mikkasida/Documents/New%20project/morning_inferno_pipeline.py)

### Inferno Watchdog

Responsible for:

- checking whether today’s dawn cycle actually landed
- checking whether email was sent
- attempting a rescue run during the morning window
- escalating only if the desk is still stale after rescue

Main file:

- [inferno_watchdog.py](/Users/mikkasida/Documents/New%20project/inferno_watchdog.py)

### Approval Desk

Responsible for:

- holding the top review queue
- creating a stable shortlist for paper trades and later live approvals

Main file:

- [inferno_approval_queue.py](/Users/mikkasida/Documents/New%20project/inferno_approval_queue.py)

### Dashboard

Responsible for:

- turning the tracker into a tactical decision surface
- making conviction legible
- showing ops health, shortlist, and ticker detail without spreadsheet fatigue

Main files:

- [index.html](/Users/mikkasida/Documents/New%20project/index.html)
- [app.js](/Users/mikkasida/Documents/New%20project/app.js)
- [styles.css](/Users/mikkasida/Documents/New%20project/styles.css)

## Process Flow

### Pre-market

1. Mac wakes before the trading desk window.
2. Dawn runner enters the morning automation window.
3. BC/P/Q/R jobs refresh the source sheet.
4. Formula repair and ATR repair self-heal common breakpoints.
5. Snapshot, brief, and approval queue are rebuilt.
6. Email goes out.
7. Watchdog validates the result and attempts rescue if needed.

### Decision phase

1. Read the brief.
2. Review the approval queue.
3. Move names into:
   - strike now
   - stalk it
   - stand down
4. Capture paper trades or approvals.

### Learning phase

1. After earnings, record what happened.
2. Compare setup, readiness, and score mix against the outcome.
3. Tighten thresholds using evidence, not vibes.

## What Success Looks Like

- one morning brief per day, not duplicates
- no stale data in the email
- no manual spreadsheet rescue before the bell
- shortlist agrees across brief, queue, and dashboard
- failures are obvious and diagnosable
- outcome tracking improves the model over time

## Immediate Cleanup Priorities

### 1. Reduce noise

- keep automation logs quiet outside the morning window
- make failures loud and successes boring

### 2. Add a doctor check

- one command that tells us whether the desk is healthy
- use it as the default preflight and troubleshooting tool

### 3. Centralize config

- keep schedule, automation window, and thresholds in one place
- reduce magic values spread across scripts

### 4. Rotate runtime artifacts

- prune old snapshots and reports on a schedule
- keep the repo and local runtime folder readable

## Next Strategic Steps

### Phase 1: Reliability

- add artifact pruning
- add stale-data guardrails
- add a second email path or fallback alert channel
- add explicit lock-file protection so overlapping runs never fight

### Phase 2: Decision quality

- classify outcomes after earnings
- compare forecast vs realized move
- score which combinations of value/momentum/squeeze/ready actually work
- tune thresholds based on recorded outcomes

### Phase 3: Agency

The desk should become a small agency with distinct jobs:

- `Runner`
  - refresh and compute
- `Auditor`
  - verify freshness, formulas, and delivery
- `Strategist`
  - summarize why the top names deserve attention
- `Execution Clerk`
  - prepare paper tickets and approval-ready orders
- `Archivist`
  - track what happened after earnings

That is the right way to think about "agents" here: each role owns one narrow responsibility and hands clean state to the next role.

### Phase 4: Execution

- paper-trade adapter first
- broker approval queue second
- live automation only after evidence

The rule is simple:

- no broker automation before the paper journal proves the conviction model has edge

## Recommended Weekly Rhythm

### Daily

- wake
- refresh
- brief
- shortlist
- queue

### Weekly

- review false positives
- review missed winners
- update thresholds
- clean runtime artifacts

### Monthly

- decide whether the desk is earning more automation authority
- promote or demote rules based on actual outcomes

## One-line Strategy

Make the system boringly reliable in the morning, brutally honest about edge, and increasingly strict about what earns the right to automate capital.
