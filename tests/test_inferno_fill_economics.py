"""Adversarial fill economics checks; fixtures never touch broker/runtime data."""
import copy
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from inferno_tos_fill_ingest import apply_fill_row, fill_pnl_reconciliation, row_fingerprint
from inferno_paper_provenance import outcome_provenance
from inferno_strategy_lab import build_strategy_lab, closed_trade_records
from tests.test_inferno_tos_fill_ingest import _row, _ticket
from tests.paper_source_fixtures import add_recorded_fill, source_for


def recorded(**fields):
    ticket = add_recorded_fill({'ticketId': 'paper-1', 'ticker': 'DELL', 'strategy': 'CALL_DEBIT_SPREAD',
                               'status': 'paper-staged', 'outcome': {'status': 'closed', 'estimatedPnl': 30,
                               'reviewedAt': '2026-04-27T09:00:00-06:00'}}, risk=180)
    row = {**ticket['_sourceFixture'], **fields}
    ticket['importedFillKeys'] = []
    updated, changed, _ = apply_fill_row(ticket, row)
    assert changed
    return updated, {'status': 'ok', 'rows': [row]}


class FillEconomicsTests(unittest.TestCase):
    def test_legacy_gross_consistency_never_implies_zero_fees(self):
        audit = fill_pnl_reconciliation(_ticket(), _row(realizedPnl='70'))
        self.assertTrue(audit['arithmeticReconciled'])
        self.assertEqual(audit['grossPnl'], 70)
        self.assertIsNone(audit['netPnl'])
        self.assertIsNone(audit['totalFees'])
        self.assertEqual(audit['costStatus'], 'unknown')

    def test_blank_reported_pnl_is_derived_but_invalid_number_is_rejected(self):
        self.assertEqual(fill_pnl_reconciliation(_ticket(), _row())['scoringPnl'], 70)
        for value in ('nan', 'inf', 'oops', True):
            self.assertFalse(fill_pnl_reconciliation(_ticket(), _row(realizedPnl=value))['arithmeticReconciled'])

    def test_identical_forged_pnl_in_log_execution_and_outcome_still_fails(self):
        ticket, source = recorded()
        row = source['rows'][0]
        row['realizedPnl'] = '9999'
        ticket['paperExecution']['realizedPnl'] = 9999
        ticket['outcome']['estimatedPnl'] = 9999
        ticket['importedFillKeys'] = [row_fingerprint(row)]
        audit = outcome_provenance(ticket, source)
        self.assertIn('source-economics-reported-pnl-does-not-reconcile', audit['issues'])
        self.assertEqual(closed_trade_records([ticket], source), [])

    def test_total_round_trip_costs_subtracted_once_for_multiple_positions(self):
        for cost_type, entry, exit_price in (('debit','1.5','2.2'), ('credit','2.2','1.5')):
            audit = fill_pnl_reconciliation(_ticket(entryCostType=cost_type),
                _row(entryPrice=entry, exitPrice=exit_price, contracts='3', totalFees='7.80', realizedPnlBasis='net', realizedPnl='202.20'))
            self.assertTrue(audit['arithmeticReconciled'])
            self.assertEqual(audit['grossPnl'], 210)
            self.assertEqual(audit['netPnl'], 202.2)

    def test_gross_and_net_reporting_have_identical_net_scoring(self):
        for basis, pnl in (('gross','30'), ('net','27.40')):
            ticket, source = recorded(realizedPnlBasis=basis, totalFees='2.60', realizedPnl=pnl)
            before = copy.deepcopy((ticket, source))
            records = closed_trade_records([ticket], source)
            self.assertEqual(records[0]['estimatedPnl'], 27.4)
            self.assertAlmostEqual(records[0]['returnOnRisk'], 27.4/180, places=6)
            self.assertEqual(ticket['outcome']['estimatedPnl'], float(pnl))
            self.assertEqual((ticket, source), before)
            self.assertFalse(records[0]['provenance']['independentlyVerified'])

    def test_explicit_zero_fees_differs_from_missing(self):
        ticket, source = recorded(realizedPnlBasis='net', totalFees='0', realizedPnl='30')
        audit = outcome_provenance(ticket, source)['pnlReconciliation']
        self.assertEqual(audit['netPnl'], 30)
        self.assertEqual(audit['costStatus'], 'operator-reported-costs')
        self.assertFalse(audit['independentlyVerified'])

    def test_costs_can_turn_a_small_gross_win_into_a_net_loss(self):
        ticket, source = recorded(realizedPnlBasis='gross', totalFees='35', realizedPnl='30')
        overall = build_strategy_lab({'items': [ticket]}, source)['overall']
        self.assertEqual(overall['winCount'], 0)
        self.assertEqual(overall['lossCount'], 1)
        self.assertEqual(overall['netOfReportedFeesCount'], 1)
        self.assertEqual(overall['unknownFeesCount'], 0)

    def test_missing_or_ambiguous_cost_basis_and_negative_costs_fail(self):
        for fields in ({'realizedPnlBasis':'net'}, {'totalFees':'2'}, {'totalFees':'-2','realizedPnlBasis':'gross'},
                       {'totalFees':'nan','realizedPnlBasis':'net'}, {'realizedPnlBasis':'adjusted'},
                       {'contracts':0}, {'contracts':'1.5'}, {'entryPrice':True}, {'contracts':True},
                       {'entryPrice':'1e999'}):
            with self.subTest(fields=fields):
                self.assertFalse(fill_pnl_reconciliation(_ticket(), _row(**fields))['arithmeticReconciled'])

    def test_unknown_cost_direction_cannot_default_to_long(self):
        self.assertFalse(fill_pnl_reconciliation(_ticket(entryCostType=''), _row())['arithmeticReconciled'])

    def test_fee_change_invalidates_import_fingerprint_and_execution_match(self):
        ticket, source = recorded(realizedPnlBasis='gross', totalFees='2.60')
        original_key = row_fingerprint(source['rows'][0])
        source['rows'][0]['totalFees'] = '3.60'
        self.assertNotEqual(original_key, row_fingerprint(source['rows'][0]))
        audit = outcome_provenance(ticket, source)
        self.assertIn('source-fingerprint-not-imported', audit['issues'])
        self.assertIn('source-mismatch-totalFees', audit['issues'])

    def test_adding_blank_optional_columns_preserves_legacy_fingerprint(self):
        row = _row()
        self.assertEqual(row_fingerprint(row), row_fingerprint({**row, 'totalFees':'', 'realizedPnlBasis':''}))

    def test_legacy_csv_intake_stays_valid_and_remains_byte_identical(self):
        import inferno_paper_outcome_completeness as completeness
        from inferno_downloads_manager import inferno_fill_log_schema
        from inferno_tos_sandbox import REQUIRED_FILL_COLUMNS
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'fills.csv'
            with path.open('w') as stream:
                writer = csv.DictWriter(stream, fieldnames=REQUIRED_FILL_COLUMNS)
                writer.writeheader(); writer.writerow(_row())
            before = path.read_bytes()
            with patch.object(completeness, 'TOS_FILL_LOG_WORK_FILE', path):
                intake = completeness.fill_intake_readiness({'items': [_ticket()]})
            self.assertTrue(intake['schemaValid'])
            self.assertEqual(intake['closeReadyRows'], 1)
            self.assertEqual(before, path.read_bytes())
            self.assertTrue(inferno_fill_log_schema(REQUIRED_FILL_COLUMNS))

    def test_complete_but_contradictory_csv_is_not_ready_for_intake(self):
        import inferno_paper_outcome_completeness as completeness
        from inferno_tos_sandbox import FILL_LOG_COLUMNS
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'fills.csv'
            with path.open('w') as stream:
                writer = csv.DictWriter(stream, fieldnames=FILL_LOG_COLUMNS)
                writer.writeheader();writer.writerow(_row(realizedPnl='9000'))
            with patch.object(completeness, 'TOS_FILL_LOG_WORK_FILE', path):
                intake = completeness.fill_intake_readiness({'items': [_ticket()]})
            self.assertEqual(intake['closeReadyRows'], 0)
            self.assertEqual(completeness.fill_intake_verdict(intake), 'closed-fill-economics-mismatch')

    def test_completeness_names_unknown_cost_work_without_inventing_fills(self):
        from inferno_paper_outcome_completeness import build_paper_outcome_completeness
        ticket, source = recorded()
        report = build_paper_outcome_completeness({'items': [ticket]}, source)
        self.assertEqual(report['counts']['scorableUnknownFeesRows'], 1)
        self.assertEqual(report['counts']['scorableNetOfReportedFeesRows'], 0)
        self.assertIn('recover-actual-round-trip-fees', [r['kind'] for r in report['operatorWorkItems']])

    def test_download_intake_schema_helper_cannot_write_sandbox_global_paths(self):
        import inferno_downloads_manager as manager
        import inferno_tos_sandbox as sandbox
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            work, unrelated = root/'configured.csv', root/'workspace.csv'
            unrelated.write_text('untouched evidence\n')
            with (patch.object(manager, 'TOS_FILL_LOG_WORK_FILE', work),
                  patch.object(sandbox, 'TOS_FILL_LOG_WORK_FILE', unrelated),
                  patch.object(sandbox, 'TOS_FILL_LOG_TEMPLATE_FILE', root/'template.csv')):
                rows, keys = manager.load_existing_fill_log()
                manager.save_fill_log(rows)
            self.assertEqual(rows, [])
            self.assertEqual(unrelated.read_text(), 'untouched evidence\n')
            self.assertFalse((root/'template.csv').exists())

    def test_download_normalization_preserves_supplied_fee_evidence(self):
        from inferno_downloads_manager import canonicalize_inferno_row
        row = _row(realizedPnlBasis='net', totalFees='2.60', realizedPnl='67.40')
        normalized = canonicalize_inferno_row(row)
        self.assertEqual(normalized['totalFees'], '2.60')
        self.assertEqual(normalized['realizedPnlBasis'], 'net')

    def test_preview_explains_rejection_and_never_saves_a_ledger(self):
        import inferno_tos_fill_ingest as ingest
        with (patch.object(ingest, 'load_ledger', return_value={'items': [_ticket()]}),
              patch.object(ingest, 'load_fill_rows', return_value=[_row(realizedPnl='999')]),
              patch.object(ingest, 'save_ledger') as save,
              patch.object(ingest, 'save_ingest_report') as save_report):
            report = ingest.ingest_fill_log()
        self.assertEqual(report['rejectedRows'], 1)
        self.assertEqual(report['acceptedProgressUnits'], 0)
        self.assertIn('reported-pnl-does-not-reconcile', ' '.join(report['notes']))
        save.assert_not_called()
        save_report.assert_not_called()
