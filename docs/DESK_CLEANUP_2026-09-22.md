# Desk reliability and efficiency cleanup — September 22, 2026

The refresh path is restored and the four September 21 efficiency findings are repaired. The desk remains research-only. This work improves reliability, cost and reporting accuracy; it does not establish predictive edge or promotion eligibility.

## Changes and measured effects

- Account freshness separates a failed fetch attempt from the last usable observation. Recent error reports now show unavailable rather than fresh. Explicit previous-success timestamps remain visible.
- Command-center JSON reads are cached within one build only. Five runs against identical frozen inputs reduced decodes from 135 to 78 (42.2% fewer), with median aggregation time falling from 0.566722 to 0.408091 seconds (28.0%). These are local aggregation measurements, not end-to-end refresh performance.
- The evidence loop respects its existing adaptive retry window when due work and usable market evidence are unchanged. New usable option/history rows can resume research immediately; report-wrapper timestamps alone cannot. An expired explicit retry deadline cannot be extended by a recent skipped check. Safety prechecks still run. The observed 13:40 run executed two prechecks in 0.691 seconds and reported zero accepted progress, compared with the earlier 21-command duplicate full cycle.
- The dawn entry point has a 900-second process deadline, configurable up to 3,600 seconds. A provider request also receives a 20-second timeout. Deadline termination reaps the child and releases its OS file lock. A contending process no longer erases the active owner's lock metadata. Direct invocation of the legacy morning script does not acquire the outer dawn deadline.
- `--skip-email` suppresses failure email as well as normal delivery. Doctor recognizes a successful intentionally unsent morning report without labeling it a delivery failure.
- Paper-director reporting now uses source-qualified strategy-lab outcomes. Legacy numeric outcome counts remain separately available. This does not change the authority controller or its legacy warnings.
- Tests supply their own account-policy and statement-artifact fixtures; they no longer depend on private workstation files for those cases.

## Validation

All **2,116 tests passed**, including process deadline/lock release, contention metadata, failed account freshness, per-build cache invalidation, retry expiry and changed-market resumption. The complete suite ran in an isolated copy of the current code without live account files, avoiding production artifact writes. Source/test edits were copied before the final full run. `git diff --check` is clean.

SHA-256 comparisons confirm unchanged risk/configuration code, authority-controller code, operator paper ledger, approval queue, operator long-term holds and watchlist input. The latest authority manifest has live trading and broker submission disabled, and `submit_live_order` remains blocked. No operator paper ticket was staged, approved, rejected, closed or promoted. Isolated exploratory simulations remain separate from qualifying operator outcomes.

Evidence is saved locally in `outputs/desk-cleanup-2026-09-22/`: cache measurements, isolated-test logs, protected-file comparisons, final Doctor output and view validation. The private `playbook/index.html` is a standalone, source-linked 20-name view with search, cash filters, price sorting and explicit entry conditions. It preserves the existing discovery order and overlays September 22 intraday quotes on September 21 completed-session technical references. It is not a new ranking model.

## Remaining evidence work

Doctor has three attention items, not runtime failures: 159 issuer reviews remain incomplete in the durable full-universe industry layer; qualified paper evidence remains below the 30-outcome requirement; and the last actual operator fill ingest is September 7. Do not fabricate an ingest or relabel provider references as issuer diligence to clear these warnings.

The $40 GLW gain is user-reported and not yet instrument-reconciled in the broker transaction normalizer. Cash movement must not be relabeled as options profit. The qualified sample remains one outcome with a 29-outcome gap; new refreshes and isolated simulations do not close that gap. The authority manifest still retains a legacy three-numeric-outcome warning; the qualified director/lab count is the relevant research evidence count.

The next useful work is reconciliation of actual fills and costs, targeted issuer diligence, and later independent observations. Repeated identical refreshes are not a substitute. The current research list contains only grade C/D candidates, and no account-sized option construction was established in this review.
