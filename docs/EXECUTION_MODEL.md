# Inferno Execution Model

This desk should not jump from "interesting signal" to "live auto trade."

It should move through five controlled stages:

1. signal
2. shortlist
3. approval
4. execution intent
5. broker action

## Current Truth

Right now the system is strongest at:

- refreshing the sheet
- ranking names
- sending the morning brief
- staging an approval queue
- building execution intents

Right now it is **not** live auto-trading.

That is intentional.

## Roles

### Strategist

- ranks names
- separates earnings plays from long-term accumulation
- explains why a name deserves attention

### Approval Desk

- turns the best names into a short queue
- forces a human yes/no decision before anything becomes executable

### Execution Clerk

- converts approved names into broker-safe order intents
- applies risk-unit budgets
- blocks names that are not yet approved, not yet triggered, or outside allowed setup rules

### Broker Surface

- today: thinkorswim as the execution surface
- future: official broker API lane after the desk proves its edge

## Execution States

### Pending

The name is on the queue, but nobody has approved it yet.

### Approval-Ready

The setup is allowed, the trigger is live, the risk budget is available, and the human reviewer has approved it.

### Blocked

The name failed one or more safety checks.

Common block reasons:

- trigger is not live
- human approval still required
- setup not approved for broker automation lane
- daily risk budget would be exceeded

## Why Thinkorswim Is The Surface, Not The Brain

Thinkorswim is best treated as the place where orders get staged and supervised.

The inferno desk should stay responsible for:

- thesis
- ranking
- sizing limits
- approval state
- audit trail

Thinkorswim should stay responsible for:

- order entry
- order conditions
- bracket/conditional execution
- manual supervision until the system earns more authority

## Promotion Path

### Phase 1

- dashboard and email only

### Phase 2

- paper tickets
- approval queue
- execution intents

### Phase 3

- assisted broker workflow
- approved names only
- still human-submitted

### Phase 4

- paper execution adapter
- compare expected move versus realized move
- measure whether the desk actually deserves automation

### Phase 5

- broker API integration
- still behind hard risk caps and kill switches

## Hard Rules

- no auto-submit until paper execution has a real track record
- no order intent without a trigger or explicit manual override
- no more than the configured daily risk budget
- no broker automation that bypasses the approval queue
- no single script should both rank names and place real trades without audit logs

## Operator Command

To inspect the current execution desk:

```bash
python3 inferno_execution_clerk.py
```

To rebuild the staged execution queue from the latest snapshot:

```bash
python3 inferno_execution_clerk.py build
```
