---
type: research-belief
status: diagnostic-only
date: 2026-09-06
tags: [entries, exits, pnl, assumptions, research-only]
---

# Entry exit economics contract

Belief: exit percentages need explicit economic denominators and realizable
contract quantities. Neither a high target nor a frequent small win establishes
positive net expectancy. Entry fill changes must update both reward and risk.

Evidence: September 4 saved ORCL call spread risks $275; 50% of maximum
profit is $112.50 (40.91% on maximum risk). Against a $137.50 stop this implies
a 55% two-outcome break-even rate before costs; against a full $275 loss it
implies 70.97%. Neither is a forecast. Five of 17 saved structures have a
planned credit-stop loss beyond their maximum loss; two require fractional
strategy units to execute their existing debit-spread ladder.

Durable rules:

- Missing legs never create a partial position's P/L or a price-triggered exit.
- Actual paper entry fills outrank planning limits. Match quantity and both
  credit/debit payoff denominators. Missing/corrupt fills stay unknown.
- Midpoint marks and bid/ask liquidation stress are gross quote estimates.
- A -50% stop is not a guaranteed 50% loss cap.
- A 50/25/25 runner ladder at +50/+100/+200 returns +100% if filled exactly;
  one strategy unit cannot execute it. Do not increase size to fit the ladder.
- A frozen event countdown must age from a dated source. Release time stays
  unknown. No option mark is required to identify a valid calendar trigger.
- A campaign exit rule, an advisory playbook trigger and a confirmed exit fill
  are separate records. Repeated advice is not repeated action.

Falsifier: fixed chronological comparisons with original option quote paths,
actual fills/fees and event grouping show a stable net-R/downside advantage
for an existing entry/exit rule across later events. Current quote-path and
legacy-label coverage cannot establish that result.

Code: `inferno_paper_mark_to_market`, `inferno_trade_management.exit_economics`,
`inferno_trade_management.event_timing`, and the existing score-threshold
audit. Regression cases are in `tests/test_inferno_entry_exit_contract.py`.
See [[ENTRY_EXIT_REVIEW_2026-09-06]] and [[Premium Universe Fit]].

Validation: 84 focused tests and 2,010 full-suite tests pass. All 12 math
artifacts pass invariants; secret hygiene and diff checks are clean. No ledger
writer was invoked. Research-only and broker-submit-off invariants remain
verified. This manual engineering audit earns zero promotion or paper-progress
points; provider cost telemetry is unavailable, not zero.
