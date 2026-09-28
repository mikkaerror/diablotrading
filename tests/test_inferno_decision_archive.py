import copy
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import inferno_decision_archive as archive
from inferno_io import atomic_write_json, archive_written_evidence


def ticket(**changes):
    row = {'ticketId': 't1', 'ticker': 'TEST', 'strategy': 'CALL_DEBIT_SPREAD',
           'expiration': '2026-12-18', 'tradeDate': '2026-09-28', 'createdAt': '2026-09-28T10:00:00Z',
           'legs': [{'symbol': 'TEST_CALL_10', 'instruction': 'BUY_TO_OPEN', 'quantity': 1},
                    {'symbol': 'TEST_CALL_15', 'instruction': 'SELL_TO_OPEN', 'quantity': 1}],
           'status': 'paper-blocked', 'blockReasons': ['spread too wide'], 'outcome': {'status': 'not-opened'}}
    return {**row, **changes}


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root/'decision_archive'
        self.path = self.root/'inferno_shadow_evidence.json'
        self.receipt = patch.object(archive, 'code_receipt', return_value={'commit': 'fixture', 'files': {}})
        self.receipt.start(); self.addCleanup(self.receipt.stop)

    def capture(self, rows, **kwargs):
        return archive.capture_bytes(self.path, json.dumps({'items': rows}).encode(), **kwargs)

    def count(self, table):
        with sqlite3.connect(self.directory/'archive.sqlite3') as db:
            return db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]

    def test_rejected_alternatives_archived_without_approving_or_losing_reason(self):
        path = self.root / 'inferno_strategy_alternative_pricing.json'
        rows = [{'ticker':'TEST', 'recommendedStrategy':'SHORT_PREMIUM_DEFINED', 'candidateStrategyRank':1,
                 'status':'failed', 'reason':'no usable quotes'}]
        archive_written_evidence(path, json.dumps({'items': rows}).encode())
        saved = archive.show(self.directory, 1)
        self.assertEqual(saved['sourceRecord']['reason'], 'no usable quotes')
        self.assertEqual(saved['sourceRecord']['status'], 'failed')
        rows[0]['status'] = 'priced'
        rows[0]['reason'] = None
        archive_written_evidence(path, json.dumps({'items': rows}).encode())
        self.assertEqual(self.count('versions'), 2)
        self.assertTrue(archive.verify(self.directory)['ok'])

    def test_broker_ids_scoped_to_account_and_corrections_versioned(self):
        path = self.root / 'inferno_schwab_transaction_ledger.json'
        rows = [{'accountSuffix': '1234', 'transactionId': 'A', 'netAmount': 10},
                {'accountSuffix': '5678', 'transactionId': 'A', 'netAmount': 20},
                {'accountSuffix': '1234', 'transactionId': 'B', 'netAmount': 30}]
        archive.capture_bytes(path, json.dumps({'transactions': rows}).encode())
        rows[0]['netAmount'] = 11
        result = archive.capture_bytes(path, json.dumps({'transactions': list(reversed(rows))}).encode())
        self.assertEqual(result['newVersions'], 1)
        self.assertEqual(self.count('versions'), 4)
        self.assertTrue(archive.verify(self.directory)['ok'])

    def test_exact_replay_adds_no_snapshot_or_version(self):
        row = ticket(); before = copy.deepcopy(row)
        self.assertEqual(self.capture([row]), {'newSnapshots': 1, 'newVersions': 1})
        self.assertEqual(self.capture([row]), {'newSnapshots': 0, 'newVersions': 0})
        self.assertEqual(row, before)
        self.assertTrue(archive.verify(self.directory)['ok'])

    def test_refresh_metadata_retained_in_snapshot_not_new_decision(self):
        self.capture([ticket(updatedAt='A')])
        result = self.capture([ticket(updatedAt='B')])
        self.assertEqual(result, {'newSnapshots': 1, 'newVersions': 0})
        self.capture([ticket(updatedAt='B', quote={'generatedAt': 'new'})])
        self.assertEqual(self.count('versions'), 2)

    def test_reason_and_outcome_corrections_append_including_reversion(self):
        self.capture([ticket()])
        self.capture([ticket(blockReasons=['source corrected'], outcome={'status': 'closed','estimatedPnl': -20})])
        self.capture([ticket()])
        self.assertEqual(self.count('versions'), 3)
        self.assertEqual(archive.show(self.directory, 1)['sourceRecord']['blockReasons'], ['spread too wide'])
        self.assertEqual(archive.show(self.directory, 2)['sourceRecord']['outcome']['estimatedPnl'], -20)
        self.assertEqual(len(archive.history(self.directory, ticker='test', before=3)), 2)

    def test_same_contract_different_day_and_lane_grouped_not_deleted(self):
        self.capture([ticket(), ticket(ticketId='t2', tradeDate='2026-09-29')])
        archive.capture_bytes(self.root/'inferno_fast_paper_ledger.json', json.dumps({'items':[ticket(ticketId='sim')]}).encode())
        rows = archive.history(self.directory, ticker='TEST')
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({r['caseKey'] for r in rows}), 1)
        self.assertEqual({r['lane'] for r in rows}, {'shadow','simulation'})
        self.assertEqual(archive.build_decision_archive(self.directory)['counts']['contractExposureGroups'], 1)

    def test_incomplete_identity_does_not_merge_unrelated_records(self):
        self.capture([ticket(legs=[], ticketId='A'), ticket(legs=[], ticketId='B')])
        self.assertEqual(len({r['caseKey'] for r in archive.history(self.directory,ticker='TEST')}), 2)

    def test_conflicting_duplicate_ids_in_one_source_preserved(self):
        self.capture([ticket(), ticket(blockReasons=['different'])])
        self.assertEqual(self.count('versions'), 2)
        self.assertEqual(self.capture([ticket(), ticket(blockReasons=['different'])])['newVersions'], 0)

    def test_backfill_never_claims_prior_knowledge_or_invents_reason(self):
        self.capture([ticket(blockReasons=[], createdAt='2020-01-01')], mode='saved-state-observation')
        row = archive.show(self.directory,1)
        self.assertEqual(row['captureMode'],'saved-state-observation')
        self.assertNotEqual(row['capturedAt'], '2020-01-01')
        self.assertEqual(row['summary']['reasonStatus'],'not-recorded')

    def test_source_corruption_preserved_and_flagged_without_erasing_history(self):
        self.capture([ticket()])
        archive.capture_bytes(self.path,b'{bad')
        report = archive.build_decision_archive(self.directory)
        self.assertEqual(report['counts']['versions'], 1)
        self.assertEqual(report['verdict'], 'attention')
        self.assertTrue(report['sourceErrors'])
        self.assertTrue(archive.verify(self.directory)['ok'])

    def test_legacy_csv_extra_columns_preserved_without_inferred_rationale(self):
        raw=b'timestamp,ticker,action,note\n2026-09-28,TEST,skip,operator skipped,extra reason,50,2\n'
        archive.capture_bytes(self.root/'operator_decisions.csv',raw)
        row=archive.show(self.directory,1)
        self.assertEqual(row['sourceRecord']['_unmappedColumns'],['extra reason','50','2'])
        self.assertEqual(row['summary']['decisionRationaleStatus'],'not-recorded')

    def test_annotations_cannot_overwrite_original(self):
        self.capture([ticket()]); archive.annotate(self.directory,1,'operator','Later clarification')
        row=archive.show(self.directory,1)
        self.assertEqual(row['sourceRecord']['blockReasons'],['spread too wide'])
        self.assertEqual(row['retrospectiveAnnotations'][0]['reason'],'Later clarification')
        with self.assertRaises(sqlite3.IntegrityError):
            archive.annotate(self.directory,999,'operator','bad reference')

    def test_update_delete_are_rejected_and_backup_restores(self):
        self.capture([ticket()])
        with sqlite3.connect(self.directory/'archive.sqlite3') as db:
            for sql in ('DELETE FROM versions','UPDATE versions SET ticker="OTHER"','DELETE FROM snapshots'):
                with self.assertRaises(sqlite3.IntegrityError): db.execute(sql)
        restored=self.root/'restore';restored.mkdir()
        receipt=archive.backup(self.directory,restored/'archive.sqlite3')
        self.assertEqual(receipt['sqliteIntegrity'],'ok')
        self.assertTrue(archive.verify(restored)['ok'])
        self.assertEqual(archive.show(restored,1)['sourceRecord'],ticket())
        with self.assertRaises(FileExistsError): archive.backup(self.directory,restored/'archive.sqlite3')

    def test_sqlite_failure_spools_exact_evidence_and_retry_is_idempotent(self):
        with patch.object(archive,'connect',side_effect=sqlite3.OperationalError('busy')):
            with self.assertRaises(sqlite3.OperationalError): self.capture([ticket()])
        self.assertEqual(len(list((self.directory/'pending').glob('*.capture'))),1)
        self.assertEqual(archive.drain(self.directory)['newVersions'],1)
        self.assertEqual(archive.drain(self.directory)['newVersions'],0)

    def test_crash_after_commit_before_spool_cleanup_does_not_replay_transitions(self):
        archive.spool_capture(self.path.name,json.dumps({'items':[ticket()]}).encode(),self.directory,'test')
        archive.spool_capture(self.path.name,json.dumps({'items':[ticket(blockReasons=['changed'])]}).encode(),self.directory,'test')
        with patch.object(Path,'unlink',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError): archive.drain(self.directory)
        self.assertEqual(self.count('versions'),2)
        self.assertEqual(archive.drain(self.directory)['newVersions'],0)
        self.assertEqual(self.count('versions'),2)

    def test_concurrent_identical_captures_have_one_version(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.capture([ticket()]),range(8)))
        self.assertEqual(self.count('snapshots'),1)
        self.assertEqual(self.count('versions'),1)
        self.assertTrue(archive.verify(self.directory)['ok'])

    def test_atomic_writer_observes_exact_bytes_and_failure_does_not_repeat_primary_write(self):
        raw={'items':[ticket()]}
        atomic_write_json(self.path,raw)
        self.assertEqual(archive.show(self.directory,1)['sourceRecord'],ticket())
        with patch.object(archive,'drain',side_effect=sqlite3.OperationalError('busy')):
            atomic_write_json(self.path,{'items':[ticket(blockReasons=['new'])]})
        self.assertEqual(json.loads(self.path.read_text())['items'][0]['blockReasons'],['new'])
        self.assertTrue((self.directory/'capture_failures.jsonl').exists())
        archive.drain(self.directory)
        self.assertEqual(self.count('versions'),2)

    def test_unrelated_writes_are_never_archived(self):
        atomic_write_json(self.root/'credentials.json',{'secret':'fixture-only'})
        self.assertFalse(self.directory.exists())

    def test_tampered_object_is_detected(self):
        self.capture([ticket()])
        with sqlite3.connect(self.directory/'archive.sqlite3') as db:
            db.execute('DROP TRIGGER no_UPDATE_objects')
            db.execute('UPDATE objects SET body=?',(b'broken',))
        self.assertFalse(archive.verify(self.directory)['ok'])
