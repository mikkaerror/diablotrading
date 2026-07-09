# Autotrading Roadmap

This is the promotion path from research desk to broker-aware execution. The
goal is not to force automation. The goal is to make automation earn its seat.

## North Star

The bot may only gain authority when the desk can prove:

- the exact instrument or spread
- the maximum loss before order entry
- positive expectancy from paper evidence
- quote quality and liquidity
- account and buying-power safety
- a working kill switch

## Stages

1. `Conviction Engine`
   - Status: active
   - Refreshes the tracker, ranks candidates, sends the brief, and stages approvals.

2. `Strike Selection`
   - Status: active
   - Builds paper-only option plans and rejects missing or bad quotes.

3. `Paper Ledger`
   - Status: active
   - Records staged, blocked, rejected, closed, and reviewed paper tickets.
   - The bounded evidence goal loop runs process/authority prechecks, harvests
     isolated paper evidence, verifies the resulting artifacts, persists state,
     and stops on safety drift, no progress, timeout, or iteration cap.

4. `Broker Preview`
   - Status: active
   - Creates broker-neutral order previews. It cannot send orders.

5. `Read-Only Broker API`
   - Status: active for Schwab option-chain market data
   - Current lane is quotes, chains, liquidity, Greeks, and expected-move
     checks via the ignored local OAuth token vault.
   - Account, order, and fill endpoints remain out of scope until a separate
     approval, sandbox, and authority review.

6. `Human-Approved Live Orders`
   - Status: future
   - Still requires final user confirmation before order placement.

7. `Limited Automation`
   - Status: future
   - Only possible after promotion gates, risk caps, and kill switches pass.

## Current Gate

The desk is still blocked by paper evidence quality. Until the paper loop
produces enough scored outcomes, live automation stays off.

## Commands

```bash
./inferno strike-cycle
python3 inferno_schwab_options.py AAPL NVDA --json
./inferno daily-ops
python3 inferno_paper_execution.py status
python3 inferno_strategy_lab.py status
./run_inferno_broker_preview.sh
./inferno doctor
```

## Authority Rule

Roadmap stages describe possible future capability. They do not grant
permission. The authority manifest is the only operational source of truth.
