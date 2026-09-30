import copy
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import inferno_paper_candidate_research as candidates
import inferno_paper_funnel as funnel
import inferno_strike_selector as selector
import inferno_paper_execution as execution
from inferno_short_premium_study import forward_record
from tests.test_inferno_short_premium_shadow import chain

NOW = datetime(2026, 10, 12, 16, tzinfo=timezone.utc)


def source():
    contracts = chain()
    for c in contracts:
        c.update(symbol=f"XYZ_{c['putCall']}_{c['strikePrice']}", volume=1000, openInterest=1000, volatility=30)
    return {'status': 'ok', 'quoteSessionIsRegular': True, 'sourceGeneratedAt': NOW.isoformat(),
            'sourceStatus': 'ok', 'underlyingPrice': 100, 'contracts': contracts,
            'quoteQualityScore': 95, 'quoteQualityLabel': 'excellent', 'qualityFlags': [],
            'paperLiquidityPass': True, 'atmLiquidityScore': 95, 'atmSpreadQuality': 'tight',
            'atmWindowMedianSpreadPct': .02, 'atmExpectedMoveBucket': 'normal'}


class PaperFunnelTests(unittest.TestCase):
    def test_weekly_counts_estimates_do_not_qualify_or_fill(self):
        rows = [
            {'ticketId': 'a', 'createdAt': '2026-09-28', 'strategy': 'S', 'status': 'paper-blocked', 'blockReasons': ['size', 'size', 'spread']},
            {'ticketId': 'b', 'createdAt': '2026-09-29', 'strategy': 'S', 'status': 'paper-staged', 'outcome': {'status': 'closed'}},
            {'ticketId': 'c', 'createdAt': '2026-09-30', 'strategy': 'S', 'status': 'paper-staged', 'paperExecution': {'openedAt': '2026-09-30', 'entryPrice': 1}},
        ]
        result = funnel.weekly_funnel({'items': rows + [rows[0]]}, {'records': [{'recordId': 'c', 'source': 'paper-execution-ledger', 'promotionEligible': True}]})[0]
        self.assertEqual([result[k] for k in ('proposed','blocked','staged','filled','qualified')], [3,1,2,1,1])
        self.assertEqual(result['blockedByReason'], {'size': 1, 'spread': 1})

    def test_five_dawn_days_required_and_best_rerun_cannot_inflate_average(self):
        runs = [{'generatedAt': f'2026-10-{d}T07:30:00-06:00', 'runKind': 'dawn', 'gatePassing': 3} for d in ('05','06','07','08','09')]
        runs += [{'generatedAt': '2026-10-05T08:00:00-06:00', 'runKind': 'dawn', 'gatePassing': 100}]
        result = funnel.dawn_acceptance(runs, today=date(2026,10,12))
        self.assertEqual(result['averageGatePassing'], 3)
        self.assertTrue(result['candidateTargetMet'])
        self.assertFalse(result['done'])  # boundary audit remains independent
        self.assertIsNone(funnel.dawn_acceptance(runs[2:5], today=date(2026,10,12))['averageGatePassing'])

    def test_answered_families_are_retained_only_in_shadow(self):
        shadow = {'items': [{'ticker': f'T{i}', 'strategy': 'CALL_DEBIT_SPREAD', 'expiration': '2026-10-16',
                             'outcome': {'status': 'closed', 'estimatedReturnOnRisk': -1}} for i in range(30)]}
        plan = {'ticker': 'NEW', 'ok': True, 'strikePlan': {'strategy': 'CALL_DEBIT_SPREAD'}}
        with patch.object(selector, 'build_strike_plan_for_intent', return_value=plan), patch.object(selector, 'annotate_strike_plans', return_value=([plan], {})):
            result = selector.build_strike_plan_from_queue({'items': [{'ticker': 'NEW'}]}, schwab_options_index={}, shadow_evidence=shadow)
        self.assertEqual(result['items'], [])
        self.assertEqual(result['shadowItems'][0]['primaryExclusionReason'], 'family-answered')
        self.assertTrue(result['shadowItems'][0]['shadowOnly'])
        self.assertIsNone(candidates.answered_reason(plan, {'items': shadow['items'][:29]}))

    def test_fly_uses_existing_constructor_and_survives_forward_arm(self):
        with patch.object(candidates, 'local_now', return_value=NOW):
            fly, reason = candidates.iron_fly_plan({'nextEarnings': '2026-10-14'}, source())
        self.assertEqual(reason, '')
        self.assertEqual(fly['contracts'], 1)
        self.assertEqual(fly['estimatedCredit'], 9.4)
        self.assertEqual(fly['estimatedMaxLoss'], 1060)
        self.assertEqual(len(fly['legs']), 4)
        row = {**fly, 'ticker': 'XYZ', 'arm': fly['arm'], 'outcome': {'status': 'closed', 'estimatedPnl': 100}}
        self.assertEqual(forward_record(row)['arm'], 'SHORT_PREMIUM_DEFINED')
        stale = {**source(), 'sourceGeneratedAt': '2026-10-01T16:00:00Z'}
        with patch.object(candidates, 'local_now', return_value=NOW):
            self.assertIsNone(candidates.iron_fly_plan({'nextEarnings': '2026-10-14'}, stale)[0])

    def test_new_candidate_cannot_use_auto_selection_instead_of_delegate(self):
        from types import SimpleNamespace
        with patch.object(execution, 'AUTO_PAPER_SELECTION_ENABLED', True):
            allowed, reason = execution.paper_auto_selection_decision(
                {'requiresDelegateApproval': True, 'approvalStatus': 'pending', 'ok': True}, SimpleNamespace(passed=True), [], [])
        self.assertFalse(allowed)
        self.assertEqual(reason, 'delegate-or-operator-approval-required')

    def test_size_only_retry_never_discards_other_blocks(self):
        item = {'riskVerdict': {'blocks': ['max loss $3000 exceeds single-ticket cap $2000', 'wide spread']},
                'strikePlan': {'contracts': 3, 'estimatedMaxLoss': 3000}}
        before = copy.deepcopy(item)
        with patch('inferno_risk_policy.evaluate_strike_item') as evaluate:
            self.assertEqual(candidates.fit_size_only(item, NOW.isoformat()), item)
            evaluate.assert_not_called()
        self.assertEqual(item, before)

    def test_one_lot_retry_rechecks_policy_and_records_original(self):
        from types import SimpleNamespace
        item = {'riskVerdict': {'blocks': ['max loss $3000 exceeds single-ticket cap $2000']},
                'strikePlan': {'strategy': 'S', 'contracts': 3, 'estimatedMaxLoss': 3000, 'estimatedMaxProfit': 600}}
        with patch('inferno_risk_policy.evaluate_strike_item', return_value=SimpleNamespace(as_dict=lambda: {'passed': True, 'blocks': []})) as evaluate:
            result = candidates.fit_size_only(item, NOW.isoformat())
        self.assertEqual(result['strikePlan']['estimatedMaxLoss'], 1000)
        self.assertEqual(result['sizeFit']['originalPlan']['contracts'], 3)
        self.assertEqual(evaluate.call_args.kwargs['mode'], 'paper')

    def test_priced_alternative_replaces_failed_primary_and_answered_count_is_exact(self):
        failed = {'ticker': 'XYZ', 'ok': False}
        passing = {'ticker': 'XYZ', 'ok': True, 'riskVerdict': {'passed': True}}
        with patch.object(selector, 'build_strike_plan_for_intent', side_effect=[failed, passing]), patch.object(selector, 'annotate_strike_plans', return_value=([failed, passing], {})):
            result = selector.build_strike_plan_from_queue({'items': [{}, {}]}, schwab_options_index={}, shadow_evidence={})
        self.assertTrue(result['items'][0]['ok'])
        self.assertEqual(result['answeredPrimaryExclusions'], 0)
        self.assertEqual(len(result['shadowItems']), 1)

    def test_dawn_observation_excludes_blocked_and_shadow_and_deduplicates(self):
        import json
        passing = {'ok': True, 'riskVerdict': {'passed': True}, 'strikePlan': {'strategy': 'S'}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'runs.jsonl'
            plan = {'generatedAt': NOW.isoformat(), 'runKind': 'dawn', 'items': [passing,
                    {**passing, 'shadowOnly': True}, {**passing, 'concentrationDemoted': True},
                    {**passing, 'intentBlocks': ['trigger not ready']}]}
            funnel.observe_run(plan, path)
            funnel.observe_run(plan, path)
            records = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['gatePassing'], 1)

    def test_narrower_vertical_is_repriced_and_rechecked(self):
        from types import SimpleNamespace
        src = source()
        item = {'price': 100, 'riskVerdict': {'blocks': ['max loss $3000 exceeds single-ticket cap $2000']},
                'schwabOptions': src, 'strikePlan': {'strategy': 'CALL_DEBIT_SPREAD', 'width': 40,
                'expiration': '2026-10-16', 'estimatedMaxLoss': 3000}}
        with patch('inferno_risk_policy.evaluate_strike_item', return_value=SimpleNamespace(as_dict=lambda: {'passed': True, 'blocks': []})) as evaluate:
            result = candidates.fit_size_only(item, NOW.isoformat())
        self.assertIn('originalPlan', result['sizeFit'])
        self.assertLess(result['strikePlan']['width'], 40)
        self.assertLess(result['strikePlan']['estimatedMaxLoss'], 3000)
        self.assertTrue(evaluate.called)
