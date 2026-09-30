# Friction model: diagnose the accounting basis before changing the formula

Status: **research comparison complete; runtime adoption not approved**.
Owner: Codex; independent review: Claude; operator decision: Mikka.
Mission: `mission-1d80e7de`. No risk, prereg, ledger, fill or evaluator was changed.

## Finding and recommendation

The net-premium × ATM-spread formula is a poor description of the legs' quoted
half-spread. The five comparable paper call-debit-spread rows reproduce Claude's
**2.93×** median quote-cost/model-cost ratio. However, this is a quote arithmetic
comparison, not measured execution slippage or proof that P/L is overstated.

**Do not adopt a blanket additional entry charge.** Every one of the 104 paper
rows with valid leg quotes already has `entryLimit` equal to natural price.
That embeds entry spread cost in premium and expiration P/L. Replacing an extra
charge with leg half-spread still double-counts the same entry cost. The model
needs explicit P/L basis and charged-versus-embedded costs before a runtime repair.

A second defect is separate: the scenario backtest reads saved
`outcome.estimatedReturnOnRisk` (or raw estimated P/L/risk), not the friction field.
An in-memory replay changing only `estimatedTotalSpreadFrictionDollars` leaves
**all 12 scenario scorecards unchanged**. A friction-field-only patch cannot
make those scorecards cost-consistent.

## Frozen population and quality

Inputs were copied with SHA-256 hashes under
`outputs/friction-proposal-2026-09-30/inputs/`; protocol and manifest were saved
before computing comparison results. Paper last-success stamp: September 30
09:10:09 Mountain; shadow: 09:10:31. Their old top-level generatedAt values are
creation dates, not current observation freshness.

| Check | Paper | Shadow |
|---|---:|---:|
| Records | 112 | 1,534 |
| Closed records | 3 | 1,025 |
| Complete valid leg quotes | 104 (92.9%) | 1,188 (77.4%) |
| Missing legs | 8 | 346 |
| Duplicate / missing ticket IDs | 0 / 0 | 0 / 0 |
| Entry equal to natural | 104 / 104 | 1,182 / 1,188 |
| Recorded execution excluded from hypothetical rescoring | 1 | 0 |

The DELL recorded execution is preserved. The two other closed paper rows are
estimates, not qualified fills. Shadow closes never gain promotion credit.

Of 382 shadow call-debit-spread records, 287 are closed with usable leg quotes;
4 have invalid risk or inconsistent return data and stay out of the comparable
R population. The remaining **283 rows represent 47 ticker/expiration proxy
groups**, not 283 independent earnings events. All 47 lack explicit event IDs;
no independent-event confidence interval or predictive edge is claimed.
Missing quantity uses the legacy one-contract convention and is recorded per row.
Prices are historical saved entry quotes, not synchronized exit quotes.

Severity/confidence: **high/high** for embedded-entry double counting and bypassed
backtest friction; **high/high** for incomplete quotes and repeated event proxies
limiting adoption; **medium/high** for 4 unusable spread risk/return records.
The minimum remediation is explicit cost basis, historical contract identity and
exit quotes, plus tests for costs already embedded in fills/limits.

## Literal extra-charge sensitivity — not corrected P/L

The frozen challenger sums `(ask − bid) / 2 × 100 × leg quantity`, using the
existing crossing count or existing exit-rule mapping. Complete quotes are
required. Missing/invalid inputs are unknown, never zero. Existing explicit
outcome fees take precedence. Actual recorded executions are not rescored.

The table deliberately shows what a naive additional charge would do. Because
natural entries already include entry spread, **these are stress estimates and
must not replace any official outcome or be presented as measured returns**.

| Comparable shadow call spreads (same 283 rows) | Positive rows | Mean R |
|---|---:|---:|
| Saved raw estimated P/L | 53 | −0.6435 |
| Current normalized-outcome helper | 52 | −0.6785 |
| Literal extra leg-cost charge | 25 | −1.0434 |

25 of 53 raw winners remain positive under the literal stress; the full row list,
including losses, is in `comparison.json`. Equal-weighting the 47 proxy-group
means yields −1.0084R under that stress; five group means are positive. This
changes neither ticket eligibility nor the existing answered-family rules.
The two closed paper estimates remain losers; there are no paper estimate winners
to preserve in this comparison.

For the full scenario replay, source records without comparable data retain their
saved outcomes, so this is a **partial-coverage sensitivity**, not a corrected
backtest. Population size is preserved. QCOM changes from supportive to mixed:
15 observations, mean R 0.1861 → 0.1404 under the unchanged descriptive thresholds.
No live/paper action follows from that label. The result concerns its scenario
comparison population, not a newly validated call-spread edge.

The two current paper iron-fly rows yield a 2.74× quote/model ratio in this frozen
snapshot. Claude's earlier report showed 3.74×; its source preceded the 09:10
ledger refresh. These are different saved observations, not independent fills.

## Concrete runtime design for peer/operator review

1. Store quoted leg half-spread as an informational estimate, with quantity,
   multiplier, quote timestamps, source and missingness. Preserve the ATM fallback
   as explicitly labeled low-coverage context; it is not a substitute for leg facts.
2. Record `pnlBasis`: midpoint simulation, natural-entry simulation, actual-fill
   P/L or intrinsic proxy. Separate `entryCostEmbedded`, charged entry cost,
   exit cost and explicit fees. Never subtract actual-fill slippage twice.
3. For natural-entry intrinsic proxies, additional entry spread cost is zero;
   intrinsic settlement is not a market exit. Assignment/exercise costs remain
   unknown without evidence. For a market exit, use actual exit fills or a saved
   exit bid/ask estimate, not an assumed copy of entry spreads.
4. Version the research economics. Keep old outcomes and both scorecards visible;
   do not rewrite prereg evidence or silently change strategy-family routing.
5. After Claude reviews a concrete implementation and Mikka approves it under
   `CLAUDE.md §8`, adopt prospectively. Re-run fixed comparisons and report
   coverage, not only better-looking winners. Existing preregs require their own
   version/approval process before any change to their rules.

Falsifiers: a fixture charges natural entry twice; changing an economics version
leaves the intended net scorecard unchanged; an actual fill is overwritten;
missing quote/risk data alters the comparable population; or a shadow row gains
qualification. Any is a failed implementation, not a reason to tune a threshold.

## Reproduce and verify

```bash
python3 -m unittest tests.test_friction_proposal
python3 -m research.friction_proposal \
  --inputs outputs/friction-proposal-2026-09-30/inputs \
  --output outputs/friction-proposal-2026-09-30
```

Seven focused regressions cover leg quantities, zero/invalid quotes, exact natural
entry, unchanged actual executions, explicit cost precedence, fixed populations,
and the friction-field/backtest disconnect. The script validates frozen input
hashes and writes only to its explicit research output directory. Full source
verification is recorded separately in the command-center note.

Controlling sources: `inferno_paper_execution.py::paper_fill_friction_model`,
`inferno_strike_selector.py` construction prices, `inferno_trade_evidence.py`
normalization, `inferno_scenario_backtest.py::outcome_r`, and the frozen ledger
manifest. Repeated row counts and changed cost assumptions are not accepted
paper outcomes or proof of positive expectancy.
