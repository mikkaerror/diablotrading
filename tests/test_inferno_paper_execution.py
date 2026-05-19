from __future__ import annotations

"""Regression tests for paper-only rehearsal variants in the ledger."""

import unittest

import inferno_paper_execution as paper_execution


class InfernoPaperExecutionVariantTests(unittest.TestCase):
    """Verify capped rehearsal variants are recorded without widening authority."""

    def test_paper_status_auto_stages_approval_only_ticket(self) -> None:
        item = {
            "ticker": "WSC",
            "setupRec": "Straddle",
            "ok": True,
            "approvalStatus": "pending",
            "intentStatus": "blocked",
            "intentBlocks": ["human approval still required"],
            "strikePlan": {
                "strategy": "LONG_STRADDLE",
                "estimatedDebit": 2.95,
                "estimatedMaxLoss": 295.0,
                "estimatedMaxProfit": "uncapped",
                "liquidityNotes": [],
                "legs": [
                    {"symbol": "WSC_20260515C50", "instruction": "BUY_TO_OPEN", "ask": 1.5},
                    {"symbol": "WSC_20260515P50", "instruction": "BUY_TO_OPEN", "ask": 1.45},
                ],
            },
        }

        status, reasons, verdict = paper_execution.paper_status_for_item(
            item,
            strike_plan_generated_at=paper_execution.local_now().isoformat(),
            ledger={"items": []},
        )

        self.assertEqual(status, "paper-staged")
        self.assertEqual(reasons, [])
        self.assertTrue(verdict["passed"])

    def test_rehearsal_variant_item_only_appears_for_size_cap_blocks(self) -> None:
        item = {
            "ticker": "GDS",
            "setupRec": "Straddle",
            "ok": True,
            "approvalStatus": "pending",
            "intentStatus": "blocked",
            "riskVerdict": {"blocks": ["max loss $900.00 exceeds single-ticket cap $500.00"]},
            "strikePlan": {"strategy": "LONG_STRADDLE"},
            "paperRehearsalVariant": {
                "strategy": "LONG_STRANGLE",
                "paperVariantOnly": True,
                "variantFamily": "cap-aware-long-strangle",
                "variantForStrategy": "LONG_STRADDLE",
                "riskVerdict": {"passed": True, "blocks": [], "warnings": []},
            },
        }

        variant = paper_execution.rehearsal_variant_item(item)

        self.assertIsNotNone(variant)
        self.assertTrue(variant["paperVariantOnly"])
        self.assertEqual(variant["strikePlan"]["strategy"], "LONG_STRANGLE")

    def test_rehearsal_variant_item_skips_structurally_bad_primary(self) -> None:
        item = {
            "ticker": "THR",
            "setupRec": "Vertical Call",
            "ok": True,
            "riskVerdict": {"blocks": ["reward/risk 0.35 is below debit-spread floor 0.50"]},
            "strikePlan": {"strategy": "CALL_DEBIT_SPREAD"},
            "paperRehearsalVariant": {
                "strategy": "LONG_STRANGLE",
                "paperVariantOnly": True,
                "riskVerdict": {"passed": True, "blocks": [], "warnings": []},
            },
        }

        self.assertIsNone(paper_execution.rehearsal_variant_item(item))


if __name__ == "__main__":
    unittest.main()
