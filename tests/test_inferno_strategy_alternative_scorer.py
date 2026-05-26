from __future__ import annotations

"""Tests for the research-only defined-risk alternative scorer."""

import unittest

import inferno_strategy_alternative_scorer as scorer


def expected_move() -> dict:
    return {
        "currentCandidates": [
            {
                "ticker": "BULL",
                "premiumHurdleLabel": "extreme",
                "requiredMoveAtrMultiple": 3.4,
                "rankPressureScore": 55,
                "scenarioScore": 75,
                "impliedMovePct": 15,
                "atrPercent": 5,
                "estimatedMaxLoss": 900,
            },
            {
                "ticker": "MESSY",
                "premiumHurdleLabel": "hard",
                "requiredMoveAtrMultiple": 2.6,
                "rankPressureScore": 50,
                "scenarioScore": 62,
                "impliedMovePct": 14,
                "atrPercent": 7,
                "estimatedMaxLoss": 1200,
            },
        ],
    }


def reducer() -> dict:
    return {
        "scenarioSlate": [
            {
                "ticker": "BULL",
                "daysUntilEarnings": 12,
                "marketContextSummary": {
                    "trend": "Bullish",
                    "distanceToSupportPct": 18,
                    "distanceToResistancePct": 9,
                    "atrPercent": 5,
                    "ivRank": 35,
                    "rvol": 0.9,
                },
            },
            {
                "ticker": "MESSY",
                "daysUntilEarnings": 5,
                "marketContextSummary": {
                    "trend": "Bullish",
                    "distanceToSupportPct": 4,
                    "distanceToResistancePct": 3,
                    "atrPercent": 7,
                    "ivRank": 18,
                    "rvol": 2.4,
                },
            },
        ],
    }


def strike_plan() -> dict:
    return {
        "items": [
            {
                "ticker": "BULL",
                "riskVerdict": {
                    "metrics": {
                        "underlyingSourceDriftPct": 0.8,
                        "schwabOptions": {
                            "quoteQualityLabel": "good",
                            "qualityFlags": [],
                            "atmSpreadPct": 0.04,
                            "atmLiquidityScore": 80,
                        },
                    }
                },
            },
            {
                "ticker": "MESSY",
                "riskVerdict": {
                    "metrics": {
                        "underlyingSourceDriftPct": 12,
                        "schwabOptions": {
                            "quoteQualityLabel": "poor",
                            "qualityFlags": ["no-liquid-contracts", "thin-atm-liquidity"],
                            "atmSpreadPct": 0.28,
                            "atmLiquidityScore": 5,
                        },
                    }
                },
            },
        ],
    }


class StrategyAlternativeScorerTests(unittest.TestCase):
    """Alternative scoring should stay diagnostic and quality-aware."""

    def test_bullish_supportive_context_prefers_put_credit(self) -> None:
        payload = scorer.build_strategy_alternative_scorer(
            expected_move=expected_move(),
            reducer=reducer(),
            strike_plan=strike_plan(),
        )

        bull = next(item for item in payload["scorecards"] if item["ticker"] == "BULL")

        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["liveTradingAllowed"])
        self.assertEqual(bull["recommendation"]["strategy"], "PUT_CREDIT_SPREAD")
        self.assertEqual(bull["recommendation"]["verdict"], "prefer-alternative-research")
        self.assertEqual(bull["alternatives"][0]["expectedGreekPosture"]["theta"], "positive")
        self.assertGreater(bull["alternatives"][0]["scoreEdgeVsLongVol"], 5)

    def test_bad_chain_quality_can_force_stand_aside(self) -> None:
        payload = scorer.build_strategy_alternative_scorer(
            expected_move=expected_move(),
            reducer=reducer(),
            strike_plan=strike_plan(),
        )

        messy = next(item for item in payload["scorecards"] if item["ticker"] == "MESSY")

        self.assertEqual(messy["recommendation"]["strategy"], "STAND_ASIDE")
        self.assertGreaterEqual(messy["chainPenalty"], 40)
        self.assertIn("no-liquid-contracts", messy["chainQuality"]["qualityFlags"])

    def test_text_report_renders_core_sections(self) -> None:
        payload = scorer.build_strategy_alternative_scorer(
            expected_move=expected_move(),
            reducer=reducer(),
            strike_plan=strike_plan(),
        )
        rendered = scorer.strategy_alternative_scorer_text(payload)

        self.assertIn("Inferno Strategy Alternative Scorer", rendered)
        self.assertIn("Ticker scorecards", rendered)
        self.assertIn("research-only", rendered)


if __name__ == "__main__":
    unittest.main()
