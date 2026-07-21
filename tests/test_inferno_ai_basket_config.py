from __future__ import annotations

import json
import unittest

import inferno_ai_basket_config as config


class InfernoAiBasketConfigTests(unittest.TestCase):
    def test_config_matches_tracked_universe_contract(self) -> None:
        payload = json.loads(config.UNIVERSE_FILE.read_text(encoding="utf-8"))

        self.assertEqual(config.SYMBOLS, payload["expectedUniverse"])
        # Universe widened 27 -> 30 on 2026-07-20 by explicit operator approval:
        # the bearings/robotics sleeve (RBC, RRX, TKR) was requested by the
        # operator and was previously present in the tracker artifact but missing
        # from the engine contract, so the email silently covered only 27 names.
        self.assertEqual(len(config.SYMBOLS), 30)
        for symbol in ("RBC", "RRX", "TKR"):
            self.assertIn(symbol, config.BASKET)
            self.assertEqual(config.BASKET[symbol], "Bearings")

    def test_missing_contract_fails_closed(self) -> None:
        self.assertEqual(config.load_basket(config.ROOT / "research" / "missing.json"), {})

    def test_symbol_normalization_does_not_create_membership(self) -> None:
        self.assertEqual(config.normalize_symbol(" nvda "), "NVDA")
        # intent preserved: normalizing a NON-member must not fabricate membership.
        # ("rbc" was the original example; it is a real member as of 2026-07-20.)
        self.assertEqual(config.category(config.normalize_symbol("tsla")), "")

    def test_contract_requires_explicit_trust(self) -> None:
        self.assertTrue(config.data_contract_trusted({"signalsTrusted": True}))
        self.assertFalse(config.data_contract_trusted({"signalsTrusted": False}))
        self.assertFalse(config.data_contract_trusted({}))


if __name__ == "__main__":
    unittest.main()
