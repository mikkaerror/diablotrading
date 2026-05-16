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
./run_inferno_model_command_center.sh
```

Append a note:

```bash
python3 inferno_model_command_center.py note \
  --author codex \
  --title "What changed" \
  --body "Updated the live-account review lane and re-ran tests." \
  --tags live,review
```

Add a mission:

```bash
python3 inferno_model_command_center.py mission-add \
  --owner shared \
  --status pending \
  --priority high \
  --title "Wire live holdings into dashboard" \
  --body "Surface live posture, risk flags, and tracker alignment in the UI." \
  --tags dashboard,live
```

Update a mission:

```bash
python3 inferno_model_command_center.py mission-update \
  --id mission-1234abcd \
  --status in-progress \
  --owner claude
```

## Workflow

1. Read `../docs/MODEL_COLLABORATION_BRIEF.md`
2. Read `../reports/model_command_center_latest.txt`
3. Claim or update a mission
4. Make changes with tests and backups
5. Append a note
6. Rebuild the command center

## Specialization lanes

- Codex: capital deployment readiness, risk gates, test coverage, docs, command-center hygiene.
- Claude: native thinkorswim export stabilization and broker UI evidence collection.
- Shared: paper evidence loop, backtest artifacts, and handoff notes.

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
