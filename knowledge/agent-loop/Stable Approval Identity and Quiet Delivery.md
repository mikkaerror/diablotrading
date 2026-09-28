# Stable Approval Identity and Quiet Delivery

A refreshed report timestamp is not a new approval event. Minting a new token on
every refresh defeated token-only email dedupe and made older replies unusable.

Use the source event date and a live pending request to preserve the reply token;
keep a separate ticker/event/Denver-day delivery reservation. Changed event or
route identity invalidates token reuse. A failure after SMTP begins is ambiguous,
so reserve first and keep a visible failure instead of automatically resending.

Evidence: regression tests rebuild the actual queue, apply the existing inbox
reply parser to a temporary refreshed queue, rotate tokens, cross a day boundary,
change events and routes, and simulate SMTP timeout. Falsifier: two send attempts
for one event/day in a shared state store, or an old-event token matching a new
request. Independent cloud/local stores still require one canonical sender and
shared transactional state; local locking cannot establish that property.

[[../../docs/EMAIL_CONSOLIDATION]] documents operator opt-in. Mode suppression is
a delivery outcome, not a failed job; report generation continues. No research
progress, approval, or authority is inferred from fewer emails.
