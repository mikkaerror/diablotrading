# Model Theory

How the desk thinks. One page. No drift.

## Premise

A durable trading desk is one that can tell the difference between belief and
evidence. Strong opinions are not proof. Good vibes are not authority.

Every action on this desk is gated by evidence quality, a confidence bound, and
an authority manifest. Every artifact is timestamped. Every promotion is earned
by math.

## The operating loop

```
Observe  →  Hypothesise  →  Prove  →  Promote
   ↑                                   │
   └──────────── feedback ─────────────┘
```

### Observe

Ask: what is true right now?

The desk watches the sheet, the brief, the live-book health, and the command
center. If observation is stale, the desk pauses. We do not act on a blind
surface.

### Hypothesise

Ask: what edge might the evidence support?

Research layers turn ideas into testable claims with explicit thresholds and
failure modes. A hypothesis is not a recommendation; it is a candidate for
measurement.

### Prove

Ask: what happened on paper?

Paper tickets, shadow outcomes, and outcome review decide whether a strategy is
actually durable. No paper proof, no promotion.

### Promote

Ask: has the strategy earned more authority?

Authority is computed, not declared. The authority manifest flips only when the
evidence earns it. Today the desk remains pinned to:

```text
authorityLevel: paper-evidence-only
brokerSubmitAllowed: false
liveTradingAllowed: false
```

## Why this works

The architecture is conservative by design:

- same evidence in, same verdict out
- confidence bounds over point estimates
- minimum sample sizes before any claim becomes promotable
- isolated failures instead of global collapse
- atomic writes so partial state does not masquerade as truth

The desk does not become smarter than its evidence. It becomes more honest
about the evidence it has.

## What the model never does

- Place a trade.
- Open a new thinkorswim instance.
- Edit the authority manifest outside the authority controller.
- Promote a strategy by hand.
- Pretend a backtest is proof when the paper loop has not closed.

## Single sentence

Build the desk that survives the math, not the desk that survives the quarter.
