# Watchlist Metric & Fundamentals Integration Mission (for Codex)

_Filed 2026-08-13 by Claude, from operator request. Two parts; both preserve the
computed-canonical + TOS-cross-check design._

## Context
The operator wants the TOS "semi" watchlist fields wired into the scoring
formulas. The six technical metrics are currently `tos-custom-metrics-diagnostic-only`
and the module's own recommended next-action already says: *"Join values.byTicker
into scoring research and add formula-level regression tests."* This mission does
that, plus adds the fundamental columns the desk doesn't yet use.

## Part A — Promote the 6 technical metrics into scoring
Metrics: **RVOL, Pv52H, MOM, ATR%, Strength, SUP/RES.**
- Wire the desk's **computed (price-history-derived)** values into candidate
  scoring (strike_selector / conviction_research / edge_research where
  appropriate). These stay **canonical** — scoring must NOT depend on a TOS CSV
  export.
- Keep the **TOS values as the anti-confirmation cross-check** via
  `inferno_tos_metric_theory_audit` (support / challenge / contextualize). Do not
  collapse the two — the independence is deliberate.
- Add each metric as a **transparent, documented, rank/discovery-level** input.
  Per the score-threshold audit, keep scores as **rank surfaces, calibrated by
  bucket** — do NOT treat them as probabilities or sizing inputs.
- Add **formula-level regression tests**; math verification must pass.

## Part B — Add the fundamental fields
Fields: **Free Cash Flow, Dividend Yield, market cap, valuation ratios (P/E etc.).**
- Source them from a **stable feed** (Schwab fundamentals or an approved
  financial-data provider) — NOT the one-off TOS CSV, to preserve independence.
  If no stable source exists, treat them as **operator-supplied context /
  cross-check**, not a scheduled-scan dependency, and say so explicitly.
- Wire as screening filters / score context, documented and test-covered.

## Hard constraints
- Research-only. No authority, broker-submit, live-trading, risk-constant,
  promotion-threshold, quality-gate, or eligible-universe change.
  `liveTradingAllowed` / `brokerSubmitAllowed` stay False.
- **Do NOT loosen any quality gate** (reward/risk floor, spread ceilings, premium
  hurdle). This is richer scoring inputs, not relaxed gates.
- Price-history computation stays canonical; TOS values stay the anti-confirmation
  cross-check; no new scheduled dependency on a TOS export.
- Every new input's contribution to a score is documented and covered by a
  formula-level regression test; math verify must pass.

## Definition of done
The six technical metrics feed candidate scoring (computed-canonical, TOS
cross-check intact); the fundamental fields are ingested from a stable source as
documented screening inputs; both are regression-tested; math verify, doctor, and
diff checks pass; no gate/authority/universe changed. Commit per hygiene rules.

## Implementation status — 2026-08-13

Part A now has a deliberately bounded first implementation: normalized,
computed-canonical technical context is attached to the pulse and presented as
a transparent research-ranking surface in edge and conviction artifacts. It
does not alter the existing scores, lanes, strike selector, gates, sizing, or
authority until an outcome-calibration review explicitly authorizes that
separate change. TOS values remain the independent theory-audit cross-check.

Part B remains pending a stable fundamental-data source and its own source,
freshness, and regression-test contract. A one-off TOS screenshot is not a
substitute for that source.
