# TOS Formula Mirror

This document is the local, testable mirror for the tracker formulas we
currently treat as TOS-style custom columns: RVOL, trend, support,
resistance, momentum, and strength.

User-authored ThinkScript columns from TOS have a separate capture lane in
[TOS_CUSTOM_METRICS.md](TOS_CUSTOM_METRICS.md). Those metrics are treated as
TOS-native until their exact ThinkScript source is pasted into the registry.

The contract is deliberately conservative:

- TOS remains a great visual and trade-entry surface.
- Schwab/API plus local math become the automation source.
- Exact ThinkScript can be pasted here later and mapped line by line.
- The mirror is read-only and cannot stage, approve, or place trades.

## Ownership

| Surface | Module | Artifact |
|---|---|---|
| Pure formulas | `inferno_tos_formula_math.py` | import-only |
| Drift audit | `inferno_tos_formula_audit.py` | `reports/tos_formula_audit_latest.txt` |
| Pipeline wrapper | `morning_inferno_pipeline.py` | `data/latest_snapshot.json` market context |

Run:

```bash
./run_inferno_tos_formula_audit.sh --limit 20
```

## RVOL

Current formula:

```text
rvol = volume_t / mean(volume_(t-1) ... volume_(t-n))
```

Defaults:

- `n = 20`
- the latest bar is excluded from the baseline
- at least 6 usable volume bars are required
- missing/zero baseline returns `N/A`

Buckets:

| RVOL | Bucket |
|---:|---|
| `>= 2.0` | surge |
| `>= 1.4` | active |
| `>= 1.0` | normal |
| `>= 0.7` | quiet |
| `< 0.7` | thin |

## Trend

The history-based trend mirror uses close, SMA20, SMA50, and recent SMA20
slope:

```text
if price >= sma20 >= sma50 and sma20 >= sma20_5_bars_ago:
    Bullish
elif price <= sma20 <= sma50 and sma20 <= sma20_5_bars_ago:
    Bearish
elif price > sma20:
    Uptrend
elif abs(price - sma20) / price <= 0.03:
    Basing
else:
    Neutral
```

Tone mapping:

| Label | Tone |
|---|---|
| Bullish, Uptrend, Breakout | hot |
| Bearish, Downtrend, Breakdown | cold |
| everything else | wild |

## Support And Resistance

History-based levels use the recent 20-bar range:

```text
support = min(low over trailing 20 bars)
resistance = max(high over trailing 20 bars)
range_width = resistance - support
```

Tracker-row fallback uses ATR if history is absent:

```text
range_width = max(atr20_day, price * atr_percent / 100, price * 0.02)
support = max(0, price - range_width)
resistance = price + range_width
```

## Tracker Scores

The current U:Y score formulas are mirrored separately from price momentum.
This is the important semantic split exposed by the first audit pass.

```text
value_score = confidence * (iv_rank / 100) * (abs(atr_z_score) + 1)
momentum_score = max(0, iv_rank_change)
squeeze_score = max(0, -atr_z_score)
ready_score = value_score if signal_trigger and setup_rec != "Avoid" else 0
priority = value_score + momentum_score + squeeze_score + ready_score
```

In other words, the current tracker `Momentum Score` is IV-rank momentum,
not price momentum. The price-based calculation below is kept as a richer
research signal and feeds the strength composite.

## Price Momentum

Price momentum is a tracker-scale `0.0` to `2.5` score derived from a
multi-horizon return stack.

Returns:

```text
roc_n = close_t / close_(t-n) - 1
weighted_return_pct = roc5 * 0.25 + roc20 * 0.45 + roc60 * 0.30
acceleration_pct = roc5 - (roc20 * 5 / 20)
atr_multiple = weighted_return_pct / max(atr_percent, 1)
```

Score:

```text
base = 1.25
trend_bonus = +0.25 hot, +0.05 wild, -0.25 cold
momentum_score = clamp(base + atr_multiple * 0.18 + acceleration_pct * 0.035 + trend_bonus, 0, 2.5)
momentum_score_100 = momentum_score / 2.5 * 100
```

This is intentionally not a buy signal by itself. It answers a narrower
question: "Is price movement strong enough, relative to its own realized
range, to deserve extra attention?"

## Strength

Strength is a `0` to `100` composite that adds participation and relative
performance to momentum:

```text
relative_strength_pct = symbol_weighted_return_pct - benchmark_weighted_return_pct
relative_score = clamp(50 + relative_strength_pct * 2, 0, 100)
participation_score = rvol bucket score
strength = momentum_score_100 * 0.35
         + relative_score * 0.25
         + trend_score * 0.20
         + participation_score * 0.20
```

Trend scores:

| Trend | Score |
|---|---:|
| Bullish, Breakout | 86 |
| Uptrend | 76 |
| Basing, Range | 58 |
| Neutral | 50 |
| Downtrend | 28 |
| Bearish, Breakdown | 18 |

Strength labels:

| Score | Label |
|---:|---|
| `>= 72` | leader |
| `>= 58` | improving |
| `>= 45` | neutral |
| `< 45` | lagging |

## Drift Audit

`inferno_tos_formula_audit.py` compares the tracker snapshot against the
formula mirror.

Flags:

| Flag | Trigger |
|---|---|
| `rvol-drift` | absolute RVOL delta greater than `0.35` |
| `trend-mismatch` | tracker trend label differs from calculated label |
| `support-drift` | support level delta greater than `3%` |
| `resistance-drift` | resistance level delta greater than `3%` |
| `momentum-drift` | tracker Momentum Score differs from `max(0, iv_rank_change)` by more than `0.45` |

Verdicts:

| Verdict | Meaning |
|---|---|
| `formula-sync-clean` | checked rows had no drift flags |
| `formula-drift-review` | at least one row needs formula review |
| `insufficient-history` | selected rows could not be calculated |
| `insufficient-data` | no selected rows were available |

## Exact TOS Crosswalk

Paste current TOS custom-column formulas here when available. We will map
each ThinkScript expression to the pure Python mirror and add a regression
test before changing the live tracker behavior.

| TOS column | ThinkScript source | Local mirror |
|---|---|---|
| RVOL | `volume / Average(volume, 30)` | `tosCustomFormulaMirror.tos_rvol`; observed `tosCustomMetrics.tos_rvol` |
| Pv52H | `close / Highest(high, 252) * 100` | `tosCustomFormulaMirror.tos_pv52h`; observed `tosCustomMetrics.tos_pv52h` |
| MOM | `close - Average(close, 10)` | `tosCustomFormulaMirror.tos_momentum`; observed `tosCustomMetrics.tos_momentum` |
| ATR% | `Average(TrueRange(high, close, low), 14) / close * 100` | `tosCustomFormulaMirror.tos_atr_percent`; observed `tosCustomMetrics.tos_atr_percent` |
| Str... | `(close - low) / (high - low) * 100` | `tosCustomFormulaMirror.tos_strength`; observed `tosCustomMetrics.tos_strength` |
| SUP/RES * | within 2% of trailing 10-bar high/low, else Neutral | `tosCustomFormulaMirror.tos_support_resistance_state`; observed `tosCustomMetrics.tos_support_resistance_state` |
| Trend | pending exact formula | `trend_descriptor_from_history()` |
| Support | pending exact formula | `support_resistance_from_history()` |
| Resistance | pending exact formula | `support_resistance_from_history()` |
| Momentum Score | `MAX(0, IV Rank Change)` | `tracker_score_snapshot_from_row()` |
| Price Momentum | pending exact formula if one exists | `momentum_snapshot()` |
