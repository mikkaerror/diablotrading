from __future__ import annotations

"""Regression tests for the strategy evidence lab.

These tests protect the statistical brakes that sit between "good-looking
paper results" and future broker authority. The lab should be conservative,
deterministic, and unwilling to promote tiny samples.
"""

import unittest

from inferno_strategy_lab import build_strategy_lab, summarize_strategy, wilson_lower_bound


def closed_ticket(index: int, pnl: float, strategy: str = "TEST_EDGE") -> dict[str, object]:
    """Build a minimal closed paper ticket for strategy-lab tests."""
    return {
        "ticketId": f"ticket-{index}",
        "ticker": f"T{index}",
        "strategy": strategy,
        "status": "paper-staged",
        "riskVerdict": {"metrics": {"maxLossDollars": 10}},
        "outcome": {
            "status": "closed",
            "reviewedAt": "2026-04-27T09:00:00-06:00",
            "estimatedPnl": pnl,
        },
    }


class StrategyLabTests(unittest.TestCase):
    """Verify the evidence lab stays conservative and promotion-safe."""

    def test_wilson_lower_bound_penalizes_small_hot_streak(self) -> None:
        """A perfect tiny sample should not be treated as certain edge."""
        lower = wilson_lower_bound(4, 4)
        self.assertIsNotNone(lower)
        self.assertLess(lower or 0, 0.7)

    def test_empty_strategy_is_insufficient_data(self) -> None:
        """No closed trades means no promotion and no risk cap."""
        summary = summarize_strategy("EMPTY", [])
        verdict = summary["verdict"]
        self.assertEqual(verdict["level"], "insufficient-data")
        self.assertEqual(summary["riskUnitCap"], 0.0)

    def test_positive_tiny_sample_stays_evidence_building(self) -> None:
        """Positive early outcomes still need sample depth."""
        tickets = [closed_ticket(index, 10.0) for index in range(5)]
        summary = summarize_strategy("SMALL_EDGE", tickets)
        self.assertEqual(summary["verdict"]["level"], "evidence-building")
        self.assertFalse(summary["verdict"]["promotable"])

    def test_large_positive_sample_can_be_promotable(self) -> None:
        """A broad, positive, low-drawdown sample may pass promotion gates."""
        tickets = []
        for index in range(25):
            tickets.append(closed_ticket(index, 10.0, strategy="PROMOTABLE_EDGE"))
        for index in range(25, 35):
            tickets.append(closed_ticket(index, -5.0, strategy="PROMOTABLE_EDGE"))
        lab = build_strategy_lab(
            {
                "updatedAt": "2026-04-27T09:00:00-06:00",
                "items": tickets,
            }
        )
        self.assertIn("PROMOTABLE_EDGE", lab["promotionCandidates"])
        self.assertEqual(lab["deskVerdict"]["level"], "review-for-promotion")

    def test_drawdown_forces_cooldown(self) -> None:
        """A severe losing run should force cooldown regardless of sample count."""
        tickets = [closed_ticket(index, -10.0, strategy="BROKEN_EDGE") for index in range(31)]
        summary = summarize_strategy("BROKEN_EDGE", tickets)
        self.assertEqual(summary["verdict"]["level"], "cooldown")
        self.assertEqual(summary["riskUnitCap"], 0.0)


if __name__ == "__main__":
    unittest.main()
