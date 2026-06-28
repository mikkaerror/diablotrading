# Usage Optimization

Use this when model usage is getting burned by repeated context transfer.

## Default Flow

```bash
cd "<repo-root>"
./run_inferno_central_command.sh
./run_inferno_usage_optimizer.sh
```

Then give the next model only:

1. `reports/usage_optimizer_latest.txt`
2. `reports/model_command_center_onboard_latest.txt`
3. The exact failing command output, if anything failed

Files under "read only if the task needs it" are deliberately optional. Do
not paste them into the next session just because they exist.
Use `reports/model_command_center_latest.txt` when the task is broad, needs the
full report map, or may change command-center wiring.

Do not paste old chat history unless the task is specifically about that
history. The artifacts are the source of truth.

## What This Saves

- Replaces a long “where are we?” recap with one generated handoff packet.
- Tells models which files are worth reading first.
- Lists files that should not be pasted by default, especially generated data,
  logs, HTML reports, broker exports, and full terminal transcripts.
- Keeps the safety rails visible without re-summarizing the whole project.

## Cheap Checks Before Expensive Debugging

```bash
python3 inferno_doctor.py
python3 inferno_math_verify.py
python3 inferno_secret_hygiene.py
```

If those are clean except for known paper-evidence warnings, avoid deep repo
scans. Work from the command center next actions instead.

## Handoff Rule

Every meaningful cleanup should end with:

```bash
./run_inferno_model_command_center.sh note \
  --author codex \
  --title "Short title" \
  --body "What changed, what passed, what still needs attention." \
  --tags cleanup,handoff

./run_inferno_central_command.sh
./run_inferno_usage_optimizer.sh
```

That creates a small, current handoff surface and keeps future sessions from
spending their budget rediscovering the same state.
