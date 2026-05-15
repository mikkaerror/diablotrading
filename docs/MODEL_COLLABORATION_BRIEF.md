# Model Collaboration Brief

The first doc a new model should read before touching the desk.

## Mission

Run a paper-evidence-first earnings and options desk that scores short-term
setups, tracks long-term conviction, and only promotes behavior when the math
earns more authority. The system exists to be honest, not flashy.

## Operating principle

> The desk earns authority by shrinking the gap between belief and evidence.

The loop is simple:

1. **See the state.** Fresh tracker data, brief output, ops health, and live-book
   status tell us what is true right now. If we cannot see it, we do not act on it.
2. **Form a hypothesis.** The research layers turn ideas into testable claims with
   explicit thresholds, confidence bounds, and clear failure modes.
3. **Prove on paper.** Paper tickets, shadow evidence, and outcome review decide
   whether a strategy deserves promotion. No paper proof, no promotion.

Authority is computed, not declared. Today the desk remains pinned to:

```text
authorityLevel: paper-evidence-only
brokerSubmitAllowed: false
liveTradingAllowed: false
```

If that ever changes, it changes because the evidence earned it.

## Safety rails

1. Never place a trade without explicit user confirmation.
2. Only the configured approved live account is approved, and only read-only.
3. Do not open a new thinkorswim instance or extra TOS window.
4. Use the already-open TOS window only.
5. Keep paper evidence as the promotion gate.

If a feature would weaken one of these rails, the feature is wrong.

## What another model should read first

1. `docs/PROJECT_STATUS.md` — current state, priorities, saved truth, next moves.
2. `docs/MODEL_COLLABORATION_BRIEF.md` — mission, operating principle, safety rails.
3. `docs/MODEL_THEORY.md` — how the desk thinks.
4. `docs/MODULE_INDEX.md` — which module owns what.
5. `docs/ENGINEERING_CONVENTIONS.md` — the patterns every new module follows.

After those, use `docs/RUNBOOK.md` for daily operations.

## Bootstrap prompt for another model

```text
You are joining the Inferno Earnings Dashboard at <repo-root>.
Start by reading docs/PROJECT_STATUS.md, docs/MODEL_COLLABORATION_BRIEF.md,
docs/MODEL_THEORY.md, docs/MODULE_INDEX.md, and docs/ENGINEERING_CONVENTIONS.md.
Do not place trades. Do not open a new TOS instance. Only the already-open,
locally configured approved live account is approved, and only for read-only
automation. Paper evidence is the promotion gate. Preserve the health of the desk, keep the math
honest, and ship changes with tests and docstrings.
```
