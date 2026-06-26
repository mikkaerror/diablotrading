from __future__ import annotations

"""Tests for research-only strategy alternative pricing."""

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

import inferno_strategy_alternative_pricing as pricing


def scorer_payload() -> dict:
    return {
        "scorecards": [
            {
                "ticker": "AAA",
                "hurdle": "hard",
                "hurdleAtrMultiple": 2.5,
                "longVolPressureScore": 60,
                "recommendation": {
                    "strategy": "PUT_CREDIT_SPREAD",
                    "verdict": "compare-in-paper",
                    "reason": "plausible",
                },
            },
            {
                "ticker": "BBB",
                "hurdle": "extreme",
                "hurdleAtrMultiple": 3.2,
                "longVolPressureScore": 45,
                "recommendation": {
                    "strategy": "PUT_CREDIT_SPREAD",
                    "verdict": "prefer-alternative-research",
                    "reason": "better",
                },
            },
            {
                "ticker": "CCC",
                "recommendation": {
                    "strategy": "STAND_ASIDE",
                    "verdict": "stand-aside",
                },
            },
        ],
    }


def reducer_item() -> dict:
    return {
        "ticker": "BBB",
        "price": 50,
        "daysUntilEarnings": 14,
        "marketContextSummary": {
            "trend": "Bullish",
            "rvol": 0.9,
            "support": 44,
            "resistance": 58,
            "distanceToSupportPct": 12,
            "distanceToResistancePct": 16,
            "atrPercent": 5,
            "ivRank": 35,
        },
    }


def scanner_payload() -> dict:
    return {
        "pricingCandidates": [
            {
                "ticker": "DDD",
                "sourceFamily": "wheel-proxy",
                "paperVariantOnly": True,
                "recommendedStrategy": "PUT_CREDIT_SPREAD",
                "sourceRecommendedStrategy": "PAPER_VARIANT_SCANNER",
                "recommendationVerdict": "paper-variant-research",
                "recommendationReason": "cheap high-IV signal name",
                "candidateStrategyRank": 1,
                "fallbackVariant": False,
                "sourceAlternativeScore": 74.5,
                "sourceAlternativeWarnings": ["current setupRec remains premium-buy"],
                "price": 12.5,
                "baselineUnderlyingPrice": 12.5,
                "daysUntilEarnings": 21,
                "ivRank": 62,
                "atrPercent": 4,
                "marketContextSummary": {
                    "trend": "Bullish",
                    "rvol": 0.7,
                    "support": 11.2,
                    "resistance": 15.5,
                    "distanceToSupportPct": 10.4,
                    "distanceToResistancePct": 24,
                    "atrPercent": 4,
                    "ivRank": 62,
                },
            },
            {
                "ticker": "BBB",
                "sourceFamily": "credit-spread",
                "paperVariantOnly": True,
                "recommendedStrategy": "PUT_CREDIT_SPREAD",
                "sourceAlternativeScore": 99,
            },
        ]
    }


class StrategyAlternativePricingTests(unittest.TestCase):
    """Alternative pricing should not mutate authority or operational queues."""

    def setUp(self) -> None:
        fixed_now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
        self.time_patches = [
            patch("inferno_strategy_alternative_pricing.local_now", return_value=fixed_now),
            patch("inferno_strike_selector.local_now", return_value=fixed_now),
            patch("inferno_risk_policy.local_now", return_value=fixed_now),
        ]
        for time_patch in self.time_patches:
            time_patch.start()
        self.cap_patch = patch(
            "inferno_risk_policy.current_single_ticket_cap",
            return_value={
                "effectiveCap": 500.0,
                "source": "config-default",
                "recommendedCap": None,
                "ackedCap": None,
                "verdict": None,
                "shouldUseRecommendation": False,
            },
        )
        self.cap_patch.start()

    def tearDown(self) -> None:
        self.cap_patch.stop()
        for time_patch in reversed(self.time_patches):
            time_patch.stop()

    def test_source_candidates_prioritize_prefer_verdicts(self) -> None:
        rows = pricing.source_candidates(scorer_payload(), limit=2)

        self.assertEqual([row["ticker"] for row in rows], ["BBB", "AAA"])
        self.assertEqual(rows[0]["recommendedStrategy"], "PUT_CREDIT_SPREAD")
        self.assertNotIn("CCC", [row["ticker"] for row in rows])

    def test_source_candidates_expand_ranked_fallback_variants(self) -> None:
        payload = {
            "scorecards": [
                {
                    "ticker": "BBB",
                    "longVolPressureScore": 40,
                    "recommendation": {
                        "strategy": "PUT_CREDIT_SPREAD",
                        "verdict": "prefer-alternative-research",
                        "reason": "primary",
                    },
                    "alternatives": [
                        {"strategy": "PUT_CREDIT_SPREAD", "score": 72, "scoreEdgeVsLongVol": 20},
                        {"strategy": "STAND_ASIDE", "score": 62},
                        {
                            "strategy": "IRON_CONDOR",
                            "score": 48,
                            "scoreEdgeVsLongVol": 8,
                            "reasons": ["range premium backup"],
                        },
                        {
                            "strategy": "PUT_DEBIT_SPREAD",
                            "score": 29,
                            "scoreEdgeVsLongVol": -11,
                            "reasons": ["resistance is close"],
                        },
                    ],
                }
            ],
        }

        rows = pricing.source_candidates(payload, limit=1, variants_per_ticker=3)

        self.assertEqual(
            [row["recommendedStrategy"] for row in rows],
            ["PUT_CREDIT_SPREAD", "IRON_CONDOR", "PUT_DEBIT_SPREAD"],
        )
        self.assertEqual([row["candidateStrategyRank"] for row in rows], [1, 2, 3])
        self.assertFalse(rows[0]["fallbackVariant"])
        self.assertTrue(rows[1]["fallbackVariant"])
        self.assertEqual(rows[1]["recommendationVerdict"], pricing.FALLBACK_RECOMMENDATION_VERDICT)
        self.assertIn("range premium backup", rows[1]["recommendationReason"])

    def test_source_candidates_backfill_scanner_when_slots_remain(self) -> None:
        rows = pricing.source_candidates(
            scorer_payload(),
            limit=3,
            paper_variant_scanner=scanner_payload(),
        )

        self.assertEqual([row["ticker"] for row in rows], ["BBB", "AAA", "DDD"])
        self.assertTrue(rows[2]["paperVariantOnly"])
        self.assertEqual(rows[2]["sourceRecommendedStrategy"], "PAPER_VARIANT_SCANNER")
        self.assertEqual(rows[2]["sourceFamily"], "wheel-proxy")

    def test_source_candidates_do_not_backfill_when_scorer_fills_slots(self) -> None:
        rows = pricing.source_candidates(
            scorer_payload(),
            limit=2,
            paper_variant_scanner=scanner_payload(),
        )

        self.assertEqual([row["ticker"] for row in rows], ["BBB", "AAA"])
        self.assertFalse(any(row.get("paperVariantOnly") for row in rows))

    def test_intent_from_candidate_carries_market_context(self) -> None:
        candidate = pricing.source_candidates(scorer_payload(), limit=1)[0]
        intent = pricing.intent_from_candidate(candidate, reducer_item())

        self.assertEqual(intent["ticker"], "BBB")
        self.assertEqual(intent["setupRec"], "Alternative Research")
        self.assertEqual(intent["approvalStatus"], "research-only")
        self.assertEqual(intent["marketContext"]["trend"]["label"], "Bullish")
        self.assertEqual(intent["atrPercent"], 5.0)

    def test_intent_from_scanner_candidate_uses_candidate_context_without_reducer(self) -> None:
        candidate = next(
            item
            for item in pricing.scanner_candidate_rows(scanner_payload())
            if item.get("ticker") == "DDD"
        )
        intent = pricing.intent_from_candidate(candidate, None)

        self.assertEqual(intent["ticker"], "DDD")
        self.assertEqual(intent["price"], 12.5)
        self.assertEqual(intent["daysUntilEarnings"], 21)
        self.assertEqual(intent["ivRank"], 62.0)
        self.assertEqual(intent["atrPercent"], 4.0)
        self.assertEqual(intent["marketContext"]["support"], 11.2)
        self.assertEqual(intent["marketContext"]["trend"]["label"], "Bullish")

    def test_put_credit_ladder_ranks_combined_passes_before_optimizer_blocks(self) -> None:
        pricing_intent = {
            "ticker": "BBB",
            "price": 50,
            "marketContext": {
                "trend": {"label": "Bullish"},
                "rvol": 0.9,
                "support": 46,
                "resistance": 58,
                "distanceToSupportPct": 8,
                "distanceToResistancePct": 16,
                "atrExpansion": 0,
            },
        }
        puts = pd.DataFrame(
            [
                {
                    "contractSymbol": "BBB260619P00049000",
                    "strike": 49,
                    "bid": 4.2,
                    "ask": 4.4,
                    "lastPrice": 4.3,
                    "volume": 120,
                    "openInterest": 800,
                    "impliedVolatility": 0.45,
                },
                {
                    "contractSymbol": "BBB260619P00047000",
                    "strike": 47,
                    "bid": 2.1,
                    "ask": 2.25,
                    "lastPrice": 2.18,
                    "volume": 100,
                    "openInterest": 700,
                    "impliedVolatility": 0.43,
                },
                {
                    "contractSymbol": "BBB260619P00045000",
                    "strike": 45,
                    "bid": 0.95,
                    "ask": 1.05,
                    "lastPrice": 1.0,
                    "volume": 90,
                    "openInterest": 600,
                    "impliedVolatility": 0.4,
                },
                {
                    "contractSymbol": "BBB260619P00043000",
                    "strike": 43,
                    "bid": 0.25,
                    "ask": 0.32,
                    "lastPrice": 0.28,
                    "volume": 80,
                    "openInterest": 500,
                    "impliedVolatility": 0.38,
                },
            ]
        )
        base_item = {
            "ticker": "BBB",
            "stage": pricing.STRATEGY_ALTERNATIVE_PRICING_STAGE,
            "automationStage": pricing.AUTOMATION_STAGE,
            "recommendedStrategy": "PUT_CREDIT_SPREAD",
            "price": 50,
            "sourcePrice": 50,
            "paperOnly": True,
            "liveTradingAllowed": False,
            "brokerSubmitAllowed": False,
            "marketContext": pricing_intent["marketContext"],
            "marketContextSummary": {
                "trend": "Bullish",
                "rvol": 0.9,
                "support": 46,
                "resistance": 58,
                "distanceToSupportPct": 8,
                "distanceToResistancePct": 16,
            },
            "schwabOptions": None,
        }

        ladder = pricing.build_put_credit_ladder(
            pricing_intent,
            "2026-06-19",
            puts,
            base_item=base_item,
            generated_at=pricing.local_now().isoformat(),
        )

        self.assertGreaterEqual(len(ladder), 2)
        self.assertTrue(ladder[0]["combinedPassed"])
        self.assertEqual(ladder[0]["shortPutStrike"], 45)
        self.assertEqual(ladder[0]["longPutStrike"], 43)
        self.assertTrue(any(row["optimizerBlocks"] for row in ladder[1:]))
        self.assertNotIn("_strikePlan", pricing.public_ladder_row(ladder[0]))

    def test_support_aware_short_rows_include_farther_support_safe_strikes(self) -> None:
        puts = pd.DataFrame(
            [
                {
                    "contractSymbol": f"BBB260619P{int(strike * 1000):08d}",
                    "strike": strike,
                    "bid": 0.25,
                    "ask": 0.35,
                    "lastPrice": 0.3,
                    "volume": 10,
                    "openInterest": 50,
                    "impliedVolatility": 0.4,
                }
                for strike in range(49, 24, -1)
            ]
        )

        rows = pricing.support_aware_short_put_rows(
            puts,
            {"price": 50, "marketContext": {"support": 30}},
        )

        strikes = set(rows["strike"].tolist())
        self.assertIn(49, strikes)
        self.assertIn(29, strikes)
        self.assertIn(25, strikes)

    def test_strategy_optimizer_blocks_negative_credit_condor(self) -> None:
        plan = {
            "strategy": "IRON_CONDOR",
            "estimatedCredit": -0.25,
            "estimatedMaxLoss": 200,
            "estimatedMaxProfit": 0,
            "greekSummary": {
                "greeksComplete": True,
                "netTheta": 0.01,
                "netVega": -0.01,
            },
        }

        blocks, warnings = pricing.strategy_optimizer_notes(plan)

        self.assertFalse(warnings)
        self.assertIn("not positive", "; ".join(blocks))
        self.assertIn("creditRisk", plan)
        self.assertEqual(plan["creditRisk"], 0.0)

    def test_iron_condor_ladder_ranks_range_safe_combined_passes(self) -> None:
        pricing_intent = {
            "ticker": "BBB",
            "price": 100,
            "marketContext": {
                "trend": {"label": "Neutral"},
                "rvol": 0.8,
                "support": 92,
                "resistance": 108,
                "distanceToSupportPct": 8,
                "distanceToResistancePct": 8,
                "atrExpansion": 0,
            },
        }
        calls = pd.DataFrame(
            [
                {
                    "contractSymbol": "BBB260619C00105000",
                    "strike": 105,
                    "bid": 2.4,
                    "ask": 2.55,
                    "lastPrice": 2.5,
                    "volume": 100,
                    "openInterest": 500,
                    "impliedVolatility": 0.35,
                },
                {
                    "contractSymbol": "BBB260619C00108000",
                    "strike": 108,
                    "bid": 1.05,
                    "ask": 1.18,
                    "lastPrice": 1.1,
                    "volume": 100,
                    "openInterest": 500,
                    "impliedVolatility": 0.34,
                },
                {
                    "contractSymbol": "BBB260619C00110000",
                    "strike": 110,
                    "bid": 0.55,
                    "ask": 0.65,
                    "lastPrice": 0.6,
                    "volume": 100,
                    "openInterest": 500,
                    "impliedVolatility": 0.33,
                },
                {
                    "contractSymbol": "BBB260619C00112000",
                    "strike": 112,
                    "bid": 0.12,
                    "ask": 0.16,
                    "lastPrice": 0.14,
                    "volume": 100,
                    "openInterest": 500,
                    "impliedVolatility": 0.32,
                },
            ]
        )
        puts = pd.DataFrame(
            [
                {
                    "contractSymbol": "BBB260619P00095000",
                    "strike": 95,
                    "bid": 2.1,
                    "ask": 2.25,
                    "lastPrice": 2.2,
                    "volume": 100,
                    "openInterest": 500,
                    "impliedVolatility": 0.35,
                },
                {
                    "contractSymbol": "BBB260619P00092000",
                    "strike": 92,
                    "bid": 1.05,
                    "ask": 1.17,
                    "lastPrice": 1.1,
                    "volume": 100,
                    "openInterest": 500,
                    "impliedVolatility": 0.34,
                },
                {
                    "contractSymbol": "BBB260619P00090000",
                    "strike": 90,
                    "bid": 0.52,
                    "ask": 0.62,
                    "lastPrice": 0.57,
                    "volume": 100,
                    "openInterest": 500,
                    "impliedVolatility": 0.33,
                },
                {
                    "contractSymbol": "BBB260619P00088000",
                    "strike": 88,
                    "bid": 0.11,
                    "ask": 0.15,
                    "lastPrice": 0.13,
                    "volume": 100,
                    "openInterest": 500,
                    "impliedVolatility": 0.32,
                },
            ]
        )
        base_item = {
            "ticker": "BBB",
            "stage": pricing.STRATEGY_ALTERNATIVE_PRICING_STAGE,
            "automationStage": pricing.AUTOMATION_STAGE,
            "recommendedStrategy": "IRON_CONDOR",
            "price": 100,
            "sourcePrice": 100,
            "paperOnly": True,
            "liveTradingAllowed": False,
            "brokerSubmitAllowed": False,
            "marketContext": pricing_intent["marketContext"],
            "marketContextSummary": {
                "trend": "Neutral",
                "rvol": 0.8,
                "support": 92,
                "resistance": 108,
                "distanceToSupportPct": 8,
                "distanceToResistancePct": 8,
            },
            "schwabOptions": None,
        }

        ladder = pricing.build_iron_condor_ladder(
            pricing_intent,
            "2026-06-19",
            calls,
            puts,
            base_item=base_item,
            generated_at=pricing.local_now().isoformat(),
        )

        self.assertGreaterEqual(len(ladder), 2)
        self.assertTrue(ladder[0]["combinedPassed"])
        self.assertTrue(ladder[0]["rangeSafe"])
        self.assertGreater(ladder[0]["shortCallStrike"], 108)
        self.assertLess(ladder[0]["shortPutStrike"], 92)
        self.assertNotIn("_strikePlan", pricing.public_ladder_row(ladder[0]))

    def test_empty_build_is_authority_safe(self) -> None:
        payload = pricing.build_strategy_alternative_pricing(
            scorer={"scorecards": []},
            reducer={"scenarioSlate": []},
            schwab_options_index={},
        )

        self.assertEqual(payload["verdict"], "no-priceable-candidates")
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["liveTradingAllowed"])

    def test_text_report_renders_priced_and_failed_items(self) -> None:
        payload = {
            "generatedAt": "now",
            "stage": pricing.STRATEGY_ALTERNATIVE_PRICING_STAGE,
            "verdict": "priced-risk-blocked",
            "counts": {"requested": 1, "priced": 1, "riskPassed": 0, "riskBlocked": 1},
            "items": [
                {
                    "ticker": "BBB",
                    "status": "priced",
                    "recommendedStrategy": "PUT_CREDIT_SPREAD",
                    "expiration": "2026-06-19",
                    "strikePlan": {
                        "strategy": "PUT_CREDIT_SPREAD",
                        "estimatedCredit": 0.5,
                        "estimatedMaxLoss": 450,
                        "shortPutStrike": 45,
                        "longPutStrike": 40,
                        "breakEven": 44.5,
                        "supportCushionToShortPct": 2.0,
                        "greekSummary": {
                            "netDelta": 0.1,
                            "netTheta": 0.02,
                            "netVega": -0.01,
                            "volPosture": "short-vol-theta-positive",
                        },
                    },
                    "riskVerdict": {"passed": False, "blocks": ["wide spread"], "warnings": []},
                }
            ],
        }

        rendered = pricing.strategy_alternative_pricing_text(payload)

        self.assertIn("Inferno Strategy Alternative Pricing", rendered)
        self.assertIn("PUT_CREDIT_SPREAD", rendered)
        self.assertIn("wide spread", rendered)


if __name__ == "__main__":
    unittest.main()
