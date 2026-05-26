# Schwab Options API Plan

Read-only integration plan for using Schwab Trader API option chains inside the
Inferno desk.

> **Companion doc:** [`SCHWAB_EDGE_OPPORTUNITIES.md`](SCHWAB_EDGE_OPPORTUNITIES.md)
> is the research note explaining which Schwab-derivable metrics actually
> produce edge for a $500-ticket manual options book, with a tiered build
> backlog (vol calibration → cross-instrument → positioning).
>
> **Price-history companion:** [`SCHWAB_PRICE_HISTORY.md`](SCHWAB_PRICE_HISTORY.md)
> covers the read-only daily candle lane used to recompute the user's
> OHLCV-derived TOS custom metrics.

## Goal

Use broker-grade options data to improve strike selection, quote-quality
filters, expected-move checks, and paper evidence. This is a market-data lane
first, not an execution lane.

Current authority stays unchanged:

```text
authorityLevel: paper-evidence-only
brokerSubmitAllowed: false
liveTradingAllowed: false
```

## Why Schwab Fits

- The operator already uses Schwab / thinkorswim.
- Schwab option-chain data can supply bid, ask, mark, volume, open interest,
  Greeks, implied volatility, expiration, strike, and underlying quote context.
- It reduces dependency on fragile desktop exports for option quote quality.
- It gives the model a cleaner way to reject trades with bad spreads before
  anything reaches manual review.

## Phase 1: Read-Only Chain Adapter

Module: `inferno_schwab_options.py`

Status: active, read-only.

The adapter:

- builds Schwab market-data chain URLs
- loads OAuth access tokens from an ignored local token vault
- normalizes chain contracts into stable model fields
- computes midpoint, spread percent, liquidity score, ATM straddle mid, and
  implied-move proxy
- classifies quote quality, spread friction, liquidity buckets, expected-move
  buckets, Greek completeness, and fail-closed chain-quality flags
- writes `data/inferno_schwab_options.json`
- writes `reports/schwab_options_latest.txt`
- never touches account, order, or trade endpoints

Local config:

```bash
SCHWAB_OPTIONS_ENABLED=1
SCHWAB_TOKEN_FILE="/Users/mikkasida/Documents/New project/.secrets/schwab_token.json"
SCHWAB_API_BASE_URL="https://api.schwabapi.com"
```

Token file shape:

```json
{
  "access_token": "local-oauth-access-token",
  "refresh_token": "local-oauth-refresh-token",
  "expires_at": "local timestamp from your OAuth helper"
}
```

The token file must stay outside git. `.env.schwab` and `.secrets/` are ignored.

## Phase 2: OAuth Helper

Module: `inferno_schwab_oauth.py`

Status: active.

The local helper:

- opens Schwab's authorization URL
- captures the redirect code
- exchanges code for access/refresh tokens
- refreshes access tokens before expiry
- stores tokens in `.secrets/schwab_token.json`
- reports token health without printing secrets

This helper is still intentionally narrow: it does not call account, order,
preview, cancel, or replace endpoints.

## Account API Companion

Module: `inferno_schwab_account_sync.py`

Status: active, read-only.

The account companion now handles approved-account balances and positions via
Schwab's account endpoints while preserving the same no-submit authority:

- reads account-number metadata and account rows with `fields=positions`
- saves only suffix-level account identity
- persists balances and positions only for the configured approved suffix
- feeds `inferno_live_account_sync.py` as the preferred broker-truth source
- leaves thinkorswim as the visualization/manual-trading cockpit

See [`SCHWAB_ACCOUNT_API.md`](SCHWAB_ACCOUNT_API.md) for the formula migration
crosswalk and runbook.

## Phase 3: Model Enrichment

Feed the chain summaries into:

- `inferno_strike_selector`
- `inferno_broker_preview`
- `inferno_trade_conviction_audit`
- `inferno_risk_gate_audit`
- dashboard option-quality cards

Current status: `inferno_strike_selector` attaches the latest Schwab row per
ticker when the report exists, and `inferno_risk_policy` blocks or warns on
attached quote-quality failures. Schwab is the preferred option quote-quality
source; absence still fails closed and does not break the existing paper
pipeline.

## Daily Operations Layer

Module: `inferno_schwab_daily_ops.py`

Status: active.

This layer turns raw chain summaries into the daily operator tape:

- refreshes the local OAuth token when possible
- pulls chains for the active execution/approval/watchlist slate
- classifies every ticker into `tradable-research`, `paper-ready`,
  `manual-review`, or `avoid-chain`
- writes `data/inferno_schwab_daily_ops.json`
- writes `reports/schwab_daily_ops_latest.txt`
- feeds the twice-daily action pulse and strike cycle wrappers

The report is still read-only. `tradable-research` means "good enough for
strike research," not "submit a live order."

New useful fields:

| Field | Use |
|---|---|
| ATM straddle mid | earnings expected-move proxy |
| ATM implied-move percent | compare against ATR / realized move |
| bid/ask spread percent | reject bad fills |
| liquidity score | rank tradable contracts |
| delta | choose vertical-call strikes |
| theta | avoid ugly long-premium decay |
| IV / volatility | enrich vol-premium and Marks/Taleb caution rules |
| open interest / volume | guard against stale contracts |
| quoteQualityScore / quoteQualityLabel | decide whether Schwab quotes are clean enough for strike selection |
| qualityFlags | fail-closed warnings like wide ATM spread, thin liquidity, missing Greeks |
| topLiquidContracts | compact shortlist for future strike selector/broker preview work |

Daily operator values:

| Value | Daily use |
|---|---|
| `quoteQualityScore` / `quoteQualityLabel` | Primary gate before a ticker reaches strike selection |
| `atmSpreadPct` / `atmSpreadQuality` | Execution-friction gate; wide/untradeable spreads block paper tickets |
| `atmLiquidityScore` / `liquidContractCount` | Fillability/depth proxy |
| `atmImpliedMovePct` / `atmExpectedMoveDollar` | Expected-move benchmark versus ATR and support/resistance |
| `atmStraddleMid` / break-even band | Premium paid and market-implied range |
| `atmImpliedVolatility` / `greeksCompletenessPct` | Volatility regime and Greek reliability |
| `topLiquidContracts` | Contract shortlist for strike selector and broker preview |

Current quote-quality labels:

| Label | Meaning |
|---|---|
| institutional | deep, tight, high-confidence chain data |
| usable | good enough for strike research and paper evidence |
| fragile | inspect manually; do not blindly size up |
| poor | likely too thin or wide for current desk rules |
| unusable | missing core chain data |

## Phase 4: Broker-Aware Preview

Only after read-only chain data is stable:

- construct exact leg candidates
- verify max loss before order staging
- enforce per-ticket and daily risk caps
- render a Schwab/TOS-neutral preview
- require explicit human confirmation for any live order

No automatic live submit until paper evidence, kill switches, account checks,
and authority promotion all pass.

## Commands

Offline fixture / test mode:

```bash
python3 inferno_schwab_options.py AAPL --fixture tests/fixtures/schwab_chain_sample.json
```

Configured live chain pull:

```bash
SCHWAB_OPTIONS_ENABLED=1 python3 inferno_schwab_options.py AAPL NVDA AVGO
```

Daily operator tape:

```bash
./run_inferno_schwab_daily_ops.sh
```

This is also run opportunistically by:

- `./run_inferno_action_pulse.sh`
- `./run_inferno_strike_cycle.sh`

Safety checks:

```bash
python3 -m unittest tests.test_inferno_schwab_options
python3 -m unittest tests.test_inferno_schwab_daily_ops
python3 inferno_secret_hygiene.py
python3 inferno_doctor.py
```

## Safety Rules

- Never print access or refresh tokens.
- Never commit `.env.schwab`, `.secrets/`, token files, or broker exports.
- Keep account/order endpoints out of this market-data lane.
- Treat missing/expired tokens as `not-configured`, not as a runtime crash.
- Treat quote gaps, wide spreads, and missing Greeks as fail-closed blockers.

## Open Decisions

- Refresh schedule: pre-open + pre-close vs on-demand during strike cycle.
  See `SCHWAB_EDGE_OPPORTUNITIES.md` §Refresh cadence for the proposed
  tiered-polling answer.
- Chain scope: top-five briefing names only vs full tracker universe. The
  edge doc proposes a focus-list / working-universe / universe tier split.
- Historical IV rank: compute from stored Schwab chain snapshots or keep current
  tracker IV-rank feed until enough Schwab history exists. Phase 2 in the
  edge doc proposes `inferno_chain_history.py` to make this real.
