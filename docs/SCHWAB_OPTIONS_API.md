# Schwab Options API Plan

Read-only integration plan for using Schwab Trader API option chains inside the
Inferno desk.

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

Status: scaffolded.

The adapter:

- builds Schwab market-data chain URLs
- loads OAuth access tokens from an ignored local token vault
- normalizes chain contracts into stable model fields
- computes midpoint, spread percent, liquidity score, ATM straddle mid, and
  implied-move proxy
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

Add a separate local helper that:

- opens Schwab's authorization URL
- captures the redirect code
- exchanges code for access/refresh tokens
- refreshes access tokens before expiry
- stores tokens in `.secrets/schwab_token.json`
- reports token health without printing secrets

This helper should be tested with mocked HTTP responses before real OAuth.

## Phase 3: Model Enrichment

Feed the chain summaries into:

- `inferno_strike_plan`
- `inferno_broker_preview`
- `inferno_trade_conviction_audit`
- `inferno_risk_gate_audit`
- dashboard option-quality cards

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

Safety checks:

```bash
python3 -m unittest tests.test_inferno_schwab_options
python3 inferno_secret_hygiene.py
python3 inferno_doctor.py
```

## Safety Rules

- Never print access or refresh tokens.
- Never commit `.env.schwab`, `.secrets/`, token files, or broker exports.
- Keep account/order endpoints out of Phase 1.
- Treat missing/expired tokens as `not-configured`, not as a runtime crash.
- Treat quote gaps, wide spreads, and missing Greeks as fail-closed blockers.

## Open Decisions

- Token helper location: simple local script vs keychain-backed helper.
- Refresh schedule: pre-open + pre-close vs on-demand during strike cycle.
- Chain scope: top-five briefing names only vs full tracker universe.
- Historical IV rank: compute from stored Schwab chain snapshots or keep current
  tracker IV-rank feed until enough Schwab history exists.
