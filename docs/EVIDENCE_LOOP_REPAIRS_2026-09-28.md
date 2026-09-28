# Evidence-loop repairs — 2026-09-28

## Research duplication

Shadow ingestion now admits one contract exposure per fixed hold-to-expiration
protocol, regardless of report date. Existing rows, prices, entry features and
outcomes remain unchanged; legacy duplicate rows are not compacted or deleted.
New quotes for an existing experiment remain in archived strike-plan snapshots.
Changing an entry date does not create an independent earnings observation.
Incomplete contract identity is not guessed or collapsed.

Fast simulations use a different, next-session quoted-liquidation protocol.
Repeated contract/price/quote inputs are suppressed even under a new report date;
new observed quotes/economics may support a deliberate later entry. Reported
selected counts now reflect actual insertions, not merely proposed candidates.
These two exit protocols remain distinct experiments and share exposure grouping;
they are not independent confirmations of market edge.

Both producers freeze supplied IV/rank, scores, earnings distance and option
quote context at entry. Missing inputs remain unknown. Historical records are
not backfilled. No existing ticket is approved, rejected or closed by this
repair. No risk constants, authority, universe or promotion evaluator changes.

The shared identity matches the decision archive's contract exposure grouping.
Suppression counters distinguish repeated work from new experiments. Unattended
loops should back off when there are no changed inputs or newly eligible exits.
An explicit future protocol revision is required for a new shadow entry/exit
experiment on the same contract; report timestamps are not protocol versions.

## Authority and deployment boundaries

Cloud/local canonical ownership and off-device backup destination were requested
from the operator. Until answered, no ledger migration, sender/inbox cutover,
cloud deployment, paper-budget change or external upload occurs. Local source
repairs apply when the existing jobs import the updated modules. Pure replay
checks and isolated tests do not write runtime ledgers.

## Broker transaction provenance

The old normalizer kept only the first transfer item. The current API response
puts currency/fee items ahead of option legs, hiding eight option transactions.
The adapter now retains an explicit redacted allowlist for every transfer item,
including signed quantity, position effect, instrument, cost and fee type.
Parent cash is counted once; exact duplicate broker IDs are suppressed within an
account, while conflicting versions block replacement for review. Failed refreshes
retain the last good JSON/CSV with explicit stale-evidence timestamps.

Only single-security parent transactions with valid IDs, dated opening/closing
quantities, all reported costs and exact parent-cash reconciliation enter the
balanced-contract diagnostic. Open quantities, unmatched closes, missing costs,
canceled records and multi-security allocation gaps stay unresolved. No fee
allocation or tax-lot convention is invented. Four matched contract groups in the
2026-09-28 read reconcile to $64.35 net cash. These are not four independent
strategy events, a complete account return, or sweepable capital.

Normalized transaction snapshots now enter the append-only archive, keyed by
account suffix and broker transaction ID. No raw description, account number,
account hash or token is added to the archive. Corrections append new versions;
a rolling API lookback no longer erases previously captured transaction history.

## Forward collection: reuse the registered experiment

The short-premium campaign already has a dated protocol in
`SHORT_PREMIUM_PREREG_2026-07-07.md` and a 2026-10-05 deadline. Creating another
campaign would duplicate work. The existing daily research audit now separates
pricing, construction/economics, risk, combined-gate readiness, campaign paper
rows, source-reconciled events and reported-cost events. It records the first
blocking stage per candidate; simultaneous later blockers can also exist.

The current saved batch contains 40 candidates: 31 have no usable pricing and
nine fail construction/economics; none passes the combined gate. There are no
campaign paper rows or reported-cost events. This is a collection bottleneck,
not proof that the strategy works or fails. The batch is not the full universe.
The deadline is surfaced without extending it. A future restart or evaluator
revision must be registered separately; historical simulations cannot be relabeled
forward evidence. The current study's permissive record normalization (including
unknown event dates and default-zero friction) also needs a separate measured
review before its confirmation labels can be trusted as protocol compliance.
No campaign evaluator, thresholds, universe or routing changes are made here.

The alternative-pricing artifact now joins the append-only archive, including
unpriced and rejected proposals and their source reasons. Research audit source
hashes identify the observed inputs. The collection-state fingerprint excludes
report timestamps and remaining-day countdowns, so rerunning unchanged evidence
is visibly not a new collection result; crossing the existing deadline is a state
change. This diagnostic does not alter scheduler cadence or email delivery.

Next useful acquisition work is to explain the 31 missing option-chain cases
using existing read-only coverage tools. The nine construction failures warrant
research with frozen rules and counterexamples, not threshold relaxation. Fee
capture for the one existing qualified paper event remains a separate source gap.
