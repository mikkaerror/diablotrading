# Guardrails and the full infrastructure cycle

September 10, 2026. Research-only review. Runtime scores, risk constants,
eligible universe, operator decisions and broker authority remain unchanged.

## Judgment

The account and execution protections have valid purposes. Several discovery
rules are too narrow for a multi-year infrastructure thesis, and some metric
semantics need correction before trusting their ranks. A blanket relaxation
would mix these very different problems.

Our research now discusses the wider industry, but the production rank still
emphasizes a small earnings-oriented subset and generic valuation buckets. We
are not yet measuring the full investment case consistently enough. Improving
that requires more than adding names to the morning report: the same operating,
financing, valuation and horizon questions need to be applied to each name.

The goal is substantial per-share upside with enough capital remaining to
participate through uncertainty. More aggressive discovery and more precise
capital discipline are compatible. None of this sets a return ceiling of 3–5%.

## New evidence from the actual rules

The [reproducible audit](../outputs/guardrail-audit-2026-09-10/gate-attribution.md)
uses the September 10, 16:29:04 Mountain saved edge report. It preserves all
40 scored rows, numeric scores, theme penalties and existing thresholds, then
removes one Boolean requirement at a time. It reproduces every saved lane
before comparing changes. This measures gate attribution, not future returns.

| Isolated comparison | Baseline | Result | Interpretation |
|---|---:|---|---|
| Remove only the 21-day earnings requirement | 0 catalyst candidates | 4: ASML, CHKP, FFIV, TDC | The event window binds otherwise passing names; they need a different horizon, not fictional upcoming earnings |
| Remove only catalyst edge, confirmation, trigger, readiness or theme requirement | 0 | 0 for each separate removal | Lowering a single score is not the main explanation for this snapshot |
| Remove only long-term score >=6.5 | 2 ownership candidates | 6; adds ASML, CHKP, FFIV, OTEX | This composite score merits an independent usefulness test |
| Remove only ownership quality, support distance, edge or theme requirement | 2 | 2 for each separate removal | The other gates still constrain the sample; this does not prove each removed gate is useful |

Failure counts overlap: 38/40 fail the earnings window, 32/40 are unclassified,
and 34/40 fail catalyst edge. The current 40-name subset covers only 40/183
tracker names. Removing the theme gate does not erase its contribution to the
already-saved edge score. Consequently these counts cannot estimate what full
coverage and corrected classifications would do. No gate removal here creates
an eligible order, profitable trade, or proof that looser rules work.

The earlier coverage finding remains relevant: selection happens before business
evaluation. The morning report now requests 5–10 names as a starting range,
uncapped additional worthwhile coverage, and explicit gaps. That expands the
research presentation; it has not repaired production classification or ranking.

### Two defects and one unvalidated modeling choice

**Negative P/E receives favorable valuation credit.** With other inputs held
constant, the actual function gives P/E -10 and +20 the same valuation score of
94, versus 70 at P/E +100. The test row has long-term score 8, P/S 5 and beta 1.
An earnings loss is not evidence of a bargain earnings multiple. The current
cache contains eight negative effective P/Es, including three names in the
40-row sample: SMR, CCOI and LUNR. Cache values are not proven identical to the
metadata at scoring, so this is a potential footprint, not a reconstructed
historical score correction. Proposed repair: explicitly represent nonpositive
P/E as not meaningful and evaluate loss-making companies through appropriate
revenue, margin, cash and financing scenarios. Do not arbitrarily award zero
quality or best valuation.

**Past earnings dates can pass the catalyst date predicate.** Its check is
`days <= 21`, whereas the timing-score function requires `0 <= days <= 21`
for maximum timing credit. A synthetic -1-day row with otherwise passing
inputs enters the catalyst lane. No negative-day row is present in the frozen
40-name sample. Proposed repair: a consistent valid forward event interval,
with missing, invalid and unconfirmed dates kept explicit. This is date
validation, not a reason to remove the earnings window from earnings trades.

**Growth above 50% earns identical growth credit.** The actual quality function
returns the same score when only revenue growth changes from 50% to 200%.
This clipping may control extreme inputs, but it also discards differences
central to early product ramps. It is an unvalidated modeling choice rather
than automatically an arithmetic error. Test a source-checked, robust growth
feature with sequential acceleration, margin and cash conversion. Do not
assume unlimited growth credit improves returns.

Source: [edge research implementation](../inferno_edge_research.py).
The audit executes extracted pure functions, without production imports,
provider refreshes, cache writes or gate changes.

## Which protections make sense

| Guardrail | Judgment | What should change or be tested |
|---|---|---|
| Operator controls orders, ticket decisions and risk policy | Keep | Research breadth must not imply order authority |
| Quote identity, timestamps, spread liquidity and full option payoff | Keep | Judge data for the actual session and instrument; missing quotes can block an order while the stock remains on the research list |
| Account loss and correlated exposure limits | Keep the purpose | Verify the denominator, complete spread structure and shared stress; the exact percentages require operator policy and evidence |
| Raw peak-NLV drawdown as a performance label | Measurement review required | Withdrawals/deposits can move NLV without investment returns; retain the existing capital restriction while reconstructing cash-flow-aware performance |
| Earnings window on an earnings trade | Keep a valid dated window | Separate multi-quarter ownership and operating milestones so the window does not control all discovery |
| Unmapped industry means ignore | Inadequate for discovery | Show unresolved classification, source the economic role and preserve research visibility |
| One composite score and fixed cutoffs | Unvalidated | Compare incremental value against simple baselines, with missing inputs and repeated signals exposed |
| Same option move bounds for every company | Re-specify and test | Compare same-horizon premium, implied move and historical outcomes; name-relative context can reveal excessive as well as insufficient restriction |
| Fixed ownership sleeve and automatic dip tranches | Planning assumptions | Compare opportunity cost and funding milestones; price below cost basis does not justify more capital |
| Generic small profit target for all positions | Poor match to ownership | Use thesis, valuation and concentration reviews for shares; use payoff remaining and expiration for event contracts |

The existing raw drawdown formula is `(peak NLV - current NLV) / peak NLV`.
A hypothetical account going from $2,000 to $1,000 solely by withdrawal would
show 50% raw drawdown with zero investment loss. Conversely, deposits can hide
losses. That demonstrates why attribution matters; it does not establish what
happened in the operator's account or justify removing the current restriction.
Source: [capital scaling](../inferno_capital_scaling.py).

The earlier long-vol review identified a real inconsistency: one function uses
absolute 10–20% event-move bounds while another uses curated name-relative
history where available. Source inspection confirms those mechanisms still
differ. But the proposed 1.6-times-historical-median substitute is not itself
validated profitability evidence. A few earnings observations, uncertain event
dates, and a one-day realized move compared with a multi-week premium can give
a misleading ratio. Preserve event timestamps, comparable horizons, full
distribution and after-cost outcomes. The previous memo's exact population
counts were not re-estimated in this pass.
Sources: [long-vol guard](../inferno_trade_evidence.py),
[historical-move hurdle](../inferno_expected_move_ledger.py).

## The big picture we need to track

Use the full chain:

**End-customer economics → funded commitments → power and construction →
equipment delivery → customer acceptance and utilization → cash generation →
value per diluted share → purchase price and holding period.**

Each step can succeed while a later step disappoints. Hyperscaler capex is a
customer's investment and a supplier's potential revenue; do not add both as
independent demand. Likewise, the same customer may appear in several suppliers'
backlogs. Trace customer concentration through the chain rather than assuming
different ticker symbols represent unrelated demand.

Microsoft's July 29 call gives a useful counterweight to an unlimited-build
assumption. Roughly two-thirds of $41 billion quarterly capex was short-lived
assets, chiefly CPUs/GPUs, and management said hardware deployment could slow
or be staggered if demand changes. Its reported calendar-year capex also changed
with lease classification while investment expectations were unchanged. Our
inference: distinguish committed spend, discretionary installation timing,
lease treatment and recurring replacement economics before comparing headlines.
[Microsoft FY2026 Q4 call](https://www.microsoft.com/en-us/investor/events/fy-2026/earnings-fy-2026-q4).

Physical bottlenecks create opportunities and delays. The IEA describes grid
projects taking 5–15 years versus 1–3 years for data centers. It also describes
faster ways to unlock existing grid capacity. Our inference: track both scarcity
and the technologies or regulatory changes that relieve it; do not extrapolate
today's shortage or supplier pricing power indefinitely.
[IEA Electricity 2026: Grids](https://www.iea.org/reports/electricity-2026/grids).

CoreWeave's Q2 release illustrates why high demand is insufficient as a complete
equity thesis: $2.575 billion revenue and $104 billion reported revenue backlog
coexisted with $640 million net interest expense and a $626 million net loss.
The backlog includes management estimates beyond ordinary RPO definitions.
Those facts do not settle its valuation; they make funding costs and conversion
to distributable cash essential measurements.
[CoreWeave Q2 2026 results](https://investors.coreweave.com/news/news-details/2026/CoreWeave-Reports-Strong-Second-Quarter-2026-Results/default.aspx).

The IEA's July update still forecasts electricity growth of 3.6% in 2026 and
3.8% in 2027, while discussing higher generation costs and geopolitical downside
risks. That supports studying the build cycle alongside power prices, financing
and project economics. These are forecasts, not guaranteed loads or company
revenue. [IEA mid-year outlook](https://www.iea.org/reports/electricity-mid-year-update-2026/executive-summary).

### Different businesses need different clocks and measurements

The periods below are research horizons, not forecasts of stock performance.
Names are research examples from the existing work, not new eligibility or
current buy recommendations.

| Layer | Horizon to study | Measurements that matter | Evidence that weakens the thesis |
|---|---|---|---|
| Compute, memory and interconnect: NVDA, AVGO, ALAB, CRDO, LITE | Product ramps over 1–8 quarters | Design wins converted to shipments, revenue acceleration, gross margin, customer mix, inventory and receivables | Order digestion, rising inventory, substitutions, customer concentration, slowing growth despite optimistic guidance |
| Network systems: ANET | Deployment across several quarters | AI-related revenue quality, port/speed transitions, margins, customer capex conversion | Faster network supply growth than deployments, weaker pricing or customer share |
| Power, cooling and construction: ETN, VRT, GEV, FIX | Backlog conversion over 1–3 years | Organic orders, executable backlog, delivery dates, labor/component costs, cash collection | Backlog aging/cancellation, margin pressure, later energized dates |
| GPU clouds and data-center developers: IREN, CRWV, NBIS, HIVE, CLSK | Commissioning now through 2027–2028 and later | Contract stage, funded capex, energized versus contracted MW, accepted GPUs, utilization, cash interest and dilution | Equity funding gap, delivery penalties, tenant weakness, cheaper competing capacity |
| Solar and longer-cycle energy: TE and relevant energy names | Factory/energy milestones over multiple years | Funding, permits, yield, binding offtake, project economics and tax/policy exposure | Unfunded capital need, commissioning delays, economics dependent on unverified assumptions |

Power capacity is not interchangeable across these rows. Grid allocation,
contracted power, energized facility power and critical IT load need separate
fields. GPU counts require a generation and configuration. A lease LOI, a
signed conditional agreement and live billable revenue need separate statuses.

Your pricing experience can sharpen this work through testable questions:
Are customers paying more to secure scarce capacity? Are commitments binding?
Are realized prices holding as capacity arrives? Who absorbs power, equipment
and financing cost increases? What could cause customers to delay acceptance?
These connect the industry thesis to facts that can change a position decision.

### Put the upside through a per-share test

For a positive-profit business, a deliberately simplified scenario is:

`share-price factor = revenue factor × net-margin factor × P/E factor ÷ diluted-share-count factor`.

This assumes consistent periods and net income attributable to common shares;
it is not appropriate for loss-making businesses and is not a price target.
Even doubling revenue with unchanged net margin, a 30% lower earnings multiple
and 25% more shares yields `2 × 1 × 0.7 / 1.25 = 1.12`, or just 12% price
appreciation before dividends. Conversely, operating leverage, stable valuation
and controlled dilution can allow equity returns to exceed revenue growth.

For a loss-making developer, model delivered capacity, utilization, realized
pricing and costs to cash generation, then financing, debt/lease claims and
dilution to equity value. Use a range of outcomes including delay and funding
stress. Do not make negative P/E meaningful by taking its absolute value, and
do not capitalize an entire 20-year contract as today's equity value.

## Concrete next decisions

1. Correct metric semantics before tuning scores: P/E validity and future-event
   dates, with a full-universe impact diff and regression cases. These fixes
   should be reviewed separately from any threshold relaxation.
2. Complete sourced economic classifications and expose every missing input;
   keep the expanded daily watch coverage independent of ticket eligibility.
3. Compare a supplier/infrastructure ownership case with a developer case using
   consistent cash generation, financing, valuation and diluted-share scenarios.
   This is the missing link between a compelling industry and attractive stock.
4. Define and freeze a separate longer-horizon research challenger. Evaluate
   later outcomes against the present method and a simple sector benchmark,
   including rejected names, turnover, cost, drawdown and capital requirements.
5. Preserve limits while reconstructing cash-flow-aware account performance and
   verifying whole-position exposure. A wealth objective does not identify an
   optimal risk percentage; scenario losses and recovery capacity make that
   choice concrete for the operator.

Completed here: gate attribution, pure-function defect demonstrations, a
potential affected-name inventory and a full-cycle measurement framework.
Not completed or claimed: production repair, fitted thresholds, optimal sizing,
forecast returns, live realized profit or new trading authority.
