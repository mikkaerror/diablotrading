---
type: agent-loop-lesson
status: active
updated: 2026-07-16
tags:
  - inferno
  - agent-loop
  - paper-evidence
  - research-only
  - safety
---

# Isolated Simulation Boundary

Fast simulations are not operator paper tickets. They are eligible for an
automated research settlement only when their separate ledger row proves all
of the following:

- `paperOnly`, `autoSimulation`, and the `exploratory-fast` cohort are true.
- Promotion eligibility, live trading, and broker submission are hard-false.
- The row is not an operator ticket, does not require operator approval, and
  has no approval status.

Any failed condition quarantines the row without modifying it. A simulation
settlement is research telemetry only: it cannot approve, stage, reject, close,
or promote an operator paper ticket, and it earns no accepted progress in the
evidence-goal evaluator.

If an otherwise valid simulation is past expiration but has no complete
later-session option mark, terminally record `quarantined-expired-unmarked`.
Do not substitute expiry intrinsic value for the defined next-session exit,
and do not assign P/L, a score, or promotion credit. This preserves the failed
data condition while releasing only isolated simulation capacity.

## Evidence

On 2026-08-10, a settlement-only pass refreshed the read-only Schwab option
tape and closed five boundary-qualified isolated simulations using
later-session conservative bid/ask quotes. It opened no replacements and left
operator tickets, approvals, broker submission, authority, and the 29-outcome
promotion gap unchanged. The cohort's accumulated P/L remained negative, so
the run is a useful research result and a direct reminder that exploratory
simulation performance is neither live profit nor promotion evidence.

Falsifier: a test or artifact showing an operator-ticket field can pass this
boundary or that a simulation settlement changes promotion evidence. Either
case is a safety regression and must fail closed.
