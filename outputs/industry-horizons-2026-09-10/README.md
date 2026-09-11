# Industry and timeline research

Read [research.md](research.md). The PDF is at
`../../output/pdf/ai-infrastructure-industries-and-timelines.pdf`.
Twenty-four public sources and a local evidence bundle support the assessment.
Issuer guidance remains a forecast. Prices, consensus histories and option
chains were not refreshed; research priorities are not buy rankings.

## Reproduction

From the repository root:

```sh
python3 outputs/industry-horizons-2026-09-10/profile.py
```

This reads `frozen-inputs.json` and recreates `coverage-audit.json`, checking
unique ticker grain, joins, and the original 40-name selection. The taxonomy
comparison uses existing category rules on existing reference metadata. It
does not change scores or eligibility. `coverage-audit.ipynb` includes an
executed companion cell; `profile.py` contains the complete checks.

`sources.json` preserves citations and original URLs. Frozen source hashes and
individual generation times preserve provenance. Account holdings are omitted.
With ReportLab available, `build_report.py` recreates the PDF, source inventory
and notebook. `validation.json` records final checks.

Do not run `profile.py --freeze` when reproducing: it replaces historical
research inputs with current files. No production modules are imported and no
network, broker or ticket action occurs.
