"""Evidence must survive source mismatches, duplicates and tempting labels."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_paper_provenance as provenance
from inferno_strategy_lab import build_strategy_lab, closed_trade_records
from inferno_promotion_evidence_lineage import build_promotion_evidence_lineage
from tests.paper_source_fixtures import add_recorded_fill, source_for
from inferno_tos_fill_ingest import row_fingerprint


def fixture():
    ticket = add_recorded_fill({'ticketId': 'fill-1', 'ticker': 'TEST',
        'strategy': 'CALL_DEBIT_SPREAD', 'eventId': 'TEST|2026-04-26',
        'status': 'paper-staged', 'outcome': {'status': 'closed',
        'reviewedAt': '2026-04-27T09:00:00-06:00', 'estimatedPnl': 25.0}}, risk=100.0)
    return ticket, source_for([ticket])


class PaperProvenanceTests(unittest.TestCase):
    def test_consistent_record_is_source_reconciled_not_broker_verified(self):
        ticket, source = fixture()
        before = copy.deepcopy((ticket, source))
        audit = provenance.outcome_provenance(ticket, source)
        self.assertTrue(audit['sourceReconciled'])
        self.assertFalse(audit['independentlyVerified'])
        self.assertEqual((ticket, source), before)
        self.assertEqual(len(closed_trade_records([ticket], source)), 1)

    def test_a_seeded_template_note_does_not_imply_synthetic_fills(self):
        ticket, source = fixture()
        ticket['paperExecution']['notes'] = 'seeded by inferno_tos_sandbox'
        ticket['outcome']['notes'] = 'seeded by inferno_tos_sandbox'
        self.assertTrue(provenance.outcome_provenance(ticket, source)['sourceReconciled'])

    def test_explicit_synthetic_marker_and_intrinsic_proxy_are_excluded(self):
        ticket, source = fixture()
        ticket['paperExecution']['evidenceType'] = 'synthetic'
        self.assertEqual(closed_trade_records([ticket], source), [])
        ticket['paperExecution'] = None
        ticket['outcome']['notes'] = 'estimated from expiration intrinsic value'
        audit = provenance.outcome_provenance(ticket, source)
        self.assertEqual(audit['state'], 'intrinsic-estimate')
        self.assertFalse(audit['sourceReconciled'])

    def test_source_row_changes_cannot_be_hidden_behind_old_import_fingerprint(self):
        ticket, original = fixture()
        for key, value in [('ticker', 'WRONG'), ('strategy', 'OTHER'),
                           ('expiration', '2027-01-01'), ('contracts', '2'),
                           ('entryPrice', '3'), ('exitPrice', '4'),
                           ('environment', 'live'), ('closedAt', '2026-01-01T09:00:00Z')]:
            with self.subTest(key=key):
                source = copy.deepcopy(original)
                source['rows'][0][key] = value
                self.assertFalse(provenance.outcome_provenance(ticket, source)['sourceReconciled'])

    def test_ledger_changes_cannot_be_validated_by_a_still_matching_import_key(self):
        original, source = fixture()
        for field, value in [('entryPrice', 4), ('contracts', 2), ('exitPrice', 9),
                             ('realizedPnl', 500), ('closedAt', '2027-01-01T00:00:00Z')]:
            with self.subTest(field=field):
                ticket = copy.deepcopy(original)
                ticket['paperExecution'][field] = value
                self.assertEqual(closed_trade_records([ticket], source), [])

    def test_nonfinite_boolean_or_invalid_outcome_is_not_scored(self):
        original, source = fixture()
        for value in (float('nan'), float('inf'), True, 'garbage', None):
            ticket = copy.deepcopy(original)
            ticket['outcome']['estimatedPnl'] = value
            self.assertEqual(closed_trade_records([ticket], source), [])

    def test_missing_source_and_missing_import_key_fail_closed(self):
        ticket, source = fixture()
        self.assertEqual(closed_trade_records([ticket], {'status': 'unavailable', 'rows': []}), [])
        ticket['importedFillKeys'] = []
        self.assertEqual(closed_trade_records([ticket], source), [])

    def test_future_fill_cannot_become_evidence_even_if_both_copies_match(self):
        ticket, source = fixture()
        ticket['paperExecution']['closedAt'] = '2099-01-01T00:00:00Z'
        source['rows'][0]['closedAt'] = ticket['paperExecution']['closedAt']
        ticket['importedFillKeys'] = [row_fingerprint(source['rows'][0])]
        self.assertEqual(closed_trade_records([ticket], source), [])

    def test_identical_exports_deduplicate_and_conflicting_closes_block(self):
        ticket, source = fixture()
        source['rows'].append(copy.deepcopy(source['rows'][0]))
        self.assertEqual(len(closed_trade_records([ticket], source)), 1)
        source['rows'][1]['exitPrice'] = '9'
        self.assertIn('conflicting-closed-source-rows', provenance.outcome_provenance(ticket, source)['issues'])

    def test_duplicate_ticket_id_is_not_two_observations_even_across_strategies(self):
        ticket, source = fixture()
        duplicate = copy.deepcopy(ticket)
        duplicate['strategy'] = 'OTHER'
        lab = build_strategy_lab({'items': [ticket, duplicate]}, source)
        self.assertEqual(lab['overall']['scoredCount'], 0)
        self.assertTrue(all(item['scoredCount'] == 0 for item in lab['strategies']))

    def test_fill_risk_replaces_planned_debit_denominator(self):
        ticket, source = fixture()
        ticket['entryLimit'] = 3.2
        ticket['estimatedMaxLoss'] = 320
        ticket['riskVerdict'] = {'metrics': {'maxLossDollars': 320}}
        record = closed_trade_records([ticket], source)[0]
        self.assertEqual(record['maxLoss'], 100)
        self.assertEqual(record['returnOnRisk'], 0.25)

    def test_provenance_is_not_accepted_merely_because_old_lab_report_agrees(self):
        ticket, _ = fixture()
        payload = build_promotion_evidence_lineage({'items': [ticket]}, {}, {},
            {'overall': {'scoredCount': 1}}, source={'status': 'unavailable', 'rows': []})
        self.assertEqual(payload['promotion']['qualifiedPaperOutcomes'], 0)
        self.assertFalse(payload['promotion']['strategyLabCountMatchesLineage'])

    def test_source_dates_define_chronological_drawdown_order_across_offsets(self):
        first, source = fixture()
        later = copy.deepcopy(first)
        later['ticketId'] = 'fill-2'
        # 08:00 Pacific is later than 09:00 Mountain, despite the clock string.
        later['paperExecution']['closedAt'] = '2026-04-27T08:30:00-07:00'
        row = copy.deepcopy(source['rows'][0])
        row.update(ticketId='fill-2', closedAt=later['paperExecution']['closedAt'])
        later['importedFillKeys'] = [row_fingerprint(row)]
        source['rows'].append(row)
        records = closed_trade_records([later, first], source)
        self.assertEqual([row['ticketId'] for row in records], ['fill-1', 'fill-2'])

    def test_raw_numeric_growth_is_not_accepted_as_paper_progress(self):
        from inferno_evidence_goal_loop import progress_snapshot
        artifacts = {'performance': {'closedMetrics': {'scoredCount': 30}},
                     'strategyLab': {'overall': {'scoredCount': 1}}}
        self.assertEqual(progress_snapshot(artifacts)['scoredPaperTickets'], 1)

    def test_missing_malformed_source_is_read_only_and_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing.csv'
            with patch.object(provenance, 'TOS_FILL_LOG_WORK_FILE', path):
                self.assertEqual(provenance.load_fill_source()['status'], 'unavailable')
                self.assertFalse(path.exists())
                path.write_text('ticketId,ticketId\na,b\n')
                original = path.read_bytes()
                self.assertEqual(provenance.load_fill_source()['status'], 'unavailable')
                self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
