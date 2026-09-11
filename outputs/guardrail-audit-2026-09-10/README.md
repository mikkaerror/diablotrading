# Isolated guardrail audit

Run `python3 outputs/guardrail-audit-2026-09-10/audit.py` to reproduce.
The optional `--freeze` replaces the research input snapshot from local artifacts;
do not use it when reproducing the September 10 results.

`frozen-inputs.json` contains only public-market research fields, extracted pure
source functions, source timestamps and protected-code hashes. The audit does
not import production modules, refresh data or write any runtime policy file.

Checks reproduce all 40 saved lanes and independent lane predicates, assert
monotonic one-gate removals, and demonstrate negative-P/E, past-event and
growth-clipping semantics with synthetic inputs. It produces `audit.json` and
`gate-attribution.md`. These checks characterize existing behavior; they do not
endorse defective semantics or establish predictive performance.

Read [the interpretation and cycle framework](../../docs/GUARDRAILS_AND_CYCLE_REVIEW_2026-09-10.md)
before using the counts. The selected sample, theme score penalties, stale or
missing metadata and absence of future outcomes limit what can be concluded.
