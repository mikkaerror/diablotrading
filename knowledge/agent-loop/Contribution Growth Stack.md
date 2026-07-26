# Contribution Growth Stack

## Belief

When the account base is small, recurring planned deposits can materially outweigh a plausible one-year percentage return on the starting balance. The desk should expose that relationship from canonical account and deposit-plan artifacts instead of optimizing hypothetical strategy returns in isolation.

## Evidence

The research-only `inferno_growth_stack.py` reads broker NLV and the operator's deposit plan, then reports flat, 4%, and 8% mechanical scenarios with the deposit and market components separated. It marks planned contributions as non-deployable in every payload. It also exposes one-, seven-, and thirty-day observed NLV deltas using the nearest available on-or-before baseline; each row records its actual span and is explicitly unavailable to both performance claims and execution.

## Falsifier

If the saved deposit plan is missing, incomplete, or only a default assumption, the stack must not invent a schedule. If broker NLV or scheduled contributions are unavailable, it must return an explicit incomplete verdict rather than presenting a confident projection.

## Safety boundary

This layer is a forecast only. It cannot change the eligible universe, risk constants, paper tickets, broker submission, or live-trading authority. NLV deltas may include deposits, withdrawals, purchases, sales, and fees, so they remain unattributed account movements rather than returns or P/L.
