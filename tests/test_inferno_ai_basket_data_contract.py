from datetime import datetime, timezone
from pathlib import Path
import unittest

from inferno_ai_basket_data_contract import build_contract


class BasketDataContractTests(unittest.TestCase):
    def test_partial_momentum_and_inferred_snapshot_fail_closed(self):
        now = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)
        snapshot = [{"symbol": "AMD"}, {"symbol": "NVDA"}]
        momentum = {"generatedAt": now.isoformat(), "ranking": [{"symbol": "AMD"}]}
        result = build_contract(snapshot, momentum, snapshot_path=Path("missing-snapshot"), momentum_path=Path("missing-momentum"), now=now)
        self.assertEqual(result["verdict"], "fail-closed")
        self.assertEqual(result["sources"]["momentum"]["missingSymbols"], ["NVDA"])
        self.assertFalse(result["signalsTrusted"])

    def test_complete_embedded_fresh_sources_are_trusted(self):
        now = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)
        snapshot = {"generatedAt": now.isoformat(), "records": [{"symbol": "AMD"}, {"symbol": "NVDA"}]}
        momentum = {"generatedAt": now.isoformat(), "ranking": [{"symbol": "AMD"}, {"symbol": "NVDA"}]}
        result = build_contract(snapshot, momentum, now=now)
        self.assertEqual(result["verdict"], "trusted")
        self.assertTrue(result["sources"]["snapshot"]["provenanceExplicit"])

    def test_duplicates_block_complete_coverage(self):
        now = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)
        snapshot = {"generatedAt": now.isoformat(), "records": [{"symbol": "AMD"}, {"symbol": "NVDA"}]}
        momentum = {"generatedAt": now.isoformat(), "ranking": [{"symbol": "AMD"}, {"symbol": "AMD"}, {"symbol": "NVDA"}]}
        result = build_contract(snapshot, momentum, now=now)
        self.assertEqual(result["sources"]["momentum"]["duplicateSymbols"], ["AMD"])
        self.assertFalse(result["signalsTrusted"])

    def test_declared_universe_prevents_partial_snapshot_from_self_approving(self):
        now = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)
        snapshot = {
            "generatedAt": now.isoformat(),
            "expectedUniverse": ["AMD", "NVDA"],
            "records": [{"symbol": "AMD"}],
        }
        momentum = {"generatedAt": now.isoformat(), "ranking": [{"symbol": "AMD"}]}
        result = build_contract(snapshot, momentum, now=now)
        self.assertEqual(result["sources"]["snapshot"]["missingSymbols"], ["NVDA"])
        self.assertFalse(result["signalsTrusted"])


if __name__ == "__main__":
    unittest.main()
