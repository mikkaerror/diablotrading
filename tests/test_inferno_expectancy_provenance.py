import copy
import unittest

from inferno_expectancy_ledger import build_expectancy_ledger, _stats
from tests.test_inferno_fill_economics import recorded


class ExpectancyProvenanceTests(unittest.TestCase):
    def test_gross_and_net_source_reporting_subtract_fees_once(self):
        for basis, pnl in [('gross', '30'), ('net', '27.40')]:
            ticket, source = recorded(realizedPnlBasis=basis, totalFees='2.60', realizedPnl=pnl)
            before = copy.deepcopy((ticket, source))
            report = build_expectancy_ledger(paper={'items': [ticket]}, shadow={}, fill_source=source)
            row = report['records'][0]
            self.assertEqual(row['evidenceClass'], 'source-reconciled-paper-fill')
            self.assertEqual(row['grossPnlDollars'], 30)
            self.assertEqual(row['netPnlEstimateDollars'], 27.4)
            self.assertEqual(row['maxLossDollars'], 180)
            self.assertAlmostEqual(row['grossR'], 30/180, places=6)
            self.assertAlmostEqual(row['netREstimate'], 27.4/180, places=6)
            self.assertEqual(row['estimatedFrictionDollars'], 2.6)
            self.assertEqual((ticket, source), before)
            self.assertFalse(report['families'][0]['promotionEvidenceEligible'])

    def test_unknown_fees_preserve_gross_but_withhold_net(self):
        ticket, source = recorded()
        report = build_expectancy_ledger(paper={'items': [ticket]}, shadow={}, fill_source=source)
        self.assertEqual(report['counts']['sourceReconciledPaper'], 1)
        self.assertEqual(report['counts']['netEstimatesAvailable'], 0)
        self.assertIsNone(report['records'][0]['netREstimate'])
        self.assertIsNone(report['families'][0]['expectancyNetR'])

    def test_unverified_and_proxy_rows_never_join_qualified_population(self):
        ticket, source = recorded(totalFees='0', realizedPnlBasis='gross', realizedPnl='30')
        fake = copy.deepcopy(ticket); fake['ticketId'] = 'unverified'
        report = build_expectancy_ledger(paper={'items': [ticket, fake]}, shadow={'items': [ticket]}, fill_source=source)
        self.assertEqual(report['counts']['sourceReconciledPaper'], 1)
        self.assertEqual(report['counts']['unverifiedPaper'], 1)
        self.assertEqual(len(report['families']), 3)
        self.assertEqual({r['evidenceClass'] for r in report['families']},
                         {'source-reconciled-paper-fill', 'unverified-paper-estimate', 'shadow-proxy'})
        self.assertTrue(all(not r['promotionEvidenceEligible'] for r in report['families']))

    def test_injected_paper_without_source_cannot_qualify_from_runtime(self):
        ticket, _ = recorded()
        report = build_expectancy_ledger(paper={'items': [ticket]}, shadow={})
        self.assertEqual(report['counts']['sourceReconciledPaper'], 0)

    def test_repeated_variants_of_one_event_cannot_manufacture_interval(self):
        stats = _stats([{'eventId': 'DELL|2026-07-01', 'netREstimate': i/10} for i in range(30)])
        self.assertEqual(stats['expectancyNetR95'], {'lower': None, 'upper': None})
        self.assertIsNone(stats['maxDrawdownNetR'])

    def test_drawdown_uses_execution_chronology(self):
        stats = _stats([{'eventId': 'A', 'netREstimate': -2, 'reviewedAt': '2026-07-02T00:00:00Z'},
                        {'eventId': 'B', 'netREstimate': 1, 'reviewedAt': '2026-07-01T00:00:00Z'}])
        self.assertEqual(stats['maxDrawdownNetR'], -2)
