# Paper fill arithmetic and costs — September 7, 2026

This repair makes reported paper P/L accountable to the recorded entry, exit
and quantity. Previously a finite explicit P/L could override those facts,
and the source reconciliation would accept that same number copied into the
fill log, execution and outcome. Matching copies did not prove the arithmetic.

## Supported accounting contract

The existing standard-option convention is a multiplier of 100. Entry and
exit prices are the net strategy premium per position unit, not dollar totals
and not a sum of leg quantities. Quantity is the number of identical position
units. Debit gross P/L is `(exit − entry) × 100 × quantity`; credit gross P/L
reverses the price difference. Amounts reconcile at USD cent precision using
decimal arithmetic. Unknown debit/credit direction, invalid or nonfinite
numbers, nonintegral quantities, negative prices and contradictory P/L fail
closed instead of silently becoming usable observations.

Optional CSV fields:

| Field | Meaning |
| --- | --- |
| `realizedPnlBasis` | `gross` or `net`. Required whenever `totalFees` is supplied. |
| `totalFees` | Total dollar commissions and fees for the entire round trip, every leg and position unit. It is subtracted once, not multiplied by contracts again. |
| `realizedPnl` | Optional supplied P/L. Must match the declared basis; if blank, derive it from the supplied execution facts. |

A net declaration requires known fees. Blank fees remain unknown; zero is an
explicit operator-reported zero, never a default. Negative fees or rebates
are outside this simple total-cost contract and need separate reviewed support.
Legacy rows without either new field must match gross arithmetic and remain
labelled `gross; fees unknown`. Adding blank columns does not change their
legacy import fingerprints. Supplied costs and basis participate in the new
fingerprint and must agree with the stored execution record.

The lab uses net P/L whenever the source and recorded fee metadata reconcile.
The original reported outcome remains unchanged when it was reported gross.
Its return-on-risk denominator remains the existing fill-adjusted premium/payoff
risk, before fees; this repair does not alter risk limits or claim an all-in
cash-return denominator. Unknown-fee observations remain gross, with explicit
counts in the lab, completeness report and doctor. They are not validated net
expectancy. Statistical thresholds and promotion authority are unchanged.

Actual fill prices already describe the execution. This calculation does not
subtract hypothetical slippage a second time or invent a broker fee schedule.

## Measured result and falsifiers

The existing DELL record still reconciles: entry 1.80, exit 2.10, one position,
$30 gross on $180 fill-adjusted premium risk (0.166667 R). Fees are absent, so
net P/L remains unknown. There is still one source-reconciled paper outcome,
zero independently verified executions, and no new paper promotion progress.
MOD and IREN remain excluded intrinsic estimates.

Adversarial tests establish that:

- A forged $9,999 P/L repeated consistently across source, execution and outcome
  is excluded when the prices imply $30.
- Gross and net reporting of the same fills and $2.60 total fees both score
  $27.40, without changing the gross historical outcome.
- A fixture with $30 gross and $35 total fees becomes a $5 net loss.
- Multiple-position fees are subtracted once, fee edits invalidate provenance,
  zero differs from missing, and invalid/ambiguous fee bases block intake.
- Legacy CSVs remain readable and new fee fields survive normalization.
- Preview reports the rejection reason and saves no ticket or ingest report.

These are fixture checks, not newly observed trades. A contradictory row being
counted, fees being silently zeroed or multiplied twice, or a net declaration
without known costs would falsify the repair.

## Intake isolation and authority

Tests uncovered an existing Downloads helper that initialized the sandbox's
global files even when intake pointed to a temporary fill log. It added the
two new blank columns to the workspace CSV; no fill values changed. The exact
original CSV bytes were recovered and verified against the pre-run hash.
The helper now initializes only its configured file, with a regression that
keeps an unrelated workspace file byte-identical. A later existing schema
writer added the empty columns again; final verification compares all original
CSV cells, which remain identical, and verifies that both added fields are
blank. The five other protected files remain byte-identical. This narrow compatibility
and isolation repair crosses the reserved Downloads lane under the operator's
continued instruction to take over while Claude is unavailable.

Schema upgrades occur only through existing writer paths. This repair neither
runs an operator fill import nor approves, rejects, stages, closes or promotes
a ticket. No risk constants, eligible universe, broker submission or schedules
change. The audit/report paths stay read-only with respect to execution data.

## Limits and next step

This is operator-log arithmetic, not independent broker proof. Contract-level
identity, adjusted deliverables, partial exits, assignments, financing and tax
accounting are not established by this aggregate row schema. The OIC describes
standard equity-option premiums per share and usual 100-share units, while
also noting corporate-action adjustments; those cases require their actual
contract specifications. [OIC Options Basics](https://www.optionseducation.org/optionsoverview/options-basics).

Next: retain immutable source evidence and link individual execution facts and
cost records before treating the outcome set as suitable for tuning entry/exit
thresholds. Missing evidence must remain an explicit blocker, not a modeled
replacement for a fill.

## Validation

- 89 focused tests and 2,083 full repository tests passed.
- First full run caught an old end-to-end fixture using an order-type string
  for entry cost direction; the fixture now uses the actual `debit` enum.
- Math verifier: 12 artifacts, zero violations. Secret hygiene: healthy.
- Doctor: 11 existing attention items. Its strategy-lab line now reports one
  observation with unknown fees and zero net-of-reported-fee observations.
- Read-only lab, lineage, completeness and preview refreshed. Preview imported
  zero rows, changed zero tickets, and earned zero accepted progress.
- Paper ledger, actual ingest report, risk/config files and local environment
  hashes match pre-run values. Original fill CSV cell values match exactly;
  the two optional added columns are empty. No claim of new execution proof.
- Authority manifest remains paper-evidence-only, live and broker-submit off.
- `git diff --check` is clean. No schedules or deployed entrypoints changed;
  existing runners import these repository modules.
- A final guarded full-suite run also passed all 2,083 tests with zero
  attempts to initialize global fill-schema paths.
