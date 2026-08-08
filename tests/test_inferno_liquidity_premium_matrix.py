from __future__ import annotations

"""Regression tests for the research-only liquidity/premium matrix."""

import unittest
from datetime import datetime, timezone

import inferno_liquidity_premium_matrix as matrix


NOW = datetime(2026, 8, 7, 23, 40, tzinfo=timezone.utc)


def quote(*, snapshot: str = "2026-08-07T18:30:00-06:00", pass_gate: bool = False) -> dict:
    return {
        "sourceGeneratedAt": snapshot,
        "quoteQualityScore": 41,
        "quoteQualityLabel": "poor",
        "atmSpreadPct": 1.25,
        "atmSpreadQuality": "untradeable",
        "atmWindowOpenInterest": 950,
        "atmLiquidityScore": 25,
        "paperLiquidityPass": pass_gate,
        "qualityFlags": ["wide-atm-spread", "thin-atm-liquidity"],
    }


def pricing_payload() -> dict:
    return {
        "generatedAt": NOW.isoformat(),
        "items": [
            {
                "ticker": "AAA",
                "status": "priced",
                "recommendedStrategy": "CALL_DEBIT_SPREAD",
                "expiration": "2026-08-14",
                "chainSource": "schwab-options",
                "riskVerdict": {
                    "passed": False,
                    "blocks": [
                        "Schwab paper liquidity gate failed: quoted spread is untradeable",
                    ],
                    "metrics": {"schwabOptions": quote()},
                },
                "strikePlan": {"strategy": "CALL_DEBIT_SPREAD", "liquidityNotes": []},
                "combinedPassed": False,
            },
            {
                "ticker": "AAA",
                "status": "priced",
                "recommendedStrategy": "PUT_CREDIT_SPREAD",
                "expiration": "2026-08-21",
                "chainSource": "schwab-options",
                "capFitFallback": True,
                "capFitFallbackOfStrategy": "LONG_STRADDLE",
                "capFitFallbackStructure": "credit_1w",
                "riskVerdict": {
                    "passed": False,
                    "blocks": [
                        "Schwab option chain quality block: wide-atm-spread",
                    ],
                    "metrics": {"schwabOptions": quote()},
                },
                "strikePlan": {"strategy": "PUT_CREDIT_SPREAD", "liquidityNotes": []},
                "combinedPassed": False,
            },
            {
                "ticker": "BBB",
                "status": "failed",
                "recommendedStrategy": "IRON_CONDOR",
                "reason": "no usable chain",
                "riskVerdict": {"passed": False, "blocks": []},
                "strikePlan": {},
                "combinedPassed": False,
            },
        ],
    }


def blocker_swarm_payload() -> dict:
    return {
        "generatedAt": NOW.isoformat(),
        "candidateFindings": [
            {
                "ticker": "AAA",
                "sourceSlate": "hardBlockedSlate",
                "strategy": "LONG_STRADDLE",
                "activeLanes": ["liquidity", "premium_hurdle", "alternative_structure"],
                "reasons": ["Decision card incomplete or the premium hurdle failed: long-vol-premium-hurdle"],
                "warnings": [],
            },
            {
                "ticker": "BBB",
                "sourceSlate": "hardBlockedSlate",
                "strategy": "LONG_STRADDLE",
                "activeLanes": ["premium_hurdle"],
                "reasons": ["Decision card incomplete or the premium hurdle failed"],
                "warnings": [],
            },
        ],
    }


def expected_move_payload() -> dict:
    return {
        "generatedAt": NOW.isoformat(),
        "currentCandidates": [
            {
                "ticker": "AAA",
                "premiumHurdleLabel": "hard",
                "requiredMoveAtrMultiple": 2.4,
                "impliedMovePct": 16.2,
                "hurdleAction": "demote long vol unless alternatives have worse defined-risk math",
            },
            {
                "ticker": "BBB",
                "premiumHurdleLabel": "stretch",
                "requiredMoveAtrMultiple": 1.7,
                "impliedMovePct": 10.1,
                "hurdleAction": "require catalyst confirmation",
            },
        ],
    }


class LiquidityPremiumMatrixTests(unittest.TestCase):
    def test_rows_and_ticker_exposures_are_counted_separately(self) -> None:
        payload = matrix.build_liquidity_premium_matrix(
            strategy_pricing=pricing_payload(),
            paper_blocker_swarm=blocker_swarm_payload(),
            expected_move=expected_move_payload(),
            now=NOW,
        )

        self.assertEqual(payload["verdict"], "mixed-market-quality-and-premium-pressure")
        self.assertTrue(payload["researchOnly"])
        self.assertTrue(payload["diagnosticOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["authorityChanged"])
        self.assertFalse(payload["brokerSubmitAllowed"])
        self.assertFalse(payload["liveTradingAllowed"])
        self.assertEqual(payload["counts"]["pricingRows"], 3)
        self.assertEqual(payload["counts"]["tickerExposures"], 2)
        self.assertEqual(payload["counts"]["quoteObservations"], 1)
        self.assertEqual(payload["counts"]["rowsWithoutQuoteEvidence"], 1)
        self.assertEqual(payload["counts"]["tickerExposuresWithoutQuoteEvidence"], 1)
        self.assertEqual(payload["counts"]["liquidityBlockedRows"], 2)
        self.assertEqual(payload["counts"]["liquidityBlockedTickers"], 1)
        self.assertEqual(payload["counts"]["premiumHurdleBlockedRows"], 3)
        self.assertEqual(payload["counts"]["bothBlockedRows"], 2)
        self.assertEqual(payload["counts"]["capFitFallbackRows"], 1)
        self.assertEqual(payload["counts"]["capFitFallbackTickers"], 1)

        first = payload["rows"][0]
        self.assertEqual(first["ticker"], "AAA")
        self.assertEqual(first["quoteSnapshotTimeLocal"], "18:30 -0600")
        self.assertEqual(first["atmSpreadPct"], 1.25)
        self.assertEqual(first["atmWindowOpenInterest"], 950.0)
        self.assertEqual(first["sourceLongVolHurdleLabel"], "hard")
        self.assertTrue(first["sourceCandidatePremiumHurdleBlocked"])
        self.assertTrue(first["pricedStructureLiquidityBlocked"])
        self.assertFalse(first["pricedStructurePremiumEvidenceBlocked"])

        aaa = next(row for row in payload["tickerExposures"] if row["ticker"] == "AAA")
        self.assertEqual(aaa["pricingRows"], 2)
        self.assertEqual(aaa["quoteObservations"], 1)
        self.assertEqual(aaa["expirations"], ["2026-08-14", "2026-08-21"])
        self.assertEqual(aaa["sourceLongVolHurdleLabels"], ["hard"])

        bbb = next(row for row in payload["rows"] if row["ticker"] == "BBB")
        self.assertEqual(bbb["liquidityEvidenceStatus"], "unobserved")
        self.assertEqual(bbb["premiumEvidenceStatus"], "blocked")

    def test_render_text_keeps_snapshot_time_and_limitations_explicit(self) -> None:
        payload = matrix.build_liquidity_premium_matrix(
            strategy_pricing=pricing_payload(),
            paper_blocker_swarm=blocker_swarm_payload(),
            expected_move=expected_move_payload(),
            now=NOW,
        )
        rendered = matrix.render_text(payload)

        self.assertIn("Inferno Liquidity / Premium Blocker Matrix", rendered)
        self.assertIn("ticker exposures / quote observations: 2 / 1", rendered)
        self.assertIn("rows / ticker exposures without quote evidence: 1 / 1", rendered)
        self.assertIn("AAA | CALL_DEBIT_SPREAD | priced | exp 2026-08-14 | quote 18:30 -0600", rendered)
        self.assertIn("spread 125%", rendered)
        self.assertIn("source hurdle hard", rendered)
        self.assertIn("not an intraday time-of-day study", rendered)
        self.assertIn("unobserved, not clear", rendered)
        self.assertIn("broker submit OFF", rendered)

    def test_empty_pricing_is_a_safe_non_promotable_outcome(self) -> None:
        payload = matrix.build_liquidity_premium_matrix(
            strategy_pricing={"items": []},
            paper_blocker_swarm={},
            expected_move={},
            now=NOW,
        )

        self.assertEqual(payload["verdict"], "no-pricing-candidates")
        self.assertEqual(payload["counts"]["pricingRows"], 0)
        self.assertEqual(payload["counts"]["tickerExposures"], 0)
        self.assertFalse(payload["promotable"])

    def test_nonpremium_source_lane_does_not_imply_a_clear_premium_hurdle(self) -> None:
        row = matrix.source_row(
            {
                "ticker": "CCC",
                "status": "failed",
                "recommendedStrategy": "PUT_CREDIT_SPREAD",
                "riskVerdict": {"passed": False, "blocks": []},
                "strikePlan": {},
            },
            blockers={"CCC": {"lanes": ["liquidity"], "reasons": [], "strategies": []}},
            expected={},
        )

        self.assertTrue(row["liquidityBlocked"])
        self.assertFalse(row["premiumHurdleBlocked"])
        self.assertEqual(row["premiumEvidenceStatus"], "unobserved")


if __name__ == "__main__":
    unittest.main()
