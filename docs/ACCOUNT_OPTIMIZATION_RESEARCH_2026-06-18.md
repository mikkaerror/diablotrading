# Account Optimization Research - 2026-06-18

**Stage:** research-only
**Authority:** unchanged; no order staging or broker submit
**Account source:** fresh Schwab read-only sync for approved suffix 8499

## Decision

Treat 10% monthly as a stretch hypothesis, not the desk's operating baseline.
Ten percent compounded monthly is a 213.84% annual return. From the current
$1,600.87 NLV, it would produce about $5,024 after twelve months without
deposits. That arithmetic is correct; assuming it can be repeated is the
unsupported part.

The account should optimize for survival, contribution rate, evidence quality,
and independent risk exposures. The immediate live-options risk budget remains
$0 because the strategy lab has one scored loss, no positive expectancy, and a
zero evidence-based risk cap.

## Current account

| Item | Current value |
|---|---:|
| Net liquidating value | $1,600.87 |
| Cash | $599.93 / 37.47% |
| Invested holdings | $1,000.94 / 62.53% |
| Largest holding, TE | 23.44% |
| Top two holdings, TE + IREN | 38.42% |
| Holdings with fragile model alignment | 4 of 4 |

The four positions are different companies but share material exposure to
capital-intensive power, data-center, AI-compute, and Bitcoin economics. The
portfolio therefore has fewer independent bets than its ticker count implies.

## Why contract size matters

The allocator's current $149.98 starter ticket is 9.37% of total NLV. Three
max-loss tickets would remove 28.10% of the account and require a 39.08% gain
to recover.

| Max loss as % of NLV | NLV needed for a $149.98 ticket |
|---:|---:|
| 0.5% | $29,996 |
| 1.0% | $14,998 |
| 2.0% | $7,499 |
| 5.0% | $3,000 |

This is the practical small-account constraint: even a defined-risk trade can
be oversized when the indivisible contract is large relative to the account.
The next sensible live-options checkpoint is not "cash is available." It is
"the strategy is promotable and one ticket is no more than 2% of NLV."

## Contribution and return scenarios

End-of-month contributions, before taxes and fees:

| Monthly return | No contribution | $500/month |
|---:|---:|---:|
| 0% | $1,601 | $7,601 |
| 1% | $1,804 | $8,145 |
| 2% | $2,030 | $8,736 |
| 5% | $2,875 | $10,834 |
| 10% | $5,024 | $15,716 |

At this account size, contributions are the dominant reliable growth lever.
A $500 monthly contribution adds $6,000 in principal over a year. By
comparison, a very strong 2% monthly return adds about $429 to the original
balance before the contribution gains are counted.

## Current holdings research

### TE

T1 Energy reported $123.7 million of cash and restricted cash at March 31,
2026, including $46.4 million unrestricted. On June 3 it announced the KORE
Power acquisition, 20 GWh of planned storage capacity, and a 5 GWh annual
offtake commitment. This creates a real growth catalyst but also acquisition,
financing, and execution risk. Because TE is already 23.44% of NLV, new cash
should not automatically enlarge it.

Sources:

- [T1 Energy Q1 2026 results](https://ir.t1energy.com/news-releases/news-release-details/t1-energy-reports-first-quarter-2026-results)
- [T1 Energy KORE Power transaction](https://ir.t1energy.com/news-releases/news-release-details/t1-energy-acquire-kore-power-and-expand-us-battery-energy/)

### IREN

IREN's Q3 FY26 materials reported $144.8 million of revenue, a $247.8 million
net loss, and $2.2 billion of cash and cash equivalents. The company is
building a large AI-cloud platform while retaining Bitcoin-mining exposure.
The cash balance supports expansion, but the plan is highly capital intensive
and earnings remain volatile.

Source:

- [IREN Q3 FY26 results](https://iren.com/investors/presentations)

### HIVE

HIVE reported a June 18, 2026 ten-year sovereign AI contract worth roughly
$220 million. It described about $250 million of contracted AI-cloud revenue
including the earlier Bell Canada agreement, with the new deployment expected
to contribute about $24 million of annual recurring revenue at full run rate.
This supports the AI thesis, but deployment milestones, financing, customer
concentration, and Bitcoin sensitivity still matter.

Source:

- [HIVE sovereign AI contract announcement](https://www.hivedigitaltechnologies.com/news/hives-buzz-hpc-closes-usd-220-million-sovereign-ai-gpu-contract-with-bell-ai-fabric-for-cohere-inc/)

### CLSK

CleanSpark reported Q2 FY26 revenue of $181.7 million, a net loss of $185.4
million, $1.18 billion of cash and Bitcoin, and $1.8 billion of debt. It also
reported 26 EH/s of average hashrate. The liquidity is substantial, but so are
leverage and Bitcoin-price exposure.

Source:

- [CleanSpark Q2 FY26 results](https://investors.cleanspark.com/news/news-details/2026/CleanSpark-Reports-Second-Fiscal-Quarter-2026-Results/default.aspx)

## External evidence

- S&P Dow Jones Indices reports that the S&P 500 has produced roughly 10%
  annualized total return since 1957, not 10% monthly. Its historical average
  bear-market decline is about 33%.
  [S&P 500 brochure](https://www.spglobal.com/spdji/en/documents/additional-material/sp-500-brochure.pdf)
- In SPIVA U.S. Year-End 2025, 79% of active large-cap U.S. equity funds
  underperformed the S&P 500 during 2025.
  [SPIVA U.S. Year-End 2025](https://www.spglobal.com/spdji/en/documents/spiva/spiva-us-year-end-2025.pdf)
- Barber and Odean found the most active households earned 11.4% annually
  versus 17.9% for the market in their sample.
  [Trading Is Hazardous to Your Wealth](https://faculty.haas.berkeley.edu/odean/papers/returns/individual_investor_performance_final.pdf)
- FINRA emphasizes that options involve leverage and can lose the entire
  premium; assignment and other obligations can create additional losses
  depending on the structure.
  [FINRA options overview](https://www.finra.org/investors/investing/investment-products/options)
- Investor.gov describes diversification across and within asset categories as
  essential to a long-term investment plan and warns against rash allocation
  changes during volatility.
  [Investor.gov portfolio rebalancing guidance](https://www.investor.gov/additional-resources/spotlight/formerdirectorlorischock-directors-take/it-time-rebalance-your-investment-portfolio)
- Recent academic evidence on retail options is mixed enough that the desk
  should prove its own edge rather than borrow a generic claim.
  [An Anatomy of Retail Option Trading](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4682388)

## Action order

1. Close and score the four fast-paper simulations on Monday, June 22, 2026,
   using later-session Schwab bid/ask quotes.
2. Open the next diversified fast-paper cohort after those slots clear.
3. Keep live options max loss at $0 until the promotion gates pass.
4. Preserve the current cash unless a less-correlated long-term candidate
   clears the thesis and price gates.
5. Use new deposits to dilute concentration instead of automatically adding
   to the largest current holding.
6. Reconcile broker transactions so deposits, realized options profit, and
   share accumulation cannot be double counted.
7. Revisit one-contract live options near $7,500 NLV, and only with promotable
   strategy evidence and max loss at or below 2% of NLV.

The objective is still ambitious compounding. The optimization is to make the
account large enough, and the evidence strong enough, that ambition no longer
requires one contract to carry existential weight.
