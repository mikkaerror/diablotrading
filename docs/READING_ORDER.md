# Reading Order

How to walk into this project for the first time.

## Start With Live State

Run the onboard digest first:

```bash
python3 inferno_central_command.py onboard
```

Then run the one-screen console:

```bash
python3 inferno_brain_console.py
```

Generated artifacts are the current trading-day truth. Durable docs explain
why the system exists and how to change it safely.

## The five-doc anchor (10 minutes)

Read these in order. After them, you can write or operate without breaking
the safety rails:

1. [**PROJECT_STATUS.md**](PROJECT_STATUS.md) — current state, priorities, saved truth, next moves.
2. [**MODEL_COLLABORATION_BRIEF.md**](MODEL_COLLABORATION_BRIEF.md) — mission, operating principle, safety rails.
3. [**MODEL_THEORY.md**](MODEL_THEORY.md) — how the desk thinks.
4. [**MODULE_INDEX.md**](MODULE_INDEX.md) — which module owns what behaviour.
5. [**ENGINEERING_CONVENTIONS.md**](ENGINEERING_CONVENTIONS.md) — patterns every new module follows.

## The mission

6. [**MISSION.md**](MISSION.md) — the operator's North Star. Honest expectations, four-phase journey, entry + exit framework, monthly milestones. Reread monthly.

## The day-to-day

7. [**TRADING_DAY_CHECKLIST.md**](TRADING_DAY_CHECKLIST.md) — the seven-step flow from morning brief to filled order, with exit rules baked in.
8. [**DAILY_BRIEFING_SETUP.md**](DAILY_BRIEFING_SETUP.md) — get the operator briefing in your inbox at 6:10 AM.

## Touch the math

9. [**MATH.md**](MATH.md) — every probability and statistical primitive the desk uses, with formulas, edge cases, and worked examples. Required reading before changing any math module.

## Operate the desk (add ~50 minutes)

10. [**RUNBOOK.md**](RUNBOOK.md) — every CLI command, the day-to-day reference.
11. [**OPERATING_MODEL.md**](OPERATING_MODEL.md) — how decisions flow from evidence to action.
12. [**CHECKLISTS.md**](CHECKLISTS.md) — daily, weekly, pre-trade.
13. [**RISK_POLICY.md**](RISK_POLICY.md) — hard caps no automation may exceed.

## Touch execution

14. [**EXECUTION_MODEL.md**](EXECUTION_MODEL.md) — order flow from approval to broker preview.
15. [**PAPER_TEST_LOOP.md**](PAPER_TEST_LOOP.md) — paper-evidence promotion gate.
16. [**BROKER_AUTOMATION_REQUIREMENTS.md**](BROKER_AUTOMATION_REQUIREMENTS.md) — what must be true before live submit.
17. [**AUTOTRADING_ROADMAP.md**](AUTOTRADING_ROADMAP.md) — long-term path to broker-assisted execution.

## Touch thinkorswim

18. [**THINKORSWIM_AUTOMATION.md**](THINKORSWIM_AUTOMATION.md) — AppleScript / accessibility automation.
19. [**THINKORSWIM_SANDBOX.md**](THINKORSWIM_SANDBOX.md) — paperMoney mode and sandbox isolation.

## Touch cloud automation

20. [**CLOUD_AUTOMATION.md**](CLOUD_AUTOMATION.md) — Cloud Run scheduler topology.

## Research and playbooks

21. [**HEDGE_FUND_METRICS.md**](HEDGE_FUND_METRICS.md) — the broader math context for promotion decisions.
22. [**CAMPAIGN_SIMULATION.md**](CAMPAIGN_SIMULATION.md) — campaign-mode replay framework.
23. [**PLAYBOOK_EARNINGS.md**](PLAYBOOK_EARNINGS.md) — earnings-catalyst playbook.
24. [**PLAYBOOK_LONG_TERM.md**](PLAYBOOK_LONG_TERM.md) — long-term holdings playbook.

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
