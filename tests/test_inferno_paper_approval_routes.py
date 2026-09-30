from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import inferno_approval_queue as queue
import inferno_paper_approval_routes as routes
import inferno_paper_delegate as delegate
import inferno_paper_execution as paper

NOW = datetime(2026, 9, 30, 14, tzinfo=timezone.utc)


def candidate(strategy, loss, family=None):
    return {'ticker': 'ACN', 'generatedAt': NOW.isoformat(), 'nextEarnings': '2026-10-01',
            'daysUntilEarnings': 1, 'ok': True, 'approvalStatus': 'pending',
            'intentStatus': 'blocked', 'intentBlocks': ['human approval missing'],
            'paperVariantFamily': family,
            'strikePlan': {'strategy': strategy, 'expiration': '2026-10-02',
                'estimatedMaxLoss': loss, 'estimatedDebit': loss/100,
                'legs': [{'symbol': strategy+'-leg', 'instruction': 'BUY_TO_OPEN', 'quantity': 1}]}}


def entry(item, blocks=None):
    item = routes.apply_route_approval(item, {}, NOW.isoformat())
    strike = item['strikePlan']
    return {'ticker': item['ticker'], 'ticketId': strike['strategy'], 'strategy': strike['strategy'],
            'estimatedMaxLoss': strike['estimatedMaxLoss'], 'daysUntilEarnings': 1,
            'sourceStrikePlanGeneratedAt': NOW.isoformat(), 'legs': strike['legs'],
            'approvalRouteKey': item['approvalRouteKey'], 'approvalCandidate': item,
            'paperVariantFamily': item.get('paperVariantFamily'),
            'blockReasons': blocks or ['human approval missing'],
            'riskVerdict': {'passed': True, 'blocks': [], 'metrics': {
                'maxLossDollars': strike['estimatedMaxLoss'], 'effectiveSingleTicketCap': 2000}}}


class ApprovalRouteTests(unittest.TestCase):
    def setUp(self):
        self.primary = candidate('LONG_STRADDLE', 12520)
        self.spread = candidate('CALL_DEBIT_SPREAD', 330, 'cap-fit-debit-5w')
        self.fly = candidate('SHORT_PREMIUM_DEFINED', 500, 'iron-fly')
        self.entries = [entry(self.primary), entry(self.spread), entry(self.fly)]
        self.queue = routes.queue_from_entries(self.entries, {}, NOW.isoformat())

    def test_same_name_has_distinct_tokens_and_complete_risk_family(self):
        self.assertEqual(len({x['approvalToken'] for x in self.queue['items']}), 3)
        spread = self.queue['items'][1]
        self.assertEqual((spread['strategy'], spread['maxLoss'], spread['family']), ('CALL_DEBIT_SPREAD', 330, 'cap-fit-debit-5w'))
        self.assertIsNone(queue.find_item(self.queue, 'ACN'))
        self.assertIsNone(queue.find_item({'items':[self.queue['items'][1]]}, 'ACN'))
        with patch.object(queue, 'save_queue') as save:
            self.assertEqual(queue.update_item.__wrapped__(self.queue, 'ACN', 'approved'), 1)
            save.assert_not_called()
        result = queue.apply_reply_commands(self.queue, 'APPROVE ACN')
        self.assertEqual(result['matchedCount'], 0)

    def test_variant_decision_does_not_approve_primary_or_sibling(self):
        token = self.queue['items'][1]['approvalToken']
        queue.apply_reply_commands(self.queue, 'APPROVE '+token)
        self.assertEqual(routes.apply_route_approval(self.spread, self.queue, NOW.isoformat())['approvalStatus'], 'approved')
        self.assertEqual(routes.apply_route_approval(self.primary, self.queue, NOW.isoformat())['approvalStatus'], 'pending')
        self.assertEqual(routes.apply_route_approval(self.fly, self.queue, NOW.isoformat())['approvalStatus'], 'pending')
        for change in ['estimatedMaxLoss', 'expiration', 'legs']:
            changed = deepcopy(self.spread)
            changed['strikePlan'][change] = {'estimatedMaxLoss': 331, 'expiration': '2026-10-09',
                'legs': [{'symbol': 'changed', 'quantity': 2}]}[change]
            self.assertEqual(routes.apply_route_approval(changed, self.queue, NOW.isoformat())['approvalStatus'], 'pending')

    def test_existing_nonapproval_gate_survives_and_primary_rejection_does_not_leak(self):
        self.spread.update(approvalStatus='rejected', intentBlocks=['human reviewer rejected the name', 'trigger is not live'])
        self.queue['items'][1]['approvalStatus'] = 'approved'
        result = routes.apply_route_approval(self.spread, self.queue, NOW.isoformat())
        self.assertEqual(result['intentBlocks'], ['trigger is not live'])
        self.assertEqual(result['intentStatus'], 'blocked')

    def test_refresh_preserves_exact_decision_and_pending_token_but_drops_changed_request(self):
        self.queue['items'][1]['approvalStatus'] = 'approved'
        fresh = routes.queue_from_entries(self.entries, self.queue, (NOW+timedelta(hours=1)).isoformat())
        self.assertEqual(fresh['items'][1]['approvalStatus'], 'approved')
        self.assertEqual(fresh['items'][0]['approvalToken'], self.queue['items'][0]['approvalToken'])
        altered = deepcopy(self.spread); altered['strikePlan']['estimatedMaxLoss'] = 340
        refreshed = routes.queue_from_entries([entry(altered)], self.queue, NOW.isoformat())
        self.assertEqual(refreshed['items'][0]['approvalStatus'], 'pending')
        self.assertNotEqual(refreshed['items'][0]['approvalToken'], self.queue['items'][1]['approvalToken'])

    def test_delegate_uses_each_ledger_construction_not_ticker_primary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, data in [('inferno_approval_queue.json', self.queue),
                               ('inferno_strike_plan.json', {'generatedAt': NOW.isoformat(), 'items': [self.primary]}),
                               ('inferno_paper_execution_ledger.json', {'items': self.entries})]:
                (root/name).write_text(json.dumps(data))
            report = delegate.build_paper_delegate(root, NOW)
            self.assertEqual([(d['strategy'], d['action']) for d in report['decisions']],
                             [('LONG_STRADDLE', 'reject'), ('CALL_DEBIT_SPREAD', 'approve'), ('SHORT_PREMIUM_DEFINED', 'approve')])
            self.entries[1]['blockReasons'] = ['human approval missing', 'Schwab paper liquidity gate failed']
            (root/'inferno_paper_execution_ledger.json').write_text(json.dumps({'items': self.entries}))
            self.assertEqual(delegate.build_paper_delegate(root, NOW)['decisions'][1]['action'], 'hold')

    def test_family_rejection_and_stale_gate_still_apply_to_variant(self):
        c, stamp = routes.delegate_candidate(self.queue['items'][1], {'items': self.entries})
        shadow = {'items': [{'ticker': 'ACN', 'strategy': 'CALL_DEBIT_SPREAD',
                             'outcome': {'status': 'closed', 'estimatedReturnOnRisk': -.8}} for _ in range(15)]}
        self.assertEqual(delegate.decide(self.queue['items'][1], c, 1, shadow)['rule'], 'shadow-answered')
        self.assertEqual(delegate.decide(self.queue['items'][1], c, 100, {})['rule'], 'stale-plan')
        broken = deepcopy(self.entries); broken[1]['approvalCandidate']['strikePlan']['estimatedMaxLoss'] = 1
        self.assertEqual(routes.delegate_candidate(self.queue['items'][1], {'items': broken}), (None, None))

    def test_blocked_to_staged_updates_same_ticket_without_rewriting_fills_or_closes(self):
        old = {'ticketId':'x', 'status':'paper-blocked', 'ticker':'ACN', 'strategy':'CALL_DEBIT_SPREAD',
               'tradeDate':'2026-09-30', 'expiration':'2026-10-02', 'legs':[],
               'outcome':{'status':'not-opened'}, 'createdAt':'original'}
        staged = {**old, 'status':'paper-staged', 'outcome':{'status':'open'}, 'createdAt':'refresh'}
        result, inserted = paper.merge_entries({'items':[old]}, [staged])
        self.assertEqual((result['items'][0]['status'],result['items'][0]['outcome']['status'], inserted),('paper-staged','open',0))
        self.assertEqual(result['items'][0]['createdAt'], 'original')
        for outcome in ['closed', 'open']:
            protected = {**old, 'outcome':{'status':outcome}, 'paperExecution':{'entry':{'price':3.3}}}
            result, _ = paper.merge_entries({'items':[protected]}, [staged])
            self.assertEqual(result['items'][0], protected)

    def test_shadow_alternate_can_supply_variant_without_staging_shadow_primary(self):
        shadow = {**self.primary, 'shadowOnly': True, 'primaryExclusionReason': 'alternate-to-primary'}
        def fake_entry(item, stamp, ledger):
            row = entry(item)
            row['status'] = 'paper-blocked'
            row['outcome'] = {'status':'not-opened'}
            return row
        with patch('inferno_ledger_ownership.ownership', return_value={'status':'active'}), \
             patch('inferno_ledger_ownership.require_paper_writer'), \
             patch.object(paper, 'load_ledger', return_value={'items':[]}), \
             patch.object(paper, 'load_json_file', return_value={}), \
             patch.object(paper, 'save_ledger'), \
             patch.object(paper, 'build_ledger_entry', side_effect=fake_entry), \
             patch.object(paper, 'rehearsal_variant_item', return_value=None), \
             patch.object(paper, 'cap_fit_defined_risk_variant_item', side_effect=lambda item, _: self.spread if item is shadow else None), \
             patch.object(queue, 'load_queue', return_value={}), patch.object(queue, 'save_queue') as save:
            result = paper.record_from_strike_plan.__wrapped__({'generatedAt':NOW.isoformat(),'items':[self.fly],'shadowItems':[shadow]}, {'items':[]})
        strategies = {r['strategy'] for r in result['ledger']['items']}
        self.assertEqual(strategies, {'CALL_DEBIT_SPREAD','SHORT_PREMIUM_DEFINED'})
        self.assertEqual({r['strategy'] for r in save.call_args.args[0]['items']}, strategies)

    def test_morning_refresh_keeps_exact_route_decisions_for_canonical_repricing(self):
        import morning_inferno_pipeline as morning
        with tempfile.TemporaryDirectory() as tmp, patch.object(morning, 'APPROVAL_QUEUE_FILE', Path(tmp)/'queue.json'), \
             patch('inferno_ledger_ownership.is_cloud', return_value=False), \
             patch('inferno_ledger_ownership.require_paper_writer'), \
             patch.object(morning, 'load_json_file', return_value=self.queue):
            self.queue['items'][1]['approvalStatus'] = 'rejected'
            row = {'ticker':'ACN','setupRec':'Straddle','readiness':90,'daysUntilEarnings':1,
                   'signalTrigger':True,'rec1':'Straddle','rec2':'Watch'}
            rebuilt = morning.write_approval_queue({'generatedAt':NOW.isoformat(),'rows':[row],'reviewQueueTickers':['ACN']})
        self.assertEqual(len(rebuilt['items']),3)
        self.assertEqual(rebuilt['items'][1]['approvalStatus'],'rejected')

    def test_scoped_decision_cannot_make_ticker_execution_ready(self):
        from inferno_execution_clerk import build_execution_queue
        self.queue['items'][1]['approvalStatus']='approved'
        snapshot={'reviewQueueTickers':['ACN'],'rows':[{'ticker':'ACN','setupRec':'Straddle',
                  'signalTrigger':True,'readiness':90,'confidence':3}]}
        result=build_execution_queue(snapshot,self.queue)
        self.assertEqual(result['items'][0]['approvalStatus'],'pending')
        self.assertNotEqual(result['items'][0]['intentStatus'],'approval-ready')

    def test_event_passed_is_recomputed_instead_of_reusing_old_countdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'inferno_approval_queue.json').write_text(json.dumps(self.queue))
            (root/'inferno_paper_execution_ledger.json').write_text(json.dumps({'items':self.entries}))
            report=delegate.build_paper_delegate(root,NOW+timedelta(days=1))
        self.assertEqual(report['decisions'][1]['rule'],'event-passed')

    def test_variant_repricing_invalidates_canonical_cycle_cache(self):
        import inferno_mac_paper_cycle as cycle
        with tempfile.TemporaryDirectory() as tmp, patch.object(cycle,'ROOT',Path(tmp)):
            data=Path(tmp)/'data';data.mkdir()
            for n in ['latest_snapshot.json','inferno_approval_queue.json','inferno_schwab_options.json']:
                (data/n).write_text('{}')
            first=cycle.input_revision()
            (data/'inferno_strategy_alternative_pricing.json').write_text('{"newPrice":330}')
            second=cycle.input_revision()
            self.assertNotEqual(first,second)
            self.assertEqual(second,cycle.input_revision())
