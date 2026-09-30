import copy
import hashlib
import json
import os
import platform
import tempfile
import unittest
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch, Mock

import inferno_ledger_ownership as owner
import inferno_ledger_reconciliation as reconciliation
import inferno_canonical_paper_snapshot as snapshots
import inferno_paper_execution as paper
import inferno_approval_queue as approvals
import inferno_record_fill as fills
import inferno_tos_fill_ingest as ingest
import inferno_tos_sandbox as sandbox
import inferno_paper_provenance as provenance
from inferno_promotion_evidence_lineage import build_promotion_evidence_lineage


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        # A Cowork copy can contain the real Mac receipt. Tests must never use
        # that receipt, its host paths, or a deployed cloud job's environment.
        stack = ExitStack()
        self.addCleanup(stack.close)
        root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        ack = root / 'operator_ack.json'
        ack.write_text(json.dumps({'decisions': {
            'D5_ledgerOwner': {'answer': 'mac'},
            'D6_paperSingleTicketCapDollars': {'answer': 2000}}}))
        for name, value in [('ROOT', root), ('STATE_FILE', root / 'ownership.json'), ('ACK_FILE', ack)]:
            stack.enter_context(patch.object(owner, name, value))
        stack.enter_context(patch.dict(os.environ, {
            'CLOUD_RUN_JOB': '', 'K_SERVICE': '', 'INFERNO_DESK_HOST_ROLE': ''}))

    def test_copied_canonical_receipt_cannot_grant_another_host_write_access(self):
        owner.STATE_FILE.write_text(json.dumps({'status': 'active', 'owner': 'mac',
            'canonicalRoot': '/another-host/canonical-checkout', 'hostname': 'another-host'}))
        with patch.object(snapshots.subprocess, 'run') as run:
            with self.assertRaisesRegex(PermissionError, 'designated canonical Mac checkout'):
                snapshots.publish('example-bucket')
            run.assert_not_called()

    @patch.dict(os.environ, {'INFERNO_DESK_HOST_ROLE': 'cloud-research'})
    def test_cloud_blocks_paper_queue_fill_and_delegate_before_writes(self):
        import inferno_paper_delegate as delegate
        for call in (lambda: paper.record_from_strike_plan({'items': []}),
                     lambda: approvals.save_queue({'items': []}),
                     lambda: fills.record_fill('TEST', entry_price=1),
                     lambda: delegate.apply_decisions({'ackActive': True})):
            with self.assertRaises(PermissionError): call()

    def test_reconciliation_keeps_conflicts_and_never_invents_credit(self):
        a={'ticketId': 'x', 'status': 'paper-staged', 'ticker': 'X', 'outcome': {'status': 'closed', 'estimatedPnl': 20}}
        b={**a, 'outcome': {'status': 'closed', 'estimatedPnl': 99}}
        inputs=({'items': [a]}, {'items': [b, {'ticketId': 'y', 'status': 'paper-blocked'}]})
        before=copy.deepcopy(inputs)
        report=reconciliation.reconcile(*inputs)
        self.assertEqual(inputs,before)
        self.assertEqual(report['classes'], {'conflicted': 1, 'cloud-only': 1})
        self.assertEqual(report['qualifiedIncreaseFromMigration'], 0)
        self.assertEqual(report, reconciliation.reconcile(*inputs))

    def test_corrupt_snapshot_fails_before_local_sources_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in snapshots.REQUIRED:
                p=root/name; p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
            manifest, contents=snapshots.snapshot(root)
            store={snapshots.POINTER: json.dumps(manifest).encode()}
            for name,raw in contents.items():store[f'{snapshots.PREFIX}/{manifest["revision"]}/{name}']=raw
            corrupt=next(k for k in store if k.endswith('inferno_tos_fill_log.csv'));store[corrupt]=b'bad'
            bucket=Mock();bucket.blob.side_effect=lambda name: Mock(download_as_bytes=lambda: store[name])
            with self.assertRaisesRegex(ValueError,'checksum'):snapshots.restore_snapshot(bucket,root)
            self.assertEqual((root/'data/inferno_paper_execution_ledger.json').read_text(),'{}')

    def test_approve_stage_record_fills_qualify_on_one_canonical_host(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root=Path(tmp); data=root/'data';data.mkdir()
            ledger=data/'ledger.json'; ledger.write_text('{"items": []}')
            queue_file=data/'queue.json'; fill_log=data/'fills.csv'; state=data/'ownership.json'
            state.write_text(json.dumps({'status':'active','owner':'mac','hostname':platform.node(),
                'canonicalRoot':str(root),'ackSha256':hashlib.sha256(owner.ACK_FILE.read_bytes()).hexdigest()}))
            for module,name,value in [(owner,'ROOT',root),(owner,'STATE_FILE',state),
                (paper,'PAPER_EXECUTION_LEDGER_FILE',ledger),(paper,'PAPER_EXECUTION_TEXT_FILE',data/'ledger.txt'),
                (approvals,'APPROVAL_QUEUE_FILE',queue_file),(sandbox,'TOS_FILL_LOG_WORK_FILE',fill_log),
                (sandbox,'TOS_FILL_LOG_TEMPLATE_FILE',data/'template.csv'),(ingest,'TOS_FILL_LOG_WORK_FILE',fill_log),
                (provenance,'TOS_FILL_LOG_WORK_FILE',fill_log)]:stack.enter_context(patch.object(module,name,value))
            stack.enter_context(patch.object(approvals,'refresh_execution_queue'))
            stack.enter_context(patch.object(ingest,'save_ingest_report'))
            stack.enter_context(patch.object(fills,'save_performance_analytics'))
            stack.enter_context(patch.object(paper,'load_json_file',side_effect=lambda p: json.loads(ledger.read_text()) if p == ledger else {}))
            now=paper.local_now(); expiration=(now.date()+timedelta(days=20)).isoformat()
            item={'ticker':'TEST','ok':True,'setupRec':'Vertical Call','approvalStatus':'pending',
                'intentStatus':'blocked','intentBlocks':['human approval still required'],'price':100,
                'ivRank':30,'atrPercent':3,'forecastRealizedMovePct':8,
                'strikePlan':{'strategy':'CALL_DEBIT_SPREAD','expiration':expiration,'estimatedDebit':2,
                'estimatedMaxLoss':200,'estimatedMaxProfit':300,'width':5,'liquidityNotes':[],
                'greekSummary':{'netDelta':.5,'netGamma':.04,'netTheta':-.03,'netVega':.03,'greeksComplete':True},
                'legs':[{'symbol':'TEST_CALL100','instruction':'BUY_TO_OPEN','optionType':'CALL','strike':100,'expiration':expiration,'bid':2.8,'ask':3},
                        {'symbol':'TEST_CALL105','instruction':'SELL_TO_OPEN','optionType':'CALL','strike':105,'expiration':expiration,'bid':1,'ask':1.1}]}}
            blocked=paper.build_ledger_entry(item,now.isoformat(),{'items':[]})
            self.assertEqual(blocked['status'],'paper-blocked')
            plan={'generatedAt':now.isoformat(),'items':[item]}
            paper.record_from_strike_plan(plan,strategy_pricing={'items':[]})
            queue=approvals.load_queue()
            self.assertEqual(len(queue['items']),1)
            self.assertEqual(approvals.update_item(queue,queue['items'][0]['approvalToken'],'approved'),0)
            result=paper.record_from_strike_plan(plan,strategy_pricing={'items':[]})
            ticket=result['ledger']['items'][0]
            self.assertEqual(ticket['status'],'paper-staged', ticket['blockReasons'])
            sandbox.seed_fill_log_from_stageable([ticket],now.date().isoformat())
            fills.record_fill(ticket['ticketId'],entry_price=2,contracts=1)
            self.assertEqual(paper.load_ledger()['items'][0]['paperExecution']['status'],'open')
            fills.record_fill(ticket['ticketId'],exit_price=3.5)
            final=paper.load_ledger()
            lineage=build_promotion_evidence_lineage(final,{}, {}, {},source=provenance.load_fill_source())
            self.assertEqual(lineage['promotionTruth']['qualified'],1,lineage['records'])
            self.assertFalse(final['items'][0]['brokerSubmitAllowed'])
            self.assertFalse(final['items'][0]['liveTradingAllowed'])

    def test_service_reload_at_night_cannot_stage_paper(self):
        from datetime import datetime
        from inferno_mac_paper_cycle import in_dawn_window
        self.assertFalse(in_dawn_window(datetime(2026, 9, 29, 22)))
        self.assertTrue(in_dawn_window(datetime(2026, 9, 30, 7)))
        self.assertFalse(in_dawn_window(datetime(2026, 10, 3, 7)))

    def test_unconfigured_checkout_cannot_publish_canonical_state(self):
        with patch.object(snapshots, 'ownership', return_value={}), patch.object(snapshots.subprocess, 'run') as run:
            with self.assertRaisesRegex(PermissionError, 'active Mac ownership'):
                snapshots.publish('example-bucket')
            run.assert_not_called()
