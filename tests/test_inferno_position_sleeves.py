import json
import tempfile
import unittest
from pathlib import Path

from inferno_position_sleeves import sleeve_tag, save_history
from inferno_live_account_sync import build_position_packet
from inferno_live_position_review import build_position_review


class PositionSleeveTests(unittest.TestCase):
    def setUp(self):
        self.context = {'holds': {'symbols': ['IREN']}, 'plan': {'coreVehicle': 'SMH'},
                        'ack': {'active': True, 'operator': 'Mikka', 'signedAt': '2026-09-30', 'signed': ['sleeveTargets']},
                        'sourceHashes': {'fixture': 'hash'}, 'assignments': {'positions': [
                            {'symbol': 'VRT', 'sleeve': 'conviction', 'effectiveFrom': '2026-09-30', 'source': 'operator attribution'}]}}
        self.asof = '2026-09-30T15:00:00Z'

    def tag(self, symbol, **extra):
        return sleeve_tag({'symbol': symbol, **extra}, self.context, self.asof)

    def test_all_sleeves_are_sourced_and_scores_do_not_assign(self):
        for symbol, sleeve in [('IREN', 'holds'), ('SMH', 'core'), ('VRT', 'conviction'), ('IREN 261016C00050000', 'options')]:
            row = self.tag(symbol)
            self.assertEqual(row['sleeve'], sleeve)
            self.assertTrue(row['sleeveSource'])
        self.assertEqual(self.tag('IREN', assetType='OPTION')['sleeve'], 'options')
        self.assertIsNone(self.tag('NVDA', convictionScore=100, bucket='long-term-core')['sleeve'])

    def test_unsigned_core_future_mapping_and_conflicts_remain_unknown(self):
        self.context['ack']['active'] = False
        self.assertIsNone(self.tag('SMH')['sleeve'])
        self.assertIsNone(sleeve_tag({'symbol': 'VRT'}, self.context, '2026-09-01')['sleeve'])
        self.context['assignments']['positions'].append(dict(self.context['assignments']['positions'][0]))
        self.assertEqual(self.tag('VRT')['sleeveStatus'], 'conflicted')

    def test_metadata_survives_sync_and_review_without_altering_bucket(self):
        packet = build_position_packet({'symbol': 'IREN', 'assetType': 'EQUITY'}, None, 1000)
        packet.update(self.tag('IREN'))
        review = build_position_review(packet, {}, {}, {'IREN'})
        self.assertEqual(review['sleeve'], 'holds')
        self.assertEqual(review['bucket'], packet['bucket'])
        self.assertEqual(review['sleeveSourceHashes'], {'fixture': 'hash'})
        self.assertEqual(review['assetType'], 'EQUITY')

    def test_history_deduplicates_refreshes_and_preserves_mapping_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = {'ok': True, 'schwabAccountGeneratedAt': self.asof, 'matchedSuffix': 'fixture',
                      'positions': [{'symbol': 'IREN', **self.tag('IREN')}]}
            save_history(report, root)
            report['generatedAt'] = 'later refresh'
            save_history(report, root)
            self.assertEqual(len(list((root / 'data/position_sleeve_history').glob('*.json'))), 1)
            report['positions'][0]['sleeve'] = 'conviction'
            save_history(report, root)
            self.assertEqual(len(list((root / 'data/position_sleeve_history').glob('*.json'))), 2)
            report['ok'] = False
            report['positions'][0]['sleeve'] = 'core'
            save_history(report, root)
            rows = [json.loads(p.read_text()) for p in (root / 'data/position_sleeve_history').glob('*.json')]
            self.assertEqual({r['positions'][0]['sleeve'] for r in rows}, {'holds', 'conviction'})
