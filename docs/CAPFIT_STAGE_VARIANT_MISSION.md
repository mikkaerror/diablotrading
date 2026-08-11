# Cap-Fit Stage-the-Variant Mission — the final connector (for Codex)

_Filed 2026-08-11 by Claude, from live diagnosis. This is the last link that
makes the operator paper loop actually score._

## The problem
The cap-fit defined-risk route is surfaced as operator-routable, but the
**execution-ledger ticket is the underlying blocked straddle**, so no clean
`paper-staged` ticket exists for `record-fill` to attach to. The loop dead-ends.

## Evidence (live, today)
IREN in `data/inferno_paper_execution_ledger.json`:
```
status=paper-blocked  approvalStatus=approved  intentStatus=approval-ready
ticketId=1be6f96d665a730e  strategy=LONG_STRADDLE
block: long-vol-premium-hurdle, long-vol-size-above-25pct-nlv
```
But the paper-test-director operator-routable route for IREN is the cap-fit
variant:
```
CALL_DEBIT_SPREAD  BUY 40C / SELL 45C 2026-08-28
max loss $200 (~12% of ~$1,629 NLV)  reward/risk 1.50  quote quality 84  liquidity PASS
```
The **debit-spread variant clears both gates the straddle fails**: its $200
defined risk is well under the 25%-NLV size cap, and a defined-risk spread is not
subject to the long-vol premium hurdle the way a naked straddle is.

## The target
When a cap-fit defined-risk variant is the operator-routable route, **record
THAT VARIANT as the `paper-staged` execution-ledger ticket** — with its own
defined-risk profile (the actual spread legs and $200 max loss) — instead of
leaving the blocked underlying straddle as the ledger ticket. Then it is
`paper-staged`, `record-fill` attaches to it, and it can score.

## Hard constraints (this is NOT a gate loosening)
- Evaluate the **variant's real risk profile** through the existing gates. It
  must pass the size gate and premium hurdle **on its own terms** ($200 defined
  risk, defined-risk structure) — do not exempt it, do not relax any threshold.
- The underlying straddle stays blocked. Only the variant that genuinely passes
  becomes staged.
- Research-only. No authority, risk-constant, gate, threshold, eligible-universe,
  or approval change. `liveTradingAllowed` / `brokerSubmitAllowed` stay False.

## Definition of done
A cap-fit defined-risk variant that passes the gates appears as a `paper-staged`
row in the execution ledger (fillable), and `./inferno record-fill IREN --entry
… / --exit …` round-trips it to one scored outcome. Test covers: cap-busting
straddle stays blocked, its passing defined-risk variant stages, record-fill
scores it. Full unittest discovery, math, doctor, diff checks pass; commit per
hygiene rules.
