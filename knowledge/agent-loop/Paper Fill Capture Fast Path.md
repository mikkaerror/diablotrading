# Paper Fill Capture Fast Path

## Belief

Paper-evidence velocity improves when an operator can record actual entry and
exit prices against a pre-seeded paper ticket without editing the fill CSV, as
long as the canonical ingest owns all evidence and scoring decisions.

## Evidence — 2026-08-11

- `./inferno record-fill <TICKER|ticketId> --entry <price>` records only an
  existing sandbox-seeded `paper-staged` fill-log row, then runs the existing
  ingest and performance scorer.
- The matching exit command reuses the canonical close-evidence validators:
  exact ticket identity, paperMoney environment, finite non-negative prices,
  positive integer contracts, timezone-aware timestamps, and chronological
  order.
- Regression coverage round-trips the IREN seed id `1be6f96d665a730e` through
  planned, open, closed, and one scored outcome in an isolated test ledger.

## Boundary

The command is operator-invoked and requires actual paperMoney fill prices. It
does not create a ticket, make a candidate stageable, approve or reject one,
change any gate, or enable broker submission or live trading. A blocked seed is
rejected without changing the CSV.

## Falsifier

Reject any target that lacks one exact paper-staged ledger match and one seeded
fill-log row. Reject an exit without a prior imported open fill, and leave the
fill log unchanged on malformed input.
