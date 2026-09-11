# Supplier/developer valuation companion

Read [the interpretation](../../docs/SUPPLIER_DEVELOPER_VALUATION_2026-09-10.md).
`assumptions.json` separates reported facts, dated reference prices and invented
scenario inputs. Source URLs and periods are retained. Only public market data
are included; no account holdings or buying power are stored here.

From the repository root:

```sh
python3 outputs/valuation-scenarios-2026-09-10/calculate.py
python3 -m unittest discover -s outputs/valuation-scenarios-2026-09-10 -p 'test_*.py' -v
```

The standard-library script writes `results.json` and `scenario-tables.md`
beside itself. It imports no application, network or broker code. Four checks
pass. All values are USD; IREN operating/balance values are millions of dollars
and shares are millions. ANET EPS and prices are dollars per share.

Three years is an illustrative common holding period. Returns are terminal
price changes before distributions, taxes and transaction costs. No annualized
expected return, case likelihood, executable quote or option valuation is
claimed. Scenario multiples and growth/margin/replacement assumptions are not
calibrated. Terminal debt/share assumptions are not a construction financing
schedule; the model must not be used as one.

The historical IREN book net-debt bridge uses June 30 balances and excludes
restricted cash. It is not current enterprise value: the price and reported
share count have different later dates, and debt carrying values may differ
from principal. It is not used as the future scenario debt balance. Deferred
revenue remains an operating obligation; the one-item cash-flow adjustment is
not a complete working-capital normalization. Future issuance proceeds, debt
conversions and construction spending need an integrated schedule before
claiming the terminal capital structure is feasible.
