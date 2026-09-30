import copy
import unittest
from research.friction_proposal import leg_cost, diagnose, build


class FrictionProposalTests(unittest.TestCase):
    def ticket(self):
        return {'ticketId':'fixture','ticker':'TEST','strategy':'CALL_DEBIT_SPREAD','expiration':'2026-09-18',
                'entryCostType':'debit','entryLimit':3.2,'estimatedMaxLoss':320,
                'estimatedTotalSpreadFrictionDollars':12.86,'paperFrictionCrossings':1,
                'legs':[{'instruction':'BUY_TO_OPEN','bid':4,'ask':5},
                        {'instruction':'SELL_TO_OPEN','bid':1.8,'ask':2.4}],
                'outcome':{'status':'closed','estimatedPnl':180,'estimatedReturnOnRisk':0.5625}}

    def test_quote_sum_and_embedded_natural_are_distinct(self):
        t=self.ticket();q=leg_cost(t)
        self.assertEqual(q['halfSpreadDollars'],80)
        self.assertEqual(q['natural'],3.2)
        self.assertEqual(q['mid'],2.4)
        result=diagnose(t,'shadow')
        self.assertTrue(result['entryAtNatural'])
        self.assertEqual(result['literalChallenger']['netPnlEstimateDollars'],100)

    def test_ratios_and_quantities_use_each_leg(self):
        t=self.ticket();t['legs'][0]['quantity']=2
        self.assertEqual(leg_cost(t)['halfSpreadDollars'],130)
        t['legs'][0]['quantity']=0
        self.assertFalse(leg_cost(t)['ok'])

    def test_invalid_quotes_fail_without_zero_or_partial_charge(self):
        for value in [None,float('nan'),-1,6]:
            t=self.ticket();t['legs'][0]['bid']=value
            self.assertFalse(leg_cost(t)['ok'])
        t=self.ticket();t['legs'][0]['instruction']='UNKNOWN'
        self.assertFalse(leg_cost(t)['ok'])

    def test_zero_spread_valid_and_actual_execution_is_not_rescored(self):
        t=self.ticket();t['legs'][0]['ask']=4;t['legs'][1]['ask']=1.8
        self.assertEqual(leg_cost(t)['halfSpreadDollars'],0)
        t['paperExecution']={'entryFilledAt':'2026-09-01'}
        self.assertNotIn('baseline',diagnose(t,'paper'))

    def test_read_only_replay_and_backtest_does_not_consume_friction_field(self):
        shadow={'items':[self.ticket()]};before=copy.deepcopy(shadow)
        reducer={'scenarioSlate':[{'ticker':'TEST','strategy':'CALL_DEBIT_SPREAD'}]}
        result=build({'items':[]},shadow,reducer,{})
        self.assertEqual(shadow,before)
        self.assertTrue(result['fieldOnlyBacktestUnchanged'])
        self.assertNotEqual(result['backtestBaseline']['scorecards'],result['backtestLiteralCostSensitivity']['scorecards'])
        self.assertFalse(result['promotable'])

    def test_explicit_outcome_costs_are_preserved(self):
        t=self.ticket();t['outcome']['feesAndSlippage']=7
        result=diagnose(t,'shadow')
        self.assertEqual(result['baseline'],result['literalChallenger'])

    def test_invalid_risk_and_inconsistent_return_cannot_change_backtest_sample(self):
        for change in ({'estimatedMaxLoss':0}, {'outcome':{'status':'closed','estimatedPnl':180,'estimatedReturnOnRisk':99}}):
            t={**self.ticket(), **change}
            self.assertFalse(diagnose(t,'shadow')['scoreComparable'])
            result=build({'items':[]},{'items':[t]},{'scenarioSlate':[{'ticker':'TEST','strategy':'CALL_DEBIT_SPREAD'}]}, {})
            self.assertEqual(result['backtestBaseline']['scorecards'],result['backtestLiteralCostSensitivity']['scorecards'])
