# Refresh completion before briefing — September 7, 2026

The morning brief previously launched at 07:30 Mountain, five minutes before
the 07:35 market-open options refresh. It could run a separate tracker refresh
or fall back to old tracker state without verifying the options research had
completed. Full-sync, nightly and paper evidence service copies also lagged
their reviewed repository sources.

## Repair

The existing market-open task now invokes `inferno_refresh_handoff.py run`.
The runner serializes OAuth, daily options operations, variant scanning,
bounded supplemental quote coverage, pricing, shadow comparison, paper
research/blockers, scenario research and score archival. It uses a process
lock, a 15-minute total deadline and a maximum three minutes per command.
An already verified fresh receipt suppresses a duplicate invocation. Failure
stops downstream steps and replaces any prior success with a failed receipt.

Completion requires the five required artifacts to have generation timestamps
inside the run interval, the primary chain to be available and nonempty, daily
ops to reference that chain, and shadow comparison to reference the rebuilt
pricing report. The receipt saves source hashes and timestamps. A successful
exit code alone cannot produce a valid handoff.

The existing Morning Conviction Brief moves to 07:50 Mountain and uses
`--skip-updates --require-market-open-refresh`. The pipeline checks the receipt
before work and immediately before writing/delivering the final snapshot.
Missing, incomplete, old, future, changed or malformed inputs block delivery.
The receipt must belong to the current session and be no older than one hour.
This is an operational freshness limit, not a change to trading risk or quote
quality thresholds. The scheduled prompt prohibits an unguarded fallback or
automatic delivery retry. No new delivery task is added.

The installed diagnostic digest retains its custom 07:30/17:10 cadence. Its
output now names the source phase and each required artifact's generation time;
a 07:30 run is explicitly before the 07:35 research refresh. The doctor checks
for same-day completion after 07:55 Mountain; the command center includes the
receipt. Closed-market days skip the runner and guarded brief using the
existing full-day session calendar. Normal hours are checked in New York time;
regular opening at 09:30 Eastern is 07:30 Mountain.

## Deployment and authority

Only reviewed executable copies are atomically replaced for full sync,
nightly, evidence goal loop and the diagnostic digest. Installed LaunchAgent
plists, wrappers and calendar times are preserved; deployment does not start
any of those jobs. Codex task updates use the app automation tool, preserving
project, model, reasoning effort, active status and the market-open cadence.
Canonical prompt text is in `coordination/prompts/`.

No paper ticket, fill log, risk constant, eligible universe, approval or broker
submission setting is changed. Verification does not send email or run a live
market data refresh. The paper evidence deployment includes the prior repair
that uses the source-reconciled strategy-lab count for progress.

## Limits and falsifier

A completion receipt is build provenance, not proof of executable quotes,
tracker correctness, validated expectancy or operator fills. The existing
quote-quality and trade gates still decide their own questions. Source hashes
are checked at the two guard points; this is not a transaction freezing all
files throughout every external delivery operation. A concurrent refresh can
conservatively block a brief. The calendar does not model extraordinary
closures or early closes. Codex task execution still depends on the app and
available model capacity; doctor exposes a missed completion. A late refresh
may result in a skipped brief and needs an operator review rather than an
unguarded fallback.

Falsifier: if a guarded brief delivers while a required artifact is missing,
stale, inconsistent or changed at either guard point, the handoff has failed.
If a deployed checksum still differs, that service has not received the fix.
Tests must cover these adverse paths without invoking providers or delivery.
Elapsed seconds are duration, monetary cost remains unmeasured, and refreshes
receive zero accepted paper-evidence progress.

## Validation

- 43 focused tests and all 2,066 repository tests passed. The first full run
  caught report-catalog ordering; the new entry now preserves the existing
  first operator handoff item, and the full suite passed on rerun.
- Math verifier: 12 artifacts, zero violations. Secret hygiene: healthy.
- Doctor: 11 existing attention items; new handoff check passes the closed-day
  case. No claim that the whole desk is healthy.
- Closed-market runner and guarded morning CLI returned a skip/block before
  provider work or delivery. No email was sent in verification.
- Original three deployed drifts resolved; updated digest also deployed. All
  four checksum audits now say synced. Plist and wrapper hashes unchanged.
- Both updated Codex prompts match the checked-in text (the app trims the final
  newline). Existing project/model/effort/status preserved. Schedule readback:
  market refresh 07:35, guarded morning 07:50, digest 07:30/17:10 Mountain;
  zero same-minute calendar collisions.
- Six protected file hashes unchanged, including paper ledger, actual ingest
  report, fill CSV, risk configuration and local environment configuration.
  Authority manifest decision still has liveTradingAllowed=false and brokerSubmitAllowed=false.
- No accepted trading-evidence progress is claimed. The next market session's
  actual refresh-to-brief execution remains unobserved.
