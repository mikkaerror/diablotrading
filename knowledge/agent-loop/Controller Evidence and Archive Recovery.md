# Controller evidence and archive recovery

September 30, 2026 — W2.

- Promotion displays consume `promotionTruth.qualified` from lineage. Reported intrinsic closes are estimates with no credit. Missing lineage is unavailable, never a fallback to reported closes.
- Python before 3.11 rejects ISO timestamps ending in Z. Normalize to +00:00 before both sorting and validating transaction times; naive timestamps remain invalid.
- CI needs the declared research dependencies before preflight. A configured developer machine is not a clean CI environment.
- Missing or nonfinite NLV produces no CSV append. Preserve the historical blank observation; do not turn absence into zero.
- Archive capture first durably spools exact bytes, then retries SQLite indexing at most three times. Persistent mount failures publish queued-retry-required and an actionable diagnostic. Recover on the canonical writable host with `./inferno archive run`; capture IDs prevent duplicate indexing. Never retry a decision to repair its archive.

Evidence: controller contract regressions plus existing archive crash/concurrency tests; initial full suite 2,286 passed. No gate/evaluator constants or authority changed. Falsifier: a missing-NLV append, inconsistent qualified count, lost queued capture, or duplicate version after recovery.
