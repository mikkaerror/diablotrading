# Coordination Workspace

This folder is the shared brain for multi-model collaboration on the Inferno
desk.

## Purpose

Use this workspace when Codex, Claude, or the human operator need one place to:

- see the current operating picture
- claim or update a mission
- leave a durable note for the next model
- preserve safety rails between sessions

## Canonical files

- `../data/inferno_model_command_center.json`
  - machine-readable command-center state
- `../reports/model_command_center_latest.txt`
  - human-readable command-center memo
- `../docs/SYSTEM_MAP.md`
  - one-page architecture, safety stack, ownership map, and verify commands
- `active_missions.json`
  - current mission queue
- `model_notes.jsonl`
  - append-only note log
- `prompts/CLAUDE_ONRAMP.md`
  - bootstrap prompt for Claude
- `prompts/CODEX_ONRAMP.md`
  - bootstrap prompt for Codex

## Commands

Build or refresh the command center:

```bash
cd "<repo-root>"
./inferno status
./inferno usage
```

Append a note:

```bash
./inferno note \
  --author codex \
  --title "What changed" \
  --body "Updated the live-account review lane and re-ran tests." \
  --tags live,review
```

Add a mission:

```bash
./inferno mission-add \
  --owner shared \
  --status pending \
  --priority high \
  --title "Wire live holdings into dashboard" \
  --body "Surface live posture, risk flags, and tracker alignment in the UI." \
  --tags dashboard,live
```

Update a mission:

```bash
./inferno mission-update \
  --id mission-1234abcd \
  --status in-progress \
  --owner claude
```

## Workflow

1. Run `../inferno status` and `../inferno usage`
2. Read `../reports/usage_optimizer_latest.txt`
3. Read `../reports/model_command_center_latest.txt`
4. Check `../docs/SYSTEM_MAP.md` if you are new to the architecture
5. Claim or update a mission
6. Make changes with tests and backups
7. Append a note
8. Rebuild central command and the usage optimizer with `./inferno status` and `./inferno usage`

## Sync Protocol

- One owner per mission by default; mark a mission `shared` only when two models
  truly need to touch the same lane.
- Claude stabilizes broker/TOS export evidence. Codex consumes export artifacts,
  hardens tests, docs, and command-center reporting.
- If a model changes mission scope, safety rails, or handoff instructions, it
  must append a note and refresh the generated handoff packets before stopping.
- Generated artifacts are operational truth; durable docs explain intent.

## Specialization lanes

- Codex: capital deployment readiness, risk gates, test coverage, docs, command-center hygiene.
- Claude: native thinkorswim export stabilization and broker UI evidence collection.
- Shared: paper evidence loop, paper-auto selections, shadow/backtest artifacts, and handoff notes.

Codex and Claude should not solve the same problem at the same time unless the
mission queue explicitly says the work is shared.

## Capital readiness command

Run this before sizing any new cash:

```bash
cd "<repo-root>"
./run_inferno_capital_deployment_readiness.sh --deployable-cash 525
./run_inferno_risk_gate_audit.sh
./run_inferno_model_command_center.sh
```

## Safety

- Never place trades without explicit human confirmation.
- Never open a new thinkorswim instance.
- Only the configured approved live account is approved, and only in read-only mode.
- Paper evidence remains the promotion gate.
