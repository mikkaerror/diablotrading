from datetime import datetime, timezone
import unittest

from inferno_industry_coverage import build_industry_coverage


class IndustryCoverageTests(unittest.TestCase):
    def test_every_name_retained_including_low_score_and_missing_reference(self):
        snapshot={'rows':[{'ticker':f'T{i}','readiness':0} for i in range(183)]}
        result=build_industry_coverage(snapshot,{'entries':[]},{})
        self.assertEqual(result['coveredRows'],183)
        self.assertEqual(result['evidenceCounts'],{'unresolved':183})
        self.assertFalse(result['gateInput'])
        self.assertFalse(result['brokerSubmitAllowed'])

    def test_provider_label_is_not_presented_as_issuer_verified(self):
        result=build_industry_coverage({'rows':[{'ticker':'ABC'}]}, {'entries':[{
            'ticker':'ABC','industry':'Software','sector':'Technology','economicExposure':'software'}]}, {})
        self.assertEqual(result['rows'][0]['evidenceLevel'],'provider-reference')
        self.assertTrue(result['rows'][0]['issuerReviewDue'])

    def test_role_override_is_dated_and_does_not_add_outside_symbol(self):
        role=dict(role='GPU developer',sourceUrl='https://example.test/issuer',
                  horizon='commissioning',watchMetrics=['utilization'],reviewedAt='2026-01-01',reviewAfter='2026-04-01')
        result=build_industry_coverage({'rows':[{'ticker':'ABC'}]}, {'entries':[]},
                 {'ABC':role,'OUTSIDE':role},now=datetime(2026,9,10,tzinfo=timezone.utc))
        self.assertEqual(result['trackedRows'],1)
        self.assertEqual(result['rows'][0]['economicRole'],'GPU developer')
        self.assertTrue(result['rows'][0]['issuerReviewDue'])
        self.assertFalse(result['authorityChanged'])


if __name__=='__main__':unittest.main()
