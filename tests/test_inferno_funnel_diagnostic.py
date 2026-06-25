"""Contract tests for inferno_funnel_diagnostic.

Pinned invariants:
  - researchOnly=True, diagnosticOnly=True, promotable=False.
  - Strategy classification: known buy/sell families map deterministically.
  - Bias-verdict thresholds are pinned.
  - The module NEVER mutates snapshot, director, queue, or any gate.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import inferno_funnel_diagnostic as fd


class ClassifyTests(unittest.TestCase):
    def test_straddle_is_premium_buy(self) -> None:
        self.assertEqual(fd._classify_setup("Straddle"), "premium-buy")

    def test_iron_condor_is_premium_sell(self) -> None:
        self.assertEqual(fd._classify_setup("Iron Condor"), "premium-sell")

    def test_avoid_is_avoid(self) -> None:
        self.assertEqual(fd._classify_setup("Avoid"), "avoid")

    def test_empty_is_no_setup(self) -> None:
        self.assertEqual(fd._classify_setup(""), "no-setup")
        self.assertEqual(fd._classify_setup(None), "no-setup")

    def test_unknown_is_other(self) -> None:
        self.assertEqual(fd._classify_setup("Astrology Spread"), "other")


class BuildDiagnosticTests(unittest.TestCase):
    def _snap(self, rows: list[dict]) -> dict:
        return {"generatedAt": "2026-06-25T00:00:00Z", "rows": rows}

    def test_monoculture_verdict_when_all_premium_buy(self) -> None:
        rows = [
            {"ticker": f"T{i}", "setupRec": "Straddle", "price": 10.0, "ivRank": 40}
            for i in range(10)
        ]
        with patch.object(fd, "_load_json", side_effect=lambda p: self._snap(rows) if str(p).endswith("latest_snapshot.json") else {}):
            out = fd.build_diagnostic()
        self.assertEqual(out["biasVerdict"], "premium-buy-monoculture")
        self.assertIsNone(out["biasRatio"])

    def test_balanced_verdict_when_mixed_families(self) -> None:
        rows = [
            {"ticker": "A", "setupRec": "Straddle", "price": 10.0, "ivRank": 40},
            {"ticker": "B", "setupRec": "Iron Condor", "price": 10.0, "ivRank": 40},
        ]
        with patch.object(fd, "_load_json", side_effect=lambda p: self._snap(rows) if str(p).endswith("latest_snapshot.json") else {}):
            out = fd.build_diagnostic()
        self.assertEqual(out["biasVerdict"], "balanced")

    def test_credit_spread_candidate_filter(self) -> None:
        # IV rank > 50, dte_earn > 14 (or None), price < $100
        rows = [
            {"ticker": "A", "setupRec": "Straddle", "price": 50.0, "ivRank": 60, "daysUntilEarnings": 30},  # qualifies
            {"ticker": "B", "setupRec": "Straddle", "price": 50.0, "ivRank": 60, "daysUntilEarnings": 5},   # too close to earnings
            {"ticker": "C", "setupRec": "Straddle", "price": 200.0, "ivRank": 60, "daysUntilEarnings": 30}, # too expensive
            {"ticker": "D", "setupRec": "Straddle", "price": 50.0, "ivRank": 40, "daysUntilEarnings": 30},  # IVR too low
        ]
        with patch.object(fd, "_load_json", side_effect=lambda p: self._snap(rows) if str(p).endswith("latest_snapshot.json") else {}):
            out = fd.build_diagnostic()
        self.assertEqual(out["counts"]["creditSpread"], 1)
        self.assertEqual(out["creditSpreadCandidates"][0]["ticker"], "A")

    def test_wheel_candidate_filter(self) -> None:
        rows = [
            {"ticker": "W", "setupRec": "Vertical Call", "price": 15.0, "ivRank": 40, "signalTrigger": True},   # qualifies
            {"ticker": "X", "setupRec": "Vertical Call", "price": 50.0, "ivRank": 40, "signalTrigger": True},   # too expensive
            {"ticker": "Y", "setupRec": "Vertical Call", "price": 15.0, "ivRank": 20, "signalTrigger": True},   # IVR too low
            {"ticker": "Z", "setupRec": "Vertical Call", "price": 15.0, "ivRank": 40, "signalTrigger": False},  # no signal
        ]
        with patch.object(fd, "_load_json", side_effect=lambda p: self._snap(rows) if str(p).endswith("latest_snapshot.json") else {}):
            out = fd.build_diagnostic()
        self.assertEqual(out["counts"]["wheel"], 1)
        self.assertEqual(out["wheelCandidates"][0]["ticker"], "W")

    def test_sweet_spot_filter(self) -> None:
        # 7-14 DTE earnings + ATR>2
        rows = [
            {"ticker": "S1", "setupRec": "Straddle", "price": 50.0, "ivRank": 40, "daysUntilEarnings": 10, "atrPercent": 3.0},  # qualifies
            {"ticker": "S2", "setupRec": "Straddle", "price": 50.0, "ivRank": 40, "daysUntilEarnings": 20, "atrPercent": 3.0},  # too far
            {"ticker": "S3", "setupRec": "Straddle", "price": 50.0, "ivRank": 40, "daysUntilEarnings": 10, "atrPercent": 1.0},  # low ATR
        ]
        with patch.object(fd, "_load_json", side_effect=lambda p: self._snap(rows) if str(p).endswith("latest_snapshot.json") else {}):
            out = fd.build_diagnostic()
        self.assertEqual(out["counts"]["sweetSpot"], 1)


class InvariantTests(unittest.TestCase):
    def test_payload_has_research_only_invariants(self) -> None:
        with patch.object(fd, "_load_json", return_value={}):
            out = fd.build_diagnostic()
        self.assertEqual(out["stage"], "funnel-diagnostic-research-only")
        self.assertTrue(out["researchOnly"])
        self.assertTrue(out["diagnosticOnly"])
        self.assertFalse(out["promotable"])
        self.assertFalse(out["authorityChanged"])
        self.assertFalse(out["brokerSubmitAllowed"])
        self.assertFalse(out["liveTradingAllowed"])


if __name__ == "__main__":
    unittest.main()
