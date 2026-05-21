# Reading Order

How to walk into this project for the first time.

## Start With Live State

Run the generated handoff packets first:

```bash
./run_inferno_central_command.sh onboard
./run_inferno_usage_optimizer.sh
```

Then run the one-screen console:

```bash
python3 inferno_brain_console.py
```

Generated artifacts are the current trading-day truth. Durable docs explain
why the system exists and how to change it safely.

When context is tight, start with `reports/usage_optimizer_latest.txt`. It is
the smallest safe read list for Codex, Claude, or any new model joining the
desk.

## The five-minute orientation

Read this first. Everything else is depth.

0. [**MISSION_CONTROL.md**](MISSION_CONTROL.md) — one page: mission, strategy thesis, data authority, decision ladder, hard boundaries, and next build priorities.
1. [**SYSTEM_MAP.md**](SYSTEM_MAP.md) — one page: architecture, trade lifecycle, safety stack, canonical artifact map.

## The core anchor (10 minutes)

Read these in order. After them, you can write or operate without breaking
the safety rails:

1. `reports/usage_optimizer_latest.txt` — smallest safe read list and do-not-paste list.
2. `reports/model_command_center_latest.txt` — current missions, notes, safety rails, next actions.
3. [**MISSION_CONTROL.md**](MISSION_CONTROL.md) — durable command brief.
4. [**PROJECT_STATUS.md**](PROJECT_STATUS.md) — current state, priorities, saved truth, next moves.
5. [**MODEL_COLLABORATION_BRIEF.md**](MODEL_COLLABORATION_BRIEF.md) — model split, collaboration rules, safety rails.
6. [**MODEL_THEORY.md**](MODEL_THEORY.md) — how the desk thinks.

Use [**MODULE_INDEX.md**](MODULE_INDEX.md) and
[**ENGINEERING_CONVENTIONS.md**](ENGINEERING_CONVENTIONS.md) when you are
about to change code.

## The mission

7. [**MISSION.md**](MISSION.md) — the operator's North Star. Honest expectations, four-phase journey, entry + exit framework, monthly milestones. Reread monthly.
8. [**STRATEGY_REQUIREMENTS.md**](STRATEGY_REQUIREMENTS.md) — strategy families, required data, objective function, gates, and metrics.
9. [**RESEARCH_ROADMAP.md**](RESEARCH_ROADMAP.md) — the three-phase research plan (post-trade learning → portfolio-level → consensus risk). Read before claiming a research mission.
9a. [**PORTFOLIO_CONSTRUCTION.md**](PORTFOLIO_CONSTRUCTION.md) — correlation, drawdown, capacity, and sizing discipline.
9b. [**CONSENSUS_AND_CROWDEDNESS.md**](CONSENSUS_AND_CROWDEDNESS.md) — crowdedness, reflexivity, and what the desk still refuses to infer.

## The day-to-day

10. [**TRADING_DAY_CHECKLIST.md**](TRADING_DAY_CHECKLIST.md) — the seven-step flow from morning brief to filled order, with exit rules baked in.
11. [**DAILY_BRIEFING_SETUP.md**](DAILY_BRIEFING_SETUP.md) — get the operator briefing in your inbox at 6:10 AM.

## Touch the math

12. [**MATH.md**](MATH.md) — every probability and statistical primitive the desk uses, with formulas, edge cases, and worked examples. Required reading before changing any math module.

## Operate the desk (add ~50 minutes)

13. [**RUNBOOK.md**](RUNBOOK.md) — every CLI command, the day-to-day reference.
14. [**OPERATING_MODEL.md**](OPERATING_MODEL.md) — how decisions flow from evidence to action.
15. [**CHECKLISTS.md**](CHECKLISTS.md) — daily, weekly, pre-trade.
16. [**RISK_POLICY.md**](RISK_POLICY.md) — hard caps no automation may exceed.

## Touch execution

17. [**EXECUTION_MODEL.md**](EXECUTION_MODEL.md) — order flow from approval to broker preview.
18. [**PAPER_TEST_LOOP.md**](PAPER_TEST_LOOP.md) — paper-evidence promotion gate.
19. [**BROKER_AUTOMATION_REQUIREMENTS.md**](BROKER_AUTOMATION_REQUIREMENTS.md) — what must be true before live submit.
20. [**AUTOTRADING_ROADMAP.md**](AUTOTRADING_ROADMAP.md) — long-term path to broker-assisted execution.

## Touch thinkorswim

21. [**THINKORSWIM_AUTOMATION.md**](THINKORSWIM_AUTOMATION.md) — AppleScript / accessibility automation.
22. [**THINKORSWIM_SANDBOX.md**](THINKORSWIM_SANDBOX.md) — paperMoney mode and sandbox isolation.

## Touch cloud automation

23. [**CLOUD_AUTOMATION.md**](CLOUD_AUTOMATION.md) — Cloud Run scheduler topology.

## Touch Schwab live data

23a. [**SCHWAB_OPTIONS_API.md**](SCHWAB_OPTIONS_API.md) — read-only chain adapter plan, OAuth posture, and quote-quality contract.
23b. [**SCHWAB_EDGE_OPPORTUNITIES.md**](SCHWAB_EDGE_OPPORTUNITIES.md) — honest framing of retail options edge, tiered metric hierarchy, refresh cadence, anti-goals, and proposed Phase 2-4 module backlog.

## Research and playbooks

24. [**HEDGE_FUND_METRICS.md**](HEDGE_FUND_METRICS.md) — the broader math context for promotion decisions.
25. [**CAMPAIGN_SIMULATION.md**](CAMPAIGN_SIMULATION.md) — campaign-mode replay framework.
26. [**PLAYBOOK_EARNINGS.md**](PLAYBOOK_EARNINGS.md) — earnings-catalyst playbook.
27. [**PLAYBOOK_LONG_TERM.md**](PLAYBOOK_LONG_TERM.md) — long-term holdings playbook.

## Authoritative ordering

Where docs conflict (rare):

1. `MODEL_COLLABORATION_BRIEF.md` — absolute authority.
2. `RISK_POLICY.md` — caps and forbidden actions.
3. `RUNBOOK.md` — operational truth.
4. `MODULE_INDEX.md` — the directory (not policy).
5. `MODEL_THEORY.md` — operating theory.
6. Everything else — context.

## Low-Context Handoff

When usage is tight, run:

```bash
./run_inferno_central_command.sh
./run_inferno_usage_optimizer.sh
```

Then start with `reports/usage_optimizer_latest.txt`. It lists the smallest
safe reading set and the generated artifacts that should not be pasted by
default.

## Archive

Historical plans live in [`archive/`](archive/). Useful for archeology;
not operational.
