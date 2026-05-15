# Hedge-Fund-Style Metrics For Inferno

This desk is aggressive by design, so the metrics need to punish sloppy
conviction. The goal is not to make every signal look smart. The goal is to
separate repeatable edge from expensive noise.

## Metrics Now Automated

These are produced by:

- [inferno_performance_analytics.py](inferno_performance_analytics.py)
- [inferno_shadow_evidence.py](inferno_shadow_evidence.py)
- [inferno_strategy_lab.py](inferno_strategy_lab.py)
- [inferno_exposure_analytics.py](inferno_exposure_analytics.py)
- [inferno_edge_research.py](inferno_edge_research.py)
- [inferno_authority_controller.py](inferno_authority_controller.py)

Run:

```bash
./run_inferno_performance_analytics.sh
./run_inferno_shadow_evidence.sh
./run_inferno_strategy_lab.sh
./run_inferno_exposure_analytics.sh
./run_inferno_edge_research.sh
./run_inferno_authority_controller.sh
```

Outputs:

- `data/inferno_performance_analytics.json`
- `reports/performance_analytics_latest.txt`
- `data/inferno_strategy_lab.json`
- `reports/strategy_lab_latest.txt`
- `data/inferno_shadow_evidence.json`
- `reports/shadow_evidence_latest.txt`
- `data/inferno_exposure_analytics.json`
- `reports/exposure_analytics_latest.txt`
- `data/inferno_edge_research.json`
- `reports/edge_research_latest.txt`
- `data/inferno_authority_manifest.json`
- `reports/authority_manifest_latest.txt`

### Ticket Quality

- ticket count by status
- block reasons
- false-positive rate by strategy
- strategy-level promotion eligibility
- shadow-only outcome tracking for blocked but valid strike plans

### P/L And Edge

- win rate
- Wilson lower-bound win rate
- average win
- average loss
- payoff ratio
- expectancy
- conservative expectancy-per-risk confidence interval
- expectancy per dollar at risk
- profit factor
- total estimated paper P/L
- strategy-lab promotion verdict and risk-unit cap

### Downside Risk

- max drawdown on cumulative paper P/L
- historical 95% VaR on paper-ticket outcomes
- historical 95% CVaR / expected shortfall
- trade-level Sharpe-like ratio
- trade-level Sortino-like ratio
- informational Kelly fraction

### Liquidity And Execution Quality

- average option-leg spread percentage
- widest option-leg spread percentage
- zero-volume leg count
- zero-open-interest leg count
- liquidity block counts

### Portfolio And Regime Risk

- sector exposure by candidate risk units
- setup concentration by risk units
- high-correlation ticker pairs
- correlation clusters that reveal crowded factor bets
- SPY trend tag
- 20-day realized volatility
- VIX risk tag
- QQQ and IWM 20-day leadership checks

### Online-World Shovel Edge

- AI/compute pick-and-shovel classification
- semiconductor supply-chain classification
- cloud/data rail classification
- cybersecurity toll-booth classification
- ad/attention rail classification
- catalyst trade lane versus long-term accumulation lane

### Automation Authority

- daily maximum authority level
- explicit allowed action list
- explicit blocked action list
- live-submit flag forced false
- broker-submit flag forced false
- next milestones before more authority is reviewed

## Promotion Gates

A strategy does not earn more automation authority unless it clears:

- at least 30 scored paper tickets
- positive expectancy
- profit factor >= 1.25
- false-positive rate <= 45%
- no unresolved doctor warnings
- no live-trading flag surprises
- positive strategy-lab lower-bound edge
- max drawdown no worse than -6 risk units
- strategy-lab risk cap above zero

Shadow evidence is excluded from promotion gates. It is a research-only
counterfactual lane that tells us whether blocked candidates were useful
signals, not whether broker submission should be unlocked.

These gates are intentionally conservative. The system can always recommend
ideas. It must earn the right to automate.

## Next Institutional Metrics

The next layer should add:

- earnings-window bucket performance
- implied move versus realized move
- slippage estimate versus mid
- market-regime tags
- capacity constraints by option volume/open interest
- kill-switch incident log

## Operator Rule

No strategy graduates because it looks cool on one morning.

It graduates when the ledger says:

- it finds enough trades
- it avoids bad liquidity
- it survives drawdown
- it pays for its losers
- it keeps working across multiple market sessions
