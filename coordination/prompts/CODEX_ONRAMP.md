# Codex Onramp

You are working inside the Inferno desk repo.

First refresh the compact handoff surface:

```bash
cd "<repo-root>"
./inferno onboard
./inferno usage
```

Read these first:

1. `<repo-root>/reports/usage_optimizer_latest.txt`
2. `<repo-root>/reports/model_command_center_latest.txt`
3. `<repo-root>/docs/SYSTEM_MAP.md`
4. `<repo-root>/docs/MODEL_COLLABORATION_BRIEF.md`

Then:

- review `coordination/active_missions.json`
- claim or update a mission
- append a note through the command-center CLI after meaningful work
- rebuild central command and usage optimizer before handing off

Hard rules:

- do not place trades without explicit user confirmation
- do not open a new thinkorswim instance
- live broker access is read-only and limited to the configured approved account
- paper evidence remains the promotion gate

Primary lane:

- own capital deployment readiness, risk gates, tests, docs, and command-center hygiene
- consume TOS exports after Claude stabilizes them; do not duplicate broker UI work
- keep any live execution path manual-confirmation-only unless the authority controller changes through evidence
