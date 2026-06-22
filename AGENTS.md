# AGENTS.md — Inferno agent operating contract

Read `CLAUDE.md`, `docs/SYSTEM_MAP.md`, and the latest command-center report before broad changes.

## Safety boundary

- This repository is research-only unless a human explicitly performs an allowed operator action.
- Never enable `liveTradingAllowed`, `brokerSubmitAllowed`, or `submit_live_order`.
- Never approve, reject, close, or promote a paper ticket for the operator.
- Never change risk constants or the eligible universe autonomously.
- Autonomous optimization may refresh data, recompute research artifacts, run tests, and improve paper/shadow evidence tooling.

## Agent-loop standard

- Separate safety, execution, and value gates.
- A clean command is not evidence of progress.
- Use fixed evaluators and record measurable deltas before calling a run productive.
- Keep evaluator and authority code outside any unattended self-modification scope.
- Suppress duplicate work when the meaningful state is unchanged.
- Use bounded adaptive backoff after repeated no-progress runs; skipped checks must not extend the gate indefinitely.
- Record run cost, outcome, blocker, and accepted progress in the loop state and `knowledge/agent-loop/`.
- After the same failure or blocker repeats, add a durable rule, test, or deterministic lesson.
- Consolidate recent traces into explicit beliefs with measurable evidence and a falsifier.
- Retrieve only the notes relevant to the current blocker; do not load the whole memory store into context.

## Definition of done

- Focused tests pass.
- The broader relevant test suite passes.
- `git diff --check` is clean.
- Research-only and broker-submit-off invariants remain verified.
- Documentation and the Obsidian-compatible knowledge layer reflect material loop changes.
