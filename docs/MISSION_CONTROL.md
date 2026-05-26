# Mission Control

Current as of 2026-05-20.

This is the shortest honest description of the desk. Read this before changing
code, interpreting a signal, opening thinkorswim, or asking another model to
help.

## Mission

Build a disciplined AI-infrastructure trading desk that refreshes data,
identifies asymmetric opportunities, collects paper evidence, and briefs the
operator without granting live trading authority before the math earns it.

The desk is here to create repeatable decision quality. It is not here to make
every morning exciting.

## Operating Principle

Evidence first. Authority second. Execution last.

The system can research, rank, simulate, size, and brief. It cannot submit live
orders unless the authority manifest explicitly permits that future state.

Current posture:

```text
authorityLevel: paper-evidence-only
brokerSubmitAllowed: false
liveTradingAllowed: false
```

## Current Desk Snapshot

Updated 2026-05-20 after the live-position intake pass.

| Lane | Current read |
|---|---|
| Approved account scope | read-only TOS account ending 8499 |
| Live positions captured | IREN, HIVE, TE, CLSK |
| Tracker sync | HIVE, TE, and CLSK appended; IREN already existed; formulas hydrated and audits healthy |
| Fresh capital posture | blocked until fragile live-book issues are reviewed |
| Schwab option tape | IREN paper-ready; CLSK and TE manual-review; HIVE avoid-chain |
| Automation authority | unchanged: research/paper only, no live submit |

## Strategy Thesis

The operator is bullish on the AI infrastructure cycle: semiconductors,
datacenter power, cooling, networking, security, cloud rails, and adjacent
industrial shovel sellers.

The desk should not treat that thesis as permission to chase. It should turn
the thesis into falsifiable strategy cells:

| Strategy cell | What it tries to capture | What must confirm it |
|---|---|---|
| AI infrastructure momentum | Winners keep winning in a real capex cycle | trend, RVOL, support/resistance, sector breadth |
| Earnings catalyst timing | Pre-event repricing before/around earnings | fresh earnings date, readiness, trigger, implied-vs-realized move |
| Defined-risk options | Conviction with known maximum loss | tight spread, liquidity, Greeks, written exit, capped risk |
| Long-term discount buys | Quality names offered at temporary discount | drawdown context, thesis intact, support, fundamental quality |
| Paper scenario slate | More evidence without forcing live trades | timestamped setup, reason code, realized outcome, R-unit score |

## What Counts As Edge

An edge is not a good story. An edge is a rule cell that survives:

1. enough closed outcomes
2. positive expectancy after friction
3. confidence-bound testing
4. walk-forward validation
5. drawdown limits
6. liquidity and slippage checks
7. authority controls

The desk should assume every signal is guilty until evidence proves otherwise.

## Data Authority

| Need | Source of truth | Role |
|---|---|---|
| Universe and tracker columns | Google Earnings Tracker | Strategy source of truth |
| Options chain and quote quality | Schwab API | Primary read-only option market-data source |
| Broker cash, positions, fills | Schwab account API for cash/positions; supervised TOS/fill export for fills | Broker reality check only |
| Prices, ATR, RVOL, support/resistance | Market context layer and tracker scripts | Setup and timing evidence |
| Outcomes | Paper/shadow/live ledgers | Promotion evidence |

If these disagree, generated artifacts win for the trading day, but docs win
for policy.

## Decision Ladder

1. Observe: refresh tracker, Schwab/TOS posture, health checks.
2. Rank: score the universe and identify top candidates.
3. Simulate: build paper/shadow scenarios before forcing live action.
4. Prove: close outcomes and score them in R-units.
5. Size: apply conservative Kelly, risk caps, and concentration gates.
6. Stage: prepare broker-neutral intents.
7. Approve: operator confirms any real-money action.

Skipping a rung means the trade is research-only.

## Hard Boundaries

- No live submit without explicit final operator confirmation.
- No new TOS window from background automation.
- No undefined-risk options while the desk is in early authority phases.
- No stale earnings dates, stale tracker rows, or stale option quotes.
- No trade without a written exit.
- No promotion from backtests alone.
- No credentials, broker exports, or account artifacts in git.

## Current Strategic Bottleneck

The bottleneck is not idea generation. The bottleneck is evidence throughput.

We need more closed paper/shadow outcomes, cleaner quote quality, and tighter
post-trade attribution before the desk can honestly say which rule cells work.

## Next Build Priorities

1. Schwab chain freshness, IV calibration, and quote-quality thresholds inside
   strike selection / risk policy.
2. Support/resistance + RVOL gates as first-class risk-policy inputs.
3. Paper outcome capture throughput so attribution, edge decay, portfolio
   correlation, and drawdown rules have enough closed evidence to judge.
4. Capacity / slippage-decay limits after more closed outcomes exist.
5. Crowdedness/reflexivity v2: /movers, sector ETF vol, VIX term structure,
   and short-interest context after the v1 monitor proves useful.
6. Cleaner two-model workflow: Codex owns repo/risk/tests/docs; Claude owns
   TOS export stabilization; both write concise coordination notes.

## One-Line Strategy

Trade the AI infrastructure cycle only when timing, liquidity, structure,
evidence, and authority all agree.

If they do not agree, collect evidence instead.
