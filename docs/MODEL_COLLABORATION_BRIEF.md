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

## Paper Automation Distinction

The desk may auto-select simulated paper candidates and research variants for
operator review. Unattended agents must not stage, approve, reject, close, or
promote paper tickets. Live orders remain explicit-confirmation only until
closed paper outcomes earn promotion through the authority controller.

## What another model should read first

Before reading docs, refresh the compact handoff surface:

```bash
./inferno status
./inferno usage
```

Then read the generated usage packet first. It exists specifically to keep
Codex and Claude from spending context on stale chat history.

1. `reports/usage_optimizer_latest.txt` — smallest safe read list and do-not-paste list.
2. `reports/model_command_center_onboard_latest.txt` — compact command-center digest.
3. `reports/central_command_latest.txt` — supervisor verdict and headline metrics.
4. `docs/SYSTEM_MAP.md` — one-page architecture, ownership map, and safety stack.
5. `docs/PROJECT_STATUS.md` — stable PM snapshot.
6. `docs/MODEL_COLLABORATION_BRIEF.md` — mission, operating principle, safety rails.

After those, read `reports/model_command_center_latest.txt` before broad
changes or when you need the full report map. Use `docs/RUNBOOK.md`,
`docs/MODEL_THEORY.md`, `docs/MODULE_INDEX.md`, and
`docs/ENGINEERING_CONVENTIONS.md` only when the task needs implementation
depth.

## Bootstrap prompt for another model

```text
You are joining the Inferno Earnings Dashboard at <repo-root>.
Start by running ./inferno status and ./inferno usage.
Then read reports/usage_optimizer_latest.txt, reports/model_command_center_onboard_latest.txt,
reports/central_command_latest.txt, docs/SYSTEM_MAP.md, docs/PROJECT_STATUS.md,
and docs/MODEL_COLLABORATION_BRIEF.md.
Do not place trades. Do not open a new TOS instance. Only the already-open,
locally configured approved live account is approved, and only for read-only
automation. Paper evidence is the promotion gate. Preserve the health of the desk, keep the math
honest, and ship changes with tests and docstrings.
```
