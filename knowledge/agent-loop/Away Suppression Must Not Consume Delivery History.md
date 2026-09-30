# Away Suppression Must Not Consume Delivery History

An operator away window suppresses approval and action-pulse delivery, including
forced sends and action-pulse failures. Read the current Mountain date at send
time, not the report's historical date. The Desk Chief remains email-free.

Keep reports current but do not reserve tokens, mark sent, or advance dedupe
history for a suppressed message. On return, use the current queue and existing
dedupe rules; never replay a frozen backlog. The Desk Editor summary and separate
watchdog retain their own delivery. No authority or ticket decision changes.

Evidence: `tests/test_inferno_away_delivery.py` covers inclusive boundaries, UTC
rollover, early return, force/failure suppression, shared Chief route, continuing
reports and preserved dedupe. Falsifier: an away skip changes sent history, a
forced action email escapes, or returning repeats a previously delivered item.
