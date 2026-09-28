# Research measurement audit — 2026-09-28

The desk has an extensive research system, but it does not yet have evidence of
repeatable, deployable net returns. The immediate bottleneck is trustworthy
measurement and prospective observations, not a shortage of scores or reports.
This review complements Claude's [desk audit](DESK_AUDIT_2026-09-28.md). It does
not adopt its proposed risk, ranking or delegated-decision changes.

## Evidence and reproducibility

Codex froze 18 saved JSON inputs before repairs in
`outputs/research-audit-2026-09-28/inputs/`, with SHA-256 hashes and source dates
in `manifest.json`. A separate private fill-source receipt permits replay of the
existing paper qualifier. Outputs are local evidence, not checked-in account data.
`audit.json`, `audit.txt` and `before_after.json` record the comparison.

These are saved observations, not an independent broker audit. Generated times
can describe refresh attempts; they do not establish when underlying observations
were collected. Paper and shadow ledger creation timestamps can also precede
later updates. Counts below use the frozen sources, not a changing live report.

| Question | Observed evidence | Interpretation |
|---|---|---|
| Have paper returns been demonstrated? | 105 paper rows; 3 reported closed estimates; **1** source-reconciled fill/event; **0** with reported costs | One gross outcome is not net expectancy. The two other estimates are a separate population. |
| How much independent evidence exists? | 1,518 shadow rows; 1,025 closed; 1,021 usable by existing R diagnostics | Four closed rows lack usable positive risk/P&L. Volume is not independent sample size. |
| Are historical labels suitable for model selection? | Calibration: 713 premature settlements, 191 unverified settlement times, 1,016 legacy/unverified entry-score rows | Archive is descriptive. Do not silently repair labels with later information or train a gate on them. |
| Are repeated rows independent? | Calibration: 1,024 usable option records, 154 source/ticker/expiration groups, 870 repeated exposures | Exposure groups are proxies; they are not verified independent earnings events. Different diagnostic filters explain count differences. |
| Is issuer research complete? | 24 issuer-linked rows; 159 due; conviction grades B=3, C=17, D=163 across 183 names | Provider coverage is not a current issuer thesis. Missing research is not evidence against a company. |
| Is the short-premium idea validated? | 65 backward observations; zero forward events/names against the study's 60-event/40-name targets | Synthetic favorable results omit tradable wing/cost detail and are hypothesis generation only. |
| Can cash changes be called returns? | Realized options profit remains unproven in cash attribution | Deposits, transfers and incomplete lots prevent that inference. |
| Is more automation producing outcomes? | Last loop promotion evidence delta 0; 3/10 full runs accepted for other progress | Repair progress matters, but is not trading performance or new qualified outcomes. |

## Repairs applied

1. **Restore diagnostic input coverage.** Walk-forward and factor regression
   loaded legacy `records`/`entries`/`rows`, while the actual producer writes
   `items`. A shared adapter reads the canonical schema, nested outcome P/L,
   positive finite risk, and observation timestamps without modifying source
   rows. Empty canonical data cannot resurrect obsolete legacy rows. Before:
   both saved reports said no evidence. After: 1,021 rows reach each diagnostic
   (738 straddles and 283 debit spreads). Factor regression now correctly reports no usable varying features instead of
   no evidence. This fixes ingestion, not validity.
2. **Separate evidence and costs.** Expectancy calls the existing paper qualifier
   and groups source-reconciled fills, unverified paper estimates and shadow
   proxies separately. Reconciled risk uses actual entry economics. Reported
   fees are subtracted exactly once; unknown fees leave net return unavailable.
   Modeled net estimates remain visibly modeled and never become reported net
   paper fills. The paper qualifier and authority evaluator are unchanged.
3. **Stop presenting duplicated rows as precision.** Descriptive expectancy
   intervals resample event clusters. A single event receives no interval.
   Drawdown uses outcome chronology and is withheld if timestamps are missing.
   It is explicitly summed trade R, not capital-weighted account drawdown.
   Legacy event IDs remain approximate; clustering cannot repair their lineage.
4. **Make gaps inspectable on every refresh.** `./inferno research-audit` reads
   saved sources and publishes `reports/research_audit_latest.txt`. It exposes
   exact-byte source receipts, missing inputs, known-cost coverage, label and
   feature defects, issuer review debt, forward strategy coverage and observed
   progress deltas. Doctor and command center expose it. The existing daily
   refresh invokes it before the command center. No email or scheduler is added.
   Deployed copies still need the ordinary reviewed deployment process.
5. **Correct model claims.** Diagnostic text no longer presents retrospective
   row splits as proof of edge or logistic coefficients as calibrated causal
   probabilities. Evaluator arithmetic and thresholds are unchanged. The
   walk-forward tolerance uses pooled train/test variance, events can overlap,
   and repeated trials are not adjusted: it is not an untouched holdout.

## Research practice from here

| Area | Required protocol | Measurement of progress |
|---|---|---|
| Knowledge | For actionable names and current holdings, retain dated issuer evidence, valuation assumptions, contrary evidence, thesis horizon and explicit falsifier. Separate business quality from price and trade construction. | Fewer due issuer reviews with inspected sources; no score increase merely for adding a link. |
| Returns | Reconcile positions, fills, fees, corporate actions, cash flows and valuations. Keep gross, modeled-net and reported-net series separate. Compare identical windows and return bases. | Source-complete realized lots and reported-cost fills; reconciliation residuals explained. |
| Strategy | Freeze executable entry/exit rules, quoted strikes/wings, costs and failure criteria before future outcomes. Compare long vol, defined-risk premium and cash/no-trade under the same existing constraints. | New qualified, distinct forward events; missing quotes and rejected proposals retained in denominators. |
| Selection | Register every tested variant, including failures. Freeze the whole eligible universe and selected/rejected cohorts at decision time; specify 21/63/126 **actual trading-session** horizons and price or total-return basis in advance. | Prospective cohort completion, benchmark-relative return, missingness, turnover and concentration. No survivor-only comparison. |
| Validation | Separate events and overlapping label windows across time blocks; fit transforms on training observations only; retain an untouched later evaluation. Do not tune after viewing results without registering a new trial. | Performance versus simple fixed baselines on later data, with clustered uncertainty and costs. |
| Capital | Report trade R, actual-dollar P/L, portfolio weights, shared factor exposure and drawdown separately. Assess whether paper structures fit current deployable size without changing caps. | Source-backed feasibility coverage; no inferred permission to scale. |
| Operations | Separate data repairs, acquisition, hypotheses tested and qualified outcomes. Retain bounded backoff when meaningful state is unchanged. | Full-run acceptance and cost per accepted outcome, with unknown costs labeled unknown. |

These are evaluation requirements, not new production thresholds. Do not widen
risk or the universe to make an experiment succeed. A selected historical
short-premium study does not justify automatic family routing or rejection.
Existing legacy snapshots should remain historical replay cohorts, separately
labeled from cohorts registered before observations became available.

The official [GIPS handbook](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/)
explains why external cash flows and valuation timing matter to time-weighted
returns. Apply that measurement principle; do not claim GIPS compliance here.
Dollar P/L after subtracting net flows is not a money-weighted rate of return.
Actual flow timing, sufficient valuations and complete flows are needed before
using a flow-adjusted series to drive a capital gate.

[CFA Institute's model validation review](https://rpc.cfainstitute.org/research/foundation/2024/investment-model-validation)
supports validating assumptions and model use, not just arithmetic. The authors'
[backtest-overfitting paper](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)
explains why choosing among many trials can manufacture attractive results.
The protocol above applies that concern through trial registration, later data,
fixed comparisons and explicit limitations; it does not claim to have estimated
the desk's probability of overfitting.

## Concurrent work requiring validation

Claude's new account-performance and pick-scorecard modules are preserved.
Their initial claims need qualification before driving decisions:

- Inferred external flows and sparse valuation dates yield conditional return
  estimates. They do not independently establish the exact trading return.
- A September 8 cohort registered on September 28 is retrospective replay,
  even when its inputs come from an authentic September 8 snapshot.
- Calendar-day proxies are not trading-session horizons; price-only SPY is
  not a dividend-inclusive total-return benchmark.
- An unsupported recorded peak deserves reconciliation, not automatic deletion
  or capital-gate relaxation. A changed drawdown series can change permission.

These points were recorded in `model_notes` for coordination, rather than
editing Claude-owned files or silently endorsing new gate inputs.

## Operator boundary and next experiments

Open operator question: after source reconciliation and separate offline
validation, should the capital stepper consume an explicitly defined
flow-adjusted drawdown series? That can change deployment eligibility and needs
its own acknowledgement. This audit leaves the existing stepper untouched.
The earlier cloud paper-budget/ledger-owner question also remains unresolved.

Next research priorities are (1) complete reported costs and source evidence for
paper outcomes, (2) prospectively collect costed, gated short-premium observations,
(3) preserve entry IV/quote/score provenance and actual rule-based exits, and
(4) complete future selected-versus-rejected benchmark cohorts. Proposed score
normalization, ranking caps, family-rejection rules and new routing policies
remain separate runtime-change proposals, not consequences of this report.

Falsifiers: additional source-reconciled outcomes with known costs would change
the present net-evidence assessment; a registered later cohort beating fixed
baselines after costs would change the predictive-value assessment; complete
cash-flow and valuation records would make account attribution testable.
Until then, no measurable increase in validated returns or promotion evidence
is attributed to these code repairs.
