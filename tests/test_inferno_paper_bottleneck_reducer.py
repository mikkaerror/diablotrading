from __future__ import annotations

"""Regression tests for the paper bottleneck reducer."""

import csv
import unittest
from io import StringIO

from inferno_paper_bottleneck_reducer import build_reducer, reducer_csv, tracker_shadow_candidates


class PaperBottleneckReducerTests(unittest.TestCase):
    """Verify the reducer widens evidence without widening authority."""

    def test_reducer_supplements_thin_director_with_tracker_shadow_rows(self) -> None:
        director = {
            "verdict": "no-viable-paper-tests",
            "counts": {"stageableNow": 0},
            "hardBlockedSlate": [
                {
                    "ticker": "MOD",
                    "category": "hard-blocked",
                    "strategy": "LONG_STRADDLE",
                    "setupRec": "Straddle",
                    "readiness": 99,
                    "daysUntilEarnings": 2,
                    "estimatedMaxLoss": 550.0,
                    "priorityScore": 80,
                    "reasons": ["max loss $550.00 exceeds single-ticket cap $500.00"],
                }
            ],
        }
        snapshot = {
            "rows": [
                {"ticker": "AAPL", "setupRec": "Vertical Call", "readiness": 95, "priority": 8, "confidence": 2, "daysUntilEarnings": 10},
                {"ticker": "NVDA", "setupRec": "Straddle", "readiness": 93, "priority": 7, "confidence": 3, "daysUntilEarnings": 8},
                {"ticker": "AVOID", "setupRec": "Avoid", "readiness": 99, "priority": 99, "confidence": 3, "daysUntilEarnings": 1},
            ]
        }

        payload = build_reducer(
            director_loader=lambda: director,
            snapshot_loader=lambda: snapshot,
            scenario_target=3,
        )

        self.assertEqual(payload["verdict"], "scenario-slate-ready")
        self.assertEqual(payload["counts"]["scenarios"], 3)
        self.assertEqual(payload["counts"]["shadowOnly"], 3)
        self.assertNotIn("AVOID", [item["ticker"] for item in payload["scenarioSlate"]])
        self.assertTrue(all(not item["brokerSubmitAllowed"] for item in payload["scenarioSlate"]))

    def test_hard_blocked_shadow_reasons_suppress_approval_noise(self) -> None:
        director = {
            "verdict": "no-viable-paper-tests",
            "counts": {"stageableNow": 0},
            "hardBlockedSlate": [
                {
                    "ticker": "PRIM",
                    "category": "hard-blocked",
                    "strategy": "LONG_STRADDLE",
                    "readiness": 80,
                    "estimatedMaxLoss": 2800.0,
                    "priorityScore": 60,
                    "reasons": [
                        "human approval is missing",
                        "human approval still required",
                        "max loss $2800.00 exceeds single-ticket cap $500.00",
                    ],
                }
            ],
        }

        payload = build_reducer(
            director_loader=lambda: director,
            snapshot_loader=lambda: {"rows": []},
            scenario_target=1,
        )

        self.assertEqual(
            payload["scenarioSlate"][0]["reasons"],
            ["max loss $2800.00 exceeds single-ticket cap $500.00"],
        )

    def test_executable_paper_candidate_keeps_operator_candidate_label(self) -> None:
        director = {
            "verdict": "operator-paper-candidates",
            "stageableSlate": [
                {
                    "ticker": "OTEX",
                    "category": "stageable-now",
                    "strategy": "CALL_DEBIT_SPREAD",
                    "setupRec": "Vertical Call",
                    "readiness": 91,
                    "daysUntilEarnings": 7,
                    "estimatedMaxLoss": 120.0,
                    "priorityScore": 90,
                    "reasons": [],
                }
            ],
        }

        payload = build_reducer(
            director_loader=lambda: director,
            snapshot_loader=lambda: {"rows": [{"ticker": "OTEX", "price": 28.75, "support": 27.2}]},
            scenario_target=1,
        )

        scenario = payload["scenarioSlate"][0]
        self.assertTrue(scenario["executableInPaperMoney"])
        self.assertFalse(scenario["shadowOnly"])
        self.assertEqual(scenario["evidenceLane"], "paper-operator-candidate")
        self.assertIn("operator-routable paper candidate", scenario["reducerAction"])
        self.assertIn("do not stage it autonomously", scenario["reducerAction"])
        self.assertEqual(payload["counts"]["operatorRoutablePaper"], 1)
        self.assertEqual(payload["counts"]["paperAutoSelected"], 0)
        self.assertEqual(scenario["price"], 28.75)
        self.assertEqual(scenario["priceSource"], "latest_snapshot.rows")
        self.assertFalse(scenario["brokerSubmitAllowed"])
        self.assertFalse(scenario["liveTradingAllowed"])

    def test_auto_paper_candidate_is_executable_but_not_authority_eligible(self) -> None:
        director = {
            "verdict": "auto-paper-selected",
            "autoPaperSlate": [
                {
                    "ticker": "WSC",
                    "category": "auto-paper-selected",
                    "strategy": "LONG_STRADDLE",
                    "setupRec": "Straddle",
                    "readiness": 88,
                    "daysUntilEarnings": 2,
                    "estimatedMaxLoss": 295.0,
                    "priorityScore": 84,
                    "reasons": ["human approval is missing"],
                }
            ],
        }

        payload = build_reducer(
            director_loader=lambda: director,
            snapshot_loader=lambda: {"rows": []},
            scenario_target=1,
        )

        scenario = payload["scenarioSlate"][0]
        self.assertTrue(scenario["executableInPaperMoney"])
        self.assertTrue(scenario["paperAutoSelected"])
        self.assertFalse(scenario["requiresApproval"])
        self.assertFalse(scenario["authorityEligible"])
        self.assertEqual(scenario["evidenceLane"], "paper-auto-candidate")
        self.assertIn("operator-owned paper workflow", scenario["reducerAction"])
        self.assertIn("do not stage it autonomously", scenario["reducerAction"])
        self.assertEqual(payload["counts"]["operatorRoutablePaper"], 0)
        self.assertEqual(payload["counts"]["paperAutoSelected"], 1)
        self.assertEqual(payload["counts"]["executablePaper"], 1)
        self.assertFalse(scenario["brokerSubmitAllowed"])
        self.assertFalse(scenario["liveTradingAllowed"])

    def test_priced_paper_research_variants_are_surfaced_before_shadow_rows(self) -> None:
        director = {
            "verdict": "research-watch",
            "counts": {
                "paperResearchSelected": 2,
                "distinctPaperResearchEvents": 1,
            },
            "pricedPaperVariantWatchlist": [
                {
                    "ticker": "GOOG",
                    "category": "paper-research-selected",
                    "strategy": "CALL_DEBIT_SPREAD",
                    "expiration": "2026-07-24",
                    "eventId": "GOOG|2026-07-23",
                    "paperResearchSelected": True,
                    "estimatedMaxLoss": 330.0,
                    "priceLabel": "debit",
                    "price": 3.30,
                    "sourceAlternativeScore": 72,
                    "warnings": ["bullish call spread lacks strong RVOL confirmation"],
                },
                {
                    "ticker": "GOOG",
                    "category": "paper-research-selected",
                    "strategy": "IRON_CONDOR",
                    "expiration": "2026-07-31",
                    "eventId": "GOOG|2026-07-23",
                    "paperResearchSelected": True,
                    "estimatedMaxLoss": 330.0,
                    "priceLabel": "credit",
                    "price": 1.70,
                    "sourceAlternativeScore": 54,
                },
            ],
            "hardBlockedSlate": [
                {
                    "ticker": "GOOG",
                    "category": "hard-blocked",
                    "strategy": "LONG_STRADDLE",
                    "setupRec": "Straddle",
                    "readiness": 80,
                    "daysUntilEarnings": 16,
                    "estimatedMaxLoss": 2365.0,
                    "priorityScore": 53.55,
                    "reasons": ["max loss $2365.00 exceeds single-ticket cap $2000.00"],
                }
            ],
        }

        payload = build_reducer(
            director_loader=lambda: director,
            snapshot_loader=lambda: {"rows": [{"ticker": "GOOG", "price": 358.45, "support": 333.69}]},
            scenario_target=2,
        )

        self.assertEqual(payload["counts"]["paperResearchSelected"], 2)
        self.assertEqual(payload["counts"]["shadowOnly"], 0)
        self.assertEqual([item["evidenceLane"] for item in payload["scenarioSlate"]], ["paper-research-selected", "paper-research-selected"])
        self.assertEqual([item["strategy"] for item in payload["scenarioSlate"]], ["CALL_DEBIT_SPREAD", "IRON_CONDOR"])
        self.assertEqual([item["ticker"] for item in payload["topFiveFocus"]], ["GOOG", "GOOG"])
        self.assertTrue(all(item["paperResearchSelected"] for item in payload["scenarioSlate"]))
        self.assertTrue(all(not item["executableInPaperMoney"] for item in payload["scenarioSlate"]))
        self.assertTrue(all(not item["requiresApproval"] for item in payload["scenarioSlate"]))
        self.assertTrue(all(not item["brokerSubmitAllowed"] for item in payload["scenarioSlate"]))
        self.assertEqual(payload["scenarioSlate"][0]["price"], 358.45)
        self.assertEqual(payload["scenarioSlate"][0]["optionPremium"], 3.30)
        self.assertIn("approval-free paper research", payload["scenarioSlate"][0]["reducerAction"])

    def test_tracker_shadow_candidates_exclude_existing_and_negative_dte(self) -> None:
        snapshot = {
            "rows": [
                {"ticker": "MOD", "setupRec": "Straddle", "readiness": 99, "priority": 9, "daysUntilEarnings": 3},
                {"ticker": "OLD", "setupRec": "Straddle", "readiness": 99, "priority": 9, "daysUntilEarnings": -1},
                {"ticker": "MRVL", "setupRec": "Vertical Call", "readiness": 88, "priority": 7, "daysUntilEarnings": 12},
            ]
        }

        rows = tracker_shadow_candidates(snapshot, excluded_tickers={"MOD"}, needed=5)

        self.assertEqual([row["ticker"] for row in rows], ["MRVL"])
        self.assertTrue(rows[0]["shadowOnly"])
        self.assertEqual(rows[0]["evidenceLane"], "tracker-shadow-scenario")

    def test_reducer_csv_is_flat_and_spreadsheet_friendly(self) -> None:
        payload = {
            "scenarioSlate": [
                {
                    "rank": 1,
                    "ticker": "VNET",
                    "evidenceLane": "shadow-scenario",
                    "sourceLane": "hard-blocked",
                    "scenarioScore": 84.18,
                    "setupRec": "Straddle",
                    "strategy": "LONG_STRADDLE",
                    "daysUntilEarnings": 9,
                    "readiness": 99,
                    "confidence": 2,
                    "estimatedMaxLoss": 750,
                    "capitalGap": 250,
                    "executableInPaperMoney": False,
                    "requiresApproval": False,
                    "shadowOnly": True,
                    "reducerAction": "Track as shadow only.",
                    "reasons": ["max loss exceeds cap", "wide spread"],
                }
            ]
        }

        rows = list(csv.DictReader(StringIO(reducer_csv(payload))))

        self.assertEqual(rows[0]["ticker"], "VNET")
        self.assertEqual(rows[0]["reasons"], "max loss exceeds cap; wide spread")
        self.assertEqual(rows[0]["shadowOnly"], "True")


if __name__ == "__main__":
    unittest.main()
