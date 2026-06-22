from __future__ import annotations

"""Regression tests for paper-only rehearsal variants in the ledger."""

import unittest
from unittest.mock import patch

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
            "price": 50.0,
            "ivRank": 25.0,
            "atrPercent": 3.0,
            "forecastRealizedMovePct": 8.0,
            "strikePlan": {
                "strategy": "LONG_STRADDLE",
                "estimatedDebit": 2.45,
                "estimatedMaxLoss": 245.0,
                "estimatedMaxProfit": "uncapped",
                "lowerBreakEven": 47.55,
                "upperBreakEven": 52.45,
                "greekSummary": {
                    "netDelta": 0.0,
                    "netGamma": 0.1,
                    "netTheta": -0.2,
                    "netVega": 0.3,
                    "greeksComplete": True,
                },
                "liquidityNotes": [],
                "legs": [
                    {"symbol": "WSC_20260515C50", "instruction": "BUY_TO_OPEN", "ask": 1.25},
                    {"symbol": "WSC_20260515P50", "instruction": "BUY_TO_OPEN", "ask": 1.2},
                ],
            },
        }

        with patch(
            "inferno_risk_policy.current_single_ticket_cap",
            return_value={
                "effectiveCap": 500.0,
                "source": "config-default",
                "recommendedCap": None,
                "ackedCap": None,
                "verdict": None,
                "shouldUseRecommendation": False,
            },
        ):
            status, reasons, verdict, auto_block_reason = paper_execution.paper_status_for_item(
                item,
                strike_plan_generated_at=paper_execution.local_now().isoformat(),
                ledger={"items": []},
            )

        self.assertEqual(status, "paper-staged")
        self.assertEqual(reasons, [])
        self.assertTrue(verdict["passed"])
        self.assertEqual(auto_block_reason, "ok")

    def test_long_vol_without_forecast_stays_blocked(self) -> None:
        item = {
            "ticker": "WSC",
            "ok": True,
            "approvalStatus": "pending",
            "intentStatus": "blocked",
            "price": 50.0,
            "ivRank": 25.0,
            "strikePlan": {
                "strategy": "LONG_STRADDLE",
                "estimatedDebit": 2.45,
                "estimatedMaxLoss": 245.0,
                "lowerBreakEven": 47.55,
                "upperBreakEven": 52.45,
                "greekSummary": {
                    "netDelta": 0.0,
                    "netGamma": 0.1,
                    "netTheta": -0.2,
                    "netVega": 0.3,
                    "greeksComplete": True,
                },
                "liquidityNotes": [],
            },
        }
        status, reasons, _, _ = paper_execution.paper_status_for_item(
            item,
            strike_plan_generated_at=paper_execution.local_now().isoformat(),
            ledger={"items": []},
        )
        self.assertEqual(status, "paper-blocked")
        self.assertTrue(any("long-vol-premium-hurdle" in reason for reason in reasons))

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


class _FakeVerdict:
    """Minimal stand-in for a risk verdict in auto-paper unit tests."""

    def __init__(self, passed: bool = True) -> None:
        self.passed = passed


class PaperAutoSelectionDecisionTests(unittest.TestCase):
    """Pin the diagnostic reasons emitted by ``paper_auto_selection_decision``.

    These tests document why the auto-paper gate refuses a ticket so the
    operator can read the ``paperAutoBlockReason`` field on a ledger entry
    and immediately know which condition tripped.
    """

    def _clean_item(self, **overrides: object) -> dict[str, object]:
        item = {
            "ok": True,
            "approvalStatus": "pending",
            "intentStatus": "blocked",
        }
        item.update(overrides)
        return item

    def test_eligible_path_returns_ok(self) -> None:
        eligible, reason = paper_execution.paper_auto_selection_decision(
            self._clean_item(), _FakeVerdict(passed=True), [], []
        )
        self.assertTrue(eligible)
        self.assertEqual(reason, "ok")

    def test_approved_status_blocks_with_reason(self) -> None:
        eligible, reason = paper_execution.paper_auto_selection_decision(
            self._clean_item(approvalStatus="approved"), _FakeVerdict(True), [], []
        )
        self.assertFalse(eligible)
        self.assertIn("approval-status-is-approved", reason)

    def test_item_not_ok_blocks_with_reason(self) -> None:
        eligible, reason = paper_execution.paper_auto_selection_decision(
            self._clean_item(ok=False), _FakeVerdict(True), [], []
        )
        self.assertFalse(eligible)
        self.assertEqual(reason, "item-not-ok")

    def test_failed_risk_verdict_blocks_with_reason(self) -> None:
        eligible, reason = paper_execution.paper_auto_selection_decision(
            self._clean_item(), _FakeVerdict(passed=False), [], []
        )
        self.assertFalse(eligible)
        self.assertEqual(reason, "risk-verdict-failed")

    def test_intent_non_approval_block_surfaces_reason(self) -> None:
        eligible, reason = paper_execution.paper_auto_selection_decision(
            self._clean_item(),
            _FakeVerdict(True),
            [],
            ["wide bid-ask spread"],
        )
        self.assertFalse(eligible)
        self.assertIn("intent-has-non-approval-block", reason)
        self.assertIn("wide bid-ask spread", reason)

    def test_liquidity_non_approval_block_surfaces_reason(self) -> None:
        eligible, reason = paper_execution.paper_auto_selection_decision(
            self._clean_item(),
            _FakeVerdict(True),
            ["open interest too thin"],
            [],
        )
        self.assertFalse(eligible)
        self.assertIn("liquidity-has-non-approval-note", reason)
        self.assertIn("open interest too thin", reason)

    def test_ineligible_intent_status_blocks_with_reason(self) -> None:
        eligible, reason = paper_execution.paper_auto_selection_decision(
            self._clean_item(intentStatus="needs-refresh"),
            _FakeVerdict(True),
            [],
            [],
        )
        self.assertFalse(eligible)
        self.assertIn("intent-status-not-eligible", reason)
        self.assertIn("needs-refresh", reason)

    def test_applies_shim_still_returns_bool(self) -> None:
        """The legacy ``paper_auto_selection_applies`` boolean API still works."""
        self.assertTrue(
            paper_execution.paper_auto_selection_applies(
                self._clean_item(), _FakeVerdict(True), [], []
            )
        )
        self.assertFalse(
            paper_execution.paper_auto_selection_applies(
                self._clean_item(ok=False), _FakeVerdict(True), [], []
            )
        )


if __name__ == "__main__":
    unittest.main()
