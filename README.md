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

**If you are the operator, every morning:**

```bash
./inferno today            # one-screen glance: money, holdings, candidates
```

**If you are an agent (Claude or Codex), every session start:**

Read [`CLAUDE.md`](CLAUDE.md) at the repo root for the binding onramp
ritual, lane boundaries, and the autonomous-vs-ack discipline. Then
read [`docs/BACKLOG.md`](docs/BACKLOG.md) — the ranked queue of small,
shippable improvements with one named owner per item.

**Background loop (cron-able on Mac):**

```bash
./nightly_optimize.sh      # refresh data, recompute recommenders,
                           # regenerate reports, append NLV snapshot.
                           # Research-only; never approves a ticket.
python3 install_inferno_nightly_optimize_service.py install
                           # install the weekday 18:30 local refresh.
```

For the current operating-truth snapshot, run:

```bash
./inferno status
./inferno usage
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
./inferno doctor
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
