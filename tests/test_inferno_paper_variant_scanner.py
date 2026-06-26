from __future__ import annotations

"""Tests for the research-only paper variant scanner."""

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import inferno_paper_variant_scanner as scanner


def snapshot_payload() -> dict:
    return {
        "generatedAt": "snapshot-now",
        "rows": [
            {
                "ticker": "IREN",
                "price": 45.0,
                "ivRank": 80.0,
                "readiness": 85.0,
                "signalTrigger": True,
                "daysUntilEarnings": 30,
                "setupRec": "Straddle",
                "trend": "Bullish",
                "rvol": 0.9,
                "support": 40.0,
                "resistance": 52.0,
                "distanceToSupportPct": 12.0,
                "distanceToResistancePct": 15.0,
                "atrPercent": 5.0,
            },
            {
                "ticker": "CIFR",
                "price": 4.5,
                "ivRank": 42.0,
                "readiness": 82.0,
                "signalTrigger": True,
                "daysUntilEarnings": 25,
                "setupRec": "Avoid",
                "trend": "Neutral",
                "rvol": 0.8,
                "support": 3.8,
                "resistance": 5.4,
                "distanceToSupportPct": 15.0,
                "distanceToResistancePct": 20.0,
                "atrPercent": 5.0,
            },
            {
                "ticker": "AZZ",
                "price": 81.0,
                "ivRank": 24.0,
                "readiness": 77.0,
                "signalTrigger": True,
                "daysUntilEarnings": 10,
                "setupRec": "Vertical Call",
                "trend": "Bullish",
                "rvol": 1.1,
                "support": 76.0,
                "resistance": 90.0,
                "distanceToSupportPct": 6.0,
                "distanceToResistancePct": 11.0,
                "atrPercent": 3.5,
            },
        ],
    }


class PaperVariantScannerTests(unittest.TestCase):
    """Scanner output must stay diagnostic and paper-only."""

    def setUp(self) -> None:
        fixed_now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
        self.time_patch = patch("inferno_paper_variant_scanner.local_now", return_value=fixed_now)
        self.time_patch.start()

    def tearDown(self) -> None:
        self.time_patch.stop()

    def test_build_scanner_finds_bounded_paper_only_variants(self) -> None:
        payload = scanner.build_paper_variant_scanner(
            snapshot=snapshot_payload(),
            funnel={"generatedAt": "funnel-now", "biasVerdict": "premium-buy-monoculture"},
            limit=8,
        )

        self.assertEqual(payload["verdict"], "paper-variants-ready-for-pricing")
        self.assertTrue(payload["researchOnly"])
        self.assertTrue(payload["diagnosticOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["authorityChanged"])
        self.assertFalse(payload["brokerSubmitAllowed"])
        self.assertFalse(payload["liveTradingAllowed"])
        self.assertEqual(payload["sourceFunnelBiasVerdict"], "premium-buy-monoculture")

        families = {item["sourceFamily"] for item in payload["pricingCandidates"]}
        self.assertEqual(families, {"credit-spread", "wheel-proxy"})
        self.assertEqual(payload["counts"]["pricingCandidates"], 2)
        self.assertEqual(payload["counts"]["watchOnly"], 1)
        self.assertEqual(payload["watchOnlyCandidates"][0]["ticker"], "AZZ")
        self.assertTrue(all(item["paperVariantOnly"] for item in payload["pricingCandidates"]))
        self.assertEqual(
            {item["recommendedStrategy"] for item in payload["pricingCandidates"]},
            {"PUT_CREDIT_SPREAD"},
        )

    def test_scanner_text_keeps_authority_warning_visible(self) -> None:
        payload = scanner.build_paper_variant_scanner(
            snapshot=snapshot_payload(),
            funnel={"generatedAt": "funnel-now"},
            limit=1,
        )

        rendered = scanner.scanner_text(payload)

        self.assertIn("Authority: research-only; broker submit OFF; live trading OFF", rendered)
        self.assertIn("IREN", rendered)
        self.assertIn("no live orders", rendered)


if __name__ == "__main__":
    unittest.main()
