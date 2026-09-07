# Entries, exits and gain percentages — 2026-09-06

The next improvement is an internally consistent entry/exit contract. A gain
target must identify its denominator, a stop must be treated as an execution
trigger, and a scale-out must fit the number of whole contracts actually held.
None of the existing 50/100/200% targets or time stops is established as optimal
for the desk's semiconductors, construction stocks or earnings trades.

## What “50% gain” means on the saved structures

September 4 alternative-pricing snapshot; gross, single-unit calculations.
These examples explain saved payoff geometry and are not executable quotes.
The policy comparison assumes the entire position exits at the first target;
a partial close earns only the closed fraction of the stated dollar gain.

| Saved structure | Defined max loss | First target gain | Gain / max risk | Planned stop loss | Break-even hit rate: target vs planned stop | Target vs full loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ORCL 160/165 call debit spread | $275 | $112.50 | 40.91% | $137.50 | 55.00% | 70.97% |
| ORCL 145/144 put credit spread | $85 | $7.50 | 8.82% | $15 | 66.67% | 91.89% |
| ORCL 160/157.5 put debit spread | $175 | $37.50 | 21.43% | $87.50 | 70.00% | 82.35% |

The break-even columns are two-outcome algebra, **not win-rate predictions**:
`loss / (target gain + loss)`. They omit fees, slippage, intermediate exits,
partial fills and the actual distribution of losses. If every trade incurs
the same total cost C, the corresponding rate is `(loss + C) / (gain + loss)`;
if C exceeds the gross target, even the assumed winner loses money net.

Option ROI, profit as a share of maximum profit, return on maximum risk, stock
return and account return are different quantities. A stock moving through a
spread's short strike caps its expiration payoff; that is not a promise that
an early exit can collect the full spread value. See [OIC bull call spread](https://www.optionseducation.org/strategies/all-strategies/bull-call-spread-debit-call-spread).

## Entry price changes the exit math

For the same $5-wide call spread, using the existing first target of 50% of
maximum profit and stop of 50% of debit:

| Illustrative entry debit per share | Max profit | First target | Planned stop loss | Two-outcome break-even hit rate |
| --- | ---: | ---: | ---: | ---: |
| $2.50 | $250 | $125 | $125 | 50% |
| $2.75 | $225 | $112.50 | $137.50 | 55% |
| $3.00 | $200 | $100 | $150 | 60% |

Paying 25 cents more than the saved $2.75 entry both reduces the target and
increases the downside. This is an illustration, not a proposed limit order
or a new admission threshold. Compare the actual fill to the planned limit;
do not keep the more attractive planned percentages after a worse fill.

For credit spreads, collecting less credit similarly lowers maximum profit
and increases maximum loss for the same wings. MTM previously corrected this
only for debit entries. It now reconciles both sides and actual whole-unit
fill quantity. The credit stop uses total credit actually received.

## Exit assumptions under challenge

- **Fractional scale-outs:** The current paper convention is one strategy
  unit. Two of 17 saved priced structures use debit-spread rules calling for
  halves. A runner's 50/25/25 ladder needs at least four equal units. The audit
  exposes the mismatch; it never rounds or increases size. Closing one leg
  of a spread is not a partial exit from an intact strategy unit.
- **The full runner ladder earns +100%, not +200%:** Exact sequential fills
  yield `0.5 × 50% + 0.25 × 100% + 0.25 × 200% = 100%` on initial debit.
  After the first trim, gross cash recovered is 75% of initial debit; losing
  all remaining value leaves a total 25% loss. After the second trim, recovered
  cash is 125%, giving a 25% gross floor if the remainder becomes worthless.
  Partial-exit history is not yet reconstructed by the management report;
  repeated “trim” labels must not be treated as completed fills or new orders.
- **Stops can conflict with payoff bounds:** Five of 17 saved structures
  have a one-credit loss trigger above their defined maximum loss: QCOM,
  IREN, FFIV, ORCL and ACN in the short-premium arm. For ORCL, a $390 loss
  trigger is larger than its $110 defined maximum loss. That trigger cannot
  provide earlier protection inside the modeled payoff envelope. Thresholds
  are unchanged; execution costs or distressed quotes can depart from that
  envelope and must not be treated as guaranteed bounds on actual exit costs.
- **Stop price is not realized loss:** Gaps and liquidity can prevent a fill
  near the trigger. This matters when buying volatile names around an event.
  [Schwab explicitly distinguishes activation and execution prices](https://www.schwab.com/learn/story/three-types-options-exit-strategies).
- **Midpoint P/L is not liquidation evidence:** The MTM now separately reports
  a quoted liquidation stress (long legs at bid, shorts at ask). Neither is a
  guaranteed fill; both exclude fees. Missing legs or invalid numbers suppress
  position-level P/L rather than constructing a partial position's result.
- **An entry-day countdown cannot drive a later exit:** The management report
  used frozen days-to-earnings as if current. It now prefers explicit event
  dates or reconstructs an explicitly labelled date from a dated count.
  Undated counts remain unknown; release time is not inferred. A valid
  calendar exit no longer disappears when the option mark is missing.
- **Entry thesis must match exit timing:** A pre-event volatility run-up and
  holding through an earnings jump are different trades. Current Lane A
  remains pre-event by default; the pre-registered short-premium campaign
  retains its own evidence/exit policy. This report is advisory and does not
  modify campaign assignments or execute the playbook.

## Repairs delivered

1. Incomplete first/last legs, missing instructions, empty positions and
   nonfinite inputs cannot produce fabricated P/L or crash a partial quote
   refresh. A known partial/error MTM cannot fire price-based management rules.
2. Actual paper fills and contract counts determine credit/debit dollar and
   percentage economics. A corrupt reported fill cannot fall back to a more
   convenient planned entry. Planning-limit returns are labelled estimates.
3. `exitEconomics` exposes target/stop dollars, return on maximum risk,
   first-target/full-loss stress, integer-unit feasibility and runner cash-flow
   arithmetic in the existing management and threshold-audit reports.
4. The existing `SHORT_PREMIUM_DEFINED` strategy name maps to the credit
   playbook instead of silently falling through to “hold.” Unsupported
   strategies now report missing management coverage. The campaign's own
   hold-through evidence policy remains separate and unchanged.
5. The historical playbook no longer asserts unsupported typical 3–10× gains,
   family win rates or that a roll necessarily reduces losses. Risk constants,
   target percentages, time thresholds, tickets and authority remain unchanged.

## What to test next

Predeclare a comparison of whole-position exits versus feasible scale-outs,
using actual contract counts and identical entry snapshots. Separate event
run-up, hold-through and ordinary trend hypotheses. Evaluate later events in
chronological blocks, keeping every ticker/event's variants together.

Record gross and net option R, drawdown, holding time, missed fills, costs and
remaining exposure after partial exits. Include gap losses and unfilled stops.
Intraday target/stop claims require timestamped option quotes: daily stock
high/low or expiration intrinsic value cannot prove which option exit filled
first. A high win rate or more closed rows alone does not establish improvement.

The current ledger has zero open positions, three closed and 102 not-opened
records. No current ticket needed an exit and no ledger writer was invoked.
Legacy label integrity and limited option quote paths remain research blockers.

Validation: 84 focused and 2,010 full-suite tests pass; all 12 math artifacts,
secret hygiene and whitespace checks pass. Doctor retains operational
attention items with broker submission off. The manual run outcome is recorded in
[[Entry Exit Economics Contract]] and `data/inferno_entry_exit_audit_run.json`.
See [[PREMIUM_UNIVERSE_REVIEW_2026-09-06]] for premium/tenor evidence and
[[MODEL_CALIBRATION_REVIEW_2026-09-06]] for outcome lineage limits.
