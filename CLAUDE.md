# CLAUDE.md — repo bootstrap for Claude sessions

You are joining the **Inferno manual options desk** as a collaborator model.
This file is what you read before doing anything else. If you skip the onramp
ritual below, you will almost certainly cross into Codex's lane, accumulate
parallel uncommitted state in shared files, and create a painful sync.
This has happened. Don't repeat it.

## 0. Mandatory session-start ritual (do this every single time)

Run in order, before any user-requested work:

```bash
# 1) Refresh the handoff packets so you read the current truth, not yesterday's
cd "<repo-root>"
./run_inferno_central_command.sh onboard
./run_inferno_usage_optimizer.sh

# 2) Read the operating picture
cat reports/usage_optimizer_latest.txt
cat reports/model_command_center_latest.txt

# 3) See what changed since last sync
git log --oneline -10
git status --short

# 4) See what Codex has been doing
tail -30 coordination/model_notes.jsonl

# 5) See who owns what right now
cat coordination/active_missions.json

# 6) Read the architecture / safety map
cat docs/SYSTEM_MAP.md
cat docs/MODEL_COLLABORATION_BRIEF.md
```

Only after all six steps should you begin work. If the user gives you a task
before you run them, ask to do the onramp first. The ten-minute investment
prevents the thirty-minute commit-resolution session later.

## 1. Specialization lanes (binding unless user explicitly overrides)

- **Codex owns**: capital deployment readiness, risk gates, test coverage,
  docs, command-center hygiene. Files: `inferno_capital_*`,
  `inferno_risk_*`, `inferno_authority_*`, `inferno_doctor.py`,
  `inferno_model_command_center.py`, `inferno_strategy_*`,
  `inferno_score_calibration.py`, `inferno_expected_move_ledger.py`,
  `inferno_schwab_*`, `inferno_tos_*` (except export bridge).
- **Claude owns**: native thinkorswim export stabilization and broker UI
  evidence collection. Files: `inferno_tos_export_*`,
  `inferno_desktop_automation*`, `inferno_downloads_*` (export-side only).
- **Shared**: paper evidence loop, paper-auto selections, shadow/backtest
  artifacts. Files: `inferno_paper_*`, `inferno_action_pulse.py`,
  `inferno_decision_brief.py`.

If a user task lands you in the other agent's lane, **say so out loud**
to the user before starting and propose either:
1. queue the work for a Codex session (cleaner), or
2. cross-lane this session with explicit lane-cross documentation in
   `coordination/model_notes.jsonl` and a new shared mission via
   `python3 inferno_model_command_center.py mission-add` (faster but
   requires discipline).

## 2. The safety perimeter (never touch any of these)

These are hard-coded False in `inferno_authority_controller.decide_authority`
and they stay that way. There is no condition under which you flip them:

- `liveTradingAllowed`
- `brokerSubmitAllowed`
- `BROKER_ADAPTER_MODE` env var (default OFF)
- `submit_live_order` action (always in `blockedActions`)

The desk graduates to live submission via the 30-closed-paper-outcome
promotion gate plus explicit human ack — not via any code change.

The operator-set risk constants in `inferno_config.py`:
- `MAX_SINGLE_TICKET_DOLLARS` — env-overridable; default $500
- `MAX_DAILY_TICKET_DOLLARS` — env-overridable; default $1500
- `MAX_OPEN_PAPER_TICKETS` — env-overridable; default 5

These you don't edit directly. If you want to propose a change, build it
as a research-only recommender (see `inferno_capital_scaling.py` for the
pattern) that the operator opts into via an ack file.

## 3. The 30-outcome promotion gate

The desk has been at 0/30 closed scored paper outcomes for weeks. This
is the binding constraint on the entire system. Everything else — math
audits, position sizing research, trade-management playbooks — is
preparation. The only thing that moves the gate is closed paper outcomes.

If a user asks "can we go live?" the answer is: not until 30 outcomes
accrue and the authority controller's evidence checks all pass. You
don't relax that; you accelerate evidence accumulation.

## 4. Standard module pattern (mimic for every new module)

```
inferno_<lane>.py
  build_<lane>()        -> dict payload, research-only
  save_<lane>()         -> writes data/inferno_<lane>.json + reports/<lane>_latest.txt
  <lane>_text(payload)  -> human renderer
  parse_args(); main()  -> CLI with run / status subcommands

  Constants at top:
    <LANE>_STAGE = "<lane>-research-only"
    ...

  Payload always includes:
    "stage": <LANE>_STAGE
    "researchOnly": True
    "promotable": False
    "authorityChanged": False
    "citations": [...]
```

Tests live in `tests/test_inferno_<lane>.py`. Wire into:
- `inferno_doctor.py` (add a `<lane>_status(report)` helper, then a line
  in `main()` that loads + summarizes).
- `inferno_model_command_center.py` (add a `<LANE>_FILE` constant, an
  entry in `REPORTING_MAP`, and a key in `artifact_summary`).

## 5. Commit hygiene

- **Commit early and often.** Don't accumulate uncommitted parallel state.
  The last session had 82 uncommitted files at commit time; resolving the
  lane separation took 30 minutes.
- **One topic per commit.** Don't mix the new module with unrelated docs
  refreshes.
- **Append a model_notes entry** before committing, using the CLI:
  ```bash
  python3 inferno_model_command_center.py note \
    --author claude --title "..." --body "..." --tags "..."
  ```
- **Commit message format**: short title (one line), blank line, then a
  scoped body. Include the verdict on `researchOnly`/`promotable` and any
  authority claim ("authority unchanged", "no broker submit", etc.).

## 6. When in doubt

- **Lane uncertain** → ask the user explicitly which agent should own this.
- **Authority adjacent** → don't touch it; build a recommender that the
  operator opts into via ack file.
- **Working tree messy** → stop, run `git status`, surface the state to the
  user before adding more uncommitted work.
- **Tests failing** → never commit. Fix the tests or revert.
- **Two agents touching the same file** → surface to user, propose
  branch-per-agent or staged-by-hunks.

## 7. The fast-path operator entry point

The desk has many reports. The day-to-day entry point for the operator is
`./today.sh` (which calls `today.py`). It reads existing artifacts and
prints one screen:

  - current NLV and cash, plus change from peak
  - any paper candidates waiting on approval, each one as one line
  - a y/n/s/q prompt per candidate that calls `inferno_approval_queue.py`
    approve/reject under the hood
  - an append-only `data/operator_decisions.csv` audit trail

This is intentionally the SMALLEST surface. It does NOT fetch fresh data
(run the dawn/strike cycle first), does NOT mutate authority, does NOT
generate new reports. It exists so the operator can read one screen,
type one letter, and move on.

If you add a flag, you are reintroducing the friction the script exists
to remove. Resist.

## 8. Specific anti-patterns from past sessions

- **Don't** read `outputs/today_math_worksheet.py` and assume it's part of
  the pipeline — it's a one-off diagnostic.
- **Don't** trust `data/inferno_doctor.json` as fresh proof — many of its
  lines are warnings from stale upstream artifacts.
- **Don't** edit `inferno_config.py` directly to change risk constants;
  build a recommender (see `inferno_capital_scaling.py`).
- **Don't** create new modules under `inferno_capital_*`,
  `inferno_risk_*`, `inferno_doctor.py`, `inferno_model_command_center.py`
  without surfacing the lane-cross to the user first.
- **Don't** approve, reject, or close any paper ticket on the user's
  behalf. Surface decisions; the operator clicks the buttons.

---

This file is binding. If something here conflicts with a user instruction,
ask the user — don't unilaterally override.

Last updated: 2026-05-26 (after the capital-scaling lane-cross session).
