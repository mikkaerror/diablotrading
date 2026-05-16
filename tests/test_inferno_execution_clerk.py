from __future__ import annotations

"""Regression tests for execution-queue rehearsal widening controls."""

import unittest
from unittest.mock import patch

from inferno_execution_clerk import build_execution_queue


def row(ticker: str) -> dict:
    """Build a minimal snapshot row accepted by the execution clerk."""
    return {
        "ticker": ticker,
        "setupRec": "Vertical Call",
        "signalTrigger": True,
        "readiness": 90,
        "confidence": 3,
        "daysUntilEarnings": 7,
        "price": 50.0,
        "priority": 5.0,
        "marketContext": {},
        "rec1": "VERTICAL (10)",
        "rec2": "STRADDLE (4.5)",
    }


class InfernoExecutionClerkTests(unittest.TestCase):
    """Verify queue overrides widen paper review without mutating live rules."""

    def test_limit_override_and_capacity_override_expand_rehearsal_queue(self) -> None:
        snapshot = {
            "rows": [row("AAA"), row("BBB"), row("CCC")],
            "reviewQueueTickers": ["AAA", "BBB", "CCC"],
        }
        approval_queue = {
            "items": [
                {"ticker": "AAA", "approvalStatus": "approved"},
                {"ticker": "BBB", "approvalStatus": "approved"},
                {"ticker": "CCC", "approvalStatus": "approved"},
            ]
        }

        with (
            patch("inferno_execution_clerk.MAX_ACTIVE_EXECUTION_INTENTS", 1),
            patch("inferno_execution_clerk.MAX_DAILY_RISK_UNITS", 10.0),
        ):
            live_queue = build_execution_queue(
                snapshot,
                approval_queue,
                limit_override=3,
                enforce_capacity_limits=True,
            )
            rehearsal_queue = build_execution_queue(
                snapshot,
                approval_queue,
                limit_override=3,
                enforce_capacity_limits=False,
            )

        self.assertEqual(len(live_queue["items"]), 3)
        self.assertEqual(live_queue["activeReadyCount"], 1)
        self.assertEqual(
            [item["intentStatus"] for item in live_queue["items"]],
            ["approval-ready", "blocked", "blocked"],
        )
        self.assertEqual(rehearsal_queue["activeReadyCount"], 3)
        self.assertEqual(
            [item["intentStatus"] for item in rehearsal_queue["items"]],
            ["approval-ready", "approval-ready", "approval-ready"],
        )


if __name__ == "__main__":
    unittest.main()
