# Schwab Chain Diff

Status: active research-only comparison lane; waiting for a second valid local
chain-history capture date.

The diff engine reads only the latest two immutable normalized-chain snapshots.
It emits a compact observation only when a shared contract exceeds one of the
documented thresholds: spread widens by more than 25%, volume exceeds two
times the prior snapshot, or open interest changes by more than 10%.

Belief: comparing immutable daily snapshots filters polling noise and creates
auditable market-structure evidence without treating every quote refresh as a
signal.

Evidence: `data/inferno_chain_diff.json` carries both source capture dates,
the exact thresholds, all validation failures, and event counts. Until two
valid capture dates exist, its only valid verdict is `insufficient-history`.

Falsifier: any diff run making a network request, accepting malformed or
authority-bearing history, emitting at exact thresholds, or feeding a ticket,
promotion, risk, broker, or live-trading action. Any such result is a
fail-closed safety regression.
