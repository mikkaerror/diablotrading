import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_walk_forward as walk
import inferno_factor_regression as regression
from inferno_research_records import shadow_records


class ResearchRecordsTests(unittest.TestCase):
    def test_canonical_producer_schema_reaches_both_diagnostics(self):
        payload = {'items': [
            {'strategy': 'LONG_STRADDLE', 'estimatedMaxLoss': 200,
             'outcome': {'status': 'closed', 'estimatedPnl': -100, 'reviewedAt': '2026-07-02'}},
            {'strategy': 'LONG_STRADDLE', 'riskVerdict': {'metrics': {'maxLossDollars': 100}},
             'outcome': {'status': 'closed', 'estimatedPnl': 40, 'reviewedAt': '2026-07-01'}},
        ]}
        before = copy.deepcopy(payload)
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'inferno_shadow_evidence.json').write_text(json.dumps(payload))
            for module in (walk, regression):
                with patch.object(module, 'DATA_DIR', Path(temp)):
                    rows = module._default_shadow_loader()
                self.assertEqual(len(rows), 2)
                self.assertEqual(walk.chronologically_ordered_by_strategy(rows)['LONG_STRADDLE'], [.4, -.5])
                self.assertEqual(len(regression.build_design_matrix(rows)[1]), 2)
        self.assertEqual(payload, before)

    def test_empty_current_schema_does_not_resurrect_legacy_rows(self):
        self.assertEqual(shadow_records({'items': [], 'records': [{'estimatedPnl': 100}]}), [])
        self.assertEqual(shadow_records({'items': 'broken'}), [])
        self.assertEqual(shadow_records({'items': [None, {'outcome': 'broken'}]}), [])

    def test_invalid_numbers_never_become_scorable(self):
        for bad in (None, True, 'nan', 'inf', 'bad'):
            rows = shadow_records({'items': [{'estimatedMaxLoss': 100, 'outcome': {'status': 'closed', 'estimatedPnl': bad}}]})
            self.assertEqual(walk.chronologically_ordered_by_strategy(rows), {})
        for bad in (None, 0, -1, True, 'nan', 'inf'):
            rows = shadow_records([{'maxLossDollars': bad, 'estimatedPnl': 20, 'outcomeStatus': 'closed'}])
            self.assertEqual(walk.chronologically_ordered_by_strategy(rows), {})

    def test_legacy_input_supported_without_changing_authority(self):
        for key in ('records', 'entries', 'rows'):
            row = shadow_records({key: [{'estimatedPnl': 20, 'maxLossDollars': 100, 'outcomeStatus': 'closed'}]})[0]
            self.assertEqual(row['estimatedPnl'], 20)
            self.assertEqual(row['evidenceBasis'], 'unverified-shadow-proxy')
