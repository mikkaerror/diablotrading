from __future__ import annotations

import json
import unittest

import inferno_ai_basket_config as config


class InfernoAiBasketConfigTests(unittest.TestCase):
    def test_config_matches_tracked_universe_contract(self) -> None:
        payload = json.loads(config.UNIVERSE_FILE.read_text(encoding="utf-8"))

        self.assertEqual(config.SYMBOLS, payload["expectedUniverse"])
        self.assertEqual(len(config.SYMBOLS), 27)
        self.assertNotIn("RBC", config.BASKET)
        self.assertNotIn("RRX", config.BASKET)
        self.assertNotIn("TKR", config.BASKET)

    def test_missing_contract_fails_closed(self) -> None:
        self.assertEqual(config.load_basket(config.ROOT / "research" / "missing.json"), {})

    def test_symbol_normalization_does_not_create_membership(self) -> None:
        self.assertEqual(config.normalize_symbol(" nvda "), "NVDA")
        self.assertEqual(config.category(config.normalize_symbol("rbc")), "")

    def test_contract_requires_explicit_trust(self) -> None:
        self.assertTrue(config.data_contract_trusted({"signalsTrusted": True}))
        self.assertFalse(config.data_contract_trusted({"signalsTrusted": False}))
        self.assertFalse(config.data_contract_trusted({}))


if __name__ == "__main__":
    unittest.main()
