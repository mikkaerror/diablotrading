# Schwab Chain History

Status: active research-only evidence collection.

The local chain-history collector reads only the already-normalized Schwab
market-data artifact. It records at most one immutable snapshot per source
capture date, stores full normalized rows for later surface calculations, and
never sends a network request. Snapshot capture has no ticket, promotion,
risk, universe, broker-submit, or live-trading authority.

Retention is bounded: 90 days remain hot, then snapshots move to a controlled
archive for up to 365 days. A source that is partial, unsafe, unmarked as
research-only, or has incomplete normalized rows is rejected rather than
becoming calibration history. A missing source date remains a missing data
condition; the collector never backfills it with a later quote.

Belief: after at least 60 complete local capture dates, the desk can build a
per-ticker historical IV denominator without pretending that a single
cross-sectional quote is a ticker's IV rank.

Evidence: `data/inferno_chain_history.json` records accepted dates, source
provenance, readiness, and missing snapshot-file checks; the Doctor reports
the safety flags and collection count.

Falsifier: any test or artifact showing a history run fetches market data,
rewrites an existing capture date, accepts a partial chain report, or changes a
ticket/promotion/risk/broker field. Any such result is a fail-closed safety
regression.
