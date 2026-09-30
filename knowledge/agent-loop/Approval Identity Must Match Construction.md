# Approval Identity Must Match Construction

Observed 2026-09-30: ticker-only queue lookup exposed a $12,520 ACN straddle while a $330 cap-fit spread remained approval-blocked. Hypothesis: exact construction identity fixes routing without changing risk eligibility. Tests require separate tokens, no sibling/primary approval leakage, changed-price invalidation, event-date freshness, retained policy rejection, and blocked-to-staged progress without rewriting fills.

A cheap variant is not automatically eligible: newer saved pricing for ACN was $400 and failed reward/risk/liquidity. Falsifier: a variant gains staging while any unchanged risk/trigger/liquidity/family gate fails, or an old token approves a changed construction.

Publication lesson: two dawn emails 13 seconds apart and duplicated decision rows coincide with the second email's source-change failure. This is strong overlap evidence, not identification of the exact writer. Preserve snapshot hash checks and durable retries; a failed publication must remain visible. Never count repeated refreshes as qualified outcomes.

Sources: `docs/W1_APPROVAL_ROUTING_AND_DAWN_REVIEW_2026-09-30.md`, `tests/test_inferno_paper_approval_routes.py`.
