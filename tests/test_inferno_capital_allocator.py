from __future__ import annotations

"""Regression tests for the sleeve allocator."""

import unittest

from inferno_capital_allocator import (
    allocator_verdict,
    build_capital_allocator,
    build_long_term_lane,
    build_options_lane,
    build_sleeves,
)


class InfernoCapitalAllocatorTests(unittest.TestCase):
    """Verify options and long-term sleeves stay separated and conservative."""

    def test_build_sleeves_moves_defensive_when_authority_halted(self) -> None:
        sleeves = build_sleeves(
            {"decision": {"authorityLevel": "halted"}},
            {"deskVerdict": {"level": "insufficient-data"}},
            {"marketRegime": {"riskLevel": "high"}},
            {"topCatalystTrades": [], "topLongTermShovels": [{"ticker": "NVDA"}]},
        )
        self.assertEqual(sleeves["options"], 0.0)
        self.assertGreater(sleeves["cash"], sleeves["longTerm"])

    def test_build_sleeves_redirects_no_catalyst_budget_to_long_term_candidates(self) -> None:
        sleeves = build_sleeves(
            {"decision": {"authorityLevel": "paper-evidence-only"}},
            {"deskVerdict": {"level": "insufficient-data"}},
            {"marketRegime": {"riskLevel": "normal"}},
            {"topCatalystTrades": [], "topLongTermShovels": [{"ticker": "CHKP"}]},
        )

        self.assertEqual(sleeves["options"], 0.15)
        self.assertEqual(sleeves["longTerm"], 0.5)
        self.assertEqual(sleeves["cash"], 0.35)

    def test_build_sleeves_preserves_cash_when_no_lane_has_candidates(self) -> None:
        sleeves = build_sleeves(
            {"decision": {"authorityLevel": "paper-evidence-only"}},
            {"deskVerdict": {"level": "insufficient-data"}},
            {"marketRegime": {"riskLevel": "normal"}},
            {"topCatalystTrades": [], "topLongTermShovels": []},
        )

        self.assertEqual(sleeves["cash"], 0.55)

    def test_build_options_lane_uses_execution_intents_when_available(self) -> None:
        lane = build_options_lane(
            {
                "topCatalystTrades": [
                    {
                        "ticker": "NVDA",
                        "category": "AI/Compute Picks",
                        "edgeScore": 88,
                        "scores": {"timingScore": 90, "qualityScore": 76},
                        "daysUntilEarnings": 12,
                        "thesis": "live timing",
                    }
                ]
            },
            {
                "items": [
                    {
                        "ticker": "NVDA",
                        "setupRec": "Vertical Call",
                        "intentStatus": "approval-ready",
                        "riskUnits": 0.75,
                    }
                ]
            },
            {"options": 0.4, "longTerm": 0.35, "cash": 0.25},
        )
        self.assertEqual(lane["recommendedTicketCount"], 1)
        self.assertEqual(lane["topCandidates"][0]["setupRec"], "Vertical Call")
        self.assertEqual(lane["topCandidates"][0]["intentStatus"], "approval-ready")

    def test_build_long_term_lane_returns_tranche_plan(self) -> None:
        lane = build_long_term_lane(
            {
                "topLongTermShovels": [
                    {
                        "ticker": "ASML",
                        "category": "Semiconductor Supply Chain",
                        "edgeScore": 81,
                        "scores": {"qualityScore": 74, "valuationRiskScore": 62},
                        "longTermScore": 7.1,
                        "thesis": "tool seller",
                    }
                ]
            },
            {"options": 0.25, "longTerm": 0.5, "cash": 0.25},
        )
        self.assertEqual(len(lane["tranchePlan"]), 3)
        self.assertEqual(lane["topCandidates"][0]["ticker"], "ASML")

    def test_build_long_term_lane_respects_custom_deployable_cash(self) -> None:
        lane = build_long_term_lane(
            {
                "topLongTermShovels": [
                    {
                        "ticker": "ASML",
                        "category": "Semiconductor Supply Chain",
                        "edgeScore": 81,
                        "scores": {"qualityScore": 74, "valuationRiskScore": 62},
                        "longTermScore": 7.1,
                        "thesis": "tool seller",
                    }
                ]
            },
            {"options": 0.25, "longTerm": 0.5, "cash": 0.25},
            deployable_cash_dollars=525.0,
        )
        self.assertEqual(lane["sleeveBudgetDollars"], 262.5)
        self.assertEqual(lane["tranchePlan"][0]["dollars"], 105.0)

    def test_allocator_verdict_balances_attack_when_evidence_and_candidates_exist(self) -> None:
        verdict = allocator_verdict(
            {"decision": {"authorityLevel": "paper-evidence-only"}},
            {"deskVerdict": {"level": "promotable"}},
            {"topCandidates": [{"ticker": "NVDA"}]},
            {"topCandidates": [{"ticker": "ASML"}]},
        )
        self.assertEqual(verdict["level"], "balanced-attack")
        self.assertFalse(verdict["blockers"])

    def test_build_capital_allocator_uses_custom_cash_base(self) -> None:
        import inferno_capital_allocator as allocator
        from unittest.mock import patch

        with (
            patch.object(allocator, "load_json_file") as mocked_load,
            patch.object(allocator, "local_now") as mocked_now,
        ):
            mocked_now.return_value.isoformat.return_value = "2026-05-12T14:00:00-06:00"
            mocked_load.side_effect = [
                {"topCatalystTrades": [], "topLongTermShovels": []},
                {"items": []},
                {"deskVerdict": {"level": "insufficient-data"}},
                {"decision": {"authorityLevel": "paper-evidence-only"}},
                {"marketRegime": {"riskLevel": "normal"}},
            ]
            report = build_capital_allocator(deployable_cash_dollars=525.0)

        self.assertEqual(report["inputs"]["deployableCashDollars"], 525.0)
        self.assertEqual(report["optionsLane"]["capitalBaseDollars"], 525.0)
        self.assertEqual(report["longTermLane"]["capitalBaseDollars"], 525.0)


if __name__ == "__main__":
    unittest.main()
