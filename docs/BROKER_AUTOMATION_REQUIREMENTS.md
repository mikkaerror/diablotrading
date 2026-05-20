# Broker Automation Requirements

Broker automation is allowed to advance only through official, auditable,
fail-closed interfaces.

## Current Broker Posture

- thinkorswim desktop: supervised read-only surface and manual cockpit
- configured approved live account: read-only oversight
- native TOS export: useful when stable, not trusted as the only source
- Schwab options API: read-only market-data scaffold, no account/order calls
- broker submit authority: off

## Required Before Live Automation

1. Official broker API access.
2. Secure OAuth and token storage outside git.
3. Broker-grade quotes for underlying and option legs.
4. Account, buying-power, position, order, and fill reads.
5. Broker preview or validation before submission.
6. Hard per-ticket, daily-loss, and exposure caps in code.
7. Kill switch tested in normal and failure paths.
8. Paper evidence gates passed.

## Approved Modes

- `OFF`: no broker calls.
- `READ_ONLY`: account, quote, position, order, and fill reads only.
- `PREVIEW_ONLY`: construct and validate payloads without sending.
- `PAPER`: paper ledger and sandbox rehearsal only.
- `LIVE_APPROVAL`: user confirms before every live order.
- `LIVE_LIMITED`: future only, behind promotion and kill-switch gates.

## Market Data Rule

Research feeds can support ranking and context. Execution-critical truth must
come from broker-grade data or a dedicated market-data provider:

- live underlying quote
- option bid/ask
- spread width
- open interest and volume
- quote timestamp
- session state

## Current Safe Build

```bash
./run_inferno_broker_preview.sh
python3 inferno_schwab_options.py AAPL NVDA --json
```

The broker preview builds payloads from paper-staged tickets. The Schwab
options adapter enriches quote quality when configured. Neither command can
submit orders.

## No-Go Rule

If approval, quote quality, risk policy, paper evidence, broker preview, or
doctor health fails, automation authority does not widen.
