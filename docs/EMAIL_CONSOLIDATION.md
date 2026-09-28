# Desk Editor delivery mode

`INFERNO_EMAIL_MODE=full|editor` is a delivery-only switch. Unset, `full`, or
unrecognized values retain full delivery. The operator can opt into `editor`
after the Desk Editor trial. No local environment or deployed job was changed.
Set the value in the environment used by each sending process; for local jobs,
`.env.inferno` is loaded by the existing configuration bootstrap. The deployment
script passes an explicitly exported value through to the cloud job environment,
defaulting to `full`. This does not deploy or schedule the Desk Editor agent.

In editor mode the Morning Conviction Brief, Strike Plan (including Claude's
compact digest), and routine Action Pulse are suppressed. Report generation and
`reports/*_latest.txt` writes continue. Pipeline status records an intentional
email skip; cloud strike exits successfully after a suppressed delivery. Forced
routine resend paths obey the mode. Approval requests, explicit operational
failure/exception alerts, and cloud auditor failure-only mail remain available.
An ordinary risk verdict of `blocked` is routine, not an operational failure.
Other independently configured email products retain their existing behavior.

Approval emails keep the `[Inferno Approval] TICKER TOKEN` subject and existing
inbox parser. Queue refresh preserves a **currently pending** token when ticker,
event, and proposed routes still match, including its original pending age.
New event dates or changed routes get a new token; resolved decisions are never
copied as new authorizations. Source `nextEarnings` identifies new events; legacy
rows use their dated countdown. Unknown events share a conservative daily bucket,
and their tokens are reused only within the same dated request day.

Dispatch reserves ticker/event/America-Denver-day before SMTP, under a local file
lock. The same token remains quiet by default; `--force` can remind on a later
day but cannot bypass the daily cap. An ambiguous SMTP failure consumes that day's
reservation and is reported as `send-failed`; inspect delivery before retrying on
a later day. Corrupt history fails closed. This favors at-most-once attempts over
retrying an email that may already have arrived. It does not claim exactly-once
SMTP delivery. Successful sends and reservations survive process restarts.

Cloud vault persistence now includes the approval queue and dispatch history.
This preserves tokens and dedupe across **serial successful cloud cycles**.
Independent Mac/cloud stores, overlapping stateless containers, failed restores,
or a crash before cloud persistence are not a distributed transaction. A single
notification owner and generation-checked shared state are required before claiming
a desk-wide guarantee across both hosts. See the cloud/local ownership proposal;
this change does not silently choose or deploy an owner.

Validation uses fake SMTP and temporary queues; no real approval message or
operator decision is sent or applied. Research-only; no authority or risk changes.
