# Position strategy research, September 10, 2026

Public methodology: [strategy](../../docs/POSITION_STRATEGY_RESEARCH_2026-09-10.md).
The isolated `analyze.py` reads a frozen account snapshot and price histories;
it does not call a broker, update policy, or run in the production pipeline.

Reproduce locally:

```sh
python3 outputs/position-strategy-2026-09-10/analyze.py
python3 -m unittest discover -s tests -p test_portfolio_strategy_research.py -v
```

Inputs and account-specific outputs are intentionally ignored in
`data/portfolio_strategy_2026_09_10/`:

- `account_snapshot.json`: selected fields from read-only account reconciliation.
- `price_history.json`: 17-symbol isolated read-only daily-history response.
- `analysis.json`: input hashes, full calculated metrics and limitations.
- `evidence.md`: positions, stress/size scenarios and dated timing references.

The global history artifact was not replaced with this partial collection.
All 17 series returned 252 observations but ended September 9 despite a
September 10 retrieval. This observation lag is retained explicitly.

Arithmetic checks establish coherent calculations, not predictive edge.
The scenario budgets do not change policy; risk constants, eligible universe,
operator long-term-hold and tracker-role policy remain untouched. Option pairing
only recognizes an unambiguous equal-quantity standard call vertical; unsupported
or additional legs require manual reconciliation rather than inferred netting.
