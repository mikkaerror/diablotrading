# Schwab Transaction Cash Reconciliation

## Belief

An exact match between an observed broker cash delta and the net amount of a
redacted, suffix-scoped Schwab transaction can establish a cash-flow source. It
cannot establish realized options P/L, deployable capital, or trading authority.

## Evidence

`inferno_schwab_transaction_ledger.py` performs only bounded GET reads for the
approved account suffix and writes redacted normalized transaction facts. On
2026-07-22, its 90-day read returned 16 rows. The `-$599.93` cash movement in
the NLV history exactly matched the eligible `CASH_DISBURSEMENT` transaction
net amount over the same date window. The ledger contained no option rows, so
there is no lot-level option realization evidence.

On 2026-07-26, the cash-attribution source contract was tightened after a
blocked paper/TOS account packet with a numeric balance could otherwise have
been presented as broker-confirmed cash. A cash value is now accepted only
from a fresh, healthy, read-only Schwab artifact in live mode with a configured
approved suffix. Rejected sources retain no cash or NLV value and use the
explicit `untrusted-account-source` state.

## Falsifier

If the account source is blocked, paper, unscoped, stale, TOS-only, or lacks an
approved suffix, cash attribution must expose no broker-confirmed cash. If the
transaction artifact is unavailable, unverified, stale, its net amounts
do not exactly match the observed cash interval, or an account change cannot be
aligned to a transaction date, cash attribution must return to an explicit
unattributed/review-required verdict. A matched net amount must never be
upgraded to realized P/L without closed-position, lot-level evidence.

## Safety boundary

The adapter has no order, preview, replace, cancel, approval, ticket, universe,
risk-constant, or authority path. It does not persist account numbers, hashes,
OAuth values, or raw transaction descriptions. Broker submission and live
trading remain false, and capital checks remain separate.
