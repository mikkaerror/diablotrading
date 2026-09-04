# Provider Recovery Discipline

## Belief

Repeatedly starting the full dawn cycle after an unchanged provider failure
adds load and noise but does not create fresh market evidence.

## Evidence

The dawn-cycle heartbeat recorded Google Sheets token DNS failures on multiple
service days. Each failure had already consumed five Google-call attempts, and
the 15-minute watchdog classified the absent brief as a generic rescue
condition.

On 2026-08-27, the reporting preflight found a non-refreshable Schwab token
alongside stale option artifacts. Repeating `daily-ops` before the account
owner completed reauthorization could not create fresher evidence and would
only repeat the known failure.

## Rule

- Classify Google Sheets boundary failures as DNS, auth, rate-limit, transport,
  or unknown without recording credential material.
- A DNS or non-retryable auth failure stops immediate duplicate client retries.
- For retryable DNS, rate-limit, and transport failures, the watchdog preserves
  a provider circuit: recovery probes wait 15m, 30m, 60m, then at most 2h.
- Only a new failed dawn result grows the cooldown. Re-reading unchanged status
  must not extend the next probe deadline.
- A Schwab `reauthorizationRequired` result is a human-owned authorization
  boundary, not a retryable provider failure. The preflight recovery plan must
  put reauthorization first, mark dependent read-only refreshes deferred, and
  never launch TOS, refresh credentials, or submit an order.
- The circuit is advisory recovery pacing only. It must not imply that source
  data is fresh or alter research, authority, risk, ticket, or broker state.

## Falsifier

If a provider failure changes identity or a probe succeeds before the recorded
deadline, the old cooldown is no longer the explanation; inspect the new status
and use the successful artifact timestamp rather than the circuit state. For
Schwab, a successful reauthorization followed by a fresh read-only tape
falsifies the prior authorization blocker; the recovery plan should then no
longer defer that refresh.
