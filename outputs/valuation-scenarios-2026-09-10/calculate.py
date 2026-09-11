"""Offline valuation sensitivities; no application imports or trade outputs."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def anet_price(eps, growth, years, multiple):
    return eps * (1 + growth) ** years * multiple


def iren_price(revenue, margin, multiple, debt, shares):
    if shares <= 0:
        raise ValueError("Shares must be positive")
    return max(0, revenue * margin * multiple - debt) / shares


def required_revenue(price, shares, debt, margin, multiple):
    return (price * shares + debt) / (margin * multiple)


def calculate(a):
    assert a['researchOnly'] is True
    assert all(a[k] is False for k in ('promotable', 'brokerSubmitAllowed', 'liveTradingAllowed', 'gateInput'))
    years = a['horizonYears']
    prices = a['referencePrices']
    eps = 2 * a['reportedFacts']['ANET']['sixMonthGaapDilutedEps']
    result = {k: a[k] for k in ('researchOnly', 'promotable', 'brokerSubmitAllowed', 'liveTradingAllowed', 'gateInput', 'horizonYears', 'assumptionsStatus', 'referencePrices')}
    result['ANET'] = {'annualizedHalfYearEps': eps, 'priceToAnnualizedHalfYearEps': prices['ANET'] / eps, 'scenarios': []}
    for s in a['ANET']['scenarios']:
        price = anet_price(eps, s['epsGrowth'], years, s['terminalPE'])
        result['ANET']['scenarios'].append({**s, 'terminalPrice': price, 'priceReturn': price / prices['ANET'] - 1})
    result['ANET']['epsGrowthRequiredForDoubleAt40PE'] = (2 * prices['ANET'] / (40 * eps)) ** (1 / years) - 1
    f = a['reportedFacts']['IREN']
    capex = f['propertyPaymentsExHardware'] + f['hardwarePayments']
    net_debt = sum(f[k] for k in ('debtCurrent', 'debtLongTerm', 'financeLeasesCurrent', 'financeLeasesLongTerm')) - f['cashEquivalents']
    result['IREN'] = {
        'historicalPpeCashPayments': capex,
        'historicalCfoMinusPpePayments': f['operatingCashFlow'] - capex,
        'historicalCfoLessDeferredRevenueChange': f['operatingCashFlow'] - f['deferredRevenueCashFlowChange'],
        'historicalCfoLessDeferredRevenueChangeAndPpe': f['operatingCashFlow'] - f['deferredRevenueCashFlowChange'] - capex,
        'bookNetDebtIncludingFinanceLeasesExRestrictedCash': net_debt,
        'datedReferenceEquityValue': prices['IREN'] * f['ordinarySharesMillions'],
        'scenarios': []}
    for s in a['IREN']['scenarios']:
        price = iren_price(s['annualRevenue'], s['ebitdaMargin'], s['terminalEVtoEBITDA'], s['terminalNetDebtIncludingFinanceLeases'], s['terminalDilutedShares'])
        residual = s['annualRevenue'] * (s['ebitdaMargin'] - s['replacementCapexFraction']) - s['cashInterest'] - s['cashTaxes']
        result['IREN']['scenarios'].append({**s, 'terminalPrice': price, 'priceReturn': price / prices['IREN'] - 1,
            'partialCashResidual': residual,
            'revenueRequiredToMatchReferencePrice': required_revenue(prices['IREN'], s['terminalDilutedShares'], s['terminalNetDebtIncludingFinanceLeases'], s['ebitdaMargin'], s['terminalEVtoEBITDA']),
            'revenueRequiredForDouble': required_revenue(2 * prices['IREN'], s['terminalDilutedShares'], s['terminalNetDebtIncludingFinanceLeases'], s['ebitdaMargin'], s['terminalEVtoEBITDA'])})
    result['IREN']['fundingSensitivityAtMiddleOperatingCase'] = [
        {'netDebt': debt, 'shares': shares, 'price': iren_price(4000, .45, 12, debt, shares)}
        for debt in (2000, 4000, 6000) for shares in (400, 500, 600)]
    return result


def render(r):
    lines = ['# Three-year valuation sensitivities', '',
             'Calculated from `assumptions.json`. All case inputs are hypothetical. Prices reference September 9, 2026 closes; returns exclude distributions, taxes and transaction costs. No case probabilities or buy signals.', '',
             '| ANET case | EPS growth/year | Exit P/E | Terminal price | Price return |',
             '|---|---:|---:|---:|---:|']
    for s in r['ANET']['scenarios']:
        lines.append(f"| {s['case']} | {s['epsGrowth']:.0%} | {s['terminalPE']}x | ${s['terminalPrice']:.2f} | {s['priceReturn']:+.1%} |")
    lines += ['', '| IREN case | Annual revenue | EBITDA margin | EV/EBITDA | Net debt | Diluted shares | Terminal price | Price return |', '|---|---:|---:|---:|---:|---:|---:|---:|']
    for s in r['IREN']['scenarios']:
        lines.append(f"| {s['case']} | ${s['annualRevenue']/1000:.1f}bn | {s['ebitdaMargin']:.0%} | {s['terminalEVtoEBITDA']}x | ${s['terminalNetDebtIncludingFinanceLeases']/1000:.1f}bn | {s['terminalDilutedShares']}m | ${s['terminalPrice']:.2f} | {s['priceReturn']:+.1%} |")
    lines += ['', 'A zero equity residual is a stress result, not a prediction of insolvency. These are endpoint sensitivities, not a financing forecast.', '',
              '| IREN case | Partial cash residual/year | Revenue to match reference price | Revenue for 2x reference price |', '|---|---:|---:|---:|']
    for s in r['IREN']['scenarios']:
        lines.append(f"| {s['case']} | ${s['partialCashResidual']/1000:.2f}bn | ${s['revenueRequiredToMatchReferencePrice']/1000:.2f}bn | ${s['revenueRequiredForDouble']/1000:.2f}bn |")
    lines += ['', 'Partial cash residual = EBITDA − replacement capital spending − cash interest − cash taxes. It excludes growth capex, working capital, principal repayment and additional accounting adjustments. It is not free cash flow.', '',
              'Holding revenue at $4bn, EBITDA margin at 45% and EV/EBITDA at 12x:', '',
              '| Terminal net debt | 400m shares | 500m shares | 600m shares |', '|---|---:|---:|---:|']
    rows = r['IREN']['fundingSensitivityAtMiddleOperatingCase']
    for debt in (2000, 4000, 6000):
        values = [f"${s['price']:.2f}" for s in rows if s['netDebt'] == debt]
        lines.append(f"| ${debt/1000:.0f}bn | " + ' | '.join(values) + ' |')
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    result = calculate(json.loads((ROOT / 'assumptions.json').read_text()))
    (ROOT / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    (ROOT / 'scenario-tables.md').write_text(render(result))
    print('Wrote results.json and scenario-tables.md (research only)')
