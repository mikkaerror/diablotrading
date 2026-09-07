# Entry economics cleanup — 2026-09-07

The valuation and exit reports now use one pure entry calculation instead of
maintaining separate copies. This removes a source of disagreement after paper
fills or quantities are corrected.

## Corrections

- A valid recorded debit fill establishes its paid cost even if the original
  planning price is missing. The old planning-based maximum profit remains
  unknown when it cannot be reconciled.
- Invalid contract counts or corrupt fills cannot produce dollar targets or
  risk estimates using an implicit one-contract fallback.
- The management summary displays the actual entry price and adjusted maximum
  loss/profit, with the planning limit and price source retained separately.
- Exit economics do not inherit potentially stale denominators from a mark.
  Known mismatches in entry price, quantity, debit/credit type or payoff bounds
  block price-triggered advice until the mark is rebuilt.
- A rejected mark retains its original fetch status, timestamp and explicit
  rejection reasons. Calendar rules still operate from dated evidence.
- Negative or nonfinite adjusted payoff bounds remain unknown and carry a
  diagnostic reason; they are not silently clipped to zero risk.

The shared function is `inferno_trade_evidence.entry_economics`, used by
`inferno_paper_mark_to_market` and `inferno_trade_management`. It performs no
file writes or authority decisions. Existing report/doctor integration remains
in place. The score-threshold audit receives the same economics through its
existing exit diagnostic.

This is accounting and reporting maintenance. Existing exit percentages, risk
constants, eligible universe, paper ticket states and broker authority are
unchanged. Detecting a known entry-basis mismatch does not certify freshness
for a mark that lacks metadata. Complete quote-path evidence and prospective
event-grouped evaluation remain necessary before judging an exit strategy.

Validation is recorded in `data/inferno_entry_economics_cleanup_run.json` and
[[Entry Exit Economics Contract]]. No promotion progress is claimed.

Validation: 91 focused and 2,023 full-suite tests pass; all 12 math artifacts,
secret hygiene and diff whitespace checks pass. Running the old and new pure
exit helpers on identical September 7 pricing inputs leaves all target/stop/
risk amounts unchanged across 12 priced structures. Doctor reports 11 existing
operational attention items with broker submission off. Concurrent chain and
cap-fit work is separate from this accounting cleanup.
