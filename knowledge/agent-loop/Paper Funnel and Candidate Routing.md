# Paper Funnel and Candidate Routing

W1 implementation, 2026-09-30. Research only; no ticket decisions executed.

Weekly cohorts use ticket creation week and strategy. Proposed is the deduplicated ledger population, blocked/staged are current statuses, fills require recorded paperExecution facts, and qualification comes from lineage. Historical transitions are not reconstructed. Blocker reasons can overlap. Missing observations are unknown.

Answered ticker/family evidence uses the delegate's existing fixed predicates. Such candidates remain in shadowItems and the shadow evidence collector; they cannot consume primary slots. Each ticker has one primary, preferring passing risk verdicts. The concentration governor runs on the resulting primary set without changing its limit.

Iron flies reuse inferno_short_premium_shadow.build_iron_fly unchanged, including full crossing, wings and skip rules. Freshness uses the existing Schwab risk-policy age limit. SHORT_PREMIUM_DEFINED survives into the existing paper campaign classifier. New candidates and size-fit changes require the existing delegate/operator approval route. Size-only failures may try one lot or narrower call verticals; every attempt reruns policy and liquidity checks. No change to risk constants or eligible universe.

Dawn research builds do not record tickets or approve anything. The first recorded run per date is used, so later reruns cannot inflate acceptance. Require five completed weekday sessions averaging at least three passing candidates, then independently verify the nightly boundary audit. The implementation does not declare itself done. Canonical ledger integration still depends on W0.

Falsifier: passing tests without recorded dawn improvements is not evidence the funnel has improved. Stale chains, full-cross economics or unchanged caps can still yield zero candidates; diagnose the observed blocker rather than widening policy.

First-dawn diagnosis: inspect contract identities before attributing an oversized proposal to the cap. A straddle requires a common call/put strike; sparse disjoint chains must fail construction. Latest-slate diagnostics never overwrite frozen dawn observations or grant approval/qualification credit. Non-regular-session iron-fly blocks remain real blocks.
