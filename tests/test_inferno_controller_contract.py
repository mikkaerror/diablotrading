"""Controller regressions: reported observations never become promotion credit."""
import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import inferno_decision_archive as archive
import inferno_email_digest as email
import inferno_performance_analytics as performance
import inferno_promotion_evidence_lineage as lineage
import inferno_schwab_transaction_ledger as transactions
import record_nlv_snapshot as nlv
from tests.paper_source_fixtures import source_for
from tests.test_inferno_promotion_evidence_lineage import paper_ticket


class ControllerContractTests(unittest.TestCase):
    def test_only_lineage_qualified_is_exported_to_analytics_and_email(self):
        filled = paper_ticket('paper-01')
        estimate = {'ticketId': 'estimate', 'ticker': 'TEST', 'status': 'paper-staged',
                    'strategy': 'CALL_DEBIT_SPREAD', 'estimatedMaxLoss': 100,
                    'outcome': {'status': 'closed', 'estimatedPnl': 50,
                                'notes': 'estimated from expiration intrinsic value'}}
        with patch.object(lineage, 'load_fill_source', return_value=source_for([filled])):
            result = performance.build_performance_analytics({'items': [filled, estimate]})
        self.assertEqual(result['closedMetrics']['scoredCount'], 2)
        self.assertEqual(result['promotionTruth']['qualified'], 1)
        self.assertEqual(result['promotionTruth']['estimatesNoCredit'], 1)
        self.assertIn('promotion-qualified: 1/30', performance.analytics_text(result))
        text = '\n'.join(email.scoreboard_section({}, result))
        self.assertIn('1/30', text)
        self.assertIn('estimate — no credit', text)
        self.assertIn('unavailable', '\n'.join(email.scoreboard_section({}, {'closedMetrics': {'scoredCount': 99}})))

    def test_missing_or_nonfinite_nlv_never_appends_and_zero_is_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'history.csv'
            path.write_text('timestamp,date,nlv,cash\nold,2026-09-28,100,20\n')
            before = path.read_bytes()
            with patch.object(nlv, 'HISTORY', path), contextlib.redirect_stdout(io.StringIO()):
                for value in (None, '', 'bad', True, float('nan'), float('inf')):
                    with patch.object(nlv, '_load', return_value={'netLiquidatingValue': value}):
                        self.assertEqual(nlv.main(), 0)
                    self.assertEqual(path.read_bytes(), before)
                with patch.object(nlv, '_load', return_value={'netLiquidatingValue': 0, 'totalCash': 0}):
                    nlv.main()
            self.assertIn(',0.00,0.00', path.read_text())

    def test_z_timestamp_supported_by_pre_311_parser(self):
        class LegacyDatetime:
            @staticmethod
            def fromisoformat(value):
                if value.endswith('Z'):
                    raise ValueError('legacy parser')
                return datetime.fromisoformat(value)
        def row(tid, qty, cost, effect, day):
            return transactions.normalize_transaction({'activityId': tid, 'type': 'TRADE', 'status': 'VALID',
                'time': f'2026-09-{day}T10:00:00Z', 'netAmount': cost,
                'transferItems': [{'amount': qty, 'positionEffect': effect, 'cost': cost,
                    'instrument': {'symbol': 'TEST_CALL', 'assetType': 'OPTION'}}]}, account_suffix_value='1234')
        rows = [row('close', -1, 120, 'CLOSING', '02'), row('open', 1, -100, 'OPENING', '01')]
        with patch.object(transactions, 'datetime', LegacyDatetime):
            self.assertEqual(transactions.closed_contract_cash_reconciliation(rows)['matchedNetCash'], 20)
        rows[0]['occurredAt'] = '2026-09-02T10:00:00'
        self.assertIsNone(transactions.closed_contract_cash_reconciliation(rows)['matchedNetCash'])

    def test_archive_io_failure_is_durable_visible_and_recoverable_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); directory = root / 'decision_archive'
            source = root / 'inferno_paper_execution_ledger.json'
            raw = json.dumps({'items': [paper_ticket('paper-01')]}).encode()
            with patch.object(archive, 'code_receipt', return_value={}), patch.object(archive, 'time'):
                with patch.object(archive, 'connect', side_effect=sqlite3.OperationalError('disk I/O error')) as connect:
                    with self.assertRaises(sqlite3.OperationalError):
                        archive.capture_bytes(source, raw)
                    self.assertEqual(connect.call_count, 3)
                    report = archive.build_decision_archive(directory)
                self.assertEqual(report['verdict'], 'capture-queued-database-unavailable')
                self.assertEqual(report['counts']['pendingCaptures'], 1)
                self.assertEqual(json.loads((directory / 'queue_status.json').read_text())['state'], 'queued-retry-required')
                self.assertEqual(archive.drain(directory)['newVersions'], 1)
                self.assertEqual(archive.drain(directory)['newVersions'], 0)
                self.assertEqual(json.loads((directory / 'queue_status.json').read_text())['state'], 'drained')
