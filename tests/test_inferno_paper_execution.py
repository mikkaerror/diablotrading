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

    def test_ledger_entry_preserves_entry_score_context(self) -> None:
        item = {
            "rank": 3,
            "ticker": "SMR",
            "setupRec": "Vertical Call",
            "ok": True,
            "approvalStatus": "pending",
            "intentStatus": "blocked",
            "intentBlocks": ["human approval still required"],
            "readiness": 91,
            "confidence": 2,
            "priority": 6.75,
            "scenarioScore": 78.5,
            "routeFamily": "defined-risk directional",
            "sourceRecommendedStrategy": "PAPER_VARIANT_SCANNER",
            "sourceAlternativeScore": 74.5,
            "sourceAlternativeWarnings": ["paper variant source"],
            "price": 12.0,
            "ivRank": 62.0,
            "atrPercent": 4.0,
            "forecastRealizedMovePct": 8.0,
            "strikePlan": {
                "strategy": "CALL_DEBIT_SPREAD",
                "expiration": "2026-08-21",
                "estimatedDebit": 0.65,
                "estimatedMaxLoss": 65.0,
                "estimatedMaxProfit": 35.0,
                "breakEven": 12.65,
                "greekSummary": {
                    "netDelta": 0.2,
                    "netGamma": 0.01,
                    "netTheta": -0.01,
                    "netVega": 0.02,
                    "greeksComplete": True,
                },
                "liquidityNotes": [],
                "legs": [
                    {"symbol": "SMR260821C00012000", "instruction": "BUY_TO_OPEN", "ask": 0.8},
                    {"symbol": "SMR260821C00013000", "instruction": "SELL_TO_OPEN", "bid": 0.15},
                ],
            },
        }

        with patch("inferno_paper_execution.load_json_file", return_value={}):
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
                entry = paper_execution.build_ledger_entry(
                    item,
                    strike_plan_generated_at=paper_execution.local_now().isoformat(),
                    ledger={"items": []},
                )

        self.assertEqual(entry["readiness"], 91)
        self.assertEqual(entry["priorityScore"], 6.75)
        self.assertEqual(entry["scenarioScore"], 78.5)
        self.assertEqual(entry["setupFamily"], "defined-risk directional")
        self.assertEqual(entry["sourceRecommendedStrategy"], "PAPER_VARIANT_SCANNER")
        self.assertEqual(entry["sourceAlternativeScore"], 74.5)
        self.assertFalse(entry["liveTradingAllowed"])
        self.assertEqual(entry["eventId"], "SMR|2026-08-21")

    def test_event_ticket_count_counts_open_and_scored_staged_tickets(self) -> None:
        ledger_items = [
            {"ticker": "WSC", "eventId": "WSC|2026-07-08", "status": "paper-staged", "outcome": {"status": "open"}},
            {"ticker": "WSC", "eventId": "WSC|2026-07-08", "status": "paper-staged", "outcome": {"status": "scored"}},
            {"ticker": "WSC", "eventId": "WSC|2026-07-08", "status": "paper-blocked", "outcome": {"status": "not-opened"}},
            {"ticker": "NEW", "eventId": "NEW|2026-07-08", "status": "paper-staged", "outcome": {"status": "open"}},
        ]

        self.assertEqual(paper_execution.paper_event_ticket_count("WSC|2026-07-08", ledger_items), 2)

    def test_paper_event_id_uses_earnings_before_expiration(self) -> None:
        event_id = paper_execution.paper_event_id(
            {
                "ticker": "WSC",
                "trackerContext": {"nextEarnings": "2026-07-08T20:00:00-04:00"},
                "strikePlan": {"expiration": "2026-07-17"},
            }
        )

        self.assertEqual(event_id, "WSC|2026-07-08")

    def test_ledger_entry_stamps_campaign_arm_and_full_spread_friction(self) -> None:
        item = {
            "ticker": "WSC",
            "setupRec": "Straddle",
            "campaignArm": "B",
            "approvalStatus": "pending",
            "intentStatus": "blocked",
            "schwabOptions": {"paperFillFrictionPct": 0.15},
            "strikePlan": {
                "strategy": "LONG_STRADDLE",
                "expiration": "2026-07-17",
                "estimatedDebit": 5.0,
                "estimatedMaxLoss": 500.0,
                "legs": [
                    {"symbol": "WSC260717C00050000", "instruction": "BUY_TO_OPEN", "ask": 2.5},
                    {"symbol": "WSC260717P00050000", "instruction": "BUY_TO_OPEN", "ask": 2.5},
                ],
            },
        }
        with patch("inferno_paper_execution.load_json_file", return_value={}):
            with patch(
                "inferno_paper_execution.paper_status_for_item",
                return_value=("paper-staged", [], {"passed": True}, "ok"),
            ):
                entry = paper_execution.build_ledger_entry(
                    item,
                    strike_plan_generated_at=paper_execution.local_now().isoformat(),
                    ledger={"items": []},
                )

        self.assertEqual(entry["arm"], "B")
        self.assertEqual(entry["campaignArm"], "B")
        self.assertEqual(entry["exitRule"], "exit-before-earnings")
        self.assertEqual(entry["paperFrictionCrossings"], 2)
        self.assertEqual(entry["paperFillFrictionPct"], 0.15)
        self.assertEqual(entry["estimatedSpreadFrictionPerCrossingDollars"], 75.0)
        self.assertEqual(entry["estimatedTotalSpreadFrictionDollars"], 150.0)
        self.assertEqual(entry["frictionModel"], "full-atm-spread-per-crossing")
        self.assertFalse(entry["liveTradingAllowed"])

    def test_campaign_arm_assignment_is_always_registered(self) -> None:
        item = {"ticker": "SMR", "strikePlan": {"strategy": "CALL_DEBIT_SPREAD"}}

        arm = paper_execution.campaign_arm_for_ticket(item, "SMR|2026-07-17")

        self.assertIn(arm["arm"], {"C", "D"})
        self.assertEqual(arm["campaignArm"], arm["arm"])
        self.assertIn(arm["exitRule"], {"hold-through", "exit-before-earnings"})


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
