# Schwab Account API Lane

Read-only account-data integration for the Inferno desk.

## Purpose

Schwab is now the preferred automation source for live account truth:

- approved-account balances
- net liquidation value
- cash / buying power fields
- open positions
- average price, mark value, open P/L, day P/L

thinkorswim remains the visual cockpit and manual trade surface. It is no
longer required for routine account sync.

## Active Module

Module: `inferno_schwab_account_sync.py`

Artifacts:

- `data/inferno_schwab_account_sync.json`
- `reports/schwab_account_sync_latest.txt`

Wrapper:

```bash
./run_inferno_schwab_account_sync.sh
```

The live account sync wrapper now refreshes Schwab first:

```bash
./run_inferno_live_account_sync.sh
```

That writes `accountDataSource: schwab-account-api` when Schwab succeeds. If
Schwab fails, the legacy TOS account-statement path remains a supervised
fallback.

## Safety Rules

- Read-only account endpoints only.
- No order, preview, replace, cancel, or submit endpoints.
- No raw account numbers saved to artifacts.
- Non-approved account suffixes may be detected for guardrail visibility, but
  their balances and holdings are not persisted.
- Only the configured approved suffix is normalized into live-book positions.
- Broker submit authority remains `false`.

## Endpoint Shape

The adapter uses the Schwab Trader API account endpoints:

- `/trader/v1/accounts/accountNumbers`
- `/trader/v1/accounts?fields=positions`

The first endpoint proves which hashed account rows exist. The second provides
balances and positions. The desk stores only suffix-level identity and normalized
approved-account fields.

## TOS Formula Migration

The Schwab API cannot directly export custom thinkorswim column formulas. The
right replacement is to rebuild those formulas in Python from Schwab and tracker
inputs:

| TOS-style value | Schwab/API source | Desk replacement |
|---|---|---|
| Net liq / cash | account balances | `inferno_schwab_account_sync.py` |
| Position mark / market value | positions payload | normalized live position packet |
| Average price / open P/L | positions payload | `derivedTradePrice`, `plOpen`, `plPercent` |
| Day P/L | positions payload | `dayPl`, `dayPlPercent` |
| Option Greeks / IV / bid-ask | Schwab option chains | `inferno_schwab_options.py` |
| Expected move / straddle band | Schwab option chains | `inferno_schwab_daily_ops.py` and strategy modules |
| Tracker readiness / support / resistance | Google tracker snapshot | `latest_snapshot.json` enrichment |
| Fragility / live-book review heat | Schwab positions + tracker context | `inferno_live_position_review.py` and live-book packet |

If a TOS custom formula has no obvious source field, capture the formula text or
a screenshot of the column settings. Then rebuild it in a small pure function,
add a fixture test with a known sample row, and document the formula in
`docs/MATH.md` when it affects scoring, sizing, or risk.

For user-authored ThinkScript columns that should remain TOS-native until the
formula is ported, use `inferno_tos_custom_metrics.py`. It stores the exact
formula registry at `data/tos_custom_metric_registry.json`, captures exported
TOS values by ticker, and joins those values into the model snapshot as
`tosCustomMetrics`.

## Current Workflow

```bash
./run_inferno_schwab_account_sync.sh
./run_inferno_live_account_sync.sh
./run_inferno_live_position_review.sh
./run_inferno_live_book_review_packet.sh
```

Expected healthy account-source line:

```text
Account data source: schwab-account-api
TOS required for account sync: False
```
