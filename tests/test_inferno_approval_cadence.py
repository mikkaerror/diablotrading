from __future__ import annotations

"""Regression tests for the approval cadence diagnostic.

Contract:
- diagnostic-only: cannot mutate the approval queue
- batting order is sorted by urgency score (descending)
- decide-today flag fires for earnings within 3 days OR staleness within
  1 market day
- the urgency formula stays committed (60% earnings, 25% staleness,
  15% readiness)
"""

import unittest
from datetime import datetime

from inferno_approval_cadence import (
    CADENCE_FILE,
    CADENCE_STAGE,
    CADENCE_TEXT_FILE,
    annotate_pending_item,
    build_cadence,
    urgency_score,
)


def queue_item(
    ticker: str,
    *,
    days_to_earnings: int = 14,
    readiness: int = 80,
    setup: str = "Straddle",
    pending_since: str | None = "2026-05-08T08:00:00-06:00",
    status: str = "pending",
    decision_at: str | None = None,
) -> dict:
    payload = {
        "ticker": ticker,
        "setupRec": setup,
        "readiness": readiness,
        "daysUntilEarnings": days_to_earnings,
        "signalTrigger": True,
        "primaryRoute": "STRADDLE (10)",
        "secondaryRoute": "VERTICAL (5)",
        "approvalStatus": status,
    }
    if pending_since:
        payload["pendingSince"] = pending_since
    if decision_at:
        payload["decisionAt"] = decision_at
    return payload


class ApprovalCadenceTests(unittest.TestCase):
    """Verify cadence stays diagnostic-only and ranks pending items correctly."""

    def test_artifact_paths_are_distinct_and_stage_label_committed(self) -> None:
        self.assertTrue(str(CADENCE_FILE).endswith("inferno_approval_cadence.json"))
        self.assertTrue(str(CADENCE_TEXT_FILE).endswith("approval_cadence_latest.txt"))
        self.assertEqual(CADENCE_STAGE, "approval-cadence-diagnostic-only")

    def test_urgency_weights_are_60_25_15(self) -> None:
        """The committed urgency formula must remain 60/25/15."""
        # earnings=0 (max pressure), staleness=full TTL pending, readiness=100
        item = {"daysUntilEarnings": 0, "readiness": 100}
        score_max = urgency_score(item, days_pending=5, ttl_market_days=5)
        # 0.60*1.0 + 0.25*1.0 + 0.15*1.0 = 1.0
        self.assertAlmostEqual(score_max, 1.0, places=4)
        # earnings far away, brand-new pending, low readiness → near zero
        item_low = {"daysUntilEarnings": 21, "readiness": 0}
        score_low = urgency_score(item_low, days_pending=0, ttl_market_days=5)
        # 0 + 0 + 0 = 0
        self.assertAlmostEqual(score_low, 0.0, places=4)

    def test_decide_today_fires_when_earnings_within_three_days(self) -> None:
        now = datetime.fromisoformat("2026-05-10T08:00:00-06:00")
        annotated = annotate_pending_item(
            queue_item("CEG", days_to_earnings=2),
            now=now,
            ttl_market_days=5,
        )
        self.assertTrue(annotated["decideToday"])
        self.assertTrue(any("earnings" in r for r in annotated["decideReasons"]))

    def test_decide_today_fires_when_staleness_imminent(self) -> None:
        now = datetime.fromisoformat("2026-05-10T08:00:00-06:00")
        # Pending 5 weekdays earlier puts staleness at 0 days remaining.
        annotated = annotate_pending_item(
            queue_item("OLD", days_to_earnings=20, pending_since="2026-05-01T08:00:00-06:00"),
            now=now,
            ttl_market_days=5,
        )
        self.assertTrue(annotated["decideToday"])
        self.assertTrue(any("stale" in r for r in annotated["decideReasons"]))

    def test_decide_today_quiet_when_neither_pressure_present(self) -> None:
        now = datetime.fromisoformat("2026-05-10T08:00:00-06:00")
        annotated = annotate_pending_item(
            queue_item("CALM", days_to_earnings=14, pending_since="2026-05-10T08:00:00-06:00"),
            now=now,
            ttl_market_days=5,
        )
        self.assertFalse(annotated["decideToday"])
        self.assertEqual(annotated["decideReasons"], [])

    def test_batting_order_sorted_by_urgency_descending(self) -> None:
        now = datetime.fromisoformat("2026-05-10T08:00:00-06:00")
        queue = {
            "generatedAt": now.isoformat(),
            "items": [
                queue_item("FAR", days_to_earnings=20, readiness=50),
                queue_item("CEG", days_to_earnings=1, readiness=99),
                queue_item("MID", days_to_earnings=10, readiness=70),
            ],
        }
        cadence = build_cadence(queue, ttl_market_days=5, now=now)
        tickers = [row["ticker"] for row in cadence["battingOrder"]]
        self.assertEqual(tickers, ["CEG", "MID", "FAR"])

    def test_diagnostic_only_flags_are_always_set(self) -> None:
        cadence = build_cadence({"items": []}, ttl_market_days=5,
                                now=datetime.fromisoformat("2026-05-10T08:00:00-06:00"))
        self.assertTrue(cadence["diagnosticOnly"])
        self.assertEqual(cadence["counts"]["pending"], 0)

    def test_build_cadence_does_not_mutate_input_queue(self) -> None:
        now = datetime.fromisoformat("2026-05-10T08:00:00-06:00")
        original = {
            "generatedAt": now.isoformat(),
            "items": [queue_item("CEG", days_to_earnings=1)],
        }
        snapshot = repr(original)
        build_cadence(original, ttl_market_days=5, now=now)
        self.assertEqual(repr(original), snapshot)

    def test_decided_today_count_uses_decision_at(self) -> None:
        now = datetime.fromisoformat("2026-05-10T08:00:00-06:00")
        queue = {
            "items": [
                queue_item(
                    "DECIDED1", status="approved",
                    decision_at="2026-05-10T07:00:00-06:00",
                ),
                queue_item(
                    "DECIDED_OLD", status="rejected",
                    decision_at="2026-05-01T07:00:00-06:00",
                ),
                queue_item("PENDING1"),
            ]
        }
        cadence = build_cadence(queue, ttl_market_days=5, now=now)
        self.assertEqual(cadence["counts"]["decidedToday"], 1)
        self.assertEqual(cadence["counts"]["pending"], 1)


if __name__ == "__main__":
    unittest.main()
