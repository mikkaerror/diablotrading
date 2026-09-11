# Priority two: full industry research coverage

The new `python3 inferno_industry_coverage.py` report retains every symbol in
the current tracker, independently of score, earnings window and old theme
classification. It writes `data/inferno_industry_coverage.json` and
`reports/industry_coverage_latest.txt`. It performs no network request, changes
no score or operator role, and cannot add a symbol outside the tracker.

September 10 result: **183/183 visible**, with **24 issuer-linked research roles**
and **159 broad provider-reference classifications**. All 159 remain explicitly
due for issuer-specific review. Complete enumeration is not complete company
due diligence or proof of AI revenue exposure. Missing future references remain
visible as unresolved; a missing category never deletes a row.

The issuer-linked entries correct important context for ANET, IREN, HIVE, CLSK,
TE, CRWV and NBIS and identify compute, interconnect, physical infrastructure,
cloud monetization and energy milestones. Role assumptions, sources and review
dates are maintained in `research/industry_roles.json`. These describe business
exposure; they are not approved portfolio weights, holdings or eligibility.

The Morning Conviction Brief now rebuilds and reads this report after a
successful guarded refresh/brief run. Its weekday 07:50 Mountain schedule,
existing delivery and current model setting are preserved. It continues to
request 5–10 names as a starting range with no upper cap for worthwhile names.
Provider-only rows must be researched before making specific issuer claims.

Doctor checks coverage visibility, source freshness and research-only flags;
command center exposes the artifact and review counts. A healthy coverage
report means no tracker name was hidden, not that every company was vetted.

Tests cover all 183 low-ranked names surviving, missing references remaining
explicit, provider labels not being promoted to issuer verification, expired
role reviews, and preventing configured outside symbols from entering the report.
