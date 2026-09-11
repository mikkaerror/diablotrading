# Mission Control

Guidelines revised September 10, 2026. Generated reports supply current desk state.

## Mission

Investigate substantial upside in the AI infrastructure cycle and build a desk
that improves decisions after costs. Illustrative contribution forecasts are
not the strategy's return target. The operator's industry knowledge supplies
hypotheses to test using public evidence.

The system researches, ranks, simulates, models sizing and briefs. Agents never
enable live trading or broker submission. Operator decisions remain separate
from automated research.

```text
authorityLevel: paper-evidence-only
brokerSubmitAllowed: false
liveTradingAllowed: false
```

## Current Desk Sources

Use `./inferno status` for the latest summary, the Schwab account artifact for
positions, `reports/paper_evidence_loop_latest.txt` for final paper routing,
and `reports/strategy_lab_latest.txt` for qualified outcomes. Do not carry a
static holdings list, quote-freshness claim or historical sample count forward.

## Strategy Thesis

The operator is bullish on semiconductors, data-center power, cooling,
networking, security, cloud infrastructure and adjacent suppliers.

Apply [Model Research Guidelines](MODEL_RESEARCH_GUIDELINES.md): distinguish
business prospects, stock-price opportunity, trade construction and results.
The following cells are hypotheses; their features require validation.

| Strategy cell | What it investigates | Measurements to test |
|---|---|---|
| Business growth over quarters | Suppliers convert builds into durable earnings | funded demand, capacity delivery, pricing, margins, cash generation, financing |
| Stock opportunity over weeks/months | Growth or leadership exceeds market expectations | valuation scenarios, earnings revisions, relative strength, sector breadth |
| Earnings catalyst | Repricing around a particular event | verified announcement timing, expected versus implied move, session-aware participation |
| Defined-risk options | A priced structure expresses a declared thesis | premium, liquidity, expiration, Greeks, payoff bounds, written exit |
| Share accumulation | Longer-horizon ownership captures the thesis | business quality, valuation and portfolio fit without an expiration deadline |

A 21-day earnings window defines one lane; it is not a universal research
filter. These research cells do not change eligible instruments or tickers.

## What Counts As Edge

A strategy needs later, source-qualified outcomes showing net value and
acceptable downside against a simple baseline. Report uncertainty, costs,
concentration and opportunities missed by the filters. A sample minimum, a
profitable trade, or agreement between scores sharing inputs is insufficient.

Investigate uncertain signals through isolated comparisons. Correct an invalid
measurement; test an unproven modeling choice. Do not preserve a discovery rule
merely because it is conservative or already implemented.

## Data and Authority

Broker artifacts govern account facts. Timestamped tracker and provider data
govern observed inputs. Versioned code and operator-owned configuration govern
runtime rules; documents do not silently replace them. Separate live results,
source-qualified paper fills and exploratory simulations.

- Agents never approve, reject, close or promote operator paper tickets.
- Live broker access remains read-only; previews are not orders.
- Risk constants and eligible universe remain operator-owned.
- No new TOS window from background automation.
- Existing execution gates, defined-risk requirements and written exits remain.
- Backtests and research findings do not grant authority.
- Credentials, broker exports and account artifacts stay out of git.

## Diagnose the Bottleneck

Distinguish missing data, discovery filters, trade economics, routing and
execution authority. An empty queue does not identify which one failed. Keep
priced research visible with its actual route requirements. More shadow rows
cannot substitute for qualified paper evidence.

## Next Build Priorities

1. Correct measurement semantics: session completeness, null/zero handling,
   source dates, payoff arithmetic and independently sourced fills/costs.
2. Trace priced research through the operator workflow without dropping gates.
3. Compare the current model with simple momentum and fundamental/valuation
   baselines over declared horizons, including rejected observations.
4. Test technical features before making them risk-policy requirements; expose
   redundant inputs, clipping and category assumptions.
5. Evaluate net outcomes, downside, benchmark performance and missed winners
   on later observations. Report guideline, code, validation and authority
   status separately.

Codex owns model/risk/tests/docs; Claude owns TOS export stabilization. Shared
work is coordinated through the command center. See [System Map](SYSTEM_MAP.md).
