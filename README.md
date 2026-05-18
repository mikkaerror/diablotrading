# Inferno Earnings Dashboard

A paper-evidence-only earnings and options research desk. Pulls a Google
Sheets earnings tracker, scores short-term setups and long-term holdings,
runs paper trades against shadow evidence, and only promotes a strategy
when the math earns it.

Current status: manual-ready-with-warnings. The live read-only book is
healthy for the configured approved account suffix, math verification is
clean, and automated live trading remains locked while the paper evidence lane
matures.

## Start here

Run this first for the current operating truth:

```bash
./run_inferno_central_command.sh
./run_inferno_usage_optimizer.sh
```

Then read `reports/usage_optimizer_latest.txt` and
`reports/model_command_center_latest.txt`.

After that, the anchor docs are:

1. [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) — current state, priorities, saved truth, next moves.
2. [`docs/MODEL_COLLABORATION_BRIEF.md`](docs/MODEL_COLLABORATION_BRIEF.md) — the mission and the safety rails.
3. [`docs/MODEL_THEORY.md`](docs/MODEL_THEORY.md) — how the desk thinks.
4. [`docs/MODULE_INDEX.md`](docs/MODULE_INDEX.md) — which module owns what.
5. [`docs/ENGINEERING_CONVENTIONS.md`](docs/ENGINEERING_CONVENTIONS.md) — the patterns every new module follows.
6. [`docs/USAGE_OPTIMIZATION.md`](docs/USAGE_OPTIMIZATION.md) — how to keep model handoffs compact.

Operating from those docs is enough to land in this repo and ship
without breaking the safety rails. After the anchor five, work from
[`docs/RUNBOOK.md`](docs/RUNBOOK.md).

## One-command health check

```bash
python3 inferno_doctor.py
```

If the doctor reports warnings, treat them as work queue items, not noise.

## One-screen brain view

```bash
python3 inferno_brain_console.py
```

Every layer of the brain, current verdicts, in one screen.

## The local dashboard

```bash
python3 server.py        # serves http://localhost:8000
```

## Safety rails (non-negotiable)

1. Never place a trade without explicit user confirmation.
2. Only the configured approved live account is approved — read-only.
3. Do not open a new thinkorswim instance.
4. Use the already-open TOS window only.
5. Paper evidence remains the promotion gate.

Full details and every other operator command live in
[`docs/RUNBOOK.md`](docs/RUNBOOK.md).

## GitHub hygiene

The public repo should contain source, docs, tests, and CI only. Local state
stays local:

- never commit `.env*`, Google credentials, SMTP secrets, broker exports, account statements, `data/`, `reports/`, or `logs/`
- commit process docs and tests with the code they explain
- run the command center and doctor before any clean push
- use [`docs/REPOSITORY_HYGIENE.md`](docs/REPOSITORY_HYGIENE.md) before staging a large cleanup
