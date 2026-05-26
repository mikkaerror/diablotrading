# TOS Custom Metrics

This is the lane for the special ThinkScript-coded metrics created inside
thinkorswim.

The important rule: these are **not** generic local proxies. A custom metric is
accounted for only when we have one or both of:

- the exact ThinkScript formula source from the TOS column settings
- a fresh TOS export containing the metric's current values by ticker
- a Schwab price-history recomputation for formulas that use only OHLCV data

## Current Artifacts

| Artifact | Purpose |
|---|---|
| `data/tos_custom_metric_registry.json` | User-editable registry for exact ThinkScript formulas and aliases |
| `data/inferno_tos_custom_metrics.json` | Latest captured TOS custom values by ticker |
| `reports/tos_custom_metrics_latest.txt` | Operator memo with gaps and next actions |
| `data/inferno_schwab_price_history.json` | Schwab daily candle source used for OHLCV-derived metrics |
| `reports/schwab_tos_metrics_sync_latest.txt` | Bridge memo for Schwab-derived TOS metric sync |
| `reports/tos_metric_theory_audit_latest.txt` | Anti-confirmation audit for formula usefulness |

Run once to create the editable registry template:

```bash
./run_inferno_tos_custom_metrics.sh --init-registry
```

To pull the exact ThinkScript source from the local TOS custom quote cache:

```bash
./run_inferno_tos_custom_metrics.sh --init-registry --pull-formulas-from-cache
```

Then review `data/tos_custom_metric_registry.json`. If TOS has a newer formula
than the local cache, paste the fresh source into the relevant `thinkScript`
field.

## Capturing Values From Schwab

For the six screenshot metrics, Schwab daily candles can replace the manual TOS
value export because the formulas need only high, low, close, and volume:

```bash
./run_inferno_schwab_tos_metrics_sync.sh --from-snapshot --limit 12
```

That runner:

- pulls daily candles from Schwab price history
- recomputes RVOL, Pv52H, MOM, ATR%, Strength, and SUP/RES
- writes the canonical `data/inferno_tos_custom_metrics.json` artifact
- leaves order, account, Sheet, queue, and TOS UI authority untouched

Use `docs/SCHWAB_PRICE_HISTORY.md` for the endpoint lane and configuration.

After the sync, run:

```bash
./run_inferno_tos_metric_theory_audit.sh --limit 12
```

That audit is deliberately skeptical. It keeps exact TOS values visible, but
adds companion features such as prior-30 RVOL, ATR-normalized momentum, and
5-day close location so the model can record support and contradiction instead
of treating color-coded cells as automatic confirmation.

## Capturing Values From TOS

Export the TOS watchlist or custom quote table to CSV, then run:

```bash
./run_inferno_tos_custom_metrics.sh --values-csv "/path/to/tos-export.csv"
```

The importer:

- finds the ticker column from `Ticker`, `Symbol`, `Underlying`, or `Instrument`
- maps the visible TOS headers `RVOL`, `Pv52H`, `MOM`, `ATR%`, `Str...`,
  and `SUP/RES *`
- preserves unmapped custom columns instead of discarding them
- writes ticker-keyed values under `values.byTicker`

No broker, Sheet, TOS UI, queue, or staging writes occur.

## Model Join

`morning_inferno_pipeline.py` now joins captured custom metric values by ticker
when building `data/latest_snapshot.json`.

Rows receive:

```json
{
  "tosCustomMetrics": {
    "tos_rvol": {
      "raw": "0.62",
      "value": 0.62,
      "sourceColumn": "TOS RVOL",
      "formulaStatus": "recomputed-from-schwab-price-history",
      "hasThinkScript": true,
      "source": "schwab-price-history"
    },
    "tos_support_resistance_state": {
      "raw": "Neutral",
      "value": null,
      "sourceColumn": "SUP/RES *",
      "formulaStatus": "needs-thinkscript-source",
      "hasThinkScript": false
    }
  }
}
```

The same payload is also copied into `marketContext.tosCustomMetrics`, with
`marketContext.tosCustomMetricSourceStatus` set to `captured` or `missing`.
The model also receives `tosCustomSignalSummary`, a conservative observed-only
summary:

```json
{
  "sourceStatus": "captured",
  "observedOnly": true,
  "formulaReproduced": true,
  "rvol": 1.61,
  "rvolBand": "active",
  "pv52h": 71.1,
  "momentum": 11.88,
  "momentumSign": "positive",
  "atrPercent": 4.3,
  "strength": 80.9,
  "strengthBand": "strong",
  "supportResistanceState": "Near..."
}
```

These summary bands are for visibility and research features only. They do not
change trade gates until the ThinkScript formula and outcome calibration are
explicitly reviewed.

## Formula Registry

Each registry item should include:

```json
{
  "key": "tos_strength",
  "displayName": "TOS Strength",
  "aliases": ["Strength", "STR", "Inferno Strength"],
  "modelRole": "confirmation-strength",
  "formulaStatus": "captured",
  "thinkScript": "plot Strength = ...;",
  "notes": "What this metric is intended to prove or disprove."
}
```

Use `formulaStatus: "needs-thinkscript-source"` until the exact TOS formula
has been pasted. Values can still be captured before formulas are known, but
the report will call that out as incomplete.

Current visible TOS metric keys:

| Screenshot header | Registry key | Model role |
|---|---|---|
| `RVOL` | `tos_rvol` | participation |
| `Pv52H` | `tos_pv52h` | 52-week-high proximity |
| `MOM` | `tos_momentum` | directional momentum |
| `ATR%` | `tos_atr_percent` | realized range percent |
| `Str...` | `tos_strength` | confirmation strength |
| `SUP/RES *` | `tos_support_resistance_state` | support/resistance state |

The current cache pull also discovered `Earnings Date` and `OptionsScanv4`.
Those are preserved as `tos_earnings_date` and `tos_optionsscanv4` until their
model roles are reviewed.

`inferno_tos_formula_math.py` mirrors the six screenshot formulas from OHLCV
history and exposes them as `marketContext.tosCustomFormulaMirror`. The Schwab
sync runner uses that same formula code, then publishes the result through the
custom-metrics artifact the model already joins into tracker rows.

## Relationship To Formula Mirror

`docs/TOS_FORMULA_MIRROR.md` covers local mirrors and tracker formulas.
This document covers user-authored ThinkScript metrics that live in TOS.

If a TOS metric has an exact local equivalent, document the mapping in both
places and add a regression test using one known input/output sample.
