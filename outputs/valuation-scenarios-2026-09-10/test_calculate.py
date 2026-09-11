import json
import unittest
from calculate import ROOT, anet_price, calculate, iren_price, required_revenue


class ValuationChecks(unittest.TestCase):
    def test_inverse_hurdles_recover_target_prices(self):
        for target in (45.37, 90.74):
            for shares in (400, 500, 600):
                revenue = required_revenue(target, shares, 4000, .45, 12)
                self.assertAlmostEqual(iren_price(revenue, .45, 12, 4000, shares), target)

    def test_funding_and_dilution_reduce_positive_equity(self):
        base = iren_price(4000, .45, 12, 4000, 500)
        self.assertLess(iren_price(4000, .45, 12, 6000, 500), base)
        self.assertLess(iren_price(4000, .45, 12, 4000, 600), base)
        self.assertEqual(iren_price(2000, .3, 8, 6000, 600), 0)

    def test_compounding_and_earnings_hurdle(self):
        self.assertAlmostEqual(anet_price(3.5, .2, 3, 40), 241.92)
        growth = (2 * 192.93 / (40 * 3.5)) ** (1 / 3) - 1
        self.assertAlmostEqual(anet_price(3.5, growth, 3, 40), 385.86)

    def test_reported_cashflow_bridge_and_authority(self):
        result = calculate(json.loads((ROOT / 'assumptions.json').read_text()))
        self.assertAlmostEqual(result['IREN']['historicalCfoMinusPpePayments'], -2232.7)
        self.assertAlmostEqual(result['IREN']['historicalCfoLessDeferredRevenueChange'], 258.7)
        self.assertAlmostEqual(result['IREN']['historicalCfoLessDeferredRevenueChangeAndPpe'], -4074.4)
        self.assertAlmostEqual(result['IREN']['bookNetDebtIncludingFinanceLeasesExRestrictedCash'], 1941.2)
        self.assertTrue(result['researchOnly'])
        self.assertTrue(all(result[k] is False for k in ('promotable', 'brokerSubmitAllowed', 'liveTradingAllowed', 'gateInput')))


if __name__ == '__main__':
    unittest.main()
