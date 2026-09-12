# Conviction assumptions and threshold audit

See [the big-picture review](../../docs/ASSUMPTIONS_AND_BIG_PICTURE_2026-09-12.md).

The folder date identifies the frozen September 11 research inputs. The review
was completed for the September 12 task. No account balances, holdings or ticket
details are included. `frozen-inputs.json` projects public tracker fields and
saved edge scores, records input/protected hashes and retains baseline pure
functions. `revised-source.py` is an inert frozen reference, not a production
entry point. `audit.py` evaluates functions with provider/broker imports removed.

From the repository root:

```sh
python3 outputs/assumption-audit-2026-09-11/audit.py --verify
python3 -m unittest tests.test_inferno_conviction_research tests.test_inferno_score_threshold_audit
```

The audit first matches all six saved score/action/grade/flag fields for all 183
names. It then computes the semantic-repair effects and single-score selectivity
on that fixed population. It writes only its own `results.json` unless `--verify`
is supplied. `--seal` is a one-time capture option that refuses to overwrite the
corrected source. `provenance.json` holds the separate source-label projection,
captured only after verifying the tracker hash still matched the freeze.

No later outcomes enter the comparison. Single-cutoff counts do not establish
combined eligibility or predictive value. Existing source penalties, missing
defaults, category weights and thresholds are preserved and remain hypotheses.
