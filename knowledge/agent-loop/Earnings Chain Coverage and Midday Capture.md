# Earnings Chain Coverage and Midday Capture

W4, 2026-09-30. Read-only market-data work. No eligible-universe membership, risk cap, strategy gate or broker setting changes.

The snapshot's dated earnings events 1–7 days ahead lead the capture list, ordered by days then ticker. Missing dates and stale relative day counters do not invent events. Remaining held, paper, strategy and watchlist priorities retain their order. The effective symbol limit is the greater of the existing configured limit and the event population; it is passed through the adapter so its old default cannot silently truncate the expanded list.

Weekdays at 13:00 ET (11:00 America/Denver), inferno_schwab_midday_capture fetches only read-only chains and invokes the existing v2 shadow collector. Installation validates local scheduling in both seasons. Runtime rejects starts outside 12:30–14:00 ET or on weekends, locks overlapping processes, and skips duplicate successful days. Failures persist actionable receipts; doctor rejects stale successes. The service never calls the paper delegate, ticket staging, fill capture, email or broker actions. Expiration review applies only to the preexisting shadow study.

Prereg v2 construction, gates, skip rules and first-event capture semantics remain unchanged. Captured chains are not automatically valid study observations. Inspect missing/nonregular chains and v2 skips independently. The acceptance criterion is at least ten actual v2 records during the week of October 13; no synthetic rows or tests count toward it.

Deployment: run python3 install_inferno_schwab_midday_service.py install from the canonical Mac checkout. Inspect ./inferno schedule and reports/schwab_midday_capture_latest.txt after the first scheduled run. A loaded service is schedule evidence, not proof of a successful market-session capture.
