# Gate-Preserving Cap-Fit Route

## Belief

When the primary long-vol structure is blocked only by ticket size or its
premium hurdle, a separately priced cap-fit debit spread can provide a valid
paperMoney route—but only when the already-fixed pricing and paper-risk
evaluators both pass.

## Evidence — 2026-08-11

- Fresh Schwab research chain: IREN quote quality 84 (`usable`), paper
  liquidity pass, tight ATM spread.
- A 2026-08-28 IREN 40/45 call debit spread passed the existing optimizer and
  paper-risk evaluators: $200 maximum loss within the $500 cap and 1.50
  reward/risk against the unchanged 0.50 floor.
- The paper director now exposes this exact-leg result as an
  `operatorRoutableSlate` entry with `status: stage-in-papermoney`.

## Boundary

This route is report-only. It never creates a paper ticket, changes an
approval, stages an order, enables broker submit, or enables live trading. The
operator must visually verify the quoted legs and key the simulation in
thinkorswim paperMoney.

## Falsifier

Do not route a priced variant when any source evaluator fails, its max loss is
above the active ticket cap, its debit reward/risk is below the configured
floor, its attached Schwab chain is not `ok`/paper-liquid, or the event ticket
cap is reached.
