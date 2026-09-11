# Priority three: what must happen for substantial upside?

September 10, 2026. Research only. ANET and IREN are representative cases,
not a ranking of the entire universe. The model uses September 9 closes of
$192.93 and $45.37 from the frozen read-only price-history response retrieved
September 10. They are dated comparison anchors, not current quotes or entries.

The useful question is how much operating success reaches each share at the
purchase price. For a profitable supplier, earnings growth and the eventual
valuation multiple do much of the work. For a capacity developer, delivery,
financing, equipment replacement and dilution can dominate the answer.

All three-year case inputs below are analyst-selected sensitivities. None is a
forecast, consensus estimate, probability-weighted expected value, or validated
fair value. The middle case is not labeled the most likely case. These selected
cases do not bound possible outcomes. The horizon is an illustrative three years
from the dated price anchor, with terminal annual earnings or revenue; it is not
a claim about a particular fiscal year's guidance. No option payoff is modeled.

## ANET: growth can be excellent and the entry still demanding

Arista reported Q2 revenue of $3.036bn, up 37.7% year over year, and a 45.4%
GAAP operating margin. First-half GAAP diluted EPS was $1.75. These establish
current profitability; they do not establish three more years of similar growth.
[Arista Q2 results](https://investors.arista.com/Communications/Press-Releases-and-Events/Press-Release-Detail/2026/Arista-Networks-Inc--Reports-Second-Quarter-2026-Financial-Results/default.aspx).

The calculation doubles first-half EPS to $3.50 as a simple annualized anchor.
At the dated price, that is 55.1 times annualized first-half earnings. This is
neither trailing-twelve-month nor forward P/E. Seasonality, taxes, investment
income and business mix can make this anchor unrepresentative. Per-share growth
already incorporates the assumed net effect of share issuance and repurchases;
the model does not subtract dilution a second time or add cash separately.

| Three-year assumptions | Terminal share value | Price change |
|---|---:|---:|
| EPS grows 10% annually; exit P/E 30x | $139.76 | −27.6% |
| EPS grows 20% annually; exit P/E 40x | $241.92 | +25.4% |
| EPS grows 30% annually; exit P/E 50x | $384.48 | +99.3% |

A doubling at a lower 40x exit multiple requires approximately **40.2% annual
EPS growth** from this anchor. At 50x, 30% growth nearly doubles the price.
That is the hurdle to investigate: durable earnings expansion plus the price
investors will pay for it. Revenue acceleration alone cannot answer it.

## IREN: demand must become funded, productive capacity

IREN reported $1bn operating ARR as of August 26 and $4bn contracted ARR for
2026 capacity. Its release explicitly distinguishes ARR from recognized revenue.
Horizon 1 had been delivered; Horizon 2 was commissioning and Horizons 3–4
targeted Q4 delivery. FY26 AI revenue was $128.8m within $707.0m total revenue.
These are different measures and periods, not an interchangeable growth series.
[IREN FY26 update](https://www.sec.gov/Archives/edgar/data/1878848/000187884826000051/irenreportsfy26results.htm).

The filing reports $2.1004bn operating cash flow, including a $1.8417bn increase
in deferred revenue. Payments for property excluding hardware were $2.9980bn;
hardware payments were $1.3351bn. Ordinary shares outstanding were 394.059m on
August 14. June 30 capital commitments were $13.810bn, excluding later contracts.
[IREN 10-K](https://www.sec.gov/Archives/edgar/data/1878848/000187884826000052/iren-20260630.htm).

Two arithmetic bridges make the funding distinction visible:

- Operating cash flow minus those property/hardware payments: **−$2.233bn**.
- Removing the deferred-revenue increase from that same bridge: **−$4.074bn**.

The second is a sensitivity to one working-capital item, not normalized free
cash flow. The first also omits other investing outflows. Prepayments provide
useful financing and represent future service obligations. The research must
track both their funding contribution and subsequent cash costs of delivery.

The scenario formula is `(annual revenue × EBITDA margin × EV/EBITDA − net
debt) ÷ diluted shares`, floored at zero equity value. Terminal net debt includes
finance leases and reflects any assumed conversions; the diluted share count
includes assumed issuance. No second conversion adjustment is added. The
terminal capital structures are hypothetical endpoints, not a reconciled plan
for funding construction. Restricted cash is not treated as freely available.

| Three-year case | Revenue | Margin / multiple | Net debt / shares | Share value | Price change |
|---|---:|---:|---:|---:|---:|
| Delay and funding stress | $2bn | 30% / 8x | $6bn / 600m | $0.00 | −100.0% |
| Delivery with continuing capital needs | $4bn | 45% / 12x | $4bn / 500m | $35.20 | −22.4% |
| Scale with strong economics | $6bn | 55% / 16x | $2bn / 450m | $112.89 | +148.8% |

Under the middle capital structure, margin and multiple, approximately **$4.94bn
annual recognized revenue** is needed just to match the dated reference price;
**$9.14bn** supports twice that price. Stronger margins, lower financing burden
and a higher multiple materially lower the hurdle. The upside case deliberately
combines favorable outcomes; it is not assigned an implicit probability.

EBITDA is insufficient for an equipment-intensive business. The companion
models replacement spending, cash interest and taxes separately. The middle case
leaves $350m before growth capex, working capital, principal repayment and further
accounting reconciliation. That partial residual is **not free cash flow**.
Maintenance spending needs a hardware-cohort model with useful lives, renewal
pricing and residual values before we can underwrite a durable cash yield.

## Timing and position research implications

| Window | Evidence to collect | How it changes the thesis |
|---|---|---|
| Next reported quarter | ANET actual revenue, GAAP margin and diluted EPS against dated prior expectations | Establish whether earnings are catching up with the price; do not infer a cheap entry from a pullback alone |
| Through Q4 2026 delivery targets | IREN commissioning, acceptance and recognized revenue; dated contracted-to-operating ARR bridge | Distinguish contracted demand from accepted, earning assets; record slippage rather than rolling the deadline silently |
| Each financing or results update | Debt drawn, available funding conditions, share count, remaining construction costs and prepayments | Recompute value per share and the funding gap; pipeline growth can require a different capital structure |
| Following operating quarters | Utilization, renewal pricing, cash costs and hardware replacement | Test whether early economics persist after the initial build and advance collections |

The first research addition should be supported by a plausible route through
the valuation hurdle. Subsequent additions should require better delivery,
per-share economics, or a more favorable price with the thesis intact. This is
a sequence for evaluating additions, not an adopted sizing formula. No fresh
account risk budget or trade quantity is inferred from these public scenarios.

Long-duration ownership and short-duration event trades need separate decisions.
A multi-year upside case supplies no evidence that an option expiring tomorrow
will profit. Daily reports should retain both actionable timing developments
and longer-horizon watch names, with the next milestone and unresolved valuation
question visible. Membership in this cycle alone does not establish a winner.

[All assumptions](../outputs/valuation-scenarios-2026-09-10/assumptions.json),
[full scenario and funding tables](../outputs/valuation-scenarios-2026-09-10/scenario-tables.md),
and [reproduction instructions](../outputs/valuation-scenarios-2026-09-10/README.md)
are available for review. Four calculation checks cover inverse valuation
hurdles, compounding, dilution/debt direction and the reported cash-flow bridge.
They verify arithmetic, not forecasting accuracy. Risk constants, universe,
ticket decisions and broker authority are unchanged.
