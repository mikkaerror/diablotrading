# Retry Windows Need Changed Evidence

Date: 2026-09-22
Related: [[Due Work Requires Changed Usable Evidence]], [[DESK_CLEANUP_2026-09-22]]

Belief: an unchanged due-work flag does not justify rerunning a full evidence cycle inside its retry window. A later usable market observation, changed work signature, stale artifact repair, or elapsed deadline may justify another attempt.

Evidence: the September 21 review reproduced 21 commands with zero accepted outcome change. The repaired September 22 loop executed two safety prechecks in 0.691 seconds, preserved its 14:40 deadline and reported zero accepted progress. Tests cover unchanged due settlements/reviews/operator-ready candidates, changed market rows, wrapper-only timestamp changes and deadline expiry. All 2,116 repository tests pass in an isolated workspace.

Mechanism: hash usable option/history rows separately from work identity; never count a regenerated wrapper timestamp as independent evidence. A skipped invocation preserves the explicit deadline instead of using its own recent timestamp to restart a fallback cooldown. The verifier and authority gates remain fixed and outside this change.

Falsifier: reject or revise this rule if an unchanged snapshot contains independently executable work that this cadence suppresses beyond its finite deadline, or if useful new market observations do not resume eligible research. A reported clean run without accepted progress does not validate the model.

Operational cost: per-build command-center caching reduced JSON decodes from 135 to 78 and median local aggregation from 0.566722 to 0.408091 seconds across five identical-input trials. This is an efficiency gain, not paper evidence or predictive value.

Follow-up: compare later accepted outcomes and full-run acceptance rate. Preserve operator ticket decisions, risk constants, universe membership and broker-submit-off authority. Do not resolve missing actual fills by inventing a fresh ingest.
