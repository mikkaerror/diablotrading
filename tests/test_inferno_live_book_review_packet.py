from __future__ import annotations

"""Regression tests for the live-book deployment review packet."""

import unittest
from unittest.mock import patch

from inferno_live_book_review_packet import (
    build_position_packet,
    build_review_packet,
    resistance_headroom_pct,
    support_cushion_pct,
)


class LiveBookReviewPacketTests(unittest.TestCase):
    """Verify the blocker packet turns live-review rows into actionable math."""

    def test_support_and_resistance_math_is_directional(self) -> None:
        self.assertAlmostEqual(support_cushion_pct(100, 90), 10.0)
        self.assertAlmostEqual(resistance_headroom_pct(100, 110), 10.0)
        self.assertAlmostEqual(support_cushion_pct(100, 105), -5.0)

    def test_fragile_position_hard_blocks_capital(self) -> None:
        packet = build_position_packet(
            {
                "symbol": "GDS",
                "qty": 4,
                "markValue": 180,
                "weightPct": 16,
                "plOpen": 7,
                "plPercent": 4,
                "posture": "fragile",
                "actionLabel": "manual-review",
                "convictionScore": 17.5,
                "riskFlags": ["earnings-soon", "fragile-alignment"],
                "trackerContext": {
                    "support": 40,
                    "resistance": 47,
                    "daysUntilEarnings": 6,
                    "alignmentLabel": "Fragile",
                },
            }
        )

        self.assertEqual(packet["unlockEffect"], "hard-blocks-new-capital")
        self.assertEqual(packet["math"]["earningsBucket"], "immediate")
        self.assertGreaterEqual(packet["reviewHeat"], 80)
        self.assertTrue(any("capital deployment blocked" in prompt for prompt in packet["reviewPrompts"]))

    @patch("inferno_live_book_review_packet.save_review_packet")
    @patch("inferno_live_book_review_packet.load_json_file")
    def test_review_packet_summarizes_blockers_and_warnings(self, load_json_mock, _save_mock) -> None:
        load_json_mock.side_effect = [
            {
                "generatedAt": "2026-05-14T17:00:00-06:00",
                "positions": [
                    {"symbol": "GDS", "posture": "fragile", "convictionScore": 20, "riskFlags": []},
                    {"symbol": "THR", "posture": "review", "convictionScore": 45, "riskFlags": []},
                    {"symbol": "FLR", "posture": "supported", "convictionScore": 90, "riskFlags": []},
                ],
            },
            {
                "generatedAt": "2026-05-14T17:01:00-06:00",
                "verdict": "not-ready",
                "manualDeploymentAllowed": False,
                "autoLiveAllowed": False,
            },
        ]

        packet = build_review_packet()

        self.assertEqual(packet["verdict"], "blocked")
        self.assertEqual(packet["counts"]["hardBlockers"], 1)
        self.assertEqual(packet["counts"]["warnings"], 1)
        self.assertEqual(packet["counts"]["supported"], 1)
        self.assertIn("Resolve GDS", "\n".join(packet["unlockChecklist"]))


if __name__ == "__main__":
    unittest.main()
