# AGENTS.md — Inferno agent operating contract

Read `CLAUDE.md`, `docs/SYSTEM_MAP.md`, and the latest command-center report before broad changes.

## Safety boundary

- This repository is research-only unless a human explicitly performs an allowed operator action.
- Never enable `liveTradingAllowed`, `brokerSubmitAllowed`, or `submit_live_order`.
- Never approve, reject, close, or promote a paper ticket for the operator.
- Never change risk constants or the eligible universe autonomously.
- Wealth targets, lifestyle goals, fear, urgency, or emotional distress are context—not authorization to widen risk, bypass evidence, or change authority.
- Autonomous optimization may refresh data, recompute research artifacts, run tests, and improve paper/shadow evidence tooling.

## Model research standard

- Follow `docs/MODEL_RESEARCH_GUIDELINES.md` when evaluating or changing model assumptions.
- Treat discovery scores and technical cutoffs as testable hypotheses, not established probabilities or proof of edge. A guideline may be corrected or retired when its assumptions fail; its age is not evidence for keeping it.
- Separate business prospects, stock-price opportunity, trade construction, and portfolio risk. Evaluate each strategy at its declared horizon; the earnings window is not a universal limit on research.
- Distinguish arithmetic correctness, input quality, predictive value, and execution eligibility. Reused inputs are not independent confirmation; missing observations are not negative evidence.
- Measure missed opportunities as well as selected outcomes using frozen inputs, fixed evaluation rules, and the same eligible universe. Require later data and simple baselines before claiming an improvement.
- Diagnose whether an empty queue comes from data, discovery, economics, routing, or authority. Repair authorized tooling defects; do not interpret every empty queue as either no opportunity or excessive risk limits.
- Research guideline revisions do not change production thresholds, risk constants, universe membership, evaluator code, ticket decisions, or authority. Propose concrete runtime changes separately with measured effects and the applicable operator review.

## Agent-loop standard

- Separate safety, execution, and value gates.
- A clean command is not evidence of progress.
- Use fixed evaluators and record measurable deltas before calling a run productive.
- Keep evaluator and authority code outside any unattended self-modification scope.
- Suppress duplicate work when the meaningful state is unchanged.
- Use bounded adaptive backoff after repeated no-progress runs; skipped checks must not extend the gate indefinitely.
- Record run cost, outcome, blocker, and accepted progress in the loop state and `knowledge/agent-loop/`.
- Track full-run acceptance rate and cost per accepted progress unit; throttle loops that generate activity without accepted outcomes.
- After the same failure or blocker repeats, add a durable rule, test, or deterministic lesson.
- Consolidate recent traces into explicit beliefs with measurable evidence and a falsifier.
- Retrieve only the notes relevant to the current blocker; do not load the whole memory store into context.

## Definition of done

- Focused tests pass.
- The broader relevant test suite passes.
- `git diff --check` is clean.
- Research-only and broker-submit-off invariants remain verified.
- Documentation and the Obsidian-compatible knowledge layer reflect material loop changes.
