# Schwab Price History

This lane pulls daily Schwab OHLCV candles and recomputes the visible
Thinkorswim custom columns that are pure price/volume math.

## What It Replaces

TOS is still useful for charting and manual visual confirmation, but these
columns no longer require a TOS watchlist export when Schwab market data is
configured:

| TOS column | Schwab input | Python mirror |
|---|---|---|
| RVOL | daily volume | `volume / Average(volume, 30)` |
| Pv52H | daily high/close | `(close / Highest(high, 252)) * 100` |
| MOM | daily close | `close - Average(close, 10)` |
| ATR% | daily high/low/close | `Average(TrueRange(high, close, low), 14) / close * 100` |
| Strength | latest high/low/close | `(close - low) / (high - low) * 100` |
| SUP/RES | 10-day high/low/close | near 10-day high/low within 2% |

The exact formulas live in `inferno_tos_formula_math.py`; Schwab only supplies
the candles.

## Commands

Fetch price history only:

```bash
./run_inferno_schwab_price_history.sh --from-snapshot --limit 12
```

Fetch price history and publish canonical TOS custom metrics:

```bash
./run_inferno_schwab_tos_metrics_sync.sh --from-snapshot --limit 12
```

Audit whether those metrics are actually useful thesis evidence:

```bash
./run_inferno_tos_metric_theory_audit.sh --limit 12
```

The sync writes:

| Artifact | Purpose |
|---|---|
| `data/inferno_schwab_price_history.json` | Raw normalized Schwab candle summaries and formula mirrors |
| `reports/schwab_price_history_latest.txt` | Operator memo for the history pull |
| `data/inferno_schwab_tos_metrics_sync.json` | Bridge status and counts |
| `reports/schwab_tos_metrics_sync_latest.txt` | Human-readable bridge memo |
| `data/inferno_tos_custom_metrics.json` | Canonical metric artifact already joined by `morning_inferno_pipeline.py` |
| `reports/tos_custom_metrics_latest.txt` | Canonical metric memo |
| `data/inferno_tos_metric_theory_audit.json` | Anti-confirmation review of formula usefulness |
| `reports/tos_metric_theory_audit_latest.txt` | Thesis support/challenge memo |

## Configuration

The runner loads `.env.schwab` and the ignored token vault used by the existing
Schwab OAuth helper. It honors these optional settings:

```bash
SCHWAB_PRICE_HISTORY_ENABLED=1
SCHWAB_PRICE_HISTORY_SYMBOL_LIMIT=12
SCHWAB_PRICE_HISTORY_TIMEOUT_SECONDS=20
```

If `SCHWAB_PRICE_HISTORY_ENABLED` is omitted, the lane falls back to
`SCHWAB_OPTIONS_ENABLED`, so an already-enabled market-data setup keeps working.

## Safety

This is broker market data only. It cannot read account balances, stage trades,
preview orders, submit orders, cancel orders, write Sheets, or click TOS.

## Failure Modes

- `disabled`: market-data env settings are not enabled.
- `not-configured`: no access token was found in the ignored Schwab token vault.
- `partial-error`: at least one ticker produced candles and at least one failed.
- `ok`: live Schwab candles were pulled.
- `fixture`: offline fixture data was used for tests or dry runs.
