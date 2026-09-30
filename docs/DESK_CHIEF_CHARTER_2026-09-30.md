# Desk Chief — operating charter

Status: active on the canonical Mac; isolated current-source verification accepted and recurring reviews installed. Deployment receipts are recorded in the operating plan.
Owner: Codex. Operator: Mikka. Mandate: explicit chat answers on September 30, 2026, preserved in `coordination/operator_acks/2026-09-30_desk_chief.json`.

The Chief is the final reviewer for desk operations: decide what matters next, assign an accountable owner, authorize a bounded operational retry, and accept tested work. It represents the operator's recorded preferences. It cannot infer new authority from a goal, urgency, spare usage resets or an analogy to a clone.

| Decision | Authority |
|---|---|
| Priorities, operational assignments, duplicate suppression | Chief |
| Approved report repairs and current-source test verification | Chief, within the fixed runner |
| Engineering implementation | Assigned Codex or Claude owner, with reviewed changes and tests |
| Paper approval/rejection, staging, fills and qualification | Existing delegate/operator and canonical Mac workflow |
| Capital, live orders, risk constants, universe, prereg rules | Existing operator authority; never Chief |

## One accountable work queue

`coordination/desk_roles.json` maps each desk capability to its owner, delivery artifact, freshness requirement and verifier. `./inferno chief status` rebuilds the oversight report without starting workers. Hourly ops maintenance refreshes this observation before the command center. Doctor displays the Chief's freshness, boundary state and unresolved roles. Existing missions remain visible and are never silently closed by the Chief.

`./inferno chief run` assigns stable task keys and may execute one fixed local action. `./inferno chief claim role:<id> --owner codex` (or claude) records a two-hour lease, preventing a second worker from claiming or retrying the same task. Owners read the Chief queue at session start, claim before starting, and leave artifact/test receipts. Assignment alone is not delivery or proof that a remote worker started. There is no automatic new chat, model agent, email or paid cloud job.

External Cowork/cloud workers require `data/desk_role_receipts/<role-id>.json` with an aware `generatedAt`, `ok: true`, source/run reference and summary. Missing receipts mean **unverified**, not a claim that the task failed. Future one-shot roles are not due before their first delivery date. Local receipts are operational observations, not evidence of a profitable strategy.

## Bounded operational approval

The reviewed runner permits only funnel report refresh, promotion-lineage report refresh, and CI-profile verification in a disposable source copy. It never runs arbitrary task commands. One command per review, 240-second command limit, file lock, durable attempt receipt before execution, and 60-minute exponential retry backoff capped at one day. Unchanged skips do not move the retry deadline. Active owner leases suppress automated retries.

Safety, execution and value are checked separately. A passing shell exit without the required successful artifact earns no accepted delivery. Code acceptance requires the fixed CI checks, current executable/configuration source fingerprint, and an unchanged source tree during verification. Full tests run in a disposable copy, away from canonical account and paper data. Acceptance is scoped to code verification or report recovery; it does not merge, deploy, decide tickets or create research outcomes. Work resolved by someone else is recorded by observation and not credited as Chief productivity.

The Chief requires fresh explicit research-only authority evidence and matching hashes of protected evaluator, authority, prereg and Chief code. A mismatch blocks dispatch and creates a visible safety task. A supervised source change requires explicit review and a refreshed baseline; unattended runs must never edit their own evaluator, runner, mandate, registry or guard baseline. Existing risk caps, D6 and broker flags remain unchanged.

## Keeper of operating margin

Track evidence-loop full-run acceptance rate, accepted progress units, elapsed seconds per accepted unit, existing adaptive cadence and no-progress streak. Separately track Chief executed actions, accepted operational deliveries, suppressed retries and seconds per accepted delivery. Report repair is not an accepted research outcome. No monetary cost is inferred from time or quota.

`data/desk_chief_cost_observations.json` can hold an aware `observedAt` and an account quota observation. Actual cloud spend requires `cloudSpend` with its own aware observedAt, provider, billingPeriod, source, basis=`actual-billed`, currency and finite nonnegative amount. Missing or stale billing remains unknown and creates an owned visibility task. Quota is account-wide; resets are not a budget to consume automatically.

Meaningful-state fingerprints exclude clock-only aging within the same status. A heartbeat reviews at 08:10, 12:10 and 16:10 Mountain on weekdays. It stays quiet when state is unchanged or non-actionable; notify only on a meaningful completion, failure or required operator decision. The app and Mac must be running for local reviews. No extra scheduler is installed for observation already provided by hourly maintenance.

## First priorities and acceptance

Preserve W0 ownership and W2 accounting truth; diagnose W1's actual gate-passing funnel and W4 chain collection using their unchanged acceptance criteria. Five actual dawn sessions and future prereg collection cannot be manufactured by repeated refreshes. Repair low-value loop triggers before increasing cadence. Preserve Claude's mailer, deposit and prereg lanes.

Launch acceptance: focused safety/duplicate/lease/acceptance tests, full CI-profile checks in isolation, clean diff, verified unchanged trading boundary, current Chief receipt, and active bounded review. Effectiveness acceptance remains measured over subsequent runs: lower duplicate work, source-backed cost visibility, and accepted useful progress without missed due work. A launch is not proof of efficiency improvement.
