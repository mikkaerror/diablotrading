# Agent-loop optimization research

Date: June 22, 2026

## Conclusion

The highest-leverage change is to treat the automation as a measured control system, not a scheduled script.

The loop should:

1. observe a compact state;
2. run only when useful work is eligible;
3. act inside a bounded authority scope;
4. evaluate outcomes with fixed graders;
5. keep productive changes and classify maintenance/no-ops honestly;
6. store concise episodic memory and durable lessons;
7. use those lessons to shape the next bounded experiment.

For Inferno, “the commands ran” is not success. The primary objective is verified evidence velocity. Safety and artifact freshness are mandatory gates, but neither is evidence gain.

## What the strongest systems have in common

### Trigger, process, verification, stop, and memory

CyrilXBT’s article
[“Loops: The Quiet Skill Behind Every AI System That Actually Scales in 2026”](https://x.com/cyrilXBT/status/2068850474384609543)
frames loop engineering as five practical concerns: explicit triggers, narrowly
scoped process steps, structurally separate verification, bounded stop and
escalation states, and memory across cycles. Its most useful additions to this
implementation are dynamic intervals, periodic consolidation, explicit
falsifiable belief tracking, and the warning that skipped checks must not
silently become unbounded retries.

The article also contains current vendor and benchmark claims that are not
needed for the architecture decision and were not treated as evaluator inputs.
The loop adopts the mechanisms that can be independently tested in this
repository.

### Economic eligibility and comprehension control

Codez’s
[“Loop engineering: the 14-step roadmap from prompter to loop designer”](https://x.com/0xCodez/status/2064374643729773029)
adds a useful precondition test: the task should repeat, bad output must be
machine-rejectable, resource use must be bounded, and the agent must be able to
run what it changes. It also argues that cost per accepted change matters more
than scheduled runs or attempted work.

The core framing is consistent with Addy Osmani’s primary
[loop-engineering essay](https://addyosmani.com/blog/loop-engineering/) and
Anthropic’s measured warning that increased code volume is not equivalent to
the same increase in productivity in
[“When AI builds itself”](https://www.anthropic.com/institute/recursive-self-improvement).

Applied here:

- every run records whether the automation still passes its eligibility and
  governance conditions;
- skipped invocations do not inflate full-run acceptance metrics;
- the rolling window records full-run acceptance rate, total run seconds, and
  seconds per accepted progress point;
- fewer than three full runs is labeled insufficient evidence;
- below 50% accepted full runs is labeled inefficient and keeps adaptive
  throttling active;
- authority permissions are re-audited every run, which is stricter than a
  monthly permission review;
- lifestyle goals and emotional urgency cannot alter authority, risk policy,
  or evidence standards.

The article’s broad security statistics and third-party tool claims were not
used as evaluator inputs because they were unnecessary to implement the
testable controls.

### June 23 quant-loop application

Roan's June 23, 2026 X post and linked article
[“How To Use Loop Engineering To Build A Self-Improving Quant Trading System”](https://x.com/RohOnChain/article/2069056530960490835)
adds a useful implementation pressure: keep the trading loop scoped to a small
strategy surface, make signal generation and verification separate stages, and
use hard stop criteria rather than model self-judgment.

Applied here, the evidence goal loop now includes the universe cap-fit audit
and paper-test director in the scheduled cycle. That turns candidate discovery
into a verified loop stage instead of a separate ad hoc report. The value
grader still refuses to count command success or artifact refresh as progress;
it accepts only measurable paper-candidate discovery, hard-blocker reduction,
closed exploratory evidence, or scored paper outcomes.

### June 24 swarm application

Moonshot/Kimi's K2.5 Agent Swarm work adds one useful principle for this desk:
parallelism is only valuable when the orchestrator decomposes real independent
work, each lane finishes, and the outcome reward stays tied to the end goal.
The relevant reward split is:

- coverage/instantiation reward: avoid collapsing back to one serial pass;
- finish reward: avoid spawning pseudo-lanes that do not return verdicts;
- outcome reward: count only whether the end goal actually improved.

Inferno now applies that to paper evidence as `inferno_paper_blocker_swarm.py`.
It is not a trading swarm. It is a blocker-diagnostic swarm over the paper
director's blocked candidates. Lanes separately classify operator approval,
data freshness, liquidity, strike construction, premium/evidence hurdles,
capital fit, bounded fallback structures, and concentration/process warnings.
The command center and doctor surface the result, while the evidence goal loop
still awards accepted progress only for external fixed-evaluator deltas.

Current application to the live paper bottleneck: MEI is not blocked because
the universe is too expensive. The cap-fit audit says bounded structures fit.
The blocker swarm instead separates the actionable research path: refresh the
divergent tracker/Schwab data, keep poor quote-quality chains out of staging,
and audit current-cap bounded alternatives without changing risk constants,
the eligible universe, approval state, or broker authority.

### Fixed evaluators and keep/discard discipline

Andrej Karpathy’s [autoresearch](https://github.com/karpathy/autoresearch) constrains the agent to a narrow editable surface, a fixed time budget, and a ground-truth metric. Its operating instructions establish a baseline, log every experiment, keep improvements, and discard regressions. The evaluator is not part of the agent’s editable scope.

That is the correct pattern for future self-improvement here:

- immutable authority and evaluation code;
- narrow candidate patch scope;
- fixed tests and scorecard;
- isolated experiment;
- keep only verified improvement;
- retain a complete experiment ledger.

### Evaluator-driven search with retained candidates

DeepMind’s [AlphaEvolve](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/) combines model-generated programs, automated evaluators, and an evolutionary database of prior candidates. The important general mechanism is not unconstrained self-editing. It is broad proposal generation followed by objective evaluation and selective retention.

Inferno should eventually use the same shape in a safer lane: generate candidate loop patches in isolated worktrees, test them against immutable safety and value evals, and retain only improvements. Production trading and broker authority remain outside that optimizer.

### Explicit handoffs and incremental progress

Anthropic’s [effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) emphasizes structured task state, incremental progress, end-to-end verification, progress notes, and leaving a clean handoff for the next context window. This supports a run ledger plus compact current-state note rather than relying on conversational memory.

### Context is a scarce resource

Anthropic’s [context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) recommends small, high-signal context, just-in-time retrieval, structured notes, and compaction. Loading every past run into every prompt creates context rot. The correct memory design is:

- structured properties for filtering;
- links between current state, blockers, principles, and lessons;
- compact rolling metrics;
- retrieval of only the lesson related to the current blocker.

### Outcome-oriented evals

Anthropic’s [agent eval guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) distinguishes tasks, trials, and graders; favors outcome grading over brittle path matching; recommends deterministic graders where possible; and warns about evaluator bugs and reward hacking.

Inferno therefore needs separate graders:

- safety grader: authority and process invariants;
- execution grader: commands and artifact freshness;
- value grader: accepted evidence and blocker deltas;
- efficiency grader: duration, command count, and productive-run rate.

### Interfaces shape agent performance

[SWE-agent](https://arxiv.org/abs/2405.15793) shows that the agent-computer interface materially affects coding performance. The implication is practical: give the optimizer narrow commands and explicit observables rather than an unconstrained shell objective.

[Reflexion](https://arxiv.org/abs/2303.11366) and [Self-Refine](https://arxiv.org/abs/2303.17651) show the value of iterative feedback and retained reflection. In production automation, the reflection should be grounded in deterministic traces: repeated blocker, failed gate, measured delta, and the tested guidance that followed.

[AgentBench](https://arxiv.org/abs/2308.03688) highlights long-horizon reasoning and instruction following as persistent weaknesses. This argues for short bounded cycles, explicit stop conditions, and re-verification of the authority contract on every run.

### Harness quality beats exhortation

OpenAI’s [harness engineering](https://openai.com/index/harness-engineering/) describes making desired behavior legible and enforceable through repository structure, tests, validation, and recurring cleanup. The Codex [agent-loop analysis](https://openai.com/index/unrolling-the-codex-agent-loop/) also makes the key operational point: the important output is the changed environment, while tool use continuously consumes context.

Current Codex guidance supports:

- durable repository instructions in [`AGENTS.md`](https://developers.openai.com/codex/guides/agents-md);
- explicit definitions of done and verification in [best practices](https://developers.openai.com/codex/learn/best-practices);
- scheduling only workflows that are manually reliable through [automations](https://developers.openai.com/codex/app/automations);
- deterministic lifecycle validation and memory capture through [hooks](https://developers.openai.com/codex/hooks).

## Why Obsidian fits the memory layer

Obsidian stores [local plain-text Markdown](https://obsidian.md/help/data-storage), so the memory remains usable by humans, scripts, Git, and other agents. [Internal links](https://obsidian.md/help/links) create explicit relationships; [properties](https://obsidian.md/help/properties) make notes machine-filterable; [Bases](https://obsidian.md/help/bases) provide database-like views over local notes; [Canvas](https://obsidian.md/help/plugins/canvas) and [Graph](https://obsidian.md/help/plugins/graph) can visualize the system without becoming the source of truth.

The right architecture is not “put everything in Obsidian.” It is:

- JSON for machine state and fixed evaluation;
- Markdown/properties for episodic memory and explanations;
- wiki links for retrieval paths;
- Bases for run review;
- Git-compatible static principles, while high-frequency generated run notes
  stay locally ignored to avoid making every scheduled cycle dirty the
  worktree.

Obsidian’s [CLI](https://obsidian.md/help/cli) may later support operator workflows, but direct file writes are simpler and keep the automation independent of the desktop app.

## Implemented control model

### Run classifications

- `productive`: fixed evaluator accepted measurable evidence gain.
- `maintenance`: stale artifacts were restored, but evidence did not improve.
- `no-op`: safe, fresh execution with no accepted progress.
- `skipped-duplicate-work`: meaningful state was unchanged inside the cooldown.
- `blocked`: safety, command, or verification failure.

The duplicate cooldown is now only the minimum interval. Repeated no-progress
runs use bounded exponential backoff up to 24 hours, capped when a known
fast-paper exit becomes eligible. A skipped invocation preserves the existing
next-check timestamp instead of extending it, preventing a busy caller from
starving the loop indefinitely.

### Accepted progress score

The score weights evidence by proximity to the promotion objective:

- scored promotion outcome: 100 points;
- newly verified stageable, auto-paper-selected, or approval-only paper candidate: 50 points;
- fast-paper closure: 25 points;
- scenario closure: 1 point, capped per cycle;
- paper hard-blocker reduction: 1 point, capped per cycle;
- dominant-blocker reduction: 1 point, capped per cycle.

The score is diagnostic, not authority-bearing. Candidate-discovery, scenario,
or fast-paper points cannot satisfy the 30 scored-outcome promotion gate.

### Memory and feedback

Each run records:

- baseline and final state;
- objective deltas;
- command and total duration;
- work signature;
- verifier result;
- dominant blocker;
- rolling productive-run rate.
- full-run acceptance rate and cost per accepted progress unit;
- loop eligibility, authority, and permission-scope governance.

Each saved run also becomes an Obsidian-compatible note. A blocker that dominates consecutive runs creates or updates a deterministic lesson note. This is bounded episodic memory, not free-form autonomous policy generation.

Recent evaluated traces are also consolidated into `Loop Beliefs.md`. Each
belief has a status, evidence window, evidence value, and explicit falsifier.
Examples include promotion-evidence stall, invocation inefficiency, and the
current dominant blocker. These beliefs prioritize research only; they cannot
change authority or trading policy.

## Next safe optimization phases

1. Build a regression corpus of historical run traces and expected classifications.
2. Add fixed efficiency targets such as productive runs per ten cycles and seconds per accepted evidence unit.
3. Introduce an isolated worktree optimizer that may edit only a loop-candidate module.
4. Evaluate candidate patches against safety invariants, unit tests, replay traces, and cost metrics.
5. Keep only candidates that improve the fixed score without weakening safety or changing authority.
6. Require human review before merging optimizer-generated production changes.

The self-improving component should optimize the research harness. It should never receive authority to optimize away the human trading boundary.
