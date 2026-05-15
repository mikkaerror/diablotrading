# Inferno Risk Policy

The automation stack is allowed to move quickly, but it is not allowed to get
reckless. This file documents the hard gates that sit between a signal and any
future broker action.

## Current Mode

The system is still paper-only for contract-level execution.

- `liveTradingAllowed` must remain `false`.
- Broker automation is not permitted to invent trades.
- A passing risk verdict means "eligible for paper tracking," not "send a live order."

## Hard Gates

The central policy lives in:

- [inferno_risk_policy.py](inferno_risk_policy.py)
- [inferno_risk_gate_audit.py](inferno_risk_gate_audit.py)

`inferno_risk_policy.py` checks ticket-level risk:

- stale strike plans
- duplicate open paper tickets for the same ticker
- open paper ticket count
- single-ticket max loss
- projected daily max loss
- debit-spread reward/risk
- missing executable-looking quotes
- liquidity warnings from the strike selector
- unexpected live-trading flags

`inferno_risk_gate_audit.py` checks desk-level readiness:

- authority live-submit lock
- approved live account suffix
- fragile live holdings
- capital deployment preflight
- broker-preview safety
- paper evidence promotion state
- approval delivery and reply capture
- TOS export, Downloads, and fill-ingest capture

## Default Limits

Defaults are intentionally conservative:

- `MAX_SINGLE_TICKET_DOLLARS=500`
- `MAX_DAILY_TICKET_DOLLARS=1500`
- `MAX_OPEN_PAPER_TICKETS=5`
- `MAX_STRIKE_PLAN_AGE_MINUTES=180`
- `MIN_DEBIT_SPREAD_REWARD_RISK=0.50`

You can override these with environment variables, but raising them should be a
deliberate desk decision, not a panic-click during market hours.

## Desk Flow

1. Morning pipeline refreshes the tracker and scores opportunities.
2. Execution clerk stages only names with allowed setup types.
3. Approval queue forces a human yes/no decision.
4. Strike selector builds contract-level tickets after options markets open.
5. Risk policy adds a formal verdict.
6. Paper execution ledger records staged, blocked, and rejected tickets.
7. Outcome review measures whether the rules deserve more authority.

## Risk Gate Audit Command

Run this whenever capital is about to be sized or when another model needs a
single risk map:

```bash
cd "<repo-root>"
./run_inferno_risk_gate_audit.sh
```

The output lives at:

- [data/inferno_risk_gate_audit.json](data/inferno_risk_gate_audit.json)
- [reports/risk_gate_audit_latest.txt](reports/risk_gate_audit_latest.txt)

If the audit says `blocked`, no new deployment should be sized until the hard
gate is reviewed.

## Why Blocked Tickets Matter

Blocked tickets are not failures. They are evidence.

If a name keeps getting blocked for poor liquidity, bad reward/risk, or stale
quotes, that tells us the strategy has an execution problem even if the signal
looked good. A hedge-fund-ish process studies the refusals, not just the wins.

## Next Risk Layer

The outcome reviewer now marks eligible paper tickets after expiration. The next
analytics layer should aggregate:

- expected versus realized move
- estimated P/L
- win rate by setup type
- average win/loss
- drawdown by campaign
- false-positive rate

That analytics layer has started in:

- [inferno_performance_analytics.py](inferno_performance_analytics.py)

It will stay conservative until enough closed paper tickets exist to make the
sample meaningful.

Only after that loop has enough data should a broker adapter move beyond
preview-only mode.
