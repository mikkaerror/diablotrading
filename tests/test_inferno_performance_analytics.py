from __future__ import annotations

"""Regression tests for performance analytics block-reason categorization.

The goal is to keep the verbose block-reason histogram from drowning out the
operator. The categorizer collapses 40+ unique strings into a handful of
actionable buckets. These tests freeze the bucket vocabulary so a future
edit cannot silently drop a category or reroute approval failures into the
wrong bucket.
"""

import unittest

from inferno_performance_analytics import (
    BLOCK_REASON_CATEGORIES,
    block_reason_categories,
    block_reason_counts,
    categorize_block_reason,
)


def blocked_ticket(reasons: list[str]) -> dict:
    return {
        "ticketId": f"ticket-{abs(hash(tuple(reasons))) % 10000}",
        "status": "paper-blocked",
        "blockReasons": reasons,
    }


class BlockReasonCategorizerTests(unittest.TestCase):
    """Verify the bucket vocabulary stays meaningful and stable."""

    def test_bucket_vocabulary_is_committed(self) -> None:
        """The committed category labels are part of the contract."""
        labels = {label for label, _ in BLOCK_REASON_CATEGORIES}
        for required in (
            "approval-missing",
            "size-cap-violation",
            "wide-spread",
            "reward-risk-floor",
            "setup-concentration-cap",
            "exception",
        ):
            self.assertIn(required, labels)

    def test_categorize_block_reason_routes_known_strings(self) -> None:
        cases = [
            ("human approval missing", "approval-missing"),
            ("execution intent is not approval-ready", "approval-missing"),
            ("max loss $2075.00 exceeds single-ticket cap $500.00", "size-cap-violation"),
            ("projected daily max loss $2075.00 exceeds cap $1500.00", "size-cap-violation"),
            ("CLFD260515C00035000 spread is wide at 105%", "wide-spread"),
            ("reward/risk 0.30 is below debit-spread floor 0.50", "reward-risk-floor"),
            ("no supported strike plan for Vertical Call", "strike-plan-error"),
            ("KeyError: 'ask'", "exception"),
            ("setup-concentration-cap", "setup-concentration-cap"),
            ("something completely unrelated", "other"),
        ]
        for reason, expected in cases:
            with self.subTest(reason=reason):
                self.assertEqual(categorize_block_reason(reason), expected)

    def test_block_reason_categories_collapses_verbose_reasons(self) -> None:
        tickets = [
            blocked_ticket(["human approval missing", "execution intent is not approval-ready"]),
            blocked_ticket(["max loss $2075.00 exceeds single-ticket cap $500.00"]),
            blocked_ticket(["max loss $560.00 exceeds single-ticket cap $500.00"]),
            blocked_ticket(["CLFD spread is wide at 105%"]),
            blocked_ticket(["KeyError: 'ask'"]),
        ]
        categories = block_reason_categories(tickets)
        self.assertEqual(categories["approval-missing"]["count"], 2)
        self.assertEqual(categories["size-cap-violation"]["count"], 2)
        self.assertEqual(categories["wide-spread"]["count"], 1)
        self.assertEqual(categories["exception"]["count"], 1)
        # Each bucket keeps up to 3 example strings for context.
        for payload in categories.values():
            self.assertLessEqual(len(payload["examples"]), 3)

    def test_block_reason_categories_handles_empty_input(self) -> None:
        self.assertEqual(block_reason_categories([]), {})

    def test_block_reason_counts_remains_unchanged(self) -> None:
        """The verbose histogram must still be available alongside categories."""
        tickets = [blocked_ticket(["foo reason", "bar reason"])]
        counts = block_reason_counts(tickets)
        self.assertEqual(counts["foo reason"], 1)
        self.assertEqual(counts["bar reason"], 1)


if __name__ == "__main__":
    unittest.main()
