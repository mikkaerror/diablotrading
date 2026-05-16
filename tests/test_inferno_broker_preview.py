from __future__ import annotations

"""Regression tests for broker-preview quarantine rules."""

import unittest

from inferno_broker_preview import eligible_paper_tickets


class InfernoBrokerPreviewTests(unittest.TestCase):
    """Keep paper-only rehearsal variants out of broker-preview escalation."""

    def test_eligible_paper_tickets_excludes_paper_variant_only_rows(self) -> None:
        ledger = {
            "items": [
                {
                    "ticker": "GDS",
                    "status": "paper-staged",
                    "paperVariantOnly": True,
                    "outcome": {"status": "open"},
                    "riskVerdict": {"passed": True},
                    "liveTradingAllowed": False,
                },
                {
                    "ticker": "FLR",
                    "status": "paper-staged",
                    "paperVariantOnly": False,
                    "outcome": {"status": "open"},
                    "riskVerdict": {"passed": True},
                    "liveTradingAllowed": False,
                },
            ]
        }

        tickets = eligible_paper_tickets(ledger)

        self.assertEqual([item["ticker"] for item in tickets], ["FLR"])


if __name__ == "__main__":
    unittest.main()
