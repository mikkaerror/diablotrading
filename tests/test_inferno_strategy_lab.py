from __future__ import annotations

"""Regression tests for the strategy evidence lab.

These tests protect the statistical brakes that sit between "good-looking
paper results" and future broker authority. The lab should be conservative,
deterministic, and unwilling to promote tiny samples.
"""

import unittest

from inferno_math_config import MIN_WILSON_LOWER_FOR_EDGE
from inferno_strategy_lab import (
    MIN_WIN_RATE_LOWER_BOUND,
    build_strategy_lab,
    summarize_strategy,
    verdict_for_metrics,
    wilson_lower_bound,
)


def closed_ticket(index: int, pnl: float, strategy: str = "TEST_EDGE") -> dict[str, object]:
    """Build a minimal closed paper ticket for strategy-lab tests."""
    return {
        "ticketId": f"ticket-{index}",
        "ticker": f"T{index}",
        "eventId": f"T{index}|2026-07-01",
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

    def test_fixed_winrate_fallback_is_sourced_from_math_config(self) -> None:
        """The legacy fixed floor should not drift from the math audit surface."""
        self.assertEqual(MIN_WIN_RATE_LOWER_BOUND, MIN_WILSON_LOWER_FOR_EDGE)

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

    def test_repeated_same_event_cannot_clear_promotion_gate(self) -> None:
        """Thirty raw trades on one event are not thirty independent bets."""
        tickets = []
        for index in range(25):
            ticket = closed_ticket(index, 10.0, strategy="CORRELATED_EDGE")
            ticket["eventId"] = "ONE|2026-07-01"
            tickets.append(ticket)
        for index in range(25, 35):
            ticket = closed_ticket(index, -5.0, strategy="CORRELATED_EDGE")
            ticket["eventId"] = "ONE|2026-07-01"
            tickets.append(ticket)

        summary = summarize_strategy("CORRELATED_EDGE", tickets)

        self.assertEqual(summary["scoredCount"], 35)
        self.assertEqual(summary["distinctEventCount"], 1)
        self.assertEqual(summary["distinctEventGap"], 29)
        self.assertFalse(summary["verdict"]["promotable"])
        self.assertIn("distinct paper events", "; ".join(summary["verdict"]["blockers"]))

    def test_convex_payoff_edge_uses_payoff_aware_win_floor(self) -> None:
        """A low-hit-rate convex strategy can clear the corrected win-rate gate."""
        tickets = []
        idx = 0
        for _ in range(6):
            tickets.append(closed_ticket(idx, 25.0, strategy="CONVEX_EDGE"))
            idx += 1
            tickets.append(closed_ticket(idx, -10.0, strategy="CONVEX_EDGE"))
            idx += 1
            tickets.append(closed_ticket(idx, -10.0, strategy="CONVEX_EDGE"))
            idx += 1
        for _ in range(21):
            tickets.append(closed_ticket(idx, 25.0, strategy="CONVEX_EDGE"))
            idx += 1
            tickets.append(closed_ticket(idx, -10.0, strategy="CONVEX_EDGE"))
            idx += 1

        summary = summarize_strategy("CONVEX_EDGE", tickets)

        self.assertEqual(summary["scoredCount"], 60)
        self.assertEqual(summary["distinctEventCount"], 60)
        self.assertEqual(summary["winCount"], 27)
        self.assertEqual(summary["lossCount"], 33)
        self.assertEqual(summary["payoffRatio"], 2.5)
        self.assertEqual(summary["winRateBreakeven"], 0.2857)
        self.assertEqual(summary["winRateLowerBoundTarget"], 0.3157)
        self.assertEqual(
            summary["winRateLowerBoundTargetSource"],
            "payoff-implied-breakeven-plus-margin",
        )
        self.assertGreaterEqual(summary["winRateLowerBound"], summary["winRateLowerBoundTarget"])
        self.assertEqual(summary["verdict"]["level"], "promotable")

    def test_symmetric_payoff_requires_above_coinflip_floor(self) -> None:
        """The payoff-aware floor is stricter than 0.42 for 1:1 strategies."""
        verdict = verdict_for_metrics(
            {
                "scoredCount": 60,
                "winRateLowerBound": 0.49,
                "winRateLowerBoundTarget": 0.53,
                "winRateLowerBoundTargetSource": "payoff-implied-breakeven-plus-margin",
                "expectancyPerRiskConfidence": {"lower": 0.1},
                "profitFactor": 1.6,
                "maxDrawdownRiskUnits": -2.0,
                "falsePositiveRate": 0.2,
            }
        )

        self.assertFalse(verdict["promotable"])
        self.assertIn(
            "win-rate lower bound below 0.53 (payoff-implied-breakeven-plus-margin)",
            verdict["blockers"],
        )

    def test_drawdown_forces_cooldown(self) -> None:
        """A severe losing run should force cooldown regardless of sample count."""
        tickets = [closed_ticket(index, -10.0, strategy="BROKEN_EDGE") for index in range(31)]
        summary = summarize_strategy("BROKEN_EDGE", tickets)
        self.assertEqual(summary["verdict"]["level"], "cooldown")
        self.assertEqual(summary["riskUnitCap"], 0.0)


if __name__ == "__main__":
    unittest.main()
