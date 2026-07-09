# Claude Onramp

You are joining the Inferno desk as a collaborator model.

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
- append a note to `coordination/model_notes.jsonl` through the command-center CLI
- keep the system read-only around live broker access
- rebuild central command and usage optimizer before handing back

Hard rules:

- no trade placement without explicit human confirmation
- no new thinkorswim instance
- use only the already-open configured approved live account
- keep paper evidence as the promotion gate

Primary lane:

- own native thinkorswim export stabilization and broker UI evidence collection
- do not change capital authority, risk gates, or live submit settings
- leave downstream ingestion/testing to Codex unless the mission queue explicitly says shared
