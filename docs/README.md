# Docs

This is the index. The full reading order lives in
[`READING_ORDER.md`](READING_ORDER.md).

## The five-doc anchor

Read these first — together they define the desk:

- [`PROJECT_STATUS.md`](PROJECT_STATUS.md) — current state, priorities, saved truth, and next moves.
- [`MODEL_COLLABORATION_BRIEF.md`](MODEL_COLLABORATION_BRIEF.md) — mission, operating principle, safety rails.
- [`MODEL_THEORY.md`](MODEL_THEORY.md) — how the desk thinks.
- [`MODULE_INDEX.md`](MODULE_INDEX.md) — which module owns what.
- [`ENGINEERING_CONVENTIONS.md`](ENGINEERING_CONVENTIONS.md) — the patterns every new module follows.

## The mission (read once a month)

- [`MISSION.md`](MISSION.md) — the honest North Star: compound survival, four phases, entry + **exit** framework, milestones, ambitious compounding without ruin.

## Operator one-pagers

- [`TRADING_DAY_CHECKLIST.md`](TRADING_DAY_CHECKLIST.md) — the daily flow from morning brief to filled order, with the exit rules built in.
- [`DAILY_BRIEFING_SETUP.md`](DAILY_BRIEFING_SETUP.md) — get the operator briefing in your inbox at 6:10 AM every day.

## The math

- [`MATH.md`](MATH.md) — every probability and statistical primitive the desk uses, with formulas, edge cases, and worked examples. Required reading before changing any math module.

## Operate the desk

- [`RUNBOOK.md`](RUNBOOK.md) — every operator command.
- [`OPERATING_MODEL.md`](OPERATING_MODEL.md) — process flow, role ownership.
- [`CHECKLISTS.md`](CHECKLISTS.md) — daily / weekly / pre-trade.
- [`RISK_POLICY.md`](RISK_POLICY.md) — hard caps.
- [`REPOSITORY_HYGIENE.md`](REPOSITORY_HYGIENE.md) — what is safe to commit, ignore, and push.

## Execution lane

- [`EXECUTION_MODEL.md`](EXECUTION_MODEL.md)
- [`PAPER_TEST_LOOP.md`](PAPER_TEST_LOOP.md)
- [`BROKER_AUTOMATION_REQUIREMENTS.md`](BROKER_AUTOMATION_REQUIREMENTS.md)
- [`AUTOTRADING_ROADMAP.md`](AUTOTRADING_ROADMAP.md)

## Thinkorswim

- [`THINKORSWIM_AUTOMATION.md`](THINKORSWIM_AUTOMATION.md)
- [`THINKORSWIM_SANDBOX.md`](THINKORSWIM_SANDBOX.md)

## Cloud

- [`CLOUD_AUTOMATION.md`](CLOUD_AUTOMATION.md)

## Research / math

- [`MATH.md`](MATH.md) — every probability and statistical primitive the desk uses (Wilson, bootstrap, Kelly, VRP).
- [`HEDGE_FUND_METRICS.md`](HEDGE_FUND_METRICS.md)
- [`CAMPAIGN_SIMULATION.md`](CAMPAIGN_SIMULATION.md)
- [`PLAYBOOK_EARNINGS.md`](PLAYBOOK_EARNINGS.md)
- [`PLAYBOOK_LONG_TERM.md`](PLAYBOOK_LONG_TERM.md)

## Live state

Live state lives in artifacts, not docs. Start with the command center:

```bash
python3 inferno_model_command_center.py build
```

Then read:

- `reports/model_command_center_latest.txt` — executive summary, safety rails, next actions, canonical report map.
- `docs/PROJECT_STATUS.md` — durable PM snapshot and priorities.

For a fast console view, run the brain console:

```bash
python3 inferno_brain_console.py
```

For health only, run the doctor:

```bash
python3 inferno_doctor.py
```

## Archive

Historical plan docs (shipped or superseded): [`archive/`](archive/).
