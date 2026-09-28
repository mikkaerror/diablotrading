import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_research_audit as audit
import inferno_central_command as central
import inferno_doctor as doctor
import inferno_model_command_center as center
from tests.test_inferno_fill_economics import recorded


class ResearchAuditTests(unittest.TestCase):
    def test_forward_funnel_has_one_first_block_per_candidate_and_no_authority(self):
        arm = 'SHORT_PREMIUM_DEFINED'
        base = {'recommendedStrategy': arm, 'ticker': 'TEST', 'status': 'priced',
                'strikePlan': {'legs': [{'symbol': 'TEST_CALL'}]}, 'optimizerPassed': True,
                'paperRiskPassed': True, 'combinedPassed': True}
        rows = [dict(base, status='failed', reason='missing quotes'),
                dict(base, strikePlan={}), dict(base, optimizerPassed=False),
                dict(base, paperRiskPassed=False), dict(base, combinedPassed=False), base,
                dict(base, recommendedStrategy='CALL_DEBIT_SPREAD')]
        sources = {'alternativePricing': {'items': rows}, 'paper': {'items': []},
                   'shortPremium': {'forwardCampaign': {'timeboxEnd': '2026-10-05', 'distinctEvents': 0}}}
        before = copy.deepcopy(sources)
        from datetime import date
        result = audit.forward_collection_status(sources, [], today=date(2026,9,28))
        self.assertEqual(result['latestBatchCandidates'], 6)
        self.assertEqual(sum(result['firstBlockingStageCounts'].values()), 6)
        self.assertEqual(result['firstBlockingStageCounts']['research-ready-not-approved'], 1)
        self.assertEqual(result['daysRemaining'], 7)
        self.assertEqual(result['campaignReportedCostEvents'], 0)
        self.assertFalse(result['eligibleUniverseChanged'])
        self.assertFalse(result['evaluatorChanged'])
        self.assertEqual(sources, before)
        later = audit.forward_collection_status(sources, [], today=date(2026,9,29))
        self.assertEqual(result['meaningfulStateSha256'], later['meaningfulStateSha256'])
        expired = audit.forward_collection_status(sources, [], today=date(2026,10,6))
        self.assertEqual(expired['phase'], 'expired')
        self.assertNotEqual(result['meaningfulStateSha256'], expired['meaningfulStateSha256'])

    def test_forward_unknowns_and_report_refresh_are_not_new_evidence(self):
        missing = audit.forward_collection_status({}, [])
        self.assertIsNone(missing['latestBatchCandidates'])
        self.assertIsNone(missing['campaignPaperRows'])
        self.assertEqual(missing['phase'], 'deadline-unknown')
        sources = {'alternativePricing': {'items': []}, 'paper': {'items': []}}
        first = audit.build_research_audit(sources=sources)
        again = audit.build_research_audit(sources=sources, previous=first)
        self.assertFalse(again['forwardCollection']['meaningfulStateChanged'])
        self.assertFalse(again['acceptedPromotionProgress'])

    def test_forward_cost_count_uses_fill_reconciliation_not_study_claim(self):
        sources = {'paper': {'items': [{'ticketId': 'one', 'campaignArm': 'SHORT_PREMIUM_DEFINED'}]}}
        records = [{'ticketId':'one','eventId':'TEST|2026-09-28', 'provenance': {'pnlReconciliation': {'netPnl': None}}}]
        result = audit.forward_collection_status(sources, records)
        self.assertEqual(result['campaignFillReconciledEvents'], 1)
        self.assertEqual(result['campaignReportedCostEvents'], 0)
        records[0]['provenance']['pnlReconciliation']['netPnl'] = 0
        result = audit.forward_collection_status(sources, records * 2)
        self.assertEqual(result['campaignReportedCostEvents'], 1)

    def test_missing_evidence_is_unknown_not_zero_or_clean(self):
        report = audit.build_research_audit(sources={})
        self.assertIsNone(report['metrics']['qualifiedPaperEvents'])
        self.assertIsNone(report['metrics']['shortPremiumForwardEvents'])
        self.assertEqual(set(report['sourceMissing']), set(audit.SOURCES))
        self.assertFalse(report['acceptedPromotionProgress'])
        self.assertFalse(doctor.research_audit_status(report)[0])

    def test_reconciled_does_not_mean_cost_verified(self):
        ticket, source = recorded()
        sources = {'paper': {'items': [ticket]},
                   'shortPremium': {'forwardCampaign': {'distinctEvents': 0, 'distinctNames': 0}},
                   'loop': {'progressDelta': {'promotionEvidenceDelta': 0}, 'verdict': 'productive'}}
        before = copy.deepcopy((sources, source))
        report = audit.build_research_audit(sources=sources, fill_source=source)
        self.assertEqual(report['metrics']['qualifiedPaperEvents'], 1)
        self.assertEqual(report['metrics']['paperFillsWithReportedCosts'], 0)
        gaps = {g['id'] for g in report['gaps']}
        self.assertTrue({'paper-costs', 'short-premium-forward', 'activity-versus-evidence'} <= gaps)
        self.assertEqual((sources, source), before)
        self.assertFalse(report['promotable'])
        self.assertFalse(report['brokerSubmitAllowed'])
        self.assertFalse(report['liveTradingAllowed'])
        self.assertTrue(all(v is None for v in report['metricDeltaSincePreviousAudit'].values()))
        again = audit.build_research_audit(sources=sources, fill_source=source, previous=report)
        self.assertEqual(again['metricDeltaSincePreviousAudit']['qualifiedPaperEvents'], 0)

    def test_source_receipts_hash_exact_bytes_and_surface_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, audit.SOURCES['paper']); path.write_text('{"items": [], "generatedAt": "2026-07-01"}')
            Path(temp, audit.SOURCES['shadow']).write_text('broken')
            sources, receipts = audit.load_sources(Path(temp))
            self.assertEqual(receipts['paper']['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(receipts['paper']['generatedAt'], '2026-07-01')
            self.assertEqual(receipts['shadow']['status'], 'unreadable')
            self.assertEqual(receipts['cash']['status'], 'missing')
            self.assertNotIn('shadow', sources)

    def test_doctor_checks_time_gaps_and_authority_contract(self):
        report = audit.build_research_audit(sources={})
        report.update(gapCount=0, gaps=[], sourceMissing=[])
        self.assertTrue(doctor.research_audit_status(report)[0])
        for update in ({'generatedAt': '1900-01-01'}, {'generatedAt': 'bad'}, {'gapCount': 1},
                       {'researchOnly': False}, {'authorityChanged': True}, {'promotable': True},
                       {'liveTradingAllowed': True}, {'brokerSubmitAllowed': True}, {'sourceMissing': ['paper']}):
            self.assertFalse(doctor.research_audit_status({**report, **update})[0])

    def test_cli_routes_read_only_audit_and_preserves_failures(self):
        with patch('sys.argv', ['inferno', 'research-audit', 'status']), patch.object(central, 'run_passthrough_command', return_value={'returncode': 2}) as run:
            self.assertEqual(central.main(), 2)
        run.assert_called_once_with(['python3', 'inferno_research_audit.py', 'status'], timeout_seconds=120)
        self.assertTrue(any(r['artifact'] == 'reports/research_audit_latest.txt' for r in center.REPORTING_MAP))
        script = Path('run_inferno_daily_model_refresh.sh').read_text()
        self.assertLess(script.index('"research measurement audit"'), script.index('"model command center"'))
        self.assertIn('"researchAudit": summarize_artifact(RESEARCH_AUDIT_FILE', Path('inferno_model_command_center.py').read_text())
