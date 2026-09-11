import copy
import importlib.util
import unittest
from pathlib import Path

import pandas as pd

PATH = Path(__file__).resolve().parents[1] / 'outputs/position-strategy-2026-09-10/analyze.py'
SPEC = importlib.util.spec_from_file_location('portfolio_strategy_research', PATH)
RESEARCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESEARCH)


class PortfolioResearchTests(unittest.TestCase):
    def setUp(self):
        self.legs = [dict(symbol='ABC  261218C00100000',assetType='OPTION',qty=1,
                          derivedTradePrice=8,markValue=900),
                     dict(symbol='ABC  261218C00105000',assetType='OPTION',qty=-1,
                          derivedTradePrice=6,markValue=-620)]

    def test_complete_vertical_uses_net_risk_and_value(self):
        result = RESEARCH.call_vertical(self.legs)
        self.assertEqual(result['initialRisk'],200)
        self.assertEqual(result['markedValue'],280)
        self.assertEqual(result['maximumProfit'],300)
        self.assertEqual(result['breakEven'],102)

    def test_mismatched_expiry_does_not_hide_naked_exposure(self):
        self.legs[1]['symbol']='ABC  270115C00105000'
        with self.assertRaises(ValueError):
            RESEARCH.call_vertical(self.legs)

    def test_mismatched_quantity_and_extra_legs_rejected(self):
        self.legs[1]['qty']=-2
        with self.assertRaises(ValueError):
            RESEARCH.call_vertical(self.legs)
        with self.assertRaises(ValueError):
            RESEARCH.call_vertical(self.legs + [copy.deepcopy(self.legs[0])])

    def test_stress_budget_and_larger_decline_reduce_size(self):
        self.assertEqual(RESEARCH.stress_size(1000,.05,.5),100)
        self.assertEqual(RESEARCH.stress_size(1000,.05,.25),200)
        for decline in [0,-.1,float('nan'),float('inf')]:
            with self.assertRaises(ValueError):
                RESEARCH.stress_size(1000,.05,decline)

    def test_currency_half_cent_rounds_consistently(self):
        self.assertEqual(RESEARCH.money(335.135),335.14)

    def row(self):
        return {'candles':[dict(datetime=d.isoformat(),open=100,close=100,
                                high=101,low=99,volume=1000)
                            for d in pd.date_range('2025-01-01',periods=220,tz='UTC')]}

    def test_flat_price_zero_return_and_true_range(self):
        frame=RESEARCH.history_frame(self.row())
        result=RESEARCH.metrics(frame,frame)
        self.assertEqual(result['return63Pct'],0)
        self.assertEqual(result['relative63PctPoints'],0)
        self.assertEqual(result['atr14'],2)
        self.assertEqual(result['sma200'],100)

    def test_prior_high_excludes_current_observation(self):
        row=self.row()
        row['candles'][-1]['high']=200
        frame=RESEARCH.history_frame(row)
        self.assertEqual(RESEARCH.metrics(frame,frame)['prior20High'],101)

    def test_duplicate_and_bad_ohlc_rejected(self):
        row=self.row()
        row['candles'][-1]['datetime']=row['candles'][-2]['datetime']
        with self.assertRaises(ValueError):
            RESEARCH.history_frame(row)
        row=self.row()
        row['candles'][-1]['low']=102
        with self.assertRaises(ValueError):
            RESEARCH.history_frame(row)

    def test_unaligned_benchmark_rejected(self):
        frame=RESEARCH.history_frame(self.row())
        with self.assertRaises(ValueError):
            RESEARCH.metrics(frame,frame.iloc[1:])


if __name__ == '__main__':
    unittest.main()
